from __future__ import annotations

import time
from urllib.parse import urlparse
from platforms.adobe.browser_register import AdobeBrowserRegister
from platforms.adobe.browser_subscribe import SubscribeResult

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

    def _click_auth_light_sign_in_link(self, timeout: float = 8) -> bool:
        click_sign_in_js = """
        const largeButtons = document.querySelector('large-buttons');
        const overflow = largeButtons?.shadowRoot?.querySelector('overflow-page');
        const signIn = overflow?.querySelector('sp-link#sign-in');
        const anchor = signIn?.shadowRoot?.querySelector('a');
        if (!anchor) {
            return { ok: false, reason: 'auth_light_sign_in_not_found' };
        }
        anchor.click();
        return { ok: true, target: 'auth-light-sign-in' };
        """
        return self._click_auth_light_link(click_sign_in_js, "auth-light-sign-in", timeout)

    def _click_auth_light_create_account_link(self, timeout: float = 8) -> bool:
        click_create_account_js = """
        const largeButtons = document.querySelector('large-buttons');
        const overflow = largeButtons?.shadowRoot?.querySelector('overflow-page');
        const createAccount = overflow?.querySelector('sp-link#create-account');
        const anchor = createAccount?.shadowRoot?.querySelector('a');
        if (!anchor) {
            return { ok: false, reason: 'auth_light_create_account_not_found' };
        }
        anchor.click();
        return { ok: true, target: 'auth-light-create-account' };
        """
        return self._click_auth_light_link(click_create_account_js, "auth-light-create-account", timeout)

    def _auth_light_dom_snapshot(self):
        script = """
        return (function() {
            const seen = new Set();
            const frames = [];
            const dialogs = [];
            const hosts = [];
            const visit = (root, path) => {
                if (!root || seen.has(root)) return;
                seen.add(root);
                let nodes = [];
                try { nodes = Array.from(root.querySelectorAll('*')); } catch (e) { return; }
                for (const node of nodes) {
                    const tag = (node.tagName || '').toLowerCase();
                    const id = node.id || '';
                    const testid = node.getAttribute?.('data-testid') || node.getAttribute?.('data-test-id') || '';
                    const title = node.getAttribute?.('title') || '';
                    const src = node.getAttribute?.('src') || '';
                    const role = node.getAttribute?.('role') || '';
                    const label = node.getAttribute?.('aria-label') || '';
                    if (tag === 'iframe') {
                        frames.push({ index: frames.length, path, src, title, id, testid, visible: !!(node.offsetWidth || node.offsetHeight || node.getClientRects().length) });
                    }
                    if (tag.includes('dialog') || role === 'dialog' || testid.includes('dialog') || id.includes('dialog')) {
                        dialogs.push({ tag, path, id, testid, title, role, label });
                    }
                    if (node.shadowRoot) {
                        hosts.push({ tag, path, id, testid });
                        visit(node.shadowRoot, `${path}/${tag}${id ? '#' + id : ''}::shadow`);
                    }
                }
            };
            visit(document, 'document');
            return {
                authLightFrames: frames.filter((frame) => (frame.src || '').includes('auth-light.identity.adobe.com')),
                frames: frames.slice(0, 20),
                dialogs: dialogs.slice(0, 20),
                shadowHosts: hosts.slice(0, 20),
                url: location.href,
            };
        })();
        """
        try:
            result = self.page.run_js(script)
            return result if isinstance(result, dict) else {}
        except Exception as exc:
            self._debug(f"Firefly auth-light DOM 诊断失败: {exc}")
            return {}

    def _log_auth_light_snapshot(self, snapshot) -> None:
        if not isinstance(snapshot, dict):
            return
        self._debug(f"auth-light 诊断 URL: {snapshot.get('url', '')}")
        for frame in (snapshot.get("frames") or [])[:8]:
            if not isinstance(frame, dict):
                continue
            self._debug(
                "iframe 诊断: "
                f"idx={frame.get('index')} visible={frame.get('visible')} "
                f"src={str(frame.get('src') or '')[:120]} "
                f"title={frame.get('title', '')} testid={frame.get('testid', '')} path={frame.get('path', '')}"
            )
        for dialog in (snapshot.get("dialogs") or [])[:5]:
            if isinstance(dialog, dict):
                self._debug(f"dialog 诊断: {dialog}")
        for host in (snapshot.get("shadowHosts") or [])[:5]:
            if isinstance(host, dict):
                self._debug(f"shadow host 诊断: {host}")

    def _click_auth_light_link(self, script: str, label: str, timeout: float = 8) -> bool:
        start = time.time()
        seen_auth_light = False
        while time.time() - start < timeout:
            try:
                iframes = self.page.eles("iframe", timeout=1)
            except Exception as exc:
                self._debug(f"枚举 Firefly 登录 iframe 失败: {exc}")
                iframes = []

            for index, iframe in enumerate(iframes or []):
                try:
                    src = iframe.attr("src") or ""
                    if "auth-light.identity.adobe.com" not in src:
                        continue
                    seen_auth_light = True
                    frame = self.page.get_frame(iframe)
                    if not frame:
                        continue
                    result = frame.run_js(script)
                    self._debug(f"Firefly auth-light 链接点击结果 iframe[{index}]: {result}")
                    if isinstance(result, dict) and result.get("ok"):
                        self.log(f"✅ 点击成功: Firefly auth-light 链接 ({label})")
                        self._delay(0.5, 1)
                        return True
                except Exception as exc:
                    self._debug(f"Firefly auth-light iframe[{index}] 点击失败: {exc}")
            snapshot = self._auth_light_dom_snapshot()
            auth_light_frames = snapshot.get("authLightFrames") or [] if isinstance(snapshot, dict) else []
            if auth_light_frames:
                seen_auth_light = True
                for frame_info in auth_light_frames:
                    try:
                        frame_index = frame_info.get("index") if isinstance(frame_info, dict) else None
                        frame = self.page.get_frame(frame_index)
                        if not frame:
                            continue
                        result = frame.run_js(script)
                        self._debug(f"Firefly auth-light DOM 发现点击结果 frame[{frame_index}]: {result}")
                        if isinstance(result, dict) and result.get("ok"):
                            self.log(f"✅ 点击成功: Firefly auth-light 链接 ({label})")
                            self._delay(0.5, 1)
                            return True
                    except Exception as exc:
                        self._debug(f"Firefly auth-light DOM 发现 iframe 点击失败: {exc}")
            time.sleep(0.5)
        if not seen_auth_light:
            self._log_auth_light_snapshot(self._auth_light_dom_snapshot())
            self.log(f"⚠️ 未检测到 Firefly auth-light iframe，无法点击 {label}")
        return False

    def _confirm_firefly_login_modal(self, before_tab_ids: set) -> bool:
        clicked = self._click_auth_light_sign_in_link(timeout=30)
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
            '[data-test-id="unav-profile--sign-in"]',
            '[data-testid="unav-profile--sign-in"]',
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
            self._delay(1, 2)
            if self._switch_to_new_tab_after_click(before_tab_ids, timeout=2):
                return
            self._confirm_firefly_login_modal(before_tab_ids)
            return

        self.log("⚠️ 未在 Firefly 首页找到真实登录入口，放弃自动登录")
        raise Exception("无法找到 Firefly 登录入口")

    def _open_firefly_create_account_entry(self) -> None:
        self.page.get("https://firefly.adobe.com/")
        self._wait_page_ready(20)
        self._delay(2, 3)
        before_tab_ids = set(self._current_tab_ids())
        clicked = self._click_first_visible([
            '[data-test-id="unav-profile--sign-in"]',
            '[data-testid="unav-profile--sign-in"]',
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
        ], "Firefly 注册入口前置登录按钮", timeout=12)
        if not clicked:
            raise Exception("无法找到 Firefly 注册入口")
        self._delay(1, 2)
        if not self._click_auth_light_create_account_link(timeout=30):
            raise Exception("无法在 Firefly auth-light 弹窗中找到创建账户入口")
        if not self._switch_to_new_tab_after_click(before_tab_ids, timeout=12):
            raise Exception("点击 Firefly 创建账户后未出现新的注册窗口")

    def _open_firefly_upgrade_paywall(self) -> bool:
        self.page.get("https://firefly.adobe.com/")
        self._wait_page_ready(20)
        self._delay(2, 3)
        return self._click_first_visible([
            'button[data-testid="persistent-upgrade"]',
            '[data-testid="persistent-upgrade"]',
            'tag:button@@text():升级',
            'tag:button@@text():Upgrade',
        ], "Firefly 升级按钮", timeout=12)

    def _find_frame_by_url_part(self, url_part: str, timeout: float = 20):
        start = time.time()
        while time.time() - start < timeout:
            try:
                iframes = self.page.eles("iframe", timeout=1)
            except Exception:
                iframes = []
            for iframe in iframes or []:
                try:
                    src = iframe.attr("src") or ""
                    if url_part not in src:
                        continue
                    frame = self.page.get_frame(iframe)
                    if frame:
                        return frame
                except Exception:
                    continue
            time.sleep(0.5)
        return None

    def _find_paywall_frame(self, timeout: float = 20):
        return self._find_frame_by_url_part("commerce.adobe.com/mini-apps/paywall", timeout=timeout)

    def _find_checkout_frame(self, timeout: float = 20):
        return self._find_frame_by_url_part("commerce.adobe.com/store/checkout", timeout=timeout)

    def _find_credit_tokenizer_frame(self, timeout: float = 45):
        selectors = [
            'iframe[data-testid="credit-form-iframe"]',
            'iframe[src*="tokui-commerce.adobe.com/tokenizer-ui/tokenizer"]',
            'iframe[src*="tokenizer-ui/tokenizer"]',
            'iframe[title*="Card"]',
            'iframe[title*="Payment"]',
        ]
        start = time.time()
        while time.time() - start < timeout:
            contexts = [self.page]
            checkout_frame = self._find_checkout_frame(timeout=1)
            if checkout_frame:
                contexts.insert(0, checkout_frame)
            for context in contexts:
                for selector in selectors:
                    try:
                        iframe = context.ele(selector, timeout=1)
                        if not iframe:
                            continue
                        frame_getter = getattr(context, "get_frame", None) or self.page.get_frame
                        frame = frame_getter(iframe)
                        if frame:
                            self._debug(f"找到信用卡 tokenizer iframe: {selector}")
                            return frame
                    except Exception as exc:
                        self._debug(f"信用卡 tokenizer iframe 选择器失败 {selector}: {exc}")
            time.sleep(1)
        return None

    def _open_firefly_pro_trial_checkout(self) -> bool:
        paywall_frame = self._find_paywall_frame(timeout=20)
        if not paywall_frame:
            return False
        selectors = [
            'button[aria-label="免費試用, Adobe Firefly Pro"]',
            'button[aria-label="免费试用, Adobe Firefly Pro"]',
            'button[aria-label="Free trial, Adobe Firefly Pro"]',
            'button[aria-label*="免費試用, Adobe Firefly Pro"]',
            'button[aria-label*="免费试用, Adobe Firefly Pro"]',
        ]
        start = time.time()
        while time.time() - start < 20:
            for selector in selectors:
                try:
                    button = paywall_frame.ele(selector, timeout=1)
                    if button and button.states.is_displayed:
                        button.click()
                        self.log("✅ 点击成功: Adobe Firefly Pro 免费试用")
                        self._delay(1, 2)
                        return True
                except Exception as exc:
                    self._debug(f"Firefly Pro 免费试用按钮点击失败 ({selector}): {exc}")
            time.sleep(0.5)
        return False

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

    def _fill_frame_input(self, frame, selectors: list[str], value: str, label: str) -> bool:
        return self._fill_context_input(frame, selectors, value, label)

    def _fill_context_input(self, context, selectors: list[str], value: str, label: str) -> bool:
        for selector in selectors:
            try:
                element = context.ele(selector, timeout=2)
                if element and element.states.is_displayed:
                    if self._safe_type(element, value):
                        self.log(f"✅ {label} 已填写")
                        try:
                            element.run_js('this.dispatchEvent(new Event("change", {bubbles:true})); this.dispatchEvent(new Event("blur", {bubbles:true}));')
                        except Exception:
                            pass
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
        frame = self._find_credit_tokenizer_frame()
        if not frame:
            return SubscribeResult(False, "fill_card", "信用卡 iFrame 未加载", "iframe_not_found")

        if not self._fill_frame_input(frame, [
            'input[autocomplete="cc-number"]',
            '#card-number',
            'input[name="cardNumber"]',
            '#cardNumber',
            'input[type="tel"]',
        ], card.card_number, "卡号"):
            return SubscribeResult(False, "fill_card", "iFrame 内找不到卡号输入框", "card_input_not_found")

        exp_value = f"{str(card.exp_month).zfill(2)}{str(card.exp_year)[-2:]}"
        if not self._fill_frame_input(frame, [
            'input[autocomplete="cc-exp"]',
            '#expiry-date',
            'input[name="cardExpirationDate"]',
            '#cardExpirationDate',
            'input[placeholder*="MM"]',
        ], exp_value, "有效期"):
            return SubscribeResult(False, "fill_card", "iFrame 内找不到有效期输入框", "card_exp_not_found")
        if not self._fill_frame_input(frame, [
            'input[autocomplete="cc-csc"]',
            'input[name="securityCode"]',
            '#securityCode',
            '#cvc',
            '#cvv',
            'input[id*="cvc" i]',
            'input[id*="cvv" i]',
            'input[placeholder*="CVC"]',
            'input[placeholder*="CVV"]',
        ], card.cvc, "CVC"):
            self.log("ℹ️ 当前 checkout 结构无显式 CVC 字段，继续后续校验")
        return None

    def _fill_checkout_address(self) -> SubscribeResult | None:
        from core.virtual_card import generate_random_address

        checkout_frame = self._find_checkout_frame(timeout=10)
        if not checkout_frame:
            return SubscribeResult(False, "fill_address", "找不到 checkout iFrame", "checkout_frame_not_found")
        address = generate_random_address()
        if not self._fill_context_input(checkout_frame, [
            '#email-input-field',
            'input[name="email"]',
            'input[type="email"]',
        ], getattr(address, "email", "") or "", "账单邮箱"):
            self._debug("checkout 未要求邮箱或邮箱字段不可见，继续填写账单姓名")
        if not self._fill_context_input(checkout_frame, [
            '#firstName',
            'input[name="firstName"]',
            'input[autocomplete="given-name"]',
        ], address.first_name, "账单名"):
            return SubscribeResult(False, "fill_address", "找不到账单名输入框", "billing_first_name_not_found")
        if not self._fill_context_input(checkout_frame, [
            '#lastName',
            'input[name="lastName"]',
            'input[autocomplete="family-name"]',
        ], address.last_name, "账单姓"):
            return SubscribeResult(False, "fill_address", "找不到账单姓输入框", "billing_last_name_not_found")
        if not self._fill_context_input(checkout_frame, [
            '#postalCode',
            'input[name="postalCode"]',
            'input[autocomplete="postal-code"]',
        ], address.postal_code, "邮编"):
            return SubscribeResult(False, "fill_address", "找不到邮编输入框", "billing_postal_code_not_found")
        return None

    def _wait_firefly_logged_in_after_signup(self, timeout: int = 60) -> bool:
        start = time.time()
        while time.time() - start < timeout:
            current_url = self.page.url or ""
            if current_url.startswith("https://firefly.adobe.com") and self._looks_logged_in():
                return True
            time.sleep(1)
        return False

    def _submit_subscription(self) -> SubscribeResult:
        self.log("[Adobe] 10. 提交 Firefly Pro 订阅...")
        checkout_frame = self._find_checkout_frame(timeout=10)
        if not checkout_frame:
            return SubscribeResult(False, "submit", "找不到 checkout iFrame", "checkout_frame_not_found")
        clicked = self._click_first_visible_in_context(checkout_frame, [
            'button[data-testid="action-container-cta-summary-panel-inline"]',
            'button[data-id="checkout-submit-button"]',
            'button[type="submit"]',
            'button[aria-label*="Subscribe"]',
            'button[aria-label*="Agree"]',
            'tag:button@@text():Agree and subscribe',
            'tag:button@@text():Start free trial',
            'tag:button@@text():Subscribe',
            'tag:button@@text():Place order',
            'tag:button@@text():Review order',
            'tag:button@@text():同意並訂閱',
            'tag:button@@text():同意并订阅',
        ], "提交订阅", timeout=20)
        if not clicked:
            return SubscribeResult(False, "submit", "找不到提交按钮", "submit_btn_not_found")

        for index in range(60):
            page_text = ""
            try:
                page_text = (getattr(checkout_frame, "html", "") or getattr(self.page, "html", "") or "").lower()
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
                self._click_first_visible_in_context(checkout_frame, [
                    'button[data-id="checkout-submit-button"]',
                    'button[type="submit"]',
                    'tag:button@@text():Confirm',
                    'tag:button@@text():Place order',
                    'tag:button@@text():Subscribe',
                ], "二次确认订阅", timeout=2)
            time.sleep(1)
        return SubscribeResult(False, "verify", "等待超时，请手动检查订阅状态", "result_timeout")

    def _click_first_visible_in_context(self, context, selectors: list[str], label: str, timeout: float = 8) -> bool:
        start = time.time()
        while time.time() - start < timeout:
            for selector in selectors:
                try:
                    element = context.ele(selector, timeout=0.5)
                    if element and element.states.is_displayed and self._click_element(element):
                        self.log(f"✅ 点击成功: {label} ({selector})")
                        self._delay(0.5, 1)
                        return True
                except Exception as exc:
                    self._debug(f"选择器不可用 {selector}: {exc}")
            time.sleep(0.5)
        self.log(f"⚠️ 未找到可点击元素: {label}")
        return False

    def _subscribe_firefly_pro(self, card) -> SubscribeResult:
        if not card:
            return SubscribeResult(False, "checkout", "未提供虚拟卡，跳过订阅", "card_missing")
        self.log("[Adobe] 8. 从 Firefly 升级入口进入 Pro 试用结算页...")
        if not self._open_firefly_upgrade_paywall():
            return SubscribeResult(False, "checkout", "找不到 Firefly 升级按钮", "upgrade_btn_not_found")
        self._wait_page_ready(30)
        self._delay(4, 6)
        if not self._open_firefly_pro_trial_checkout():
            return SubscribeResult(False, "checkout", "找不到 Adobe Firefly Pro 免费试用入口", "pro_trial_btn_not_found")
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
            self._open_firefly_create_account_entry()
            self._register_account(email, password)
            self._wait_registration_closure()
        except Exception as exc:
            self.log(f"注册流程异常: {exc}")
            raise

        try:
            if not self._wait_firefly_logged_in_after_signup(timeout=60):
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
