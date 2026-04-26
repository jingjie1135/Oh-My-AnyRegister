"""
Adobe Firefly Pro Plus 免费试用自动订阅脚本

使用 DrissionPage 实现：
1. 登录 → 2. 直跳 checkout URL → 3. 切 iFrame 填卡 → 4. 填地址 → 5. 提交订阅

关键技术点：
- checkout 页面在 commerce.adobe.com 上，登录后直接跳转
- 信用卡输入框在跨域 iframe[data-testid="credit-form-iframe"] 中
- 主页面表单字段：#firstName, #lastName, #postalCode, #country
"""
from __future__ import annotations

import logging
import json
import os
import random
import re
import time
from dataclasses import dataclass
from typing import Callable, Optional
from urllib.parse import urlparse

from DrissionPage import ChromiumOptions, ChromiumPage

logger = logging.getLogger("adobe_subscribe")

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


def _extract_otp_code(result) -> str:
    """从 otp_callback 返回值中提取 6 位 Adobe 邮箱验证码。"""
    if isinstance(result, str):
        source = result.strip()
    elif isinstance(result, dict):
        source = result.get('html_body') or result.get('body') or result.get('content') or result.get('text') or ""
    else:
        return ""

    m = re.search(r'(?<!#)(?<!\d)(\d{6})(?!\d)', source)
    return m.group(1) if m else ""


def _build_otp_fill_js(code: str) -> str:
    """生成可同步 React/Vue 受控输入状态的验证码填写脚本。"""
    safe_code = json.dumps(code[:6])
    return f"""
        return (function(code) {{
            const isVisible = (el) => {{
                const rect = el.getBoundingClientRect();
                const style = window.getComputedStyle(el);
                return rect.width > 0 && rect.height > 0 && style.visibility !== 'hidden' && style.display !== 'none';
            }};
            const isUsable = (el) => !el.disabled && !el.readOnly && isVisible(el);
            const nativeValueSetter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set;
            const dispatch = (el, inputType, data) => {{
                try {{
                    el.dispatchEvent(new InputEvent('beforeinput', {{ bubbles: true, cancelable: true, inputType, data }}));
                }} catch (e) {{
                    el.dispatchEvent(new Event('beforeinput', {{ bubbles: true, cancelable: true }}));
                }}
                try {{
                    el.dispatchEvent(new InputEvent('input', {{ bubbles: true, inputType, data }}));
                }} catch (e) {{
                    el.dispatchEvent(new Event('input', {{ bubbles: true }}));
                }}
                el.dispatchEvent(new Event('change', {{ bubbles: true }}));
                el.dispatchEvent(new KeyboardEvent('keyup', {{ bubbles: true, key: data || '' }}));
                el.dispatchEvent(new Event('blur', {{ bubbles: true }}));
            }};
            const setValue = (el, value, inputType = 'insertText') => {{
                el.focus();
                nativeValueSetter.call(el, value);
                dispatch(el, inputType, value);
            }};

            const allInputs = Array.from(document.querySelectorAll('input'));
            const segmentedInputs = allInputs.filter((el) => {{
                const hint = [el.name, el.id, el.getAttribute('data-id'), el.getAttribute('aria-label'), el.placeholder, el.autocomplete]
                    .filter(Boolean).join(' ').toLowerCase();
                return isUsable(el) && (el.getAttribute('maxlength') === '1' || hint.includes('codeinput') || hint.includes('code-input'));
            }});
            if (segmentedInputs.length >= code.length) {{
                for (let i = 0; i < code.length; i += 1) {{
                    setValue(segmentedInputs[i], code[i]);
                }}
                const values = segmentedInputs.slice(0, code.length).map((el) => el.value || '');
                return {{ ok: values.join('') === code, mode: 'segmented', count: segmentedInputs.length, values }};
            }}

            const fullCodeInputs = allInputs.filter((el) => {{
                const hint = [el.name, el.id, el.getAttribute('data-id'), el.getAttribute('aria-label'), el.placeholder, el.autocomplete]
                    .filter(Boolean).join(' ').toLowerCase();
                const maxLength = Number.parseInt(el.getAttribute('maxlength') || '0', 10);
                return isUsable(el) && maxLength !== 1 && (maxLength >= 6 || hint.includes('code') || hint.includes('verification') || hint.includes('one-time-code') || hint.includes('one-time'));
            }});
            if (fullCodeInputs.length > 0) {{
                const input = fullCodeInputs[0];
                setValue(input, code, 'insertFromPaste');
                return {{ ok: input.value === code, mode: 'single', count: 1, values: [input.value] }};
            }}

            return {{ ok: false, mode: 'not_found', count: allInputs.length, values: [] }};
        }})({safe_code});
    """


def _is_trusted_adobe_auth_frame(src: str, title: str = "") -> bool:
    """只允许在 Adobe 登录/身份认证相关 iframe 中尝试填写 OTP。"""
    parsed = urlparse(src or "")
    host = (parsed.hostname or "").lower().strip(".")
    if not host:
        return False
    allowed_hosts = (
        "adobe.com",
        "adobelogin.com",
        "adobe.io",
        "adobecc.com",
        "services.adobe.com",
    )
    return any(host == item or host.endswith(f".{item}") for item in allowed_hosts)

# ── 常量 ──────────────────────────────────────────────────────

# Adobe 登录 URL
LOGIN_URL = (
    "https://auth.services.adobe.com/zh_HANS/deeplink.html"
    "?deeplink=signin"
    "&callback=https://firefly.adobe.com/"
    "&client_id=clio-playground-web"
)

# Pro Plus 免费试用 checkout URL
# items[0][id] = 商品 ID，apc = 促销代码
CHECKOUT_URL = (
    "https://commerce.adobe.com/store/checkout"
    "?items%5B0%5D%5Bid%5D=0BF366231CF390A0181EA88C96CCF989"
    "&co=US&lang=en&cli=firefly"
    "&apc=FFPLFFPU501YROW"
    "&workflowid=ondemand_purchase_subscription_workflow"
    "&ctx=if&csm=light"
)

# Stealth JS 防风控（复用 browser_register.py 的补丁）
STEALTH_JS = """
// 1. 消除 navigator.webdriver
Object.defineProperty(navigator, 'webdriver', {
    get: () => undefined, configurable: true,
});
// 2. 修复 window.chrome
if (!window.chrome) {
    window.chrome = { runtime: {
        onMessage: { addListener: function(){}, removeListener: function(){} },
        sendMessage: function(){},
    }};
}
// 3. 修复 Permissions API
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
        ];
        plugins.length = 3;
        return plugins;
    }, configurable: true,
});
// 5. 修复 navigator.languages
Object.defineProperty(navigator, 'languages', {
    get: () => ['en-US', 'en'], configurable: true,
});
// 6. 消除 CDP 痕迹
delete window.__cdp_binding__;
delete window.__selenium_unwrapped;
delete window.__driver_evaluate;
delete window.__webdriver_evaluate;
"""

# ── 订阅步骤定义 ──────────────────────────────────────────────

STEP_INIT       = "init"
STEP_LOGIN      = "login"
STEP_CHECKOUT   = "checkout"
STEP_FILL_CARD  = "fill_card"
STEP_FILL_ADDR  = "fill_address"
STEP_SUBMIT     = "submit"
STEP_VERIFY     = "verify"

STEP_LABELS = {
    STEP_INIT:      "初始化浏览器",
    STEP_LOGIN:     "登录 Adobe 账号",
    STEP_CHECKOUT:  "跳转到结算页",
    STEP_FILL_CARD: "填写信用卡信息 (iFrame)",
    STEP_FILL_ADDR: "填写账单地址",
    STEP_SUBMIT:    "提交订阅",
    STEP_VERIFY:    "等待订阅结果",
}


@dataclass
class SubscribeResult:
    """订阅执行结果"""
    success: bool
    stage: str         # 失败阶段
    message: str       # 人类可读的结果描述
    error: str = ""    # 错误详情


class AdobeBrowserSubscribe:
    """Adobe Firefly Pro Plus 免费试用自动订阅"""

    def __init__(
        self,
        headless: bool = True,
        proxy: Optional[str] = None,
        log_fn: Optional[Callable] = None,
        otp_callback: Optional[Callable] = None,
        screenshot_dir: Optional[str] = None,
        keep_browser_open: bool = False,
    ):
        self.headless = headless
        self.keep_browser_open = bool(keep_browser_open and not headless)
        self.proxy = proxy
        self.log = log_fn or logger.info
        self.otp_callback = otp_callback
        self.screenshot_dir = screenshot_dir
        self.page: Optional[ChromiumPage] = None
        self._current_step = ""

    def _take_screenshot(self, name: str):
        if not self.screenshot_dir or not self.page:
            return
        try:
            import time
            file_name = f"{int(time.time())}_{name}.png"
            self.page.get_screenshot(path=self.screenshot_dir, name=file_name)
        except Exception as e:
            self._debug(f"截图失败: {e}")

    def _set_step(self, step: str):
        """更新当前步骤并输出日志"""
        self._current_step = step
        label = STEP_LABELS.get(step, step)
        self.log(f"📌 步骤: {label}")
        self._take_screenshot(f"step_{step}")

    def _debug(self, msg: str):
        """输出调试日志"""
        self.log(f"  [debug] {msg}")

    def _delay(self, lo: float = 0.5, hi: float = 1.5):
        """随机延迟，模拟人类操作"""
        time.sleep(random.uniform(lo, hi))

    def _safe_type(self, element, text: str):
        """安全输入文本，逐字符模拟人类打字"""
        if not element:
            return False
        try:
            element.click()
            time.sleep(random.uniform(0.2, 0.5))
            # 先清除已有内容
            from DrissionPage.common import Keys
            for _ in range(30):
                element.input(Keys.BACKSPACE)
            time.sleep(0.1)
            # 逐字符输入
            for char in text:
                element.input(char)
                time.sleep(random.uniform(0.02, 0.08))
            time.sleep(random.uniform(0.2, 0.4))
            return True
        except Exception as e:
            self._debug(f"输入失败: {e}")
            return False

    def _find_visible_password_field(self, timeout: float = 0.5):
        """查找当前页面可见的 Adobe 密码输入框。"""
        for sel in ['#PasswordPage-PasswordField', 'input[type="password"]']:
            try:
                pwd_field = self.page.ele(sel, timeout=timeout)
                if pwd_field and pwd_field.states.is_displayed:
                    pwd_field.scroll.to_see()
                    return pwd_field
            except Exception:
                pass
        return None

    def _candidate_otp_contexts(self):
        """返回主页面和可能承载 Adobe 身份验证码输入框的 iframe 上下文。"""
        contexts = [("主页面", self.page)]
        try:
            iframes = self.page.eles('iframe', timeout=1)
        except Exception as e:
            self._debug(f"枚举 iframe 失败: {e}")
            return contexts

        for idx, iframe in enumerate(iframes):
            try:
                src = iframe.attr('src') or ""
                title = iframe.attr('title') or ""
                if not _is_trusted_adobe_auth_frame(src, title):
                    self._debug(f"跳过非 Adobe 身份验证 iframe[{idx}]: title='{title[:30]}' src='{src[:60]}'")
                    continue
                iframe_ctx = self.page.get_frame(iframe)
                if iframe_ctx:
                    contexts.append((f"iframe[{idx}] title='{title[:30]}' src='{src[:60]}'", iframe_ctx))
            except Exception as e:
                self._debug(f"跳过不可访问 iframe[{idx}]: {e}")
        return contexts

    def _fill_otp_code(self, code: str) -> bool:
        """填写 Adobe 邮箱验证码，兼容单输入框、六宫格和 iframe。"""
        code = (code or "").strip()[:6]
        if not re.fullmatch(r"\d{6}", code):
            self._debug(f"忽略非 6 位数字验证码: {code!r}")
            return False

        fill_js = _build_otp_fill_js(code)
        for context_label, context in self._candidate_otp_contexts():
            try:
                result = context.run_js(fill_js)
                self._debug(f"验证码 JS 填写结果 ({context_label}): {result}")
                if isinstance(result, dict) and result.get("ok"):
                    return True
            except Exception as e:
                self._debug(f"验证码 JS 填写异常 ({context_label}): {e}")

            try:
                code_inputs = context.eles('input[maxlength="1"]', timeout=1)
                if code_inputs and len(code_inputs) >= 6:
                    for i, digit in enumerate(code):
                        code_inputs[i].click()
                        self._delay(0.03, 0.08)
                        code_inputs[i].input(digit)
                    self._debug(f"验证码逐格输入完成 ({context_label})")
                    return True

                for sel in ['input[autocomplete="one-time-code"]', 'input[name="code"]', 'input[id*="code"]', 'input[type="text"]']:
                    try:
                        cf = context.ele(sel, timeout=1)
                    except Exception as e:
                        self._debug(f"验证码单框选择器不可用 ({context_label}, {sel}): {e}")
                        continue
                    if cf and cf.states.is_displayed and self._safe_type(cf, code):
                        self._debug(f"验证码单框输入完成 ({context_label}, {sel})")
                        return True
            except Exception as e:
                self._debug(f"验证码兜底输入异常 ({context_label}): {e}")

        return False

    def _init_browser(self):
        """初始化带 Stealth 补丁的浏览器"""
        self._set_step(STEP_INIT)

        import os
        import subprocess

        # 清理残留的浏览器进程和锁文件，防止端口占用
        self._debug("清理之前的浏览器进程与状态...")
        try:
            subprocess.run(["pkill", "-9", "-f", "chrome"], stderr=subprocess.DEVNULL)
            subprocess.run(["pkill", "-9", "-f", "chromium"], stderr=subprocess.DEVNULL)
            os.system("rm -rf /tmp/Crashpad /tmp/.DrissionPage*")
            os.system("rm -f /tmp/chrome_subscribe_userdata/SingletonLock")
        except Exception as e:
            self._debug(f"清理环境异常 (不影响常规执行): {e}")

        co = ChromiumOptions()
        # 使用隔离的用户数据目录，避免和注册脚本冲突
        co.set_user_data_path("/tmp/chrome_subscribe_userdata")

        if self.headless:
            co.set_argument('--headless=new')
            co.set_argument('--disable-gpu')
            self._debug("浏览器模式: headless")
        else:
            self._debug("浏览器模式: headed (可视化)")
            if self.keep_browser_open:
                self._debug("可视浏览器保持开启：脚本退出时不会自动关闭浏览器")

        co.set_argument('--ignore-certificate-errors')
        co.set_argument('--disable-notifications')
        co.set_argument('--disable-blink-features=AutomationControlled')
        co.set_argument('--no-sandbox')
        co.set_argument('--disable-infobars')
        co.set_argument('--disable-dev-shm-usage')
        co.set_argument('--excludeSwitches=enable-automation')
        co.set_argument('--lang=en-US')
        co.set_argument(f'--window-size={VISIBLE_BROWSER_WIDTH},{VISIBLE_BROWSER_HEIGHT}')
        co.set_argument('--window-position=0,0')
        co.set_argument('--force-device-scale-factor=1')
        if self.proxy:
            co.set_proxy(self.proxy)
            self._debug(f"代理: {self.proxy}")

        from fake_useragent import UserAgent
        ua = UserAgent(os='windows', browsers=['chrome'])
        ua_str = ua.random
        co.set_user_agent(ua_str)
        self._debug(f"UA: {ua_str[:60]}...")

        # 增加重试机制，防止第一次启动报错
        for attempt in range(3):
            try:
                self.page = ChromiumPage(co)
                break
            except Exception as e:
                self._debug(f"浏览器启动失败 ({attempt+1}/3): {e}")
                if attempt == 2:
                    raise
                time.sleep(2)

        try:
            self.page.run_js(STEALTH_JS)
            self.page.run_cdp('Page.addScriptToEvaluateOnNewDocument', source=STEALTH_JS)
            self._debug("Stealth JS 注入成功")
        except Exception as e:
            self._debug(f"Stealth 注入异常: {e}")

        self.page.set.window.size(VISIBLE_BROWSER_WIDTH, VISIBLE_BROWSER_HEIGHT)
        self.page.set.timeouts(base=15)
        self.log("✅ 浏览器初始化完成")

    def _wait_page_ready(self, timeout: int = 20) -> bool:
        """等待页面完全加载"""
        start = time.time()
        while time.time() - start < timeout:
            try:
                state = self.page.run_js("document.readyState")
                if state in ["complete", "interactive"]:
                    time.sleep(0.5)
                    return True
            except Exception:
                pass
            time.sleep(0.5)
        self._debug(f"页面在 {timeout}s 内未进入准备状态")
        return False

    def _do_login(self, email: str, password: str) -> SubscribeResult | None:
        """执行 Adobe 登录流程，成功返回 None，失败返回 SubscribeResult"""
        self._set_step(STEP_LOGIN)
        self._debug(f"目标账号: {email}")

        self.page.get(LOGIN_URL)
        self._wait_page_ready(20)
        self._delay(2, 3)
        self._debug(f"当前 URL: {self.page.url}")

        # 输入邮箱
        email_field = None
        for sel in ['#EmailPage-EmailField', 'input[type="email"]', 'input[name="username"]']:
            email_field = self.page.ele(sel, timeout=3)
            if email_field:
                self._debug(f"邮箱输入框: {sel}")
                break
        if not email_field:
            return SubscribeResult(False, STEP_LOGIN, "找不到邮箱输入框", "email_field_not_found")

        self._safe_type(email_field, email)
        self._delay(0.3, 0.8)

        # 点击继续
        self._debug("点击继续按钮...")
        continue_clicked = False
        for text in ['继续', 'Continue']:
            try:
                eles = self.page.eles(f'text:{text}', timeout=2)
                for ele in eles:
                    if ele.tag.lower() in ['button', 'a', 'span'] and ele.states.is_displayed:
                        try:
                            self.page.actions.move_to(ele).click()
                            self._delay(0.5, 1)
                            if ele.states.is_displayed:
                                ele.click(by_js=True)
                        except Exception:
                            try:
                                ele.click(by_js=True)
                            except Exception:
                                pass
                        continue_clicked = True
                        self._debug(f"点击了 '{text}'")
                        break
                if continue_clicked:
                    break
            except Exception:
                continue
        if not continue_clicked:
            try:
                self.page.actions.key_down('Enter').key_up('Enter')
                self._debug("使用 Enter 键继续")
            except Exception:
                pass

        self._delay(2, 3)
        self._wait_page_ready()

        # =========================================================
        # 核心改动：自适应登录循环 (最大耗时 120 秒)
        # 不再硬编码验证顺序 (如：密码 -> MFA，或 MFA -> 密码)
        # 而是不断检测当前页面出现了什么元素，出现了什么就填什么
        # =========================================================
        self._debug("开始自适应检测登录阶段 (密码 / MFA / 登录成功) ...")
        start_time = time.time()
        
        handled_password = False
        handled_mfa = False

        while time.time() - start_time < 120:
            cur_url = self.page.url or ""
            # 1. 成功判断
            if 'firefly.adobe.com' in cur_url or 'commerce.adobe.com' in cur_url:
                if 'deeplink.html' not in cur_url:
                    self.log(f"✅ 登录成功 → {cur_url[:60]}")
                    return None

            # 2. 密码错误判断 (只从可见元素找，不能查全页面 html，会把 js/正则 里的 incorrect 也匹配到)
            err_box = self.page.ele('.error-message', timeout=0.1) or self.page.ele('css:[data-id="PasswordPage-ErrorIndicator"]', timeout=0.1)
            if err_box and err_box.states.is_displayed:
                err_text = err_box.text.lower()
                if '密码错误' in err_text or 'incorrect' in err_text or 'wrong password' in err_text or '不正确' in err_text:
                    return SubscribeResult(False, STEP_LOGIN, "密码错误", "wrong_password")
            
            # 或者兜底直接查这几个关键字的可见元素
            for p_err in ['密码错误', '密码不正确', 'Incorrect password', 'Wrong password']:
                try:
                    p_ele = self.page.ele(f'text:{p_err}', timeout=0.1)
                    if p_ele and p_ele.states.is_displayed:
                        return SubscribeResult(False, STEP_LOGIN, "密码错误", "wrong_password")
                except Exception:
                    pass

            # 3. 密码框检测
            if not handled_password:
                pwd_field = self._find_visible_password_field(timeout=0.5)

                if pwd_field:
                    self._debug("找到密码输入框，开始输入...")
                    self._safe_type(pwd_field, password)
                    self._delay(0.3, 0.8)

                    # 点击登录/继续
                    login_clicked = False
                    for text in ['继续', 'Continue', '登录', 'Sign in']:
                        try:
                            eles = self.page.eles(f'text:{text}', timeout=0.5)
                            for ele in eles:
                                if ele.tag.lower() in ['button', 'a', 'span'] and ele.states.is_displayed:
                                    ele.click()
                                    login_clicked = True
                                    self._debug(f"点击了密码界面的 '{text}'")
                                    break
                            if login_clicked:
                                break
                        except Exception:
                            continue
                    
                    if not login_clicked:
                        try:
                            self.page.actions.key_down('Enter').key_up('Enter')
                        except Exception:
                            pass
                    
                    handled_password = True
                    self._delay(3, 5)
                    self._wait_page_ready()
                    continue

            # 4. MFA (验证码) 检测
            if not handled_mfa:
                is_mfa = False
                if ('challenge/mfa' in cur_url or 'challenge/verify' in cur_url
                        or self.page.ele('text:验证您的电子邮件', timeout=0.5)
                        or self.page.ele('text:验证您的身份', timeout=0.5)
                        or self.page.ele('text:Verify your identity', timeout=0.5)
                        or self.page.ele('text:Enter the code', timeout=0.5)
                        or self.page.ele('text:获取验证码', timeout=0.5)
                        or self.page.ele('text:获取代码', timeout=0.5)
                        or self.page.ele('text:Send code', timeout=0.5)
                        or self.page.ele('text:Verify your changing', timeout=0.5)):
                    is_mfa = True

                if is_mfa:
                    self._take_screenshot("detected_mfa_verify")
                    self.log("🛡️ 检测到 MFA 邮箱验证，进入接码流程...")
                    
                    # 某些页面需要先手动点一次"发送验证码"或"继续"
                    send_btn = False
                    for text in ['继续', 'Continue', 'Send code', '发送验证码']:
                        try:
                            eles = self.page.eles(f'text:{text}', timeout=0.5)
                            for ele in eles:
                                if ele.tag.lower() in ['button', 'a', 'span'] and ele.states.is_displayed:
                                    try:
                                        self.page.actions.move_to(ele).click()
                                        if ele.states.is_displayed:
                                            ele.click(by_js=True)
                                    except Exception:
                                        self._debug(f"点击触发验证码按钮 '{text}' 失败，继续尝试其它按钮")
                                    send_btn = True
                                    self._debug(f"点击了触发验证码的 '{text}'")
                                    break
                            if send_btn:
                                break
                        except Exception as e:
                            self._debug(f"查找触发验证码按钮 '{text}' 异常: {e}")
                    
                    if send_btn:
                        self._delay(2, 3)

                    if not self.otp_callback:
                        return SubscribeResult(False, STEP_LOGIN, "遇到 MFA 验证码需填写，但未提供 otp_callback", "otp_challenge_failed")

                    self.log("💬 正在等待邮箱拉取 Adobe 验证码...")
                    code_found = False
                    mfa_transitioned_to_password = False
                    mfa_timeout = time.time()
                    while time.time() - mfa_timeout < 100:
                        try:
                            if not handled_password and self._find_visible_password_field(timeout=0.2):
                                self._debug("MFA 后检测到密码输入框，退出验证码循环并回到登录阶段")
                                mfa_transitioned_to_password = True
                                break

                            result = self.otp_callback()
                            if result:
                                code = _extract_otp_code(result)
                                  
                                if code and code != "000000":
                                    self.log(f"🔑 成功获取验证码: {code}，正在填入...")
                                    if not self._fill_otp_code(code):
                                        if not handled_password and self._find_visible_password_field(timeout=0.2):
                                            self._debug("验证码提交后已进入密码页，停止重试验证码")
                                            mfa_transitioned_to_password = True
                                            break
                                        self._debug("未能找到或填入验证码输入框，继续等待页面稳定后重试")
                                        self._take_screenshot("otp_input_not_found")
                                        time.sleep(5)
                                        continue
                                     
                                    self._take_screenshot("inputted_otp_code")
                                    self._delay(1, 2)
                                    
                                    # 提交验证码
                                    submit_found = False
                                    for text in ['验证', '继续', 'Verify', 'Continue', '提交', 'Submit']:
                                        try:
                                            eles = self.page.eles(f'text:{text}', timeout=0.5)
                                            for ele in eles:
                                                if ele.tag.lower() in ['button', 'a', 'span'] and ele.states.is_displayed:
                                                    ele.click()
                                                    submit_found = True
                                                    break
                                            if submit_found:
                                                break
                                        except Exception:
                                            continue
                                    
                                    code_found = True
                                    handled_mfa = True
                                    self._delay(3, 5)
                                    break
                        except Exception as e:
                            self._debug(f"otp_callback 处理异常: {e}")
                        
                        time.sleep(5)

                    if mfa_transitioned_to_password:
                        self._wait_page_ready()
                        continue
                     
                    if not code_found:
                        return SubscribeResult(False, STEP_LOGIN, "等待登录验证码超时", "otp_timeout")
                    
                    # 验证成功，重置一下等待并回到最外层循环检测是否登录成功或还有密码流程
                    self._wait_page_ready()
                    continue

            # 5. 为了防止刷太多无用日志，主循环稍微停顿
            time.sleep(1)

        self._debug(f"登录自适应循环超时 (120s)，最终 URL: {self.page.url}")
        return SubscribeResult(False, STEP_LOGIN, "登录阶段超时未达预期点", "login_timeout")

    def _navigate_checkout(self) -> SubscribeResult | None:
        """跳转到 checkout 页面"""
        self._set_step(STEP_CHECKOUT)

        self.page.get(CHECKOUT_URL)
        self._delay(3, 5)
        self._wait_page_ready(30)
        self._debug(f"checkout URL: {self.page.url}")

        # 验证是否到达 checkout 页面
        for i in range(15):
            try:
                url = self.page.url
                if 'commerce.adobe.com' in url and 'checkout' in url:
                    self.log("✅ 已到达结算页")
                    return None
                self._debug(f"等待 checkout 加载... ({i+1}/15) URL: {url[:80]}")
            except Exception:
                pass
            time.sleep(1)

        return SubscribeResult(False, STEP_CHECKOUT, "无法到达结算页面", "checkout_unreachable")

    def _fill_card(self, card_number: str, exp_month: str, exp_year: str, cvc: str) -> SubscribeResult | None:
        """切入信用卡 iFrame 填写卡号和有效期"""
        self._set_step(STEP_FILL_CARD)
        self._delay(2, 3)

        # 等待信用卡 iframe 加载
        card_iframe = None
        for attempt in range(20):
            try:
                card_iframe = self.page.ele('iframe[data-testid="credit-form-iframe"]', timeout=2)
                if card_iframe:
                    self._debug(f"找到 iframe (尝试 {attempt+1})")
                    break
            except Exception:
                pass
            time.sleep(1)

        if not card_iframe:
            # 备用选择器
            try:
                card_iframe = self.page.ele('iframe[title="Card information"]', timeout=5)
                if card_iframe:
                    self._debug("使用备用选择器找到 iframe")
            except Exception:
                pass

        if not card_iframe:
            self._debug("页面 HTML 片段:")
            try:
                # 输出 iframe 列表用于调试
                iframes = self.page.eles('iframe')
                for idx, f in enumerate(iframes):
                    self._debug(f"  iframe[{idx}]: src={f.attr('src')[:80] if f.attr('src') else '-'} testid={f.attr('data-testid') or '-'}")
            except Exception as e:
                self._debug(f"  获取 iframe 列表失败: {e}")
            return SubscribeResult(False, STEP_FILL_CARD, "信用卡 iFrame 未加载", "iframe_not_found")

        # 切入 iframe
        iframe_page = None
        try:
            iframe_page = self.page.get_frame(card_iframe)
            self._debug("iframe 切换方式: get_frame(element)")
        except Exception as e:
            self._debug(f"get_frame(element) 失败: {e}")
            try:
                iframe_page = self.page.get_frame('iframe[data-testid="credit-form-iframe"]')
                self._debug("iframe 切换方式: get_frame(selector)")
            except Exception as e2:
                return SubscribeResult(False, STEP_FILL_CARD, f"无法切入信用卡 iFrame: {e2}", "iframe_switch_failed")

        if not iframe_page:
            return SubscribeResult(False, STEP_FILL_CARD, "无法获取 iFrame 内容", "iframe_content_null")

        # 在 iframe 内填写卡号
        try:
            card_input = None
            for sel in ['input[name="cardNumber"]', 'input[placeholder*="Card number"]',
                        'input[autocomplete="cc-number"]', '#cardNumber', 'input[type="tel"]']:
                try:
                    card_input = iframe_page.ele(sel, timeout=3)
                    if card_input:
                        self._debug(f"卡号输入框: {sel}")
                        break
                except Exception:
                    continue

            if not card_input:
                card_input = iframe_page.ele('input', timeout=3)
                if card_input:
                    self._debug("使用兜底选择器: 第一个 input")

            if not card_input:
                return SubscribeResult(False, STEP_FILL_CARD, "iFrame 内找不到卡号输入框", "card_input_not_found")

            self._safe_type(card_input, card_number)
            self.log(f"✅ 卡号已填写 (****{card_number[-4:]})")
            self._delay(0.3, 0.6)

            # 填写有效期 (MM/YY 或 MMYY)
            exp_value = f"{exp_month.zfill(2)}{exp_year[-2:]}"
            exp_input = None
            for sel in ['input[name="cardExpirationDate"]', 'input[placeholder*="MM"]',
                        'input[autocomplete="cc-exp"]', '#cardExpirationDate']:
                try:
                    exp_input = iframe_page.ele(sel, timeout=3)
                    if exp_input:
                        self._debug(f"有效期输入框: {sel}")
                        break
                except Exception:
                    continue

            if exp_input:
                self._safe_type(exp_input, exp_value)
                self.log(f"✅ 有效期已填写 ({exp_month}/{exp_year[-2:]})")
            else:
                self._debug("未找到有效期输入框，可能与卡号合并")

            # 填写 CVC
            cvc_input = None
            for sel in ['input[name="securityCode"]', 'input[placeholder*="CVC"]',
                        'input[autocomplete="cc-csc"]', '#securityCode', 'input[placeholder*="CVV"]']:
                try:
                    cvc_input = iframe_page.ele(sel, timeout=3)
                    if cvc_input:
                        self._debug(f"CVC 输入框: {sel}")
                        break
                except Exception:
                    continue

            if cvc_input:
                self._safe_type(cvc_input, cvc)
                self.log("✅ CVC 已填写")
            else:
                self._debug("未找到 CVC 输入框")

        except Exception as e:
            return SubscribeResult(False, STEP_FILL_CARD, f"填写卡信息异常: {e}", "card_fill_error")

        return None  # 成功

    def _fill_address(self, first_name: str, last_name: str, postal_code: str) -> SubscribeResult | None:
        """在主页面填写账单地址"""
        self._set_step(STEP_FILL_ADDR)

        try:
            # firstName
            fn_field = self.page.ele('#firstName', timeout=5)
            if fn_field:
                self._safe_type(fn_field, first_name)
                self._debug(f"First name: {first_name}")
            else:
                self._debug("#firstName 未找到")

            # lastName
            ln_field = self.page.ele('#lastName', timeout=3)
            if ln_field:
                self._safe_type(ln_field, last_name)
                self._debug(f"Last name: {last_name}")
            else:
                self._debug("#lastName 未找到")

            # postalCode
            zip_field = self.page.ele('#postalCode', timeout=3)
            if zip_field:
                self._safe_type(zip_field, postal_code)
                self._debug(f"Zip code: {postal_code}")
            else:
                self._debug("#postalCode 未找到")

            self.log("✅ 账单地址已填写")
            self._delay(0.5, 1.0)

        except Exception as e:
            return SubscribeResult(False, STEP_FILL_ADDR, f"填写地址异常: {e}", "address_fill_error")

        return None  # 成功

    def _submit_subscribe(self) -> SubscribeResult:
        """点击提交按钮并检测结果"""
        self._set_step(STEP_SUBMIT)

        # 查找提交按钮
        submit_btn = None
        for sel in ['text:Agree and subscribe', 'text:同意并订阅',
                     'button.ActionContainer__actionButton',
                     'button:has-text("Agree")', 'button:has-text("subscribe")']:
            try:
                submit_btn = self.page.ele(sel, timeout=3)
                if submit_btn and submit_btn.states.is_displayed:
                    self._debug(f"提交按钮: {sel}")
                    break
                submit_btn = None
            except Exception:
                continue

        if not submit_btn:
            self._debug("查找所有按钮...")
            try:
                btns = self.page.eles('button')
                for idx, b in enumerate(btns):
                    if b.states.is_displayed:
                        self._debug(f"  button[{idx}]: text='{b.text[:40]}' class='{b.attr('class')[:50] if b.attr('class') else ''}'")
            except Exception:
                pass
            return SubscribeResult(False, STEP_SUBMIT, "找不到提交按钮", "submit_btn_not_found")

        try:
            submit_btn.scroll.to_see()
            self._delay(0.3, 0.5)
            submit_btn.click()
            self.log("✅ 已点击「Agree and subscribe」")
        except Exception as e:
            return SubscribeResult(False, STEP_SUBMIT, f"点击提交按钮失败: {e}", "submit_click_error")

        # 等待并检测结果
        self._set_step(STEP_VERIFY)
        self._debug("等待支付处理结果...")

        for i in range(60):
            try:
                page_text = (self.page.html or "").lower()
                url = self.page.url or ""

                # 检测成功
                success_signals = [
                    'thank you', 'order confirmed', 'successfully subscribed',
                    'subscription confirmed', '订阅成功', '感谢您的购买',
                    'welcome to', 'your plan',
                ]
                if any(sig in page_text for sig in success_signals):
                    self.log("🎉 订阅成功！")
                    return SubscribeResult(True, STEP_VERIFY, "订阅成功")

                # 检测失败
                fail_signals = [
                    ('card was declined', '银行卡被拒'),
                    ('card_declined', '银行卡被拒'),
                    ('insufficient funds', '余额不足'),
                    ('expired card', '卡已过期'),
                    ('invalid card', '卡信息无效'),
                    ('payment failed', '支付失败'),
                    ('unable to process', '无法处理'),
                ]
                for pattern, msg in fail_signals:
                    if pattern in page_text:
                        self.log(f"❌ 支付失败: {msg}")
                        return SubscribeResult(False, STEP_VERIFY, msg, pattern)

                # 检测页面跳转
                if 'firefly.adobe.com' in url and 'checkout' not in url:
                    self.log("🎉 已跳转回 Firefly，订阅完成")
                    return SubscribeResult(True, STEP_VERIFY, "页面已跳转回 Firefly，订阅完成")

                if i % 10 == 9:
                    self._debug(f"仍在等待中... ({i+1}/60s) URL: {url[:60]}")

            except Exception:
                pass
            time.sleep(1)

        return SubscribeResult(False, STEP_VERIFY, "等待超时，请手动检查订阅状态", "result_timeout")

    def run(
        self,
        email: str,
        password: str,
        card_number: str,
        exp_month: str,
        exp_year: str,
        cvc: str,
        first_name: Optional[str] = None,
        last_name: Optional[str] = None,
        postal_code: Optional[str] = None,
    ) -> SubscribeResult:
        """
        执行完整的订阅流程

        Args:
            email: Adobe 账号邮箱
            password: Adobe 账号密码
            card_number: 虚拟卡号
            exp_month: 有效期月 (MM)
            exp_year: 有效期年 (YY 或 YYYY)
            cvc: 安全码
            first_name: 账单名（可选，不填则随机生成）
            last_name: 账单姓（可选，不填则随机生成）
            postal_code: 邮编（可选，不填则随机生成）
        """
        # 生成随机地址信息（如果未提供）
        from core.virtual_card import generate_random_address
        if not first_name or not last_name or not postal_code:
            addr = generate_random_address()
            first_name = first_name or addr.first_name
            last_name = last_name or addr.last_name
            postal_code = postal_code or addr.postal_code
            self._debug(f"随机地址: {first_name} {last_name}, ZIP={postal_code}")

        try:
            # 1. 初始化浏览器
            self._init_browser()

            # 2. 登录
            result = self._do_login(email, password)
            if result:
                return result

            # 3. 跳转 checkout
            result = self._navigate_checkout()
            if result:
                return result

            # 4. 填写信用卡
            result = self._fill_card(card_number, exp_month, exp_year, cvc)
            if result:
                return result

            # 5. 填写地址
            result = self._fill_address(first_name, last_name, postal_code)
            if result:
                return result

            # 6. 提交订阅
            return self._submit_subscribe()

        except Exception as e:
            self._take_screenshot("error_exception")
            return SubscribeResult(False, self._current_step, str(e))
        finally:
            self._take_screenshot(f"final_{self._current_step}")
            if self.page:
                if self.keep_browser_open:
                    self._debug("可视浏览器已保留，请在检查完成后手动关闭窗口")
                else:
                    try:
                        self.page.quit()
                        self._debug("浏览器已关闭")
                    except Exception:
                        pass
