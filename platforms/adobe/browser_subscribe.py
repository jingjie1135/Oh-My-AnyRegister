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
import random
import re
import time
import traceback
from dataclasses import dataclass
from typing import Callable, Optional

from DrissionPage import ChromiumOptions, ChromiumPage

logger = logging.getLogger("adobe_subscribe")

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
    ):
        self.headless = headless
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

    def _init_browser(self):
        """初始化带 Stealth 补丁的浏览器"""
        self._set_step(STEP_INIT)

        co = ChromiumOptions()
        if self.headless:
            co.set_argument('--headless=new')
            co.set_argument('--disable-gpu')
            self._debug("浏览器模式: headless")
        else:
            self._debug("浏览器模式: headed (可视化)")

        co.set_argument('--ignore-certificate-errors')
        co.set_argument('--disable-notifications')
        co.set_argument('--disable-blink-features=AutomationControlled')
        co.set_argument('--no-sandbox')
        co.set_argument('--disable-infobars')
        co.set_argument('--disable-dev-shm-usage')
        co.set_argument('--excludeSwitches=enable-automation')
        co.set_argument('--lang=en-US')
        if self.proxy:
            co.set_proxy(self.proxy)
            self._debug(f"代理: {self.proxy}")

        from fake_useragent import UserAgent
        ua = UserAgent(os='windows', browsers=['chrome'])
        ua_str = ua.random
        co.set_user_agent(ua_str)
        self._debug(f"UA: {ua_str[:60]}...")

        self.page = ChromiumPage(co)
        try:
            self.page.run_js(STEALTH_JS)
            self.page.run_cdp('Page.addScriptToEvaluateOnNewDocument', source=STEALTH_JS)
            self._debug("Stealth JS 注入成功")
        except Exception as e:
            self._debug(f"Stealth 注入异常: {e}")

        self.page.set.window.size(1920, 1080)
        self.page.set.timeouts(base=15)
        self.log("✅ 浏览器初始化完成")

    def _wait_page_ready(self, timeout: int = 20) -> bool:
        """等待页面完全加载"""
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
        self._debug(f"页面在 {timeout}s 内未完全加载")
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

        # 检测是否进入了验证码环节 (challenge/verify/email)
        verify_page = False
        if 'challenge/verify/email' in self.page.url or self.page.ele('text:验证您的电子邮件', timeout=1) or self.page.ele('text:验证您的身份', timeout=1) or self.page.ele('text:Verify your identity', timeout=1):
            verify_page = True
            
        if verify_page:
            self._take_screenshot("detected_otp_verify")
            self.log("🛡️ 检测到邮箱安全验证环节...")
            
            # 点击发送验证码的继续按钮
            send_btn = False
            for text in ['继续', 'Continue', 'Send code']:
                eles = self.page.eles(f'text:{text}', timeout=1)
                for ele in eles:
                    if ele.tag.lower() in ['button', 'a', 'span'] and ele.states.is_displayed:
                        try:
                            self.page.actions.move_to(ele).click()
                            self._delay(0.5, 1)
                            if ele.states.is_displayed: # 如果还在，补一发 JS 点击
                                ele.click(by_js=True)
                        except Exception:
                            try:
                                ele.click(by_js=True)
                            except:
                                pass
                        send_btn = True
                        self._debug(f"点击了 '{text}' 触发发送验证码")
                        break
                if send_btn: break
            if send_btn:
                self._take_screenshot("clicked_send_otp_button")
                self._delay(2, 3)

            if not self.otp_callback:
                return SubscribeResult(False, STEP_LOGIN, "遇到邮箱验证码拦截，但未提供接码回调(otp_callback)", "otp_challenge_failed")
            
            self.log("📧 呼叫 otp_callback 触发接码...")
            code_found = False
            start_otp = time.time()
            while time.time() - start_otp < 120 and not code_found:
                try:
                    content_dict = self.otp_callback()
                    if content_dict and isinstance(content_dict, dict):
                        body = content_dict.get('html_body') or content_dict.get('body') or ""
                        # 提取6位数字验证码
                        import re
                        m = re.search(r'(?<!#)(?<!\d)(\d{6})(?!\d)', body)
                        code = m.group(1) if m else None
                        if code:
                            self.log(f"🔑 获取到验证码: {code}")
                            code_inputs = self.page.eles('input[maxlength="1"]', timeout=3)
                            if code_inputs and len(code_inputs) >= 6:
                                for i, digit in enumerate(code[:6]):
                                    code_inputs[i].click()
                                    self._delay(0.05, 0.15)
                                    code_inputs[i].input(digit)
                            else:
                                cf = self.page.ele('input[name="code"]', timeout=3) or self.page.ele('input[type="text"]', timeout=3)
                                if cf: self._safe_type(cf, code)
                            
                            self._take_screenshot("inputted_otp_code")
                            self._delay(1, 2)
                            # 点击验证按钮
                            continue_btn = False
                            for text in ['验证', '继续', 'Verify', 'Continue']:
                                eles = self.page.eles(f'text:{text}', timeout=1)
                                for ele in eles:
                                    if ele.tag.lower() in ['button', 'a', 'span'] and ele.states.is_displayed:
                                        ele.click()
                                        continue_btn = True
                                        break
                                if continue_btn: break
                            self._delay(3, 5)
                            code_found = True
                            break
                except Exception as e:
                    self._debug(f"otp_callback 异常: {e}")
                time.sleep(5)
                
            if not code_found:
                return SubscribeResult(False, STEP_LOGIN, "等待登录验证码超时", "otp_timeout")

        # 输入密码
        pwd_field = None
        for sel in ['#PasswordPage-PasswordField', 'input[type="password"]']:
            pwd_field = self.page.ele(sel, timeout=5)
            if pwd_field:
                self._debug(f"密码输入框: {sel}")
                break
        if not pwd_field:
            self._take_screenshot("error_password_field_not_found")
            self._debug(f"密码页面 URL: {self.page.url}")
            return SubscribeResult(False, STEP_LOGIN, "找不到密码输入框", "password_field_not_found")

        self._safe_type(pwd_field, password)
        self._delay(0.3, 0.8)

        # 点击登录
        self._debug("点击登录按钮...")
        login_clicked = False
        for text in ['继续', 'Continue', '登录', 'Sign in']:
            try:
                eles = self.page.eles(f'text:{text}', timeout=2)
                for ele in eles:
                    if ele.tag.lower() in ['button', 'a', 'span'] and ele.states.is_displayed:
                        ele.click()
                        login_clicked = True
                        self._debug(f"点击了 '{text}'")
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

        self._delay(3, 5)

        # 等待登录完成
        self._debug("等待登录跳转...")
        for i in range(20):
            try:
                url = self.page.url
                if 'firefly.adobe.com' in url or 'commerce.adobe.com' in url:
                    self.log(f"✅ 登录成功 → {url[:60]}")
                    return None
                page_text = self.page.html or ""
                if '密码错误' in page_text or 'incorrect' in page_text.lower() or 'wrong password' in page_text.lower():
                    return SubscribeResult(False, STEP_LOGIN, "密码错误", "wrong_password")
            except Exception:
                pass
            time.sleep(1)

        self._debug(f"登录超时，最终 URL: {self.page.url}")
        return SubscribeResult(False, STEP_LOGIN, "登录超时，未跳转成功", "login_timeout")

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
                try:
                    self.page.quit()
                    self._debug("浏览器已关闭")
                except Exception:
                    pass
