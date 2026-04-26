"""Unit tests for Adobe register + subscribe workflow."""
from __future__ import annotations

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

