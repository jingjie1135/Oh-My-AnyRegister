import time
import random
import re
import logging
import os
import tempfile
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
            'xpath://iframe[contains(@title, "Arkose")]',
            'xpath://iframe[contains(@src, "funcaptcha")]',
        ]
        for sel in selectors:
            try:
                ele = self.page.ele(sel, timeout=0.5)
                if ele and ele.states.is_displayed:
                    return True
            except Exception:
                continue
        return False

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
        
        try:
            self.page.run_js(STEALTH_JS)
            self.page.run_cdp('Page.addScriptToEvaluateOnNewDocument', source=STEALTH_JS)
        except Exception as e:
            self.log(f"隐身保护注入异常: {e}")
            
        self.page.set.window.size(VISIBLE_BROWSER_WIDTH, VISIBLE_BROWSER_HEIGHT)
        self.page.set.timeouts(base=10)

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

    def run(self, email: str, password: str) -> dict:
        self.log(f"[Adobe Browser] 开始初始化环境以注册 {email}...")
        self.init_browser()
        prof = self._gen_profile()

        try:
            # 1. 导航
            self.log("[Adobe] 1. 导航到目标地址...")
            self.page.get(self.SIGNUP_URL)
            self._wait_page_ready(20)
            self._delay(2, 3)

            # 2. 账号填写
            self.log("[Adobe] 2. 填写邮箱与密码...")
            email_field = None
            for sel in ['#EmailPage-EmailField', '#Signup-EmailField', 'input[type="email"]']:
                email_field = self.page.ele(sel, timeout=3)
                if email_field:
                    break

            if not email_field:
                self._find_and_click(['使用电子邮件注册', '使用电子邮件继续注册'], timeout=10, label="邮箱入口")
                self._wait_page_ready()
                for sel in ['#EmailPage-EmailField', '#Signup-EmailField', 'input[type="email"]']:
                    email_field = self.page.ele(sel, timeout=3)
                    if email_field:
                        break

            if not email_field:
                raise Exception("找不到邮箱输入框！")

            if not self._safe_type_and_confirm(email_field, email, "邮箱"):
                raise Exception("邮箱输入未完成，停止继续点击")
            self._delay(0.5, 1.0)

            pwd_field = None
            for sel in ['#PasswordPage-PasswordField', '#Signup-PasswordField', 'input[type="password"]']:
                pwd_field = self.page.ele(sel, timeout=3)
                if pwd_field:
                    break
                
            if pwd_field:
                if not self._safe_type_and_confirm(pwd_field, password, "密码"):
                    raise Exception("密码输入未完成，停止继续点击")

            if not self._click_step1_continue(timeout=12):
                self.page.actions.key_down('Enter').key_up('Enter')
                self._delay(1, 2)

            step_wait_start = time.time()
            while time.time() - step_wait_start < 15:
                if self._is_signup_profile_step() or self._is_email_verify_page():
                    break
                if self._find_visible_input(['#PasswordPage-PasswordField', '#Signup-PasswordField', 'input[type="password"]'], timeout=0.5):
                    break
                time.sleep(1)

            if not self._is_signup_profile_step() and not self._is_email_verify_page():
                raise Exception(f"Step1 继续后未进入资料页或验证码页，当前 URL: {self.page.url}")

            self._delay(3, 5)
            self._wait_page_ready()

            # 3. 个人资料填写
            self.log("[Adobe] 3. 填写个人资料信息...")
            if self._is_email_verify_page():
                self.log("[Adobe] 已直接进入邮箱验证码页，跳过个人资料填写")
            elif not self._is_signup_profile_step():
                raise Exception(f"未检测到个人资料页，停止提交注册，当前 URL: {self.page.url}")
            elif not pwd_field:
                pwd_field2 = self.page.ele('input[type="password"]', timeout=3)
                if pwd_field2:
                    self._safe_type(pwd_field2, password)

            if self._is_signup_profile_step():
                fn_field = self.page.ele('#Signup-FirstNameField', timeout=3) or self.page.ele('input[name="firstName"]', timeout=3)
                if not self._safe_type(fn_field, prof["fn"]):
                    raise Exception("First name 输入失败")
                ln_field = self.page.ele('#Signup-LastNameField', timeout=3) or self.page.ele('input[name="lastName"]', timeout=3)
                if not self._safe_type(ln_field, prof["ln"]):
                    raise Exception("Last name 输入失败")

                month_field = self.page.ele('#Signup-DateOfBirthChooser-Month', timeout=3) or self.page.ele('select[name="month"]', timeout=3)
                if month_field:
                    try:
                        month_field.select.by_value(str(prof["month"]))
                    except Exception:
                        month_field.click()
                        self._delay()
                        month_names = ["", "一月", "二月", "三月", "四月", "五月", "六月", "七月", "八月", "九月", "十月", "十一月", "十二月"]
                        self._find_and_click([month_names[prof["month"]]], timeout=5)
                
                self._delay(0.5)
                year_field = self.page.ele('#Signup-DateOfBirthChooser-Year', timeout=3) or self.page.ele('input[name="year"]', timeout=3)
                if not self._safe_type(year_field, str(prof["year"])):
                    raise Exception("Year 输入失败")
                self._delay(0.5, 1)

            if self._is_email_verify_page():
                verify_page = True
            else:
                # 4. 提交
                self.log("[Adobe] 4. 提交注册...")
                url_before = self.page.url
                
                # 检测是否有错误提示
                for err_text in ['不允许使用此电子邮件地址', '不符合我们的要求', 'Please use another email address', 'not permitted']:
                    err_ele = self.page.ele(f'text:{err_text}', timeout=1)
                    if err_ele and err_ele.states.is_displayed:
                        raise Exception(f"暂不支持该邮箱域名: {err_ele.text}")
                
                submit_btn = self.page.ele('tag:button@@text():创建帐户', timeout=2) or self.page.ele('tag:button@@text():Create account', timeout=2)
                if submit_btn and submit_btn.states.is_displayed:
                    submit_btn.scroll.to_see()
                    self._delay()
                    submit_btn.click()
                else:
                    self._find_and_click(['创建帐户', 'Create account'], timeout=5, tag_filter=['button'])

                # 检测 Arkose / 邮箱验证码 / 成功跳转。
                # Arkose 通常需要人工介入，不能把短时间未出现邮箱验证码当作跳过。
                self._wait_page_ready()
                self.log("[Adobe] 5. 等待 Arkose / 邮箱验证码环节...")
                submit_state = self._wait_after_submit_for_verification(url_before, timeout=300)
                if submit_state == "timeout":
                    raise Exception("提交注册后等待 Arkose/邮箱验证码/成功跳转超时")
                verify_page = submit_state == "email_verify"

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

            # ============ 6. Firefly OAuth 授权 + 全域 Cookie 提取 ============
            cookie_str = ""
            try:
                # 6. 等待原生跳转回到 Firefly 主页
                # 千万不要用 page.get 去主动打断，因为后台正在创建账号并发放 ims_sid!
                self.log("[Adobe] 6. 等待原生注册流程闭环并重定向至 Firefly...")
                
                # 等待最长 60 秒让 Adobe 走完它所有的页面，期间遇到任何可以继续的按钮就点
                wait_time = 0
                while wait_time < 60:
                    cur_url = self.page.url or ""
                    
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

            # 6b. 使用 CDP Network.getAllCookies 提取浏览器内全部域名的 Cookie
            # 关键：page.cookies() 可能不返回 HttpOnly Cookie (如 ims_sid)
            # 而 CDP Network.getAllCookies 等同于 chrome.cookies.getAll()，能获取全部 Cookie
            self.log("[Adobe] 6b. 提取全域 Cookie...")
            all_cookies = []
            try:
                # 优先使用 CDP 协议获取完整 Cookie（包含 HttpOnly）
                cdp_result = self.page.run_cdp('Network.getAllCookies')
                all_cookies = cdp_result.get('cookies', [])
                self.log(f"[Adobe] CDP getAllCookies 返回 {len(all_cookies)} 条")
            except Exception as cdp_err:
                self.log(f"⚠️ CDP getAllCookies 失败，回退 page.cookies: {cdp_err}")
                try:
                    all_cookies = self.page.cookies(all_domains=True)
                except TypeError:
                    all_cookies = self.page.cookies()
            
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

            # 6c. 仅保留 Adobe 相关域名下的 Cookie (与浏览器插件提取范围一致)
            adobe_domains = ('adobe.com', 'firefly.adobe.com', 'account.adobe.com',
                             'auth.services.adobe.com', 'adobelogin.com')
            filtered = []
            seen_keys = set()

            for c in all_cookies:
                if isinstance(c, dict):
                    domain = str(c.get('domain', '')).lower().strip()
                    name = str(c.get('name', '')).strip()
                    value = str(c.get('value', '')).strip()
                else:
                    # 兼容某些版本返回 Cookie 对象
                    domain = str(getattr(c, 'domain', '')).lower().strip()
                    name = str(getattr(c, 'name', '')).strip()
                    value = str(getattr(c, 'value', '')).strip()

                if not name:
                    continue

                # 检查域名是否属于 Adobe 体系 (去除前导点的影响)
                clean_domain = domain.lstrip('.')
                is_adobe = any(clean_domain == d or clean_domain.endswith('.' + d) for d in adobe_domains)
                if not is_adobe:
                    continue

                # 去重 (与浏览器插件的 seen Set 逻辑一致)
                dedup_key = f"{domain}|{name}"
                if dedup_key in seen_keys:
                    continue
                seen_keys.add(dedup_key)
                filtered.append(f"{name}={value}")

            cookie_str = "; ".join(filtered)
            self.log(f"🍪 成功提取全域 Cookie (共 {len(filtered)} 条, 长度: {len(cookie_str)})")

            # 6d. 自动推送至 adobe2api (保留原有逻辑)
            if cookie_str:
                import requests
                import os
                try:
                    self.log("🚀 正在将新凭证 Cookie 推送至内置 adobe2api (6001)...")
                    # 支持用户通过环境变量自定义地址，例如在 docker-compose 中配置 ADOBE2API_URL
                    custom_url = os.environ.get("ADOBE2API_URL")
                    
                    if custom_url:
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
