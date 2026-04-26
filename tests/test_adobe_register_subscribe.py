"""Unit tests for Adobe register + subscribe workflow."""
from __future__ import annotations

import time

from platforms.adobe.browser_register_subscribe import (
    FIREFLY_PRO_CHECKOUT_URL,
    AdobeBrowserRegisterSubscribe,
)
from platforms.adobe.browser_subscribe import SubscribeResult


class TestAdobeRegisterSubscribeConstants:
    def test_firefly_pro_url_uses_discovered_pro_offer_not_pro_plus(self):
        assert "msg4m1782IVpeTz8mHd_P_0GG3OSG7XS932oW-7EGuM" in FIREFLY_PRO_CHECKOUT_URL
        assert "0BF366231CF390A0181EA88C96CCF989" not in FIREFLY_PRO_CHECKOUT_URL
        assert "FFPLFFPU501YROW" not in FIREFLY_PRO_CHECKOUT_URL


class TestAdobeRegisterSubscribeRun:
    def test_run_records_successful_subscription_and_extracts_cookies_after_subscribe(self):
        class Card:
            card_number = "4111111111111111"
            exp_month = "01"
            exp_year = "2030"
            cvc = "123"

        worker = AdobeBrowserRegisterSubscribe(log_fn=lambda message: None, card=Card())
        calls = []
        worker.init_browser = lambda: calls.append("init")
        worker._gen_profile = lambda: {"fn": "A", "ln": "B", "month": 1, "year": 1990}
        worker._register_account = lambda email, password: calls.append("register")
        worker._ensure_logged_in = lambda email, password: calls.append("login")
        worker._subscribe_firefly_pro = lambda card: calls.append("subscribe") or SubscribeResult(True, "verify", "ok")
        worker._extract_and_push_cookies = lambda email: calls.append("cookies") or "sid=1"

        result = worker.run("user@example.com", "Secret123!")

        assert calls == ["init", "register", "login", "subscribe", "cookies"]
        assert result["token"] == "sid=1"
        assert result["extra"]["subscription"]["success"] is True
        assert result["extra"]["subscription"]["plan"] == "firefly_pro"

    def test_run_preserves_registered_result_when_subscription_fails(self):
        class Card:
            card_number = "4111111111111111"
            exp_month = "01"
            exp_year = "2030"
            cvc = "123"

        worker = AdobeBrowserRegisterSubscribe(log_fn=lambda message: None, card=Card())
        worker.init_browser = lambda: None
        worker._gen_profile = lambda: {"fn": "A", "ln": "B", "month": 1, "year": 1990}
        worker._register_account = lambda email, password: None
        worker._ensure_logged_in = lambda email, password: None
        worker._subscribe_firefly_pro = lambda card: SubscribeResult(False, "submit", "no button", "submit_btn_not_found")
        worker._extract_and_push_cookies = lambda email: "sid=1"

        result = worker.run("user@example.com", "Secret123!")

        assert result["email"] == "user@example.com"
        assert result["token"] == "sid=1"
        assert result["extra"]["subscription"]["success"] is False
        assert result["extra"]["subscription"]["stage"] == "submit"


    def test_run_keeps_registered_account_when_login_raises_after_registration(self):
        class Card:
            card_number = "4111111111111111"
            exp_month = "01"
            exp_year = "2030"
            cvc = "123"

        worker = AdobeBrowserRegisterSubscribe(log_fn=lambda message: None, card=Card())
        worker.init_browser = lambda: None
        worker._gen_profile = lambda: {"fn": "A", "ln": "B", "month": 1, "year": 1990}
        worker._register_account = lambda email, password: None
        worker._ensure_logged_in = lambda email, password: (_ for _ in ()).throw(RuntimeError("login failed"))
        worker._subscribe_firefly_pro = lambda card: (_ for _ in ()).throw(AssertionError("should not subscribe"))
        worker._extract_and_push_cookies = lambda email: "sid=1"

        result = worker.run("user@example.com", "Secret123!")

        assert result["email"] == "user@example.com"
        assert result["token"] == "sid=1"
        assert result["extra"]["subscription"]["success"] is False
        assert result["extra"]["subscription"]["error"] == "RuntimeError"

    def test_run_keeps_registered_account_when_subscribe_raises_after_registration(self):
        class Card:
            card_number = "4111111111111111"
            exp_month = "01"
            exp_year = "2030"
            cvc = "123"

        worker = AdobeBrowserRegisterSubscribe(log_fn=lambda message: None, card=Card())
        worker.init_browser = lambda: None
        worker._gen_profile = lambda: {"fn": "A", "ln": "B", "month": 1, "year": 1990}
        worker._register_account = lambda email, password: None
        worker._ensure_logged_in = lambda email, password: None
        worker._subscribe_firefly_pro = lambda card: (_ for _ in ()).throw(RuntimeError("subscribe failed"))
        worker._extract_and_push_cookies = lambda email: "sid=1"

        result = worker.run("user@example.com", "Secret123!")

        assert result["email"] == "user@example.com"
        assert result["token"] == "sid=1"
        assert result["extra"]["subscription"]["success"] is False
        assert result["extra"]["subscription"]["error"] == "RuntimeError"


    def test_run_waits_registration_closure_before_login(self):
        class Card:
            card_number = "4111111111111111"
            exp_month = "01"
            exp_year = "2030"
            cvc = "123"

        worker = AdobeBrowserRegisterSubscribe(log_fn=lambda message: None, card=Card())
        calls = []
        worker.init_browser = lambda: calls.append("init")
        worker._gen_profile = lambda: {"fn": "A", "ln": "B", "month": 1, "year": 1990}
        worker._register_account = lambda email, password: calls.append("register")
        worker._wait_registration_closure = lambda: calls.append("closure")
        worker._ensure_logged_in = lambda email, password: calls.append("login")
        worker._subscribe_firefly_pro = lambda card: calls.append("subscribe") or SubscribeResult(True, "verify", "ok")
        worker._extract_and_push_cookies = lambda email: calls.append("cookies") or "sid=1"

        worker.run("user@example.com", "Secret123!")

        assert calls == ["init", "register", "closure", "login", "subscribe", "cookies"]

    def test_run_with_missing_card_records_subscription_failure(self):
        worker = AdobeBrowserRegisterSubscribe(log_fn=lambda message: None)
        worker.init_browser = lambda: None
        worker._gen_profile = lambda: {"fn": "A", "ln": "B", "month": 1, "year": 1990}
        worker._register_account = lambda email, password: None
        worker._wait_registration_closure = lambda: None
        worker._ensure_logged_in = lambda email, password: None
        worker._extract_and_push_cookies = lambda email: "sid=1"

        result = worker.run("user@example.com", "Secret123!")

        assert result["extra"]["subscription"]["success"] is False
        assert result["extra"]["subscription"]["error"] == "card_missing"


class TestAdobeRegisterSubscribeLogin:
    def test_login_entry_clicks_firefly_sign_in_and_raises_if_not_found(self):
        class FakeStates:
            is_displayed = True

        class FakeElement:
            states = FakeStates()

            def __init__(self, page):
                self.page = page

            class scroll:
                @staticmethod
                def to_see():
                    return None

            def click(self, by_js=False):
                self.page.url = "https://auth.services.adobe.com/signin/from-firefly"

        class FakePage:
            def __init__(self):
                self.url = ""
                self.visited = []

            def get(self, url):
                self.visited.append(url)
                self.url = url

            def ele(self, selector, timeout=0.5):
                if selector in {'a[href*="signin"]', 'a[href*="deeplink=signin"]', 'text:Sign in'}:
                    return FakeElement(self)
                return None

        worker = AdobeBrowserRegisterSubscribe(log_fn=lambda message: None)
        worker.page = FakePage()
        worker._wait_page_ready = lambda timeout=15: True
        worker._delay = lambda lo=0.5, hi=1.5: None

        worker._open_firefly_login_entry()

        assert worker.page.visited == ["https://firefly.adobe.com/"]
        assert worker.page.url == "https://auth.services.adobe.com/signin/from-firefly"

    def test_login_entry_raises_if_not_found(self):
        class FakePage:
            def __init__(self):
                self.url = ""
                self.visited = []

            def get(self, url):
                self.visited.append(url)
                self.url = url

            def ele(self, selector, timeout=0.5):
                return None

        worker = AdobeBrowserRegisterSubscribe(log_fn=lambda message: None)
        worker.page = FakePage()
        worker._wait_page_ready = lambda timeout=15: True
        worker._delay = lambda lo=0.5, hi=1.5: None

        worker._click_first_visible = lambda selectors, label, timeout=12: False
        import pytest
        with pytest.raises(Exception, match="无法找到 Firefly 登录入口"):
            worker._open_firefly_login_entry()

    def test_login_otp_ignores_code_seen_before_trigger(self, monkeypatch):
        monkeypatch.setattr(time, "sleep", lambda seconds: None)
        codes = iter(["Adobe code 111111", "Adobe code 111111", "Adobe code 222222"])
        filled = []

        worker = AdobeBrowserRegisterSubscribe(
            log_fn=lambda message: None,
            otp_callback=lambda: next(codes),
        )
        worker.page = type("FakePage", (), {"url": "https://auth.services.adobe.com/challenge"})()
        worker._visible_element = lambda selector, timeout=0.3: object() if selector == 'text:Enter the code' else None
        worker._click_first_visible = lambda selectors, label, timeout=3: True
        worker._fill_otp_code = lambda code: filled.append(code) or True
        worker._delay = lambda lo=0.5, hi=1.5: None

        assert worker._submit_login_otp_if_needed() is True
        assert filled == ["222222"]

    def test_ensure_logged_in_handles_otp_before_password(self, monkeypatch):
        monkeypatch.setattr(time, "sleep", lambda seconds: None)
        calls = []

        class FakePage:
            url = "https://auth.services.adobe.com/challenge"

        worker = AdobeBrowserRegisterSubscribe(log_fn=lambda message: None)
        worker.page = FakePage()
        worker._open_firefly_login_entry = lambda: calls.append("entry")
        worker._looks_logged_in = lambda: calls.count("password") > 0
        worker._submit_login_otp_if_needed = lambda trigger_send=True: calls.append("otp") or True

        def find_first_visible(selectors, label, timeout=10):
            if label == "登录密码" and calls.count("otp") > 0:
                return object()
            return None

        worker._find_first_visible = find_first_visible
        worker._safe_type_and_confirm = lambda element, value, label: calls.append("password") or True
        worker._click_first_visible = lambda selectors, label, timeout=8: calls.append("password_continue") or True
        worker._wait_page_ready = lambda timeout=15: True
        worker._delay = lambda lo=0.5, hi=1.5: None

        worker._ensure_logged_in("user@example.com", "Secret123!")

        assert calls == ["entry", "otp", "password", "password_continue"]

    def test_ensure_logged_in_handles_password_before_otp(self, monkeypatch):
        monkeypatch.setattr(time, "sleep", lambda seconds: None)
        calls = []

        class FakePage:
            url = "https://auth.services.adobe.com/signin"

        worker = AdobeBrowserRegisterSubscribe(log_fn=lambda message: None)
        worker.page = FakePage()
        worker._open_firefly_login_entry = lambda: calls.append("entry")
        worker._looks_logged_in = lambda: any(call.startswith("otp") for call in calls)
        worker._submit_login_otp_if_needed = lambda trigger_send=True: calls.append(f"otp:{trigger_send}") or True

        def find_first_visible(selectors, label, timeout=10):
            if label == "登录密码" and calls.count("password") == 0:
                return object()
            return None

        worker._find_first_visible = find_first_visible
        worker._safe_type_and_confirm = lambda element, value, label: calls.append("password") or True
        worker._click_first_visible = lambda selectors, label, timeout=8: calls.append("password_continue") or True
        worker._wait_page_ready = lambda timeout=15: True
        worker._delay = lambda lo=0.5, hi=1.5: None

        worker._ensure_logged_in("user@example.com", "Secret123!")

        assert calls == ["entry", "password", "password_continue", "otp:True"]

    def test_repeated_login_mfa_detection_does_not_retrigger_send_code(self, monkeypatch):
        monkeypatch.setattr(time, "sleep", lambda seconds: None)
        calls = []

        class FakePage:
            url = "https://auth.services.adobe.com/challenge"

        worker = AdobeBrowserRegisterSubscribe(log_fn=lambda message: None)
        worker.page = FakePage()
        worker._open_firefly_login_entry = lambda: None
        worker._looks_logged_in = lambda: len([call for call in calls if call.startswith("otp")]) >= 2
        worker._find_visible_password_field = lambda timeout=2: None
        worker._submit_login_otp_if_needed = lambda trigger_send=True: calls.append(f"otp:{trigger_send}") or True
        worker._wait_page_ready = lambda timeout=15: True
        worker._delay = lambda lo=0.5, hi=1.5: None

        worker._ensure_logged_in("user@example.com", "Secret123!")

        assert calls == ["otp:True", "otp:False"]

