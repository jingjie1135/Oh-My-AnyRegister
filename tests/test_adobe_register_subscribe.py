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
        worker.page = type("FakePage", (), {"url": "https://firefly.adobe.com/", "get": lambda self, url: None, "quit": lambda self: None})()
        worker._gen_profile = lambda: {"fn": "A", "ln": "B", "month": 1, "year": 1990}
        worker._open_firefly_create_account_entry = lambda: calls.append("entry")
        worker._wait_firefly_logged_in_after_signup = lambda timeout=60: False
        worker._register_account = lambda email, password: calls.append("register")
        worker._ensure_logged_in = lambda email, password: calls.append("login")
        worker._subscribe_firefly_pro = lambda card: calls.append("subscribe") or SubscribeResult(True, "verify", "ok")
        worker._extract_and_push_cookies = lambda email: calls.append("cookies") or "sid=1"

        result = worker.run("user@example.com", "Secret123!")

        assert calls == ["init", "entry", "register", "login", "subscribe", "cookies"]
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
        worker.page = type("FakePage", (), {"url": "https://firefly.adobe.com/", "get": lambda self, url: None, "quit": lambda self: None})()
        worker._gen_profile = lambda: {"fn": "A", "ln": "B", "month": 1, "year": 1990}
        worker._open_firefly_create_account_entry = lambda: None
        worker._wait_firefly_logged_in_after_signup = lambda timeout=60: False
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
        worker.page = type("FakePage", (), {"url": "https://firefly.adobe.com/", "get": lambda self, url: None, "quit": lambda self: None})()
        worker._gen_profile = lambda: {"fn": "A", "ln": "B", "month": 1, "year": 1990}
        worker._open_firefly_create_account_entry = lambda: None
        worker._wait_firefly_logged_in_after_signup = lambda timeout=60: False
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
        worker.page = type("FakePage", (), {"url": "https://firefly.adobe.com/", "get": lambda self, url: None, "quit": lambda self: None})()
        worker._gen_profile = lambda: {"fn": "A", "ln": "B", "month": 1, "year": 1990}
        worker._open_firefly_create_account_entry = lambda: None
        worker._wait_firefly_logged_in_after_signup = lambda timeout=60: False
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
        worker.page = type("FakePage", (), {"url": "https://firefly.adobe.com/", "get": lambda self, url: None, "quit": lambda self: None})()
        worker._gen_profile = lambda: {"fn": "A", "ln": "B", "month": 1, "year": 1990}
        worker._open_firefly_create_account_entry = lambda: calls.append("entry")
        worker._wait_firefly_logged_in_after_signup = lambda timeout=60: calls.append("auto-login") or False
        worker._register_account = lambda email, password: calls.append("register")
        worker._wait_registration_closure = lambda: calls.append("closure")
        worker._ensure_logged_in = lambda email, password: calls.append("login")
        worker._subscribe_firefly_pro = lambda card: calls.append("subscribe") or SubscribeResult(True, "verify", "ok")
        worker._extract_and_push_cookies = lambda email: calls.append("cookies") or "sid=1"

        worker.run("user@example.com", "Secret123!")

        assert calls == ["init", "entry", "register", "closure", "auto-login", "login", "subscribe", "cookies"]

    def test_run_skips_explicit_login_when_signup_already_establishes_firefly_session(self):
        class Card:
            card_number = "4111111111111111"
            exp_month = "01"
            exp_year = "2030"
            cvc = "123"

        worker = AdobeBrowserRegisterSubscribe(log_fn=lambda message: None, card=Card())
        calls = []
        worker.init_browser = lambda: calls.append("init")
        worker._gen_profile = lambda: {"fn": "A", "ln": "B", "month": 1, "year": 1990}
        worker._open_firefly_create_account_entry = lambda: calls.append("entry")
        worker._register_account = lambda email, password: calls.append("register")
        worker._wait_registration_closure = lambda: calls.append("closure")
        worker._wait_firefly_logged_in_after_signup = lambda timeout=60: calls.append("auto-login") or True
        worker._ensure_logged_in = lambda email, password: calls.append("login")
        worker._subscribe_firefly_pro = lambda card: calls.append("subscribe") or SubscribeResult(True, "verify", "ok")
        worker._extract_and_push_cookies = lambda email: calls.append("cookies") or "sid=1"

        worker.run("user@example.com", "Secret123!")

        assert calls == ["init", "entry", "register", "closure", "auto-login", "subscribe", "cookies"]

    def test_run_with_missing_card_records_subscription_failure(self):
        worker = AdobeBrowserRegisterSubscribe(log_fn=lambda message: None)
        worker.init_browser = lambda: None
        worker.page = type("FakePage", (), {"url": "https://firefly.adobe.com/", "get": lambda self, url: None, "quit": lambda self: None})()
        worker._gen_profile = lambda: {"fn": "A", "ln": "B", "month": 1, "year": 1990}
        worker._open_firefly_create_account_entry = lambda: None
        worker._wait_firefly_logged_in_after_signup = lambda timeout=60: False
        worker._register_account = lambda email, password: None
        worker._wait_registration_closure = lambda: None
        worker._ensure_logged_in = lambda email, password: None
        worker._extract_and_push_cookies = lambda email: "sid=1"

        result = worker.run("user@example.com", "Secret123!")

        assert result["extra"]["subscription"]["success"] is False
        assert result["extra"]["subscription"]["error"] == "card_missing"


class TestAdobeRegisterSubscribeLogin:
    def test_firefly_page_without_sign_in_text_is_not_enough_to_mark_logged_in(self):
        worker = AdobeBrowserRegisterSubscribe(log_fn=lambda message: None)
        worker.page = type("FakePage", (), {"url": "https://firefly.adobe.com/"})()
        worker._has_auth_cookie = lambda: False
        worker._visible_element = lambda selector, timeout=0.3: None

        assert worker._looks_logged_in() is False

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

    def test_login_entry_confirms_modal_and_switches_to_new_login_tab(self):
        class FakeIframe:
            def attr(self, name):
                if name == "src":
                    return "https://auth-light.identity.adobe.com/?client_id=clio-playground-web#large-buttons"
                return ""

        class FakeFrame:
            def __init__(self, browser):
                self.browser = browser

            def run_js(self, script):
                if "large-buttons" in script and "sp-link#sign-in" in script:
                    self.browser.open_login_tab()
                    return {"ok": True, "target": "auth-light-sign-in"}
                return {"ok": False, "reason": "wrong selector"}

        class FakeStates:
            is_displayed = True

        class FakeElement:
            states = FakeStates()

            def __init__(self, action):
                self.action = action

            class scroll:
                @staticmethod
                def to_see():
                    return None

            def click(self, by_js=False):
                self.action()

        class FakePage:
            def __init__(self, browser, url):
                self.browser = browser
                self.url = url
                self.visited = []
                self.frame = FakeFrame(browser)

            def get(self, url):
                self.visited.append(url)
                self.url = url

            def ele(self, selector, timeout=0.5):
                if selector == 'text:Sign in':
                    return FakeElement(lambda: setattr(self, "modal_open", True))
                return None

            def eles(self, selector, timeout=1):
                if selector == "iframe" and getattr(self, "modal_open", False):
                    return [FakeIframe()]
                return []

            def get_frame(self, iframe):
                return self.frame

        class FakeBrowser:
            def __init__(self):
                self.login_tab = None
                self.tabs = []

            @property
            def tab_ids(self):
                return [id(tab) for tab in self.tabs]

            def get_tab(self, tab_id=None):
                if tab_id is None:
                    return self.tabs[-1]
                for tab in self.tabs:
                    if id(tab) == tab_id:
                        return tab
                return None

            def open_login_tab(self):
                self.login_tab = FakePage(self, "https://auth.services.adobe.com/signin/new-window")
                self.tabs.append(self.login_tab)

        browser = FakeBrowser()
        main_page = FakePage(browser, "")
        browser.tabs.append(main_page)

        worker = AdobeBrowserRegisterSubscribe(log_fn=lambda message: None)
        worker.page = main_page
        worker._wait_page_ready = lambda timeout=15: True
        worker._delay = lambda lo=0.5, hi=1.5: None
        worker._looks_logged_in = lambda: False

        worker._open_firefly_login_entry()

        assert worker.page is browser.login_tab
        assert worker.page.url == "https://auth.services.adobe.com/signin/new-window"

    def test_login_modal_clicks_auth_light_iframe_sign_in_link(self):
        class FakeIframe:
            def attr(self, name):
                if name == "src":
                    return "https://auth-light.identity.adobe.com/?client_id=clio-playground-web#large-buttons"
                return ""

        class FakeFrame:
            def __init__(self, browser):
                self.browser = browser
                self.clicked_js = ""

            def run_js(self, script):
                self.clicked_js = script
                if "large-buttons" in script and "sp-link#sign-in" in script:
                    self.browser.open_login_tab()
                    return {"ok": True, "target": "auth-light-sign-in"}
                return {"ok": False, "reason": "wrong selector"}

        class FakePage:
            def __init__(self, browser, url):
                self.browser = browser
                self.url = url
                self.frame = FakeFrame(browser)

            def eles(self, selector, timeout=1):
                return [FakeIframe()] if selector == "iframe" else []

            def get_frame(self, iframe):
                return self.frame

        class FakeBrowser:
            def __init__(self):
                self.login_tab = None
                self.tabs = []

            @property
            def tab_ids(self):
                return [id(tab) for tab in self.tabs]

            def get_tab(self, tab_id=None):
                if tab_id is None:
                    return self.tabs[-1]
                for tab in self.tabs:
                    if id(tab) == tab_id:
                        return tab
                return None

            def open_login_tab(self):
                self.login_tab = FakePage(self, "https://auth.services.adobe.com/signin/new-window")
                self.tabs.append(self.login_tab)

        browser = FakeBrowser()
        main_page = FakePage(browser, "https://firefly.adobe.com/")
        browser.tabs.append(main_page)

        worker = AdobeBrowserRegisterSubscribe(log_fn=lambda message: None)
        worker.page = main_page
        worker._wait_page_ready = lambda timeout=15: True
        worker._delay = lambda lo=0.5, hi=1.5: None

        assert worker._confirm_firefly_login_modal(set(browser.tab_ids)) is True
        assert main_page.frame.clicked_js
        assert worker.page is browser.login_tab

    def test_create_account_entry_clicks_auth_light_iframe_create_account_link(self):
        class FakeIframe:
            def attr(self, name):
                if name == "src":
                    return "https://auth-light.identity.adobe.com/?client_id=clio-playground-web#large-buttons"
                return ""

        class FakeFrame:
            def __init__(self, browser):
                self.browser = browser
                self.clicked_js = ""

            def run_js(self, script):
                self.clicked_js = script
                if "large-buttons" in script and "sp-link#create-account" in script:
                    self.browser.open_signup_tab()
                    return {"ok": True, "target": "auth-light-create-account"}
                return {"ok": False, "reason": "wrong selector"}

        class FakeStates:
            is_displayed = True

        class FakeElement:
            states = FakeStates()

            def __init__(self, action):
                self.action = action

            class scroll:
                @staticmethod
                def to_see():
                    return None

            def click(self, by_js=False):
                self.action()

        class FakePage:
            def __init__(self, browser, url):
                self.browser = browser
                self.url = url
                self.visited = []
                self.frame = FakeFrame(browser)

            def get(self, url):
                self.visited.append(url)
                self.url = url

            def ele(self, selector, timeout=0.5):
                if selector == 'text:Sign in':
                    return FakeElement(lambda: setattr(self, "modal_open", True))
                return None

            def eles(self, selector, timeout=1):
                if selector == "iframe" and getattr(self, "modal_open", False):
                    return [FakeIframe()]
                return []

            def get_frame(self, iframe):
                return self.frame

        class FakeBrowser:
            def __init__(self):
                self.signup_tab = None
                self.tabs = []

            @property
            def tab_ids(self):
                return [id(tab) for tab in self.tabs]

            def get_tab(self, tab_id=None):
                if tab_id is None:
                    return self.tabs[-1]
                for tab in self.tabs:
                    if id(tab) == tab_id:
                        return tab
                return None

            def open_signup_tab(self):
                self.signup_tab = FakePage(self, "https://auth.services.adobe.com/signup/new-window")
                self.tabs.append(self.signup_tab)

        browser = FakeBrowser()
        main_page = FakePage(browser, "")
        browser.tabs.append(main_page)

        worker = AdobeBrowserRegisterSubscribe(log_fn=lambda message: None)
        worker.page = main_page
        worker._wait_page_ready = lambda timeout=15: True
        worker._delay = lambda lo=0.5, hi=1.5: None
        worker._looks_logged_in = lambda: False

        worker._open_firefly_create_account_entry()

        assert main_page.visited == ["https://firefly.adobe.com/"]
        assert main_page.frame.clicked_js
        assert worker.page is browser.signup_tab
        assert worker.page.url == "https://auth.services.adobe.com/signup/new-window"

    def test_wait_firefly_logged_in_after_signup_accepts_cookie_back_on_firefly(self, monkeypatch):
        monkeypatch.setattr(time, "sleep", lambda seconds: None)

        worker = AdobeBrowserRegisterSubscribe(log_fn=lambda message: None)
        worker.page = type("FakePage", (), {"url": "https://firefly.adobe.com/"})()
        worker._looks_logged_in = lambda: True

        assert worker._wait_firefly_logged_in_after_signup(timeout=2) is True

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

        def fail_click(selectors, label, timeout=8):
            return False
        worker._click_first_visible = fail_click
        worker._looks_logged_in = lambda: False

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


class TestAdobeRegisterSubscribeCheckout:
    def test_subscribe_flow_uses_upgrade_paywall_path_instead_of_direct_checkout_url(self):
        class Card:
            card_number = "4111111111111111"
            exp_month = "01"
            exp_year = "2030"
            cvc = "123"

        worker = AdobeBrowserRegisterSubscribe(log_fn=lambda message: None)
        worker.page = type("FakePage", (), {"url": "https://firefly.adobe.com/"})()
        calls = []
        worker._open_firefly_upgrade_paywall = lambda: calls.append("upgrade") or True
        worker._open_firefly_pro_trial_checkout = lambda: calls.append("trial") or True
        worker._checkout_origin_result = lambda: None
        worker._fill_checkout_card = lambda card: calls.append("card") or None
        worker._fill_checkout_address = lambda: calls.append("address") or None
        worker._submit_subscription = lambda: calls.append("submit") or SubscribeResult(True, "verify", "ok")

        result = worker._subscribe_firefly_pro(Card())

        assert result.success is True
        assert calls == ["upgrade", "trial", "card", "address", "submit"]

    def test_checkout_rejects_unexpected_top_level_origin_before_filling_card(self):
        class Card:
            card_number = "4111111111111111"
            exp_month = "01"
            exp_year = "2030"
            cvc = "123"

        class FakePage:
            url = "https://evil.example/checkout"

            def get(self, url):
                self.url = "https://evil.example/checkout"

        worker = AdobeBrowserRegisterSubscribe(log_fn=lambda message: None)
        worker.page = FakePage()
        worker._wait_page_ready = lambda timeout=30: True
        worker._delay = lambda lo=0.5, hi=1.5: None
        worker._open_firefly_upgrade_paywall = lambda: True
        worker._open_firefly_pro_trial_checkout = lambda: True
        worker._fill_checkout_card = lambda card: (_ for _ in ()).throw(AssertionError("should not fill card"))

        result = worker._subscribe_firefly_pro(Card())

        assert result.success is False
        assert result.stage == "checkout"
        assert result.error == "unexpected_checkout_origin"

    def test_checkout_card_requires_expiration_and_cvc(self):
        class Card:
            card_number = "4111111111111111"
            exp_month = "01"
            exp_year = "2030"
            cvc = "123"

        worker = AdobeBrowserRegisterSubscribe(log_fn=lambda message: None)
        worker._find_checkout_frame = lambda: object()
        calls = []

        def fill(frame, selectors, value, label):
            calls.append(label)
            return label == "卡号"

        worker._fill_frame_input = fill

        result = worker._fill_checkout_card(Card())

        assert result is not None
        assert result.success is False
        assert result.error == "card_exp_not_found"
        assert calls == ["卡号", "有效期"]

    def test_checkout_address_requires_billing_fields(self):
        worker = AdobeBrowserRegisterSubscribe(log_fn=lambda message: None)
        calls = []

        def fill(selectors, value, label):
            calls.append(label)
            return label != "账单姓"

        worker._fill_page_input = fill

        result = worker._fill_checkout_address()

        assert result is not None
        assert result.success is False
        assert result.error == "billing_last_name_not_found"
        assert calls == ["账单名", "账单姓"]

    def test_submit_subscription_does_not_treat_plain_firefly_redirect_as_success(self, monkeypatch):
        monkeypatch.setattr(time, "sleep", lambda seconds: None)

        class FakePage:
            url = "https://firefly.adobe.com/"
            html = "<html><body>Firefly home</body></html>"

        worker = AdobeBrowserRegisterSubscribe(log_fn=lambda message: None)
        worker.page = FakePage()
        worker._click_first_visible = lambda selectors, label, timeout=20: True

        result = worker._submit_subscription()

        assert result.success is False
        assert result.error == "result_timeout"

