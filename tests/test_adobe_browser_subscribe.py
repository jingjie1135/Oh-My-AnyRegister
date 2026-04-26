"""Unit tests for Adobe browser subscription helpers."""
from __future__ import annotations

from platforms.adobe.browser_subscribe import (
    AdobeBrowserSubscribe,
    _build_otp_fill_js,
    _extract_otp_code,
    _is_trusted_adobe_auth_frame,
)


class TestExtractOtpCode:
    def test_extracts_from_plain_string(self):
        assert _extract_otp_code("Your Adobe code is 123456") == "123456"

    def test_extracts_from_mail_body_dict(self):
        result = {"html_body": "<p>Verification code:</p><strong>654321</strong>"}

        assert _extract_otp_code(result) == "654321"

    def test_rejects_embedded_longer_numbers(self):
        assert _extract_otp_code("tracking 9912345677 only") == ""

    def test_ignores_non_text_result(self):
        assert _extract_otp_code(None) == ""


class TestBuildOtpFillJs:
    def test_escapes_code_as_json_literal(self):
        script = _build_otp_fill_js("123456")

        assert "})('123456');" not in script
        assert "})(\"123456\");" in script

    def test_uses_explicit_return_for_drissionpage(self):
        script = _build_otp_fill_js("123456")

        assert "return (function(code)" in script

    def test_dispatches_events_needed_by_controlled_inputs(self):
        script = _build_otp_fill_js("123456")

        for event_name in ["beforeinput", "input", "change", "keyup", "blur"]:
            assert event_name in script

    def test_supports_single_and_segmented_inputs(self):
        script = _build_otp_fill_js("123456")

        assert "one-time-code" in script
        assert "maxlength') === '1'" in script
        assert "mode: 'single'" in script
        assert "mode: 'segmented'" in script

    def test_checks_segmented_inputs_before_single_inputs(self):
        script = _build_otp_fill_js("123456")

        assert script.index("const segmentedInputs") < script.index("const fullCodeInputs")
        assert "maxLength !== 1" in script


class TestTrustedAdobeAuthFrame:
    def test_accepts_adobe_auth_frame(self):
        assert _is_trusted_adobe_auth_frame("https://auth.services.adobe.com/challenge", "") is True

    def test_rejects_unrelated_frame(self):
        assert _is_trusted_adobe_auth_frame("https://example.com/form", "Payment") is False

    def test_rejects_title_only_login_frame(self):
        assert _is_trusted_adobe_auth_frame("about:blank", "login") is False

    def test_rejects_non_adobe_auth_host(self):
        assert _is_trusted_adobe_auth_frame("https://evil.example/auth", "Adobe Login") is False


class TestFindVisiblePasswordField:
    def test_returns_visible_password_field(self):
        class FakeStates:
            is_displayed = True

        class FakeElement:
            states = FakeStates()

            class scroll:
                @staticmethod
                def to_see():
                    return None

        class FakePage:
            def ele(self, selector, timeout=0.5):
                if selector == '#PasswordPage-PasswordField':
                    return FakeElement()
                return None

        worker = AdobeBrowserSubscribe()
        worker.page = FakePage()

        assert worker._find_visible_password_field() is not None

    def test_ignores_hidden_password_field(self):
        class FakeStates:
            is_displayed = False

        class FakeElement:
            states = FakeStates()

        class FakePage:
            def ele(self, selector, timeout=0.5):
                return FakeElement()

        worker = AdobeBrowserSubscribe()
        worker.page = FakePage()

        assert worker._find_visible_password_field() is None


class TestAdobeBrowserSubscribeKeepOpen:
    def test_headed_keep_open_skips_quit(self):
        class FakePage:
            def __init__(self):
                self.quit_called = False

            def quit(self):
                self.quit_called = True

        page = FakePage()
        worker = AdobeBrowserSubscribe(headless=False, keep_browser_open=True, log_fn=lambda message: None)
        worker.page = page
        worker._init_browser = lambda: None

        def fail_login(email, password):
            raise RuntimeError("stop")

        worker._do_login = fail_login

        result = worker.run(
            email="user@example.com",
            password="Secret123!",
            card_number="4111111111111111",
            exp_month="01",
            exp_year="2030",
            cvc="123",
            first_name="A",
            last_name="B",
            postal_code="10001",
        )

        assert result.success is False
        assert page.quit_called is False
        assert worker.page is page

    def test_headless_ignores_keep_open_and_quits(self):
        class FakePage:
            def __init__(self):
                self.quit_called = False

            def quit(self):
                self.quit_called = True

        page = FakePage()
        worker = AdobeBrowserSubscribe(headless=True, keep_browser_open=True, log_fn=lambda message: None)
        worker.page = page
        worker._init_browser = lambda: None
        worker._do_login = lambda email, password: (_ for _ in ()).throw(RuntimeError("stop"))

        worker.run(
            email="user@example.com",
            password="Secret123!",
            card_number="4111111111111111",
            exp_month="01",
            exp_year="2030",
            cvc="123",
            first_name="A",
            last_name="B",
            postal_code="10001",
        )

        assert page.quit_called is True
