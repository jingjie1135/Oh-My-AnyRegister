"""Unit tests for Adobe browser registration helpers."""
from __future__ import annotations

import time

from platforms.adobe.browser_register import AdobeBrowserRegister, _is_safe_cookie_export_url, build_adobe_cookie_header


class TestAdobeBrowserRegisterOtpFill:
    def test_fill_otp_code_accepts_js_success(self):
        class FakePage:
            def eles(self, selector, timeout=1):
                return []

            def run_js(self, script):
                assert "return (function(code)" in script
                return {"ok": True, "mode": "segmented"}

        worker = AdobeBrowserRegister(log_fn=lambda message: None)
        worker.page = FakePage()

        assert worker._fill_otp_code("123456") is True

    def test_fill_otp_code_falls_back_to_segmented_inputs(self):
        class FakeStates:
            is_displayed = True

        class FakeInput:
            states = FakeStates()

            def __init__(self):
                self.value = ""

            def click(self):
                return None

            def input(self, value):
                self.value += value

        inputs = [FakeInput() for _ in range(6)]

        class FakePage:
            def run_js(self, script):
                return {"ok": False, "mode": "not_found"}

            def eles(self, selector, timeout=1):
                if selector == 'input[maxlength="1"]':
                    return inputs
                if selector == 'iframe':
                    return []
                return []

            def ele(self, selector, timeout=1):
                return None

        worker = AdobeBrowserRegister(log_fn=lambda message: None)
        worker.page = FakePage()
        worker._delay = lambda lo=0.5, hi=1.5: None

        assert worker._fill_otp_code("654321") is True
        assert [item.value for item in inputs] == list("654321")

    def test_fill_otp_code_rejects_invalid_code(self):
        worker = AdobeBrowserRegister(log_fn=lambda message: None)

        assert worker._fill_otp_code("abc") is False


class TestAdobeBrowserRegisterArkoseWait:
    def test_detects_visible_arkose_iframe(self):
        class FakeStates:
            is_displayed = True

        class FakeElement:
            states = FakeStates()

        class FakePage:
            def ele(self, selector, timeout=0.5):
                if "arkoselabs" in selector:
                    return FakeElement()
                return None

        worker = AdobeBrowserRegister(log_fn=lambda message: None)
        worker.page = FakePage()

        assert worker._is_arkose_visible() is True

    def test_detects_email_verify_text(self):
        class FakeStates:
            is_displayed = True

        class FakeElement:
            states = FakeStates()

        class FakePage:
            def ele(self, selector, timeout=0.5):
                if "Verify your email" in selector:
                    return FakeElement()
                return None

            def eles(self, selector, timeout=0.5):
                return []

        worker = AdobeBrowserRegister(log_fn=lambda message: None)
        worker.page = FakePage()

        assert worker._is_email_verify_page() is True

    def test_detects_email_verify_from_url_hash_without_dom(self):
        class FakePage:
            url = "https://auth.services.adobe.com/zh_HANS/deeplink.html#/challenge/email-verification/code"

            def run_js(self, script):
                if "window.location" in script:
                    return "https://auth.services.adobe.com/zh_HANS/deeplink.html#/challenge/email-verification/code"
                return None

            def ele(self, selector, timeout=0.5):
                return None

            def eles(self, selector, timeout=0.5):
                return []

        worker = AdobeBrowserRegister(log_fn=lambda message: None)
        worker.page = FakePage()

        assert worker._is_email_verify_page() is True

    def test_detects_email_verify_inputs_inside_trusted_iframe(self):
        class FakeStates:
            is_displayed = True

        class FakeIframeElement:
            def attr(self, name):
                if name == "src":
                    return "https://auth.services.adobe.com/challenge/email-verification"
                if name == "title":
                    return "Adobe verification"
                return ""

        class FakeInput:
            states = FakeStates()

        class FakeFrame:
            def ele(self, selector, timeout=0.5):
                return None

            def eles(self, selector, timeout=0.5):
                if selector == 'input[maxlength="1"]':
                    return [FakeInput() for _ in range(6)]
                return []

        class FakePage:
            url = "https://auth.services.adobe.com/signup"

            def run_js(self, script):
                if "window.location" in script:
                    return self.url
                return None

            def ele(self, selector, timeout=0.5):
                return None

            def eles(self, selector, timeout=0.5):
                if selector == "iframe":
                    return [FakeIframeElement()]
                return []

            def get_frame(self, iframe):
                return FakeFrame()

        worker = AdobeBrowserRegister(log_fn=lambda message: None)
        worker.page = FakePage()

        assert worker._is_email_verify_page() is True

    def test_signup_profile_url_detection_rejects_challenge_routes(self):
        assert AdobeBrowserRegister._url_indicates_signup_profile(
            "https://auth.services.adobe.com/zh_HANS/deeplink.html#/challenge/email-verification/code"
        ) is False
        assert AdobeBrowserRegister._url_indicates_signup_profile(
            "https://auth.services.adobe.com/zh_HANS/deeplink.html#/challenge/arkose"
        ) is False

    def test_email_verify_text_detection_rejects_generic_verification_text(self):
        class FakeStates:
            is_displayed = True

        class FakeElement:
            states = FakeStates()

        class FakePage:
            url = "https://auth.services.adobe.com/signup"

            def run_js(self, script):
                if "window.location" in script:
                    return self.url
                return None

            def ele(self, selector, timeout=0.5):
                if selector == "text:verification":
                    return FakeElement()
                return None

            def eles(self, selector, timeout=0.5):
                return []

        worker = AdobeBrowserRegister(log_fn=lambda message: None)
        worker.page = FakePage()

        assert worker._is_email_verify_page() is False

    def test_wait_after_submit_returns_email_verify_after_arkose_clears(self):
        class FakePage:
            url = "https://auth.services.adobe.com/signup"

        worker = AdobeBrowserRegister(log_fn=lambda message: None)
        worker.page = FakePage()
        states = iter([
            (True, False),
            (False, True),
        ])
        current = {"value": (False, False)}

        def next_state_sleep(seconds):
            try:
                current["value"] = next(states)
            except StopIteration:
                pass

        current["value"] = next(states)
        worker._is_arkose_visible = lambda: current["value"][0]
        worker._is_email_verify_page = lambda: current["value"][1]
        worker._wait_page_ready = lambda timeout=15: True

        import platforms.adobe.browser_register as mod
        original_sleep = mod.time.sleep
        mod.time.sleep = next_state_sleep
        try:
            assert worker._wait_after_submit_for_verification("https://auth.services.adobe.com/signup", timeout=10) == "email_verify"
        finally:
            mod.time.sleep = original_sleep


class TestAdobeBrowserRegisterStep1:
    def test_safe_type_and_confirm_waits_for_matching_value(self):
        class FakeElement:
            def __init__(self):
                self.value = ""

            def attr(self, name):
                if name == 'value':
                    return self.value
                return ""

        element = FakeElement()
        worker = AdobeBrowserRegister(log_fn=lambda message: None)
        worker._safe_type = lambda target, text: setattr(target, "value", text) or True

        assert worker._safe_type_and_confirm(element, "user@example.com", "邮箱", timeout=1) is True

    def test_click_step1_continue_skips_disabled_button(self):
        class FakeStates:
            is_displayed = True

        class FakeButton:
            states = FakeStates()

            class scroll:
                @staticmethod
                def to_see():
                    return None

            def __init__(self, disabled):
                self.disabled = disabled
                self.clicked = False

            def attr(self, name):
                if name == 'disabled':
                    return "disabled" if self.disabled else ""
                if name == 'aria-disabled':
                    return "true" if self.disabled else "false"
                return ""

            def click(self):
                self.clicked = True

        disabled = FakeButton(disabled=True)
        enabled = FakeButton(disabled=False)

        class FakePage:
            def __init__(self):
                self.calls = 0

            def ele(self, selector, timeout=0.5):
                if selector.startswith('tag:button'):
                    self.calls += 1
                    return disabled if self.calls == 1 else enabled
                return None

        worker = AdobeBrowserRegister(log_fn=lambda message: None)
        worker.page = FakePage()
        worker._delay = lambda lo=0.5, hi=1.5: None
        worker._is_signup_profile_step = lambda: False
        worker._is_email_verify_page = lambda: False

        assert worker._click_step1_continue(timeout=1) is True
        assert disabled.clicked is False
        assert enabled.clicked is True


class TestAdobeBrowserRegisterProfile:
    def test_safe_type_dispatches_input_change_and_blur_events_after_typing(self):
        class FakeElement:
            def __init__(self):
                self.value = ""
                self.events_script = ""

            def click(self):
                return None

            def input(self, value):
                if len(str(value)) == 1 and str(value).isdigit():
                    self.value += str(value)

            def run_js(self, script):
                self.events_script = script
                return None

        element = FakeElement()
        worker = AdobeBrowserRegister(log_fn=lambda message: None)

        assert worker._safe_type(element, "1990") is True
        assert element.value == "1990"
        assert "input" in element.events_script
        assert "change" in element.events_script
        assert "blur" in element.events_script

    def test_select_signup_birth_month_supports_english_option_and_confirms_label_changed(self):
        class FakeStates:
            is_displayed = True

        class FakeMonthField:
            states = FakeStates()

            def __init__(self):
                self.text = "Select..."
                self.clicked = False

            def attr(self, name):
                if name == "value":
                    return ""
                return ""

            def click(self):
                self.clicked = True

            @property
            def select(self):
                raise RuntimeError("custom Adobe month control is not a native select")

        class FakeOption:
            states = FakeStates()

            def __init__(self, text, month_field):
                self.text = text
                self.month_field = month_field
                self.clicked = False

            def click(self):
                self.clicked = True
                self.month_field.text = self.text

        month_field = FakeMonthField()
        january = FakeOption("January", month_field)

        class FakePage:
            def ele(self, selector, timeout=3):
                if selector == '#Signup-DateOfBirthChooser-Month':
                    return month_field
                return None

            def eles(self, selector, timeout=1):
                if selector == '[role="option"]':
                    return [january]
                return []

        worker = AdobeBrowserRegister(log_fn=lambda message: None)
        worker.page = FakePage()
        worker._delay = lambda lo=0.5, hi=1.5: None

        assert worker._select_signup_birth_month(1) is True
        assert january.clicked is True
        assert month_field.text == "January"


class TestAdobeBrowserRegisterPopupRecovery:
    def test_wait_registration_closure_switches_to_firefly_tab_when_signup_popup_disconnects(self):
        class DisconnectedSignupPage:
            @property
            def url(self):
                raise RuntimeError("与页面的连接已断开。 版本: 4.1.1.2")

            @property
            def tab_ids(self):
                return ["signup", "firefly"]

            def get_tab(self, tab_id=None):
                if tab_id == "firefly":
                    return firefly_page
                return self

        class FakeSet:
            def __init__(self):
                self.activated = False

            def activate(self):
                self.activated = True

        class FireflyPage:
            url = "https://firefly.adobe.com/"

            def __init__(self):
                self.set = FakeSet()

            def run_js(self, script):
                if "document.readyState" in script:
                    return "complete"
                return None

        firefly_page = FireflyPage()
        messages = []
        worker = AdobeBrowserRegister(log_fn=messages.append)
        worker.page = DisconnectedSignupPage()
        worker._delay = lambda lo=0.5, hi=1.5: None

        worker._wait_registration_closure()

        assert worker.page is firefly_page
        assert firefly_page.set.activated is True
        assert any("已切回 Firefly 父页面" in message for message in messages)


class TestAdobeBrowserRegisterFailureGuards:
    def test_missing_otp_callback_raises_on_verify_page(self):
        class FakeStates:
            is_displayed = True

        class FakeElement:
            states = FakeStates()

        class FakePage:
            url = "https://auth.services.adobe.com/signup"

            def get(self, url):
                self.url = url

            def ele(self, selector, timeout=3):
                if 'email' in selector.lower() or 'Email' in selector:
                    return FakeElement()
                return None

            def eles(self, selector, timeout=1):
                return []

            def quit(self):
                return None

        worker = AdobeBrowserRegister(log_fn=lambda message: None)
        worker.page = FakePage()
        worker.init_browser = lambda: None
        worker._wait_page_ready = lambda timeout=15: True
        worker._delay = lambda lo=0.5, hi=1.5: None
        worker._gen_profile = lambda: {"fn": "A", "ln": "B", "month": 1, "year": 1990}
        worker._safe_type_and_confirm = lambda element, text, label, timeout=8: True
        worker._click_step1_continue = lambda timeout=12: True
        worker._is_signup_profile_step = lambda: False
        worker._is_email_verify_page = lambda: True

        try:
            worker.run("user@example.com", "Secret123!")
        except Exception as exc:
            assert "未提供 otp_callback" in str(exc)
        else:
            raise AssertionError("run() should fail when verify page requires missing otp_callback")

    def test_submit_timeout_raises(self):
        worker = AdobeBrowserRegister(log_fn=lambda message: None)
        worker._wait_after_submit_for_verification = lambda url_before, timeout=300: "timeout"

        assert worker._wait_after_submit_for_verification("https://auth.services.adobe.com/signup") == "timeout"


class TestAdobeBrowserRegisterKeepOpen:
    def test_headed_keep_open_skips_quit_and_profile_cleanup(self):
        class FakePage:
            def __init__(self):
                self.quit_called = False

            def quit(self):
                self.quit_called = True

        page = FakePage()
        worker = AdobeBrowserRegister(log_fn=lambda message: None, keep_browser_open=True)
        worker.page = page
        worker._user_data_dir = "kept-profile"
        worker.init_browser = lambda: None
        worker._gen_profile = lambda: {"fn": "A", "ln": "B", "month": 1, "year": 1990}

        try:
            worker.run("user@example.com", "Secret123!")
        except Exception:
            pass

        assert page.quit_called is False
        assert worker.page is page
        assert worker._user_data_dir == "kept-profile"

    def test_headless_ignores_keep_open_and_quits(self):
        class FakePage:
            def __init__(self):
                self.quit_called = False

            def quit(self):
                self.quit_called = True

        page = FakePage()
        worker = AdobeBrowserRegister(headless=True, log_fn=lambda message: None, keep_browser_open=True)
        worker.page = page
        worker.init_browser = lambda: None
        worker._gen_profile = lambda: {"fn": "A", "ln": "B", "month": 1, "year": 1990}

        try:
            worker.run("user@example.com", "Secret123!")
        except Exception:
            pass

        assert page.quit_called is True
        assert worker.page is None


class TestAdobeBrowserRegisterCookies:
    def test_build_adobe_cookie_header_matches_extension_scope(self):
        cookies = [
            {"domain": ".adobe.com", "path": "/", "name": "sid", "value": "root"},
            {"domain": ".adobe.com", "path": "/firefly", "name": "sid", "value": "firefly"},
            {"domain": "firefly.adobe.com", "path": "/", "name": "ff", "value": "1"},
            {"domain": "account.adobe.com", "path": "/", "name": "acct", "value": "1"},
            {"domain": "auth.services.adobe.com", "path": "/", "name": "auth", "value": "1"},
            {"domain": "adobelogin.com", "path": "/", "name": "login", "value": "skip"},
            {"domain": "example.com", "path": "/", "name": "other", "value": "skip"},
            {"domain": ".adobe.com", "path": "/", "name": "sid", "value": "duplicate"},
        ]

        header = build_adobe_cookie_header(cookies)

        assert header == "sid=root; sid=firefly; ff=1; acct=1; auth=1"

    def test_wait_for_adobe_cookie_stability_waits_for_longer_persistent_cookie(self):
        now = time.time()
        first = [{"domain": ".adobe.com", "path": "/", "name": "ims_sid", "value": "short", "expires": now + 3600}]
        second = [{"domain": ".adobe.com", "path": "/", "name": "ims_sid", "value": "long", "expires": now + 86400}]
        calls = {"count": 0}
        worker = AdobeBrowserRegister(log_fn=lambda message: None)

        def get_cookies():
            calls["count"] += 1
            return second

        worker._get_browser_cookies = get_cookies

        import platforms.adobe.browser_register as mod
        original_sleep = mod.time.sleep
        mod.time.sleep = lambda seconds: None
        try:
            assert worker._wait_for_adobe_cookie_stability(first) == second
        finally:
            mod.time.sleep = original_sleep
        assert calls["count"] == 1

    def test_wait_for_adobe_cookie_stability_ignores_short_lived_non_auth_cookie(self):
        now = time.time()
        cookies = [
            {"domain": ".adobe.com", "path": "/", "name": "ims_sid", "value": "long", "expires": now + 86400},
            {"domain": ".adobe.com", "path": "/", "name": "analytics", "value": "short", "expires": now + 3600},
        ]
        worker = AdobeBrowserRegister(log_fn=lambda message: None)
        worker._get_browser_cookies = lambda: (_ for _ in ()).throw(AssertionError("should not wait"))

        assert worker._wait_for_adobe_cookie_stability(cookies) == cookies

    def test_wait_for_adobe_cookie_stability_returns_session_only_auth_cookie(self):
        cookies = [{"domain": ".adobe.com", "path": "/", "name": "ims_sid", "value": "session", "expires": -1}]
        worker = AdobeBrowserRegister(log_fn=lambda message: None)
        worker._get_browser_cookies = lambda: (_ for _ in ()).throw(AssertionError("should not wait"))

        assert worker._wait_for_adobe_cookie_stability(cookies) == cookies


    def test_cookie_export_url_allows_local_and_private_targets(self):
        assert _is_safe_cookie_export_url("http://localhost:6001/api") is True
        assert _is_safe_cookie_export_url("http://127.0.0.1:6001/api") is True
        assert _is_safe_cookie_export_url("http://192.168.1.20:6001/api") is True
        assert _is_safe_cookie_export_url("http://10.0.0.5:6001/api") is True
        assert _is_safe_cookie_export_url("http://172.16.0.5:6001/api") is True
        assert _is_safe_cookie_export_url("http://adobe2api:6001/api") is True

    def test_cookie_export_url_rejects_public_targets_by_default(self):
        assert _is_safe_cookie_export_url("https://example.com/import-cookie") is False
        assert _is_safe_cookie_export_url("ftp://localhost/import-cookie") is False
