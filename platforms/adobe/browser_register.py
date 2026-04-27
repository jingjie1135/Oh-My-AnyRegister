import time
import random
import re
import logging
import os
import tempfile
from urllib.parse import urlparse
from DrissionPage import ChromiumOptions, ChromiumPage
from fake_useragent import UserAgent

from platforms.adobe.browser_subscribe import (
    _build_otp_fill_js,
    _extract_otp_code,
    _is_trusted_adobe_auth_frame,
)

logger = logging.getLogger("adobe_browser")

def _visible_browser_dimension(name: str, default: int, minimum: int, maximum: int) -> int:
    try:
        value = int(os.environ.get(name, str(default)))
    except ValueError:
        return default
    if value < minimum or value > maximum:
        return default
    return value


VISIBLE_BROWSER_WIDTH = _visible_browser_dimension("VNC_WIDTH", 1280, 640, 3840)
VISIBLE_BROWSER_HEIGHT = _visible_browser_dimension("VNC_HEIGHT", 720, 480, 2160)
ADOBE_COOKIE_DOMAINS = (".adobe.com", "firefly.adobe.com", "account.adobe.com")
ADOBE_AUTH_COOKIE_NAMES = {"ims_sid", "aux_sid"}
ADOBE_COOKIE_STABLE_WAIT_SECONDS = 45
ADOBE_COOKIE_STABLE_INTERVAL_SECONDS = 5

# ====================== Stealth JS 防风控指纹补丁 ======================
STEALTH_JS = """
// 1. 消除 navigator.webdriver 标志 (最关键!)
Object.defineProperty(navigator, 'webdriver', {
    get: () => undefined,
    configurable: true,
});

// 2. 修复 window.chrome 对象
if (!window.chrome) {
    window.chrome = {
        runtime: {
            onMessage: { addListener: function() {}, removeListener: function() {} },
            sendMessage: function() {},
        },
    };
}

// 3. 修复 Permissions API (Arkose 检测 notification)
const originalQuery = window.navigator.permissions.query;
window.navigator.permissions.query = function(parameters) {
    if (parameters.name === 'notifications') {
        return Promise.resolve({ state: Notification.permission });
    }
    return originalQuery.call(this, parameters);
};

// 4. 修复 navigator.plugins
Object.defineProperty(navigator, 'plugins', {
    get: () => {
        const plugins = [
            { name: 'Chrome PDF Plugin', filename: 'internal-pdf-viewer', description: 'Portable Document Format' },
            { name: 'Chrome PDF Viewer', filename: 'mhjfbmdgcfjbbpaeojofohoefgiehjai', description: '' },
            { name: 'Native Client', filename: 'internal-nacl-plugin', description: '' },
            { name: 'Chromium PDF Plugin', filename: 'internal-pdf-viewer', description: 'Portable Document Format' },
            { name: 'Chromium PDF Viewer', filename: 'mhjfbmdgcfjbbpaeojofohoefgiehjai', description: '' },
        ];
        plugins.length = 5;
        return plugins;
    },
    configurable: true,
});

// 5. 修复 navigator.languages
Object.defineProperty(navigator, 'languages', {
    get: () => ['zh-CN', 'zh', 'en-US', 'en'],
    configurable: true,
});

// 6. 消除 CDP 痕迹
delete window.__cdp_binding__;
delete window.__selenium_unwrapped;
delete window.__driver_evaluate;
delete window.__webdriver_evaluate;

// 7. 消除报错中提取出的 CDP hook 痕迹
const originalError = Error;
const handler = {
    construct: function(target, args) {
        const error = new target(...args);
        if (error.stack) {
            error.stack = error.stack.replace(/Extension|chrome-extension|moz-extension/g, 'https');
        }
        return error;
    }
};

// 8. Canvas 噪声干扰
const originalGetContext = HTMLCanvasElement.prototype.getContext;
HTMLCanvasElement.prototype.getContext = function(type, attributes) {
    const ctx = originalGetContext.call(this, type, attributes);
    if (type === '2d' && ctx) {
        const origGetImageData = ctx.getImageData;
        ctx.getImageData = function(...args) {
            const imageData = origGetImageData.apply(this, args);
            for (let i = 0; i < imageData.data.length; i += 4) {
                imageData.data[i] ^= 1;  
            }
            return imageData;
        };
    }
    return ctx;
};
"""


def _cookie_field(cookie, field: str, default=""):
    if isinstance(cookie, dict):
        return cookie.get(field, default)
    return getattr(cookie, field, default)


def _cookie_domain_matches(cookie_domain: str, target_domain: str) -> bool:
    domain = cookie_domain.lower().strip().lstrip(".")
    target = target_domain.lower().strip().lstrip(".")
    return domain == target or domain.endswith("." + target)


def _is_adobe_cookie(cookie) -> bool:
    domain = str(_cookie_field(cookie, "domain", ""))
    return any(_cookie_domain_matches(domain, target) for target in ADOBE_COOKIE_DOMAINS)


def _cookie_dedup_key(cookie) -> str:
    domain = str(_cookie_field(cookie, "domain", "")).lower().strip()
    path = str(_cookie_field(cookie, "path", "/") or "/")
    name = str(_cookie_field(cookie, "name", "")).strip()
    return f"{domain}|{path}|{name}"


def _cookie_header_value(cookie) -> str:
    name = str(_cookie_field(cookie, "name", "")).strip()
    value = str(_cookie_field(cookie, "value", ""))
    if not name:
        return ""
    return f"{name}={value}"


def build_adobe_cookie_header(cookies) -> str:
    """Build adobe2api cookie payload using browser-cookie-exporter scope semantics."""
    parts = []
    seen_keys = set()
    for cookie in cookies:
        if not _is_adobe_cookie(cookie):
            continue
        key = _cookie_dedup_key(cookie)
        if key in seen_keys:
            continue
        seen_keys.add(key)
        header_value = _cookie_header_value(cookie)
        if header_value:
            parts.append(header_value)
    return "; ".join(parts)


def _cookie_expires(cookie):
    expires = _cookie_field(cookie, "expires", None)
    if expires is None:
        expires = _cookie_field(cookie, "expirationDate", None)
    try:
        return float(expires)
    except (TypeError, ValueError):
        return None



def _is_safe_cookie_export_url(url: str) -> bool:
    parsed = urlparse(url or "")
    host = (parsed.hostname or "").lower().strip("[]")
    if parsed.scheme not in {"http", "https"}:
        return False
    if host in {"localhost", "127.0.0.1", "::1", "adobe2api"}:
        return True
    return (
        host.startswith("10.")
        or host.startswith("192.168.")
        or any(host.startswith(f"172.{idx}.") for idx in range(16, 32))
    )

class AdobeBrowserRegister:
    """Adobe Browser Register 工作流"""
    
    SIGNUP_URL = (
        "https://auth.services.adobe.com/zh_HANS/deeplink.html"
        "?deeplink=signup"
        "&callback=https://firefly.adobe.com/"
        "&client_id=clio-playground-web"
        "&scope=AdobeID,firefly_api,openid,pps.read,pps.write,additional_info.projectedProductContext,additional_info.ownerOrg,uds_read,uds_write,ab.manage,read_organizations,additional_info.roles,account_cluster.read,creative_production"
    )

    def __init__(
        self,
        captcha=None,
        headless: bool = False,
        proxy: str = None,
        otp_callback=None,
        log_fn=None,
        keep_browser_open: bool = False,
    ):
        self.captcha = captcha
        self.headless = headless
        self.keep_browser_open = bool(keep_browser_open and not headless)
        self.proxy = proxy
        self._otp_callback = otp_callback
        self.log = log_fn or logger.info
        self.page = None
        self._browser_controller = None
        self._firefly_parent_page = None
        self._user_data_dir = ""

    def _delay(self, lo=0.5, hi=1.5):
        time.sleep(random.uniform(lo, hi))

    def _gen_profile(self):
        firsts = ["James", "Mary", "John", "Sarah", "Alex", "Emma", "David", "Lisa"]
        lasts = ["Smith", "Johnson", "Brown", "Taylor", "Wilson", "Davis", "Clark"]
        return {
            "fn": random.choice(firsts),
            "ln": random.choice(lasts),
            "month": random.randint(1, 12),
            "year": random.randint(1980, 2002),
        }

    def _wait_page_ready(self, timeout=15):
        start = time.time()
        while time.time() - start < timeout:
            try:
                state = self.page.run_js("document.readyState")
                if state == "complete":
                    time.sleep(0.5)
                    return True
            except Exception:
                pass
            time.sleep(0.5)
        return False

    def _find_and_click(self, texts, timeout=20, label="", tag_filter=None):
        start = time.time()
        while time.time() - start < timeout:
            for txt in texts:
                try:
                    eles = self.page.eles(f'text:{txt}', timeout=1)
                    for ele in eles:
                        try:
                            if tag_filter and ele.tag.lower() not in [t.lower() for t in tag_filter]:
                                continue
                            if ele.states.is_displayed:
                                ele.scroll.to_see()
                                self._delay(0.1, 0.3)
                                ele.click()
                                self.log(f"✅ 点击成功: '{txt}' <{ele.tag}> {f'({label})' if label else ''}")
                                return True
                        except Exception:
                            continue
                except Exception:
                    continue
            self._delay(1, 2)
        return False

    def _safe_type(self, locator, text):
        if isinstance(locator, str):
            target = self.page.ele(locator)
        else:
            target = locator
            
        if target:
            target.click()
            time.sleep(random.uniform(0.3, 0.7))
            
            # 使用更彻底的全选删除，应对部分 React 表单 clear() 失效的问题
            from DrissionPage.common import Keys
            try:
                # 物理删除 60 次退格键，无视任何选区失效的 bug
                for _ in range(60):
                    target.input(Keys.BACKSPACE)
                time.sleep(0.1)
            except Exception as e:
                self.log(f"⚠️ Keys 退格清理失败: {e}")
                target.clear()
                
            for char in text:
                target.input(char)
                delay = random.uniform(0.02, 0.12)
                if random.random() < 0.08:
                    delay += random.uniform(0.2, 0.5)
                time.sleep(delay)
            try:
                target.run_js(
                    """
                    this.dispatchEvent(new Event('input', { bubbles: true }));
                    this.dispatchEvent(new Event('change', { bubbles: true }));
                    this.blur && this.blur();
                    this.dispatchEvent(new Event('blur', { bubbles: true }));
                    """
                )
            except Exception as e:
                self.log(f"  [debug] 输入事件派发失败: {e}")
            time.sleep(random.uniform(0.2, 0.5))
            return True
        return False

    def _element_value(self, element) -> str:
        """读取输入框当前 value，用于确认 React 表单已同步。"""
        if not element:
            return ""
        try:
            value = element.attr('value')
            if value:
                return str(value)
        except Exception:
            pass
        try:
            return str(element.run_js('return this.value || "";') or "")
        except Exception:
            return ""

    def _safe_type_and_confirm(self, element, text: str, label: str, timeout: int = 8) -> bool:
        """输入文本并等待输入框 value 与目标值一致。"""
        for attempt in range(2):
            if not self._safe_type(element, text):
                continue
            start = time.time()
            while time.time() - start < timeout:
                if self._element_value(element) == text:
                    return True
                time.sleep(0.3)
            self.log(f"  [debug] {label} 输入值未同步，重试 ({attempt + 1}/2)")
        actual = self._element_value(element)
        self.log(f"⚠️ {label} 输入未确认，期望长度 {len(text)}，实际值: {actual!r}")
        return False

    def _find_visible_input(self, selectors, timeout: float = 0.5):
        for sel in selectors:
            try:
                ele = self.page.ele(sel, timeout=timeout)
                if ele and ele.states.is_displayed:
                    return ele
            except Exception:
                continue
        return None

    def _current_browser_location(self) -> str:
        """读取当前浏览器地址，优先用 JS 捕获 SPA hash 路由。"""
        try:
            href = self.page.run_js('return window.location.href || "";')
            if href:
                return str(href)
        except Exception:
            pass
        try:
            return str(self.page.url or "")
        except Exception:
            return ""

    @staticmethod
    def _url_indicates_email_verify(url: str) -> bool:
        normalized = (url or "").lower()
        return any(
            marker in normalized
            for marker in (
                "#/challenge/email-verification",
                "/challenge/email-verification",
                "email-verification/code",
            )
        )

    @staticmethod
    def _url_indicates_signup_profile(url: str) -> bool:
        normalized = (url or "").lower()
        if "email-verification" in normalized or "#/challenge" in normalized:
            return False
        return any(
            marker in normalized
            for marker in (
                "#/create-account/profile",
                "#/signup/profile",
                "signup/profile",
            )
        )

    def _is_signup_profile_step(self) -> bool:
        if self._url_indicates_signup_profile(self._current_browser_location()):
            return True
        return bool(self._find_visible_input(['#Signup-FirstNameField', 'input[name="firstName"]'], timeout=0.5))

    def _click_step1_continue(self, timeout: int = 12) -> bool:
        """点击邮箱/密码页的可用继续按钮，并确认页面进入下一步。"""
        start = time.time()
        while time.time() - start < timeout:
            if self._is_signup_profile_step() or self._is_email_verify_page():
                return True
            for sel in [
                'tag:button@@text():继续',
                'tag:button@@text():Continue',
                'button[type="submit"]',
            ]:
                try:
                    btn = self.page.ele(sel, timeout=0.5)
                    if not btn or not btn.states.is_displayed:
                        continue
                    disabled = str(btn.attr('disabled') or btn.attr('aria-disabled') or "").lower()
                    if disabled in {"true", "disabled"}:
                        continue
                    btn.scroll.to_see()
                    self._delay(0.2, 0.4)
                    btn.click()
                    self.log("✅ 点击成功: <button> (Step1 继续)")
                    return True
                except Exception as e:
                    self.log(f"  [debug] Step1 继续按钮点击失败 ({sel}): {e}")
            self._delay(0.5, 1)
        return False

    def _candidate_otp_contexts(self):
        """返回主页面和可能承载 Adobe 身份验证码输入框的可信 iframe。"""
        contexts = [("主页面", self.page)]
        try:
            iframes = self.page.eles('iframe', timeout=1)
        except Exception as e:
            self.log(f"  [debug] 枚举 iframe 失败: {e}")
            return contexts

        for idx, iframe in enumerate(iframes):
            try:
                src = iframe.attr('src') or ""
                title = iframe.attr('title') or ""
                if not _is_trusted_adobe_auth_frame(src, title):
                    self.log(f"  [debug] 跳过非 Adobe 身份验证 iframe[{idx}]: title='{title[:30]}' src='{src[:60]}'")
                    continue
                iframe_ctx = self.page.get_frame(iframe)
                if iframe_ctx:
                    contexts.append((f"iframe[{idx}] title='{title[:30]}' src='{src[:60]}'", iframe_ctx))
            except Exception as e:
                self.log(f"  [debug] 跳过不可访问 iframe[{idx}]: {e}")
        return contexts

    def _fill_otp_code(self, code: str) -> bool:
        """填写 Adobe 邮箱验证码，兼容单输入框、六宫格和 iframe。"""
        code = (code or "").strip()[:6]
        if not re.fullmatch(r"\d{6}", code):
            self.log(f"  [debug] 忽略非 6 位数字验证码: {code!r}")
            return False

        fill_js = _build_otp_fill_js(code)
        for context_label, context in self._candidate_otp_contexts():
            try:
                result = context.run_js(fill_js)
                self.log(f"  [debug] 验证码 JS 填写结果 ({context_label}): {result}")
                if isinstance(result, dict) and result.get("ok"):
                    return True
            except Exception as e:
                self.log(f"  [debug] 验证码 JS 填写异常 ({context_label}): {e}")

            try:
                code_inputs = context.eles('input[maxlength="1"]', timeout=1)
                if code_inputs and len(code_inputs) >= 6:
                    for i, digit in enumerate(code):
                        code_inputs[i].click()
                        self._delay(0.03, 0.08)
                        code_inputs[i].input(digit)
                    self.log(f"  [debug] 验证码逐格输入完成 ({context_label})")
                    return True

                for sel in ['input[autocomplete="one-time-code"]', 'input[name="code"]', 'input[id*="code"]', 'input[type="text"]']:
                    try:
                        cf = context.ele(sel, timeout=1)
                    except Exception as e:
                        self.log(f"  [debug] 验证码单框选择器不可用 ({context_label}, {sel}): {e}")
                        continue
                    if cf and cf.states.is_displayed and self._safe_type(cf, code):
                        self.log(f"  [debug] 验证码单框输入完成 ({context_label}, {sel})")
                        return True
            except Exception as e:
                self.log(f"  [debug] 验证码兜底输入异常 ({context_label}): {e}")

        return False

    def _is_arkose_visible(self) -> bool:
        """检测 Arkose Labs 人机验证是否仍在页面上。"""
        selectors = [
            'xpath://iframe[contains(@src, "arkoselabs")]',
            'xpath://iframe[contains(@src, "arks-client.adobe.com")]',
            'xpath://iframe[contains(@title, "Arkose")]',
            'xpath://iframe[contains(@title, "Verification challenge")]',
            'xpath://iframe[contains(@src, "funcaptcha")]',
        ]
        for sel in selectors:
            try:
                ele = self.page.ele(sel, timeout=0.5)
                if ele and ele.states.is_displayed:
                    return True
            except Exception:
                continue
        try:
            for iframe in self.page.eles("iframe", timeout=1) or []:
                src = str(iframe.attr("src") or "").lower()
                title = str(iframe.attr("title") or "").lower()
                if "arks-client.adobe.com" in src or "verification challenge" in title:
                    if iframe.states.is_displayed:
                        return True
        except Exception:
            pass
        return False

    def _fill_signup_credentials(self, email: str, password: str) -> str:
        self.log("[Adobe] 2. 填写邮箱与密码...")
        email_field = None
        for sel in ['#Signup-EmailField', '#EmailPage-EmailField', 'input[type="email"]']:
            email_field = self.page.ele(sel, timeout=3)
            if email_field:
                break

        if not email_field:
            self._find_and_click(['使用电子邮件注册', '使用电子邮件继续注册'], timeout=10, label="邮箱入口")
            self._wait_page_ready()
            for sel in ['#Signup-EmailField', '#EmailPage-EmailField', 'input[type="email"]']:
                email_field = self.page.ele(sel, timeout=3)
                if email_field:
                    break

        if not email_field:
            raise Exception("找不到邮箱输入框！")

        if not self._safe_type_and_confirm(email_field, email, "邮箱"):
            raise Exception("邮箱输入未完成，停止继续点击")
        self._delay(0.5, 1.0)

        pwd_field = None
        for sel in ['#Signup-PasswordField', '#PasswordPage-PasswordField', 'input[type="password"]']:
            pwd_field = self.page.ele(sel, timeout=3)
            if pwd_field:
                break

        if pwd_field and not self._safe_type_and_confirm(pwd_field, password, "密码"):
            raise Exception("密码输入未完成，停止继续点击")

        if not self._click_step1_continue(timeout=12):
            self.page.actions.key_down('Enter').key_up('Enter')
            self._delay(1, 2)

        step_wait_start = time.time()
        while time.time() - step_wait_start < 15:
            if self._is_signup_profile_step():
                return "profile"
            if self._is_email_verify_page():
                return "email_verify"
            if self._find_visible_input(['#Signup-PasswordField', '#PasswordPage-PasswordField', 'input[type="password"]'], timeout=0.5):
                break
            time.sleep(1)

        if not self._is_signup_profile_step() and not self._is_email_verify_page():
            raise Exception(f"Step1 继续后未进入资料页或验证码页，当前 URL: {self.page.url}")
        return "email_verify" if self._is_email_verify_page() else "profile"

    def _select_signup_birth_month(self, month: int) -> bool:
        month_field = self.page.ele('#Signup-DateOfBirthChooser-Month', timeout=3) or self.page.ele('[data-id="DateOfBirthChooser-Month"]', timeout=3)
        if not month_field:
            month_field = self.page.ele('select[name="month"]', timeout=3)
        if not month_field:
            return False
        try:
            month_field.select.by_value(str(month))
            return True
        except Exception:
            pass
        month_field.click()
        self._delay()
        month_names_zh = ["", "一月", "二月", "三月", "四月", "五月", "六月", "七月", "八月", "九月", "十月", "十一月", "十二月"]
        month_names_en = ["", "January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"]
        month_abbr_en = ["", "Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
        targets = [month_names_zh[month], month_names_en[month], month_abbr_en[month], f"{month}月", str(month)]

        def _month_committed() -> bool:
            try:
                value = str(month_field.attr('value') or "").strip()
                if value and value.lower() not in {"select", "select..."}:
                    return True
            except Exception:
                pass
            try:
                label = str(getattr(month_field, 'text', '') or "").strip()
                if label and "select" not in label.lower() and "选择" not in label and label != "...":
                    return True
            except Exception:
                pass
            return False

        start = time.time()
        while time.time() - start < 5:
            try:
                for option in self.page.eles('[role="option"]', timeout=1) or []:
                    option_text = str(option.text or "")
                    if option.states.is_displayed and any(target and target in option_text for target in targets):
                        option.click()
                        self._delay(0.2, 0.4)
                        return _month_committed()
            except Exception:
                pass
            if self._find_and_click([target for target in targets if target], timeout=1):
                return _month_committed()
        return False

    def _fill_signup_profile(self) -> None:
        prof = self._registration_profile
        self.log("[Adobe] 3. 填写个人资料信息...")
        if self._is_email_verify_page():
            self.log("[Adobe] 已直接进入邮箱验证码页，跳过个人资料填写")
            return
        if not self._is_signup_profile_step():
            raise Exception(f"未检测到个人资料页，停止提交注册，当前 URL: {self.page.url}")

        fn_field = self.page.ele('#Signup-FirstNameField', timeout=3) or self.page.ele('input[name="firstName"]', timeout=3)
        if not self._safe_type(fn_field, prof["fn"]):
            raise Exception("First name 输入失败")
        ln_field = self.page.ele('#Signup-LastNameField', timeout=3) or self.page.ele('input[name="lastName"]', timeout=3)
        if not self._safe_type(ln_field, prof["ln"]):
            raise Exception("Last name 输入失败")
        if not self._select_signup_birth_month(int(prof["month"])):
            raise Exception("Month 选择失败")
        self._delay(0.5)
        year_field = self.page.ele('#Signup-DateOfBirthChooser-Year', timeout=3) or self.page.ele('input[name="year"]', timeout=3)
        if not self._safe_type_and_confirm(year_field, str(prof["year"]), "出生年份"):
            raise Exception("Year 输入失败")
        self._delay(0.5, 1)

    def _submit_signup_profile(self) -> str:
        if self._is_email_verify_page():
            return "email_verify"
        self.log("[Adobe] 4. 提交注册...")
        url_before = self.page.url
        for err_text in ['不允许使用此电子邮件地址', '不符合我们的要求', 'Please use another email address', 'not permitted']:
            err_ele = self.page.ele(f'text:{err_text}', timeout=1)
            if err_ele and err_ele.states.is_displayed:
                raise Exception(f"暂不支持该邮箱域名: {err_ele.text}")

        submit_btn = self.page.ele('[data-id="Signup-CreateAccountBtn"]', timeout=2) or self.page.ele('tag:button@@text():创建帐户', timeout=2) or self.page.ele('tag:button@@text():Create account', timeout=2)
        if submit_btn and submit_btn.states.is_displayed:
            submit_btn.scroll.to_see()
            self._delay()
            submit_btn.click()
        else:
            self._find_and_click(['创建帐户', 'Create account'], timeout=5, tag_filter=['button'])

        self._wait_page_ready()
        self.log("[Adobe] 5. 等待 Arkose / 邮箱验证码环节...")
        submit_state = self._wait_after_submit_for_verification(url_before, timeout=300)
        if submit_state == "timeout":
            raise Exception("提交注册后等待 Arkose/邮箱验证码/成功跳转超时")
        return submit_state

    def _is_email_verify_page(self) -> bool:
        """检测是否已经进入 Adobe 邮箱验证码页面。"""
        if self._url_indicates_email_verify(self._current_browser_location()):
            return True

        verify_texts = ['验证您的电子邮件', '验证码', 'Verify your email', 'email verification', 'Enter the code']
        for _, context in self._candidate_otp_contexts():
            for txt in verify_texts:
                try:
                    ele = context.ele(f'text:{txt}', timeout=0.5)
                    if ele and ele.states.is_displayed:
                        return True
                except Exception:
                    continue
            try:
                code_inputs = context.eles('input[maxlength="1"]', timeout=0.5)
                if code_inputs and len(code_inputs) >= 6:
                    return True
            except Exception:
                continue
        return False

    def _wait_after_submit_for_verification(self, url_before: str, timeout: int = 300) -> str:
        """提交注册后等待 Arkose 通过、邮箱验证码页或成功跳转。"""
        start = time.time()
        saw_arkose = False
        last_log = 0.0
        while time.time() - start < timeout:
            cur_url = self._current_browser_location()
            if cur_url.startswith("https://firefly.adobe.com"):
                self.log("[Adobe] ✅ 已跳转到 Firefly，跳过邮箱验证码等待")
                return "success"

            if self._is_email_verify_page():
                if saw_arkose:
                    self.log("[Adobe] Arkose 已通过，检测到邮箱验证码页面")
                return "email_verify"

            if self._is_arkose_visible():
                saw_arkose = True
                now = time.time()
                if now - last_log > 15:
                    self.log("🧩 检测到 Arkose Labs 人机验证，请人工完成；脚本将持续等待通过...")
                    last_log = now
                time.sleep(2)
                continue

            if saw_arkose:
                self.log("[Adobe] Arkose 已消失，继续等待邮箱验证码页面...")
                saw_arkose = False

            if cur_url != url_before:
                self._wait_page_ready(5)

            time.sleep(2)

        self.log(f"⚠️ 提交注册后 {timeout}s 内未检测到 Arkose 通过后的邮箱验证码页，当前 URL: {self._current_browser_location()}")
        return "timeout"

    def _switch_to_existing_firefly_tab(self) -> bool:
        """Switch from a closed signup popup back to the existing Firefly parent tab."""
        saved_parent = getattr(self, '_firefly_parent_page', None)
        if saved_parent:
            try:
                parent_url = saved_parent.url or ""
            except Exception as exc:
                self.log(f"  [debug] 已保存的 Firefly 父页面不可用: {exc}")
            else:
                if parent_url.startswith("https://firefly.adobe.com"):
                    self.page = saved_parent
                    try:
                        self.page.set.activate()
                    except Exception:
                        pass
                    self.log(f"[Adobe] ✅ 已切回 Firefly 父页面: {parent_url}")
                    return True

        controller = self.page
        try:
            tab_ids = list(getattr(controller, 'tab_ids', []) or [])
        except Exception as exc:
            self.log(f"  [debug] 当前注册窗口无法读取标签页列表，尝试使用浏览器控制器: {exc}")
            try:
                controller = getattr(self.page, 'browser', None) or self._browser_controller or self.page
            except Exception as browser_exc:
                self.log(f"  [debug] 当前注册窗口无法读取 browser 引用，改用已保存控制器: {browser_exc}")
                controller = self._browser_controller or self.page

        try:
            tab_ids = list(getattr(controller, 'tab_ids', []) or [])
        except Exception as exc:
            self.log(f"  [debug] 读取标签页列表失败，无法切回 Firefly 父页面: {exc}")
            return False

        for tab_id in reversed(tab_ids):
            try:
                tab = controller.get_tab(tab_id)
            except Exception as exc:
                self.log(f"  [debug] 读取标签页失败({tab_id}): {exc}")
                continue
            if not tab or tab is self.page:
                continue
            try:
                tab_url = tab.url or ""
            except Exception as exc:
                self.log(f"  [debug] 标签页 URL 不可读({tab_id}): {exc}")
                continue
            if not tab_url.startswith("https://firefly.adobe.com"):
                continue
            self.page = tab
            try:
                self.page.set.activate()
            except Exception:
                pass
            self.log(f"[Adobe] ✅ 已切回 Firefly 父页面: {tab_url}")
            return True
        return False

    def init_browser(self):
        """初始化带有 Stealth 补丁的浏览器"""
        co = ChromiumOptions()
        self._user_data_dir = tempfile.mkdtemp(prefix="adobe_register_chrome_")
        co.set_user_data_path(self._user_data_dir)
        self.log(f"浏览器用户数据目录: {self._user_data_dir}")
        
        if self.headless:
            # 适配 DrissionPage v4 新版 API / 原生 Chrome args
            co.set_argument('--headless=new')
            co.set_argument('--disable-gpu')
        elif self.keep_browser_open:
            self.log("可视浏览器保持开启：脚本退出时不会自动关闭浏览器")
            
        co.set_argument('--ignore-certificate-errors')
        co.set_argument('--disable-notifications')
        if self.proxy:
            co.set_proxy(self.proxy)

        co.set_argument('--disable-blink-features=AutomationControlled')
        co.set_argument('--no-sandbox')
        co.set_argument('--disable-infobars')
        co.set_argument('--excludeSwitches=enable-automation')
        co.set_argument('--lang=zh-CN')
        co.set_argument(f'--window-size={VISIBLE_BROWSER_WIDTH},{VISIBLE_BROWSER_HEIGHT}')
        co.set_argument('--window-position=0,0')
        co.set_argument('--force-device-scale-factor=1')
        
        ua = UserAgent(os='windows', browsers=['chrome'])
        co.set_user_agent(ua.random)

        # 增加重试机制，防止第一次启动报错
        for attempt in range(3):
            try:
                self.page = ChromiumPage(co)
                break
            except Exception as e:
                self.log(f"浏览器启动失败 ({attempt+1}/3): {e}")
                if attempt == 2:
                    raise
                time.sleep(2)
        self._browser_controller = self.page
        
        try:
            self.page.run_js(STEALTH_JS)
            self.page.run_cdp('Page.addScriptToEvaluateOnNewDocument', source=STEALTH_JS)
        except Exception as e:
            self.log(f"隐身保护注入异常: {e}")
            
        self.page.set.window.size(VISIBLE_BROWSER_WIDTH, VISIBLE_BROWSER_HEIGHT)
        self.page.set.timeouts(base=10)

    def _get_browser_cookies(self):
        try:
            cdp_result = self.page.run_cdp('Network.getAllCookies')
            cookies = cdp_result.get('cookies', [])
            self.log(f"[Adobe] CDP getAllCookies 返回 {len(cookies)} 条")
            return cookies
        except Exception as cdp_err:
            self.log(f"⚠️ CDP getAllCookies 失败，回退 page.cookies: {cdp_err}")
            try:
                return self.page.cookies(all_domains=True)
            except TypeError:
                return self.page.cookies()

    def _log_cookie_expiry_summary(self, cookies, label: str):
        now = time.time()
        tracked = []
        for cookie in cookies:
            name = str(_cookie_field(cookie, "name", "")).strip()
            if not name or not _is_adobe_cookie(cookie):
                continue
            expires = _cookie_expires(cookie)
            ttl_seconds = None if expires is None or expires < 0 else max(0, int(expires - now))
            if name in ADOBE_AUTH_COOKIE_NAMES or ttl_seconds is None or ttl_seconds <= 3900:
                tracked.append((name, str(_cookie_field(cookie, "domain", "")), ttl_seconds))

        if not tracked:
            self.log(f"[Adobe] Cookie 有效期诊断({label}): 未发现 Adobe 短期/关键 Cookie")
            return

        for name, domain, ttl_seconds in tracked[:12]:
            ttl_text = "session" if ttl_seconds is None else f"{ttl_seconds // 60}分钟"
            self.log(f"  🍪 [Cookie有效期:{label}] {name} @ {domain} => {ttl_text}")

    def _wait_for_adobe_cookie_stability(self, initial_cookies):
        """Wait briefly for Firefly/Adobe front-end requests to refresh short-lived cookies."""
        cookies = initial_cookies
        start = time.time()
        while time.time() - start < ADOBE_COOKIE_STABLE_WAIT_SECONDS:
            adobe_cookies = [cookie for cookie in cookies if _is_adobe_cookie(cookie)]
            if not adobe_cookies:
                time.sleep(ADOBE_COOKIE_STABLE_INTERVAL_SECONDS)
                cookies = self._get_browser_cookies()
                continue

            auth_cookie_ttls = []
            for cookie in adobe_cookies:
                name = str(_cookie_field(cookie, "name", "")).strip()
                if name not in ADOBE_AUTH_COOKIE_NAMES:
                    continue
                expires = _cookie_expires(cookie)
                if expires is None or expires < 0:
                    continue
                auth_cookie_ttls.append(int(expires - time.time()))

            if not auth_cookie_ttls or min(auth_cookie_ttls) > 3900:
                return cookies

            self.log("[Adobe] 检测到 Adobe 登录关键 Cookie 仍接近 1 小时有效期，继续等待前端刷新...")
            time.sleep(ADOBE_COOKIE_STABLE_INTERVAL_SECONDS)
            cookies = self._get_browser_cookies()

        return cookies

    def extract_otp_code(self, html: str) -> str:
        """从原生邮件正文提取六位验证码"""
        patterns = [
            r'Verification code:?\s*(\d{6})',
            r'code is\s*(\d{6})',
            r'验证码[:：]?\s*(\d{6})',
            r'>\s*(\d{6})\s*<',
            r'\b(\d{6})\b',
        ]
        for p in patterns:
            m = re.search(p, html, re.IGNORECASE)
            if m and m.group(1) != "177010":
                return m.group(1)
        return ""

    def _register_account(self, email: str, password: str) -> None:
        self.log("[Adobe] 1. 使用当前 Adobe 注册页继续...")
        step_state = self._fill_signup_credentials(email, password)
        self._delay(3, 5)
        self._wait_page_ready()

        if step_state == "email_verify":
            verify_page = True
        else:
            self._fill_signup_profile()
            verify_page = self._submit_signup_profile() == "email_verify"

        if verify_page:
            self.log("📧 检测到验证码页面，呼叫 otp_callback 触发接码...")
            # 调用项目底层的全局 IMAP 接码机制 (包含轮询及阻塞等待)
            if not self._otp_callback:
                raise Exception("邮箱验证码页面需要接码，但未提供 otp_callback")
            code_found = False
            start_otp = time.time()
            while time.time() - start_otp < 120 and not code_found:
                result = self._otp_callback()
                if result:
                    # 兼容两种回调返回值：
                    # 1. 字符串 → 直接就是验证码 (来自 build_otp_callback / wait_for_code)
                    # 2. dict → 包含 html_body/body 的原始邮件内容
                    code = _extract_otp_code(result)
                     
                    if code:
                        self.log(f"🔑 拦截到验证码: {code}")
                        if not self._fill_otp_code(code):
                            self.log("  [debug] 未能找到或填入验证码输入框，继续等待页面稳定后重试")
                            time.sleep(5)
                            continue
                         
                        self._delay(1, 2)
                        self._find_and_click(['验证', '继续', 'Verify', 'Continue'], timeout=5, label="验证按钮", tag_filter=['button'])
                        self._delay(3, 5)
                        code_found = True
                        break
                time.sleep(5)
            
            if not code_found:
                raise Exception("邮箱验证码获取或输入超时")

    def _wait_registration_closure(self) -> None:
        try:
            # 6. 等待原生跳转回到 Firefly 主页
            # 千万不要用 page.get 去主动打断，因为后台正在创建账号并发放 ims_sid!
            self.log("[Adobe] 6. 等待原生注册流程闭环并重定向至 Firefly...")

            # 等待最长 60 秒让 Adobe 走完它所有的页面，期间遇到任何可以继续的按钮就点
            wait_time = 0
            while wait_time < 60:
                try:
                    cur_url = self.page.url or ""
                except Exception as exc:
                    self.log(f"⚠️ 注册窗口连接已断开，尝试切回 Firefly 父页面: {exc}")
                    if self._switch_to_existing_firefly_tab():
                        break
                    raise RuntimeError(f"注册窗口已关闭，但无法切回 Firefly 父页面: {exc}") from exc

                if cur_url.startswith("https://firefly.adobe.com"):
                    self.log("[Adobe] ✅ 原生跳转抵达 Firefly 主页！")
                    break

                # 如果卡在同意条款等页面
                try:
                    tos_texts = ['继续', '同意并继续', 'Continue', 'Agree and continue', '完成', 'Done', '跳过', 'Skip']
                    if not self.page.ele(f'@@tag()=button@@text():{tos_texts[0]}', timeout=0.1):
                        for txt in tos_texts:
                            ele = self.page.ele(f'text:{txt}', timeout=0.5)
                            if ele and ele.states.is_displayed and ele.tag.lower() in ('button', 'a', 'span'):
                                self.log(f"📋 检测到可能是拦截卡点按钮: '{txt}'，尝试点击...")
                                ele.click()
                                self._delay(1, 2)
                                break
                except Exception:
                    pass

                time.sleep(2)
                wait_time += 2
            else:
                self.log(f"⚠️ 60秒未回到火萤，当前停留网址: {self.page.url}")

            # 抵达火萤后，给前台 JS 10-15 秒的时间打底，确保任何后台的 Token check 走完
            self.log("[Adobe] 等待 Firefly 前端渲染和凭证稳定...")
            self._wait_page_ready(20)
            self._delay(10, 15)

        except Exception as e:
            self.log(f"⚠️ 耐心等待重定向环节发生异常: {e}")
            raise

    def _extract_and_push_cookies(self, email: str) -> str:
        # ============ 6. Firefly OAuth 授权 + 全域 Cookie 提取 ============
        cookie_str = ""
        self._wait_registration_closure()

        # 6b. 使用 CDP Network.getAllCookies 提取浏览器内全部域名的 Cookie
        # 关键：page.cookies() 可能不返回 HttpOnly Cookie (如 ims_sid)
        # 而 CDP Network.getAllCookies 等同于 chrome.cookies.getAll()，能获取全部 Cookie
        self.log("[Adobe] 6b. 提取全域 Cookie...")
        all_cookies = self._get_browser_cookies()
        self._log_cookie_expiry_summary(all_cookies, "初次提取")
        all_cookies = self._wait_for_adobe_cookie_stability(all_cookies)
        self._log_cookie_expiry_summary(all_cookies, "稳定后")
        
        # 诊断日志: 检查关键 Cookie 是否在原始列表中
        critical_keys = {'ims_sid', 'aux_sid', 'AWSELB', 'AWSELBCORS'}
        found_critical = set()
        for c in all_cookies:
            cname = c.get('name', '') if isinstance(c, dict) else getattr(c, 'name', '')
            if cname in critical_keys:
                cdomain = c.get('domain', '') if isinstance(c, dict) else getattr(c, 'domain', '')
                found_critical.add(cname)
                self.log(f"  🔑 [关键Cookie] {cname} @ {cdomain}")
        if not found_critical:
            self.log("  ⚠️ 未在浏览器中发现 ims_sid / aux_sid 等关键 Cookie")

        # 6c. 仅保留 Adobe 插件同等范围下的 Cookie，并按 domain|path|name 去重
        cookie_str = build_adobe_cookie_header(all_cookies)
        cookie_count = len([part for part in cookie_str.split("; ") if part])
        self.log(f"🍪 成功提取全域 Cookie (共 {cookie_count} 条, 长度: {len(cookie_str)})")

        # 6d. 自动推送至 adobe2api (保留原有逻辑)
        if cookie_str:
            import requests
            import os
            try:
                self.log("🚀 正在将新凭证 Cookie 推送至内置 adobe2api (6001)...")
                # 支持用户通过环境变量自定义地址，例如在 docker-compose 中配置 ADOBE2API_URL
                custom_url = os.environ.get("ADOBE2API_URL")
                
                if custom_url:
                    unsafe_allowed = str(os.environ.get("ADOBE2API_ALLOW_UNSAFE_REMOTE", "")).strip().lower() in {"1", "true", "yes", "on"}
                    if not unsafe_allowed and not _is_safe_cookie_export_url(custom_url):
                        self.log("⚠️ ADOBE2API_URL 指向非本地/内网地址，已拒绝发送 Adobe Cookie；如确需远程导出，请显式设置 ADOBE2API_ALLOW_UNSAFE_REMOTE=1")
                        return cookie_str
                    resp = requests.post(
                        custom_url, 
                        json={"cookie": cookie_str, "name": email},
                        timeout=4
                    )
                else:
                    # 兼容 Docker 环境内与 Host 主机间的通讯
                    try:
                        resp = requests.post(
                            "http://adobe2api:6001/api/v1/refresh-profiles/import-cookie", 
                            json={"cookie": cookie_str, "name": email},
                            timeout=4
                        )
                    except requests.exceptions.ConnectionError:
                        resp = requests.post(
                            "http://172.17.0.1:6001/api/v1/refresh-profiles/import-cookie", 
                            json={"cookie": cookie_str, "name": email},
                            timeout=4
                        )

                if resp.status_code == 200:
                    self.log("✅ 成功对接并导入至 adobe2api!")
                else:
                    self.log(f"⚠️ 导入 adobe2api 返回异常 Http {resp.status_code}")
            except Exception as he:
                self.log(f"⚠️ 尝试自动推送 adobe2api 失败 (请检查网络层或环境变量配置): {he}")
        return cookie_str

    def run(self, email: str, password: str) -> dict:
        self.log(f"[Adobe Browser] 开始初始化环境以注册 {email}...")
        self.init_browser()
        prof = self._gen_profile()
        self._registration_profile = prof

        try:
            self._register_account(email, password)
            cookie_str = self._extract_and_push_cookies(email)
            return {
                "email": email,
                "password": password,
                "token": cookie_str,  # 将完整 Cookie 填充至 Token 字段展示
                "extra": {"created_at": time.strftime("%Y-%m-%d %H:%M:%S")}
            }

        except Exception as e:
            self.log(f"注册崩溃异常: {e}")
            raise e
        finally:
            if self.page:
                if self.keep_browser_open:
                    self.log("可视浏览器已保留，请在检查完成后手动关闭窗口")
                else:
                    try:
                        self.page.quit()
                    finally:
                        self.page = None
            if self._user_data_dir and not self.keep_browser_open:
                import shutil
                try:
                    shutil.rmtree(self._user_data_dir, ignore_errors=True)
                except Exception as e:
                    self.log(f"⚠️ 清理浏览器用户数据目录失败: {e}")
