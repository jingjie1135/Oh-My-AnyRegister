from __future__ import annotations

import time
from urllib.parse import urlparse
from platforms.adobe.browser_register import AdobeBrowserRegister
from platforms.adobe.browser_subscribe import SubscribeResult

FIREFLY_PRO_CHECKOUT_URL = (
    "https://milo.adobe.com/tools/ost"
    "?osi=msg4m1782IVpeTz8mHd_P_0GG3OSG7XS932oW-7EGuM"
    "&type=checkoutUrl&text=buy-now&workflowStep=commitment"
)

CHECKOUT_ALLOWED_HOST_SUFFIXES = (
    ".adobe.com",
    ".adobe.io",
    ".adobelogin.com",
    ".demdex.net",
)
CHECKOUT_ALLOWED_HOSTS = {
    "adobe.com",
    "adobe.io",
    "adobelogin.com",
    "demdex.net",
}


class AdobeBrowserRegisterSubscribe(AdobeBrowserRegister):
    """Adobe registration worker that logs in and subscribes to Firefly Pro in one browser session."""

    def __init__(self, *args, card=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.card = card

    def _debug(self, message: str):
        self.log(f"  [debug] {message}")

    def _visible_element(self, selector: str, timeout: float = 1):
        try:
            element = self.page.ele(selector, timeout=timeout)
            if element and element.states.is_displayed:
                return element
        except Exception as exc:
            self._debug(f"选择器不可用 {selector}: {exc}")
        return None

    def _click_element(self, element) -> bool:
        if not element:
            return False
        try:
            element.scroll.to_see()
        except Exception:
            pass
        for method in ("normal", "actions", "js"):
            try:
                if method == "normal":
                    element.click()
                elif method == "actions":
                    self.page.actions.move_to(element).click()
                else:
                    element.click(by_js=True)
                return True
            except Exception as exc:
                self._debug(f"点击失败 ({method}): {exc}")
        return False

    def _click_first_visible(self, selectors: list[str], label: str, timeout: float = 8) -> bool:
        start = time.time()
        while time.time() - start < timeout:
            for selector in selectors:
                element = self._visible_element(selector, timeout=0.5)
                if element and self._click_element(element):
                    self.log(f"✅ 点击成功: {label} ({selector})")
                    self._delay(0.5, 1)
                    return True
            time.sleep(0.5)
        self.log(f"⚠️ 未找到可点击元素: {label}")
        return False

    def _find_first_visible(self, selectors: list[str], label: str, timeout: float = 10):
        start = time.time()
        while time.time() - start < timeout:
            for selector in selectors:
                element = self._visible_element(selector, timeout=0.5)
                if element:
                    self._debug(f"找到 {label}: {selector}")
                    return element
            time.sleep(0.5)
        self.log(f"⚠️ 未找到输入框: {label}")
        return None

    def _has_auth_cookie(self) -> bool:
        try:
            return any(
                str(cookie.get("name", "")) in {"ims_sid", "aux_sid"}
                for cookie in self._get_browser_cookies()
                if isinstance(cookie, dict)
            )
        except Exception as exc:
            self._debug(f"读取登录 Cookie 失败: {exc}")
            return False

    def _looks_logged_in(self) -> bool:
        current_url = self.page.url or ""
        if "auth.services.adobe.com" in current_url and "deeplink" in current_url:
            return False
        if self._has_auth_cookie():
            return True
        return bool(
            self._visible_element('button[aria-label*="Account"]', timeout=0.3)
            or self._visible_element('button[aria-label*="Profile"]', timeout=0.3)
            or self._visible_element('button[aria-label*="账户"]', timeout=0.3)
            or self._visible_element('button[aria-label*="个人资料"]', timeout=0.3)
            or self._visible_element('[data-testid*="profile"]', timeout=0.3)
            or self._visible_element('[data-test-id*="profile"]', timeout=0.3)
            or self._visible_element('[data-testid*="account"]', timeout=0.3)
            or self._visible_element('[data-test-id*="account"]', timeout=0.3)
        )

    def _host_allowed(self, url: str) -> bool:
        host = (urlparse(url).hostname or "").lower()
        return host in CHECKOUT_ALLOWED_HOSTS or any(host.endswith(suffix) for suffix in CHECKOUT_ALLOWED_HOST_SUFFIXES)

    def _checkout_origin_result(self) -> SubscribeResult | None:
        current_url = self.page.url or ""
        if not self._host_allowed(current_url):
            return SubscribeResult(False, "checkout", f"结算页来源异常: {current_url}", "unexpected_checkout_origin")
        return None

    def _tab_controller(self):
        if hasattr(self.page, "get_tab") or hasattr(self.page, "tab_ids"):
            return self.page
        try:
            return getattr(self.page, "browser", None) or self.page
        except Exception:
            return self.page

    def _current_tab_ids(self) -> list:
        controller = self._tab_controller()
        try:
            tab_ids = controller.tab_ids
        except Exception as exc:
            self._debug(f"读取标签页列表失败: {exc}")
            return []
        return list(tab_ids or [])

    def _switch_to_tab(self, tab_id=None) -> bool:
        controller = self._tab_controller()
        try:
            if tab_id is not None:
                new_page = controller.get_tab(tab_id)
            else:
                latest_tab = getattr(controller, "latest_tab", None)
                if latest_tab and not isinstance(latest_tab, str):
                    new_page = latest_tab
                elif latest_tab:
                    new_page = controller.get_tab(latest_tab)
                else:
                    new_page = controller.get_tab()
        except Exception as exc:
            self._debug(f"切换新登录窗口失败: {exc}")
            return False
        if not new_page:
            return False
        self.page = new_page
        try:
            self.page.set.activate()
        except Exception:
            pass
        self._wait_page_ready(20)
        self._delay(1, 2)
        self.log(f"✅ 已切换到新登录窗口: {self.page.url}")
        return True

    def _switch_to_new_tab_after_click(self, before_tab_ids: set, timeout: float = 10) -> bool:
        start = time.time()
        while time.time() - start < timeout:
            current_ids = self._current_tab_ids()
            for tab_id in current_ids:
                if tab_id not in before_tab_ids:
                    return self._switch_to_tab(tab_id)
            try:
                new_tab_id = self._tab_controller().wait.new_tab(timeout=1)
                if new_tab_id:
                    return self._switch_to_tab(new_tab_id)
            except Exception:
                pass
            time.sleep(0.5)
        return False

    def _confirm_firefly_login_modal(self, before_tab_ids: set) -> bool:
        clicked = self._click_first_visible([
            'button[data-testid*="register"]',
            'button[data-test-id*="register"]',
            'button[aria-label*="Register"]',
            'button[aria-label*="注册"]',
            'tag:button@@text():Register',
            'tag:button@@text():注册',
            'tag:button@@text():Create account',
            'tag:button@@text():创建账户',
            'tag:button@@text():Sign in',
            'tag:button@@text():登录',
            'tag:button@@text():Continue',
            'tag:button@@text():继续',
        ], "Firefly 登录弹窗确认", timeout=8)
        if not clicked:
            return False
        return self._switch_to_new_tab_after_click(before_tab_ids, timeout=12)

    def _open_firefly_login_entry(self) -> None:
        """Open Firefly and prefer its real sign-in link over a static auth deeplink."""
        self.page.get("https://firefly.adobe.com/")
        self._wait_page_ready(20)
        self._delay(2, 3)
        if self._looks_logged_in():
            return

        before_tab_ids = set(self._current_tab_ids())
        clicked = self._click_first_visible([
            'button.profile-comp.secondary-button',
            '.profile-comp.secondary-button',
            'button.profile-comp',
            '.profile-comp',
            'a[href*="signin"]',
            'a[href*="deeplink=signin"]',
            'a[href*="auth.services.adobe.com"]',
            'button[data-testid*="sign-in"]',
            'button[data-test-id*="sign-in"]',
            'button[aria-label*="Sign in"]',
            'button[aria-label*="登录"]',
            'tag:a@@text():Sign in',
            'tag:button@@text():Sign in',
            'tag:a@@text():登录',
            'tag:button@@text():登录',
            'text:Sign in',
            'text:登录',
        ], "Firefly 真实登录入口", timeout=12)
        if clicked:
            self._wait_page_ready(20)
            self._delay(2, 3)
            if self._switch_to_new_tab_after_click(before_tab_ids, timeout=2):
                return
            self._confirm_firefly_login_modal(before_tab_ids)
            return

        self.log("⚠️ 未在 Firefly 首页找到真实登录入口，放弃自动登录")
        raise Exception("无法找到 Firefly 登录入口")

    def _find_visible_password_field(self, timeout: float = 0.5):
        return self._find_first_visible([
            '#PasswordPage-PasswordField',
            'input[data-id="PasswordPage-PasswordField"]',
            'input[name="passwd"]',
            'input[name="password"]',
            'input[type="password"]',
        ], "登录密码", timeout=timeout)

    def _is_login_mfa_visible(self) -> bool:
        current_url = self.page.url or ""
        if "challenge" in current_url:
            return True
        return bool(
            self._visible_element('text:Enter the code', timeout=0.3)
            or self._visible_element('text:Verify your identity', timeout=0.3)
            or self._visible_element('text:验证您的身份', timeout=0.3)
            or self._visible_element('text:验证您的电子邮件', timeout=0.3)
            or self._visible_element('text:获取验证码', timeout=0.3)
            or self._visible_element('text:发送验证码', timeout=0.3)
            or self._visible_element('text:Send code', timeout=0.3)
        )

    def _collect_existing_login_otp_codes(self) -> set[str]:
        if not self._otp_callback:
            return set()
        try:
            result = self._otp_callback()
        except Exception as exc:
            self._debug(f"预读取登录验证码失败，忽略旧码过滤: {exc}")
            return set()
        if not result:
            return set()
        from platforms.adobe.browser_subscribe import _extract_otp_code
        code = _extract_otp_code(result)
        return {code} if code else set()

    def _submit_login_otp_if_needed(self, trigger_send: bool = True) -> bool:
        if not self._is_login_mfa_visible():
            return False

        self.log("🛡️ 登录阶段检测到邮箱验证码，开始接码...")
        stale_codes = self._collect_existing_login_otp_codes()
        if trigger_send:
            self._click_first_visible([
                'button[data-id="ChallengePage-ContinueButton"]',
                'button[type="submit"]',
                'tag:button@@text():Send code',
                'tag:button@@text():发送验证码',
                'tag:button@@text():继续',
                'tag:button@@text():Continue',
            ], "触发登录验证码", timeout=3)
            self._delay(2, 3)

        if not self._otp_callback:
            raise Exception("登录 MFA 需要邮箱验证码，但未提供 otp_callback")

        start = time.time()
        while time.time() - start < 120:
            result = self._otp_callback()
            if result:
                from platforms.adobe.browser_subscribe import _extract_otp_code
                code = _extract_otp_code(result)
                if code:
                    if code in stale_codes:
                        self._debug(f"跳过触发前已存在的旧登录验证码: {code}")
                        time.sleep(5)
                        continue
                    self.log(f"🔑 登录验证码: {code}")
                    if self._fill_otp_code(code):
                        self._click_first_visible([
                            'button[data-id="ChallengePage-VerifyButton"]',
                            'button[type="submit"]',
                            'tag:button@@text():Verify',
                            'tag:button@@text():Continue',
                            'tag:button@@text():验证',
                            'tag:button@@text():继续',
                        ], "提交登录验证码", timeout=5)
                        self._delay(2, 4)
                        return True
            time.sleep(5)
        raise Exception("登录验证码获取或输入超时")

    def _ensure_logged_in(self, email: str, password: str) -> None:
        self.log("[Adobe] 7. 确认并补齐 Adobe 登录态...")
        self._open_firefly_login_entry()

        email_field = self._find_first_visible([
            '#EmailPage-EmailField',
            'input[data-id="EmailPage-EmailField"]',
            'input[name="username"]',
            'input[type="email"]',
        ], "登录邮箱")
        if email_field:
            if not self._safe_type_and_confirm(email_field, email, "登录邮箱"):
                raise Exception("登录邮箱输入未完成")
            self._click_first_visible([
                'button[data-id="EmailPage-ContinueButton"]',
                'button[type="submit"]',
                'tag:button@@text():Continue',
                'tag:button@@text():继续',
            ], "邮箱继续", timeout=8)
            self._wait_page_ready(10)
            self._delay(1, 2)

        start = time.time()
        password_submit_count = 0
        mfa_triggered = False
        while time.time() - start < 150:
            if self._looks_logged_in():
                self.log("✅ 显式登录完成")
                return

            password_field = self._find_visible_password_field(timeout=2)
            if password_field and password_submit_count < 2:
                if not self._safe_type_and_confirm(password_field, password, "登录密码"):
                    raise Exception("登录密码输入未完成")
                self._click_first_visible([
                    'button[data-id="PasswordPage-ContinueButton"]',
                    'button[type="submit"]',
                    'tag:button@@text():Sign in',
                    'tag:button@@text():登录',
                    'tag:button@@text():Continue',
                    'tag:button@@text():继续',
                ], "密码继续", timeout=8)
                password_submit_count += 1
                self._wait_page_ready(15)
                self._delay(3, 5)
                continue

            if self._submit_login_otp_if_needed(trigger_send=not mfa_triggered):
                mfa_triggered = True
                self._wait_page_ready(15)
                self._delay(3, 5)
                continue

            time.sleep(1)

        raise Exception(f"显式登录超时，当前 URL: {self.page.url}")

    def _find_checkout_frame(self):
        selectors = [
            'iframe[data-testid="credit-form-iframe"]',
            'iframe[title*="Card"]',
            'iframe[title*="Payment"]',
            'iframe[src*="payment"]',
            'iframe[src*="checkout"]',
            'iframe[src*="commerce"]',
        ]
        start = time.time()
        while time.time() - start < 45:
            for selector in selectors:
                try:
                    iframe = self.page.ele(selector, timeout=1)
                    if iframe:
                        frame = self.page.get_frame(iframe)
                        if frame:
                            self._debug(f"找到支付 iframe: {selector}")
                            return frame
                except Exception as exc:
                    self._debug(f"支付 iframe 选择器失败 {selector}: {exc}")
            time.sleep(1)
        return None

    def _fill_frame_input(self, frame, selectors: list[str], value: str, label: str) -> bool:
        for selector in selectors:
            try:
                element = frame.ele(selector, timeout=2)
                if element and element.states.is_displayed:
                    if self._safe_type(element, value):
                        self.log(f"✅ {label} 已填写")
                        return True
            except Exception as exc:
                self._debug(f"填写 {label} 失败 ({selector}): {exc}")
        return False

    def _fill_page_input(self, selectors: list[str], value: str, label: str) -> bool:
        element = self._find_first_visible(selectors, label, timeout=4)
        if not element:
            return False
        if self._safe_type(element, value):
            self.log(f"✅ {label} 已填写")
            return True
        return False

    def _fill_checkout_card(self, card) -> SubscribeResult | None:
        self.log("[Adobe] 9. 填写 Firefly Pro 结算信息...")
        frame = self._find_checkout_frame()
        if not frame:
            return SubscribeResult(False, "fill_card", "信用卡 iFrame 未加载", "iframe_not_found")

        if not self._fill_frame_input(frame, [
            'input[autocomplete="cc-number"]',
            'input[name="cardNumber"]',
            '#cardNumber',
            'input[type="tel"]',
        ], card.card_number, "卡号"):
            return SubscribeResult(False, "fill_card", "iFrame 内找不到卡号输入框", "card_input_not_found")

        exp_value = f"{str(card.exp_month).zfill(2)}{str(card.exp_year)[-2:]}"
        if not self._fill_frame_input(frame, [
            'input[autocomplete="cc-exp"]',
            'input[name="cardExpirationDate"]',
            '#cardExpirationDate',
            'input[placeholder*="MM"]',
        ], exp_value, "有效期"):
            return SubscribeResult(False, "fill_card", "iFrame 内找不到有效期输入框", "card_exp_not_found")
        if not self._fill_frame_input(frame, [
            'input[autocomplete="cc-csc"]',
            'input[name="securityCode"]',
            '#securityCode',
            'input[placeholder*="CVC"]',
            'input[placeholder*="CVV"]',
        ], card.cvc, "CVC"):
            return SubscribeResult(False, "fill_card", "iFrame 内找不到 CVC 输入框", "card_cvc_not_found")
        return None

    def _fill_checkout_address(self) -> SubscribeResult | None:
        from core.virtual_card import generate_random_address

        address = generate_random_address()
        if not self._fill_page_input([
            '#firstName',
            'input[name="firstName"]',
            'input[autocomplete="given-name"]',
        ], address.first_name, "账单名"):
            return SubscribeResult(False, "fill_address", "找不到账单名输入框", "billing_first_name_not_found")
        if not self._fill_page_input([
            '#lastName',
            'input[name="lastName"]',
            'input[autocomplete="family-name"]',
        ], address.last_name, "账单姓"):
            return SubscribeResult(False, "fill_address", "找不到账单姓输入框", "billing_last_name_not_found")
        if not self._fill_page_input([
            '#postalCode',
            'input[name="postalCode"]',
            'input[autocomplete="postal-code"]',
        ], address.postal_code, "邮编"):
            return SubscribeResult(False, "fill_address", "找不到邮编输入框", "billing_postal_code_not_found")
        return None

    def _submit_subscription(self) -> SubscribeResult:
        self.log("[Adobe] 10. 提交 Firefly Pro 订阅...")
        clicked = self._click_first_visible([
            'button[data-id="checkout-submit-button"]',
            'button[type="submit"]',
            'button[aria-label*="Subscribe"]',
            'button[aria-label*="Agree"]',
            'tag:button@@text():Agree and subscribe',
            'tag:button@@text():Start free trial',
            'tag:button@@text():Subscribe',
            'tag:button@@text():Place order',
            'tag:button@@text():Review order',
            'tag:button@@text():同意并订阅',
        ], "提交订阅", timeout=20)
        if not clicked:
            return SubscribeResult(False, "submit", "找不到提交按钮", "submit_btn_not_found")

        for index in range(60):
            page_text = ""
            try:
                page_text = (self.page.html or "").lower()
            except Exception:
                pass

            if any(signal in page_text for signal in [
                "thank you", "order confirmed", "successfully subscribed", "subscription confirmed",
                "your plan", "订阅成功", "感谢您的购买",
            ]):
                return SubscribeResult(True, "verify", "订阅成功")
            for pattern, message in [
                ("card was declined", "银行卡被拒"),
                ("card_declined", "银行卡被拒"),
                ("insufficient funds", "余额不足"),
                ("expired card", "卡已过期"),
                ("invalid card", "卡信息无效"),
                ("payment failed", "支付失败"),
                ("unable to process", "无法处理"),
            ]:
                if pattern in page_text:
                    return SubscribeResult(False, "verify", message, pattern)
            if index in {8, 16}:
                self._click_first_visible([
                    'button[data-id="checkout-submit-button"]',
                    'button[type="submit"]',
                    'tag:button@@text():Confirm',
                    'tag:button@@text():Place order',
                    'tag:button@@text():Subscribe',
                ], "二次确认订阅", timeout=2)
            time.sleep(1)
        return SubscribeResult(False, "verify", "等待超时，请手动检查订阅状态", "result_timeout")

    def _subscribe_firefly_pro(self, card) -> SubscribeResult:
        if not card:
            return SubscribeResult(False, "checkout", "未提供虚拟卡，跳过订阅", "card_missing")
        self.log("[Adobe] 8. 跳转 Firefly Pro 结算页...")
        self.page.get(FIREFLY_PRO_CHECKOUT_URL)
        self._wait_page_ready(30)
        self._delay(4, 6)

        if "auth.services.adobe.com" in (self.page.url or ""):
            return SubscribeResult(False, "checkout", "结算页仍要求登录", "checkout_requires_login")

        origin_result = self._checkout_origin_result()
        if origin_result:
            return origin_result

        result = self._fill_checkout_card(card)
        if result:
            return result
        result = self._fill_checkout_address()
        if result:
            return result
        return self._submit_subscription()

    def run(self, email: str, password: str, card=None) -> dict:
        selected_card = card or self.card
        self.log(f"[Adobe Browser] 开始注册并订阅 Firefly Pro: {email}...")
        self.init_browser()
        self._registration_profile = self._gen_profile()
        subscription = SubscribeResult(False, "not_started", "订阅未开始", "not_started")

        try:
            self._register_account(email, password)
            self._wait_registration_closure()
        except Exception as exc:
            self.log(f"注册流程异常: {exc}")
            raise

        try:
            self._ensure_logged_in(email, password)
            subscription = self._subscribe_firefly_pro(selected_card)
        except Exception as exc:
            subscription = SubscribeResult(False, "subscribe", f"注册成功后自动订阅异常: {exc}", exc.__class__.__name__)
            self.log(f"⚠️ {subscription.message}")

        if subscription.success:
            self.log("🎉 Firefly Pro 订阅成功")
        else:
            self.log(f"⚠️ Firefly Pro 订阅失败: {subscription.message} ({subscription.error})")

        try:
            cookie_str = self._extract_and_push_cookies(email)
        except Exception as exc:
            self.log(f"⚠️ 注册成功后提取 Cookie 失败: {exc}")
            cookie_str = ""

        try:
            return {
                "email": email,
                "password": password,
                "token": cookie_str,
                "extra": {
                    "created_at": time.strftime("%Y-%m-%d %H:%M:%S"),
                    "subscription": {
                        "plan": "firefly_pro",
                        "success": subscription.success,
                        "stage": subscription.stage,
                        "message": subscription.message,
                        "error": subscription.error,
                    },
                },
            }
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
                except Exception as exc:
                    self.log(f"⚠️ 清理浏览器用户数据目录失败: {exc}")
