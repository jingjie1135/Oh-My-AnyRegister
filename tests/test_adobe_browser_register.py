"""Unit tests for Adobe browser registration helpers."""
from __future__ import annotations

from platforms.adobe.browser_register import AdobeBrowserRegister


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
