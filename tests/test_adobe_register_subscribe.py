"""Unit tests for Adobe register + subscribe workflow."""
from __future__ import annotations

import time

from platforms.adobe.browser_register_subscribe import (
    AdobeBrowserRegisterSubscribe,
)
from platforms.adobe.browser_subscribe import SubscribeResult
from platforms.adobe.plugin import ADOBE_OTP_MAIL_KEYWORD


class TestAdobeRegisterSubscribeConstants:
    def test_register_subscribe_module_no_longer_exports_static_milo_checkout_url(self):
        import platforms.adobe.browser_register_subscribe as module

        assert not hasattr(module, "FIREFLY_PRO_CHECKOUT_URL")

    def test_adobe_otp_mail_keyword_does_not_require_english_adobe_subject(self):
        assert ADOBE_OTP_MAIL_KEYWORD == ""


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

    def test_auth_light_click_does_not_use_dom_diagnostic_index_as_frame_handle(self):
        class FakePage:
            def __init__(self):
                self.get_frame_targets = []

            def eles(self, selector, timeout=1):
                return []

            def run_js(self, script):
                if "authLightFrames" in script:
                    return {
                        "authLightFrames": [
                            {"index": 0, "src": "https://auth-light.identity.adobe.com/#large-buttons", "title": ""}
                        ],
                        "dialogs": [],
                    }
                return None

            def get_frame(self, target):
                self.get_frame_targets.append(target)
                return None

        worker = AdobeBrowserRegisterSubscribe(log_fn=lambda message: None)
        worker.page = FakePage()
        worker._delay = lambda lo=0.5, hi=1.5: None

        assert worker._click_auth_light_create_account_link(timeout=0.1) is False
        assert worker.page.get_frame_targets == []

    def test_auth_light_click_uses_shadow_host_iframe_element(self):
        class FakeFrame:
            def __init__(self):
                self.clicked_js = ""

            def run_js(self, script):
                self.clicked_js = script
                if "sp-link#create-account" in script:
                    return {"ok": True, "target": "auth-light-create-account"}
                return {"ok": False}

        class FakeShadowRoot:
            def __init__(self, iframe):
                self.iframe = iframe

            def ele(self, selector, timeout=1):
                if selector == 'iframe':
                    return self.iframe
                return None

        class FakeHost:
            def __init__(self, iframe):
                self.shadow_root = FakeShadowRoot(iframe)
                self.sr = self.shadow_root

        class FakePage:
            def __init__(self):
                self.frame = FakeFrame()
                self.iframe = object()

            def eles(self, selector, timeout=1):
                return []

            def run_js(self, script):
                if "authLightFrames" in script:
                    return {"authLightFrames": [], "dialogs": []}
                return None

            def ele(self, selector, timeout=1):
                if selector in {'#sentry', 'tag:susi-sentry', 'susi-sentry'}:
                    return FakeHost(self.iframe)
                return None

            def get_frame(self, target):
                if target is self.iframe:
                    return self.frame
                return None

        worker = AdobeBrowserRegisterSubscribe(log_fn=lambda message: None)
        worker.page = FakePage()
        worker._delay = lambda lo=0.5, hi=1.5: None

        assert worker._click_auth_light_create_account_link(timeout=1) is True
        assert "sp-link#create-account" in worker.page.frame.clicked_js

    def test_auth_light_click_prefers_shadow_root_get_frame_for_shadow_iframe(self):
        class FakeFrame:
            def __init__(self):
                self.clicked_js = ""

            def run_js(self, script):
                self.clicked_js = script
                if "sp-link#create-account" in script:
                    return {"ok": True, "target": "auth-light-create-account"}
                return {"ok": False}

        class FakeShadowRoot:
            def __init__(self, frame):
                self.frame = frame
                self.get_frame_selectors = []

            def get_frame(self, selector):
                self.get_frame_selectors.append(selector)
                if selector == 't:iframe':
                    return self.frame
                return None

            def ele(self, selector, timeout=1):
                raise AssertionError("shadow.ele() should not be needed when shadow.get_frame() works")

        class FakeHost:
            def __init__(self, frame):
                self.shadow_root = FakeShadowRoot(frame)
                self.sr = self.shadow_root

        class FakePage:
            def __init__(self):
                self.frame = FakeFrame()
                self.host = FakeHost(self.frame)

            def eles(self, selector, timeout=1):
                return []

            def run_js(self, script):
                if "authLightFrames" in script:
                    return {"authLightFrames": [], "dialogs": []}
                return None

            def ele(self, selector, timeout=1):
                if selector in {'tag:susi-sentry#sentry', '#sentry', 'tag:susi-sentry', 'susi-sentry'}:
                    return self.host
                return None

            def get_frame(self, target):
                raise AssertionError("page.get_frame() should not be needed when shadow.get_frame() works")

        worker = AdobeBrowserRegisterSubscribe(log_fn=lambda message: None)
        worker.page = FakePage()
        worker._delay = lambda lo=0.5, hi=1.5: None

        assert worker._click_auth_light_create_account_link(timeout=1) is True
        assert worker.page.host.sr.get_frame_selectors == ['t:iframe']
        assert "sp-link#create-account" in worker.page.frame.clicked_js

    def test_auth_light_click_falls_back_to_shadow_host_when_snapshot_index_is_not_frame_handle(self):
        class FakeFrame:
            def __init__(self):
                self.clicked_js = ""

            def run_js(self, script):
                self.clicked_js = script
                if "sp-link#create-account" in script:
                    return {"ok": True, "target": "auth-light-create-account"}
                return {"ok": False}

        class FakeShadowRoot:
            def __init__(self, iframe):
                self.iframe = iframe

            def ele(self, selector, timeout=1):
                if selector == 'iframe':
                    return self.iframe
                return None

        class FakeHost:
            def __init__(self, iframe):
                self.shadow_root = FakeShadowRoot(iframe)
                self.sr = self.shadow_root

        class FakePage:
            def __init__(self):
                self.frame = FakeFrame()
                self.shadow_iframe = object()
                self.get_frame_targets = []

            def eles(self, selector, timeout=1):
                return []

            def run_js(self, script):
                if "authLightFrames" in script:
                    return {
                        "authLightFrames": [
                            {"index": 0, "src": "https://auth-light.identity.adobe.com/#large-buttons", "title": ""}
                        ],
                        "dialogs": [],
                    }
                return None

            def ele(self, selector, timeout=1):
                if selector in {'#sentry', 'tag:susi-sentry', 'susi-sentry'}:
                    return FakeHost(self.shadow_iframe)
                return None

            def get_frame(self, target):
                self.get_frame_targets.append(target)
                if target is self.shadow_iframe:
                    return self.frame
                return None

        worker = AdobeBrowserRegisterSubscribe(log_fn=lambda message: None)
        worker.page = FakePage()
        worker._delay = lambda lo=0.5, hi=1.5: None

        assert worker._click_auth_light_create_account_link(timeout=1) is True
        assert 0 not in worker.page.get_frame_targets
        assert worker.page.shadow_iframe in worker.page.get_frame_targets
        assert "sp-link#create-account" in worker.page.frame.clicked_js

    def test_auth_light_click_logs_snapshot_when_iframe_seen_but_click_fails(self):
        messages = []

        class FakePage:
            def eles(self, selector, timeout=1):
                return []

            def run_js(self, script):
                if "authLightFrames" in script:
                    return {
                        "authLightFrames": [
                            {"index": 0, "src": "https://auth-light.identity.adobe.com/#large-buttons", "title": ""}
                        ],
                        "frames": [
                            {"index": 0, "visible": True, "src": "https://auth-light.identity.adobe.com/#large-buttons", "title": "", "testid": "", "path": "document/susi-sentry#sentry::shadow"}
                        ],
                        "dialogs": [],
                        "shadowHosts": [{"tag": "susi-sentry", "path": "document", "id": "sentry", "testid": ""}],
                        "url": "https://firefly.adobe.com/",
                    }
                return None

            def ele(self, selector, timeout=1):
                return None

            def get_frame(self, target):
                return None

        worker = AdobeBrowserRegisterSubscribe(log_fn=messages.append)
        worker.page = FakePage()
        worker._delay = lambda lo=0.5, hi=1.5: None

        assert worker._click_auth_light_create_account_link(timeout=0.1) is False
        assert any("auth-light 诊断 URL" in message for message in messages)
        assert any("iframe 诊断" in message for message in messages)

    def test_login_entry_prefers_verified_firefly_header_sign_in_selector(self):
        clicked_selectors = []

        worker = AdobeBrowserRegisterSubscribe(log_fn=lambda message: None)
        worker.page = type("FakePage", (), {"get": lambda self, url: None})()
        worker._wait_page_ready = lambda timeout=20: True
        worker._delay = lambda lo=0.5, hi=1.5: None
        worker._looks_logged_in = lambda: False
        worker._current_tab_ids = lambda: []
        worker._switch_to_new_tab_after_click = lambda before_tab_ids, timeout=2: False
        worker._confirm_firefly_login_modal = lambda before_tab_ids: True

        def click_first_visible(selectors, label, timeout=12):
            clicked_selectors.extend(selectors)
            return True

        worker._click_first_visible = click_first_visible

        worker._open_firefly_login_entry()

        assert clicked_selectors[0] == '[data-test-id="unav-profile--sign-in"]'
        assert '[data-testid="unav-profile--sign-in"]' in clicked_selectors

    def test_confirm_login_modal_waits_long_enough_for_auth_light_sign_in(self):
        worker = AdobeBrowserRegisterSubscribe(log_fn=lambda message: None)
        captured = []
        worker._click_auth_light_sign_in_link = lambda timeout=8: captured.append(timeout) or False

        assert worker._confirm_firefly_login_modal(set()) is False
        assert captured == [30]

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
        assert worker._firefly_parent_page is main_page
        assert worker.page is browser.signup_tab
        assert worker.page.url == "https://auth.services.adobe.com/signup/new-window"

    def test_create_account_entry_prefers_verified_firefly_header_sign_in_selector(self):
        clicked_selectors = []

        worker = AdobeBrowserRegisterSubscribe(log_fn=lambda message: None)
        worker.page = type("FakePage", (), {"get": lambda self, url: None})()
        worker._wait_page_ready = lambda timeout=20: True
        worker._delay = lambda lo=0.5, hi=1.5: None
        worker._current_tab_ids = lambda: []
        worker._click_auth_light_create_account_link = lambda timeout=30: True
        worker._switch_to_new_tab_after_click = lambda before_tab_ids, timeout=12: True

        def click_first_visible(selectors, label, timeout=12):
            clicked_selectors.extend(selectors)
            return True

        worker._click_first_visible = click_first_visible

        worker._open_firefly_create_account_entry()

        assert clicked_selectors[0] == '[data-test-id="unav-profile--sign-in"]'
        assert '[data-testid="unav-profile--sign-in"]' in clicked_selectors

    def test_register_account_does_not_navigate_to_static_signup_after_firefly_entry(self):
        class FakePage:
            url = "https://auth.services.adobe.com/...idp_flow_type=create_account#/signup"

            def __init__(self):
                self.visited = []

            def get(self, url):
                self.visited.append(url)

        worker = AdobeBrowserRegisterSubscribe(log_fn=lambda message: None)
        worker.page = FakePage()
        worker._registration_profile = {"fn": "A", "ln": "B", "month": 1, "year": 1990}
        worker._wait_page_ready = lambda timeout=20: True
        worker._delay = lambda lo=0.5, hi=1.5: None
        worker._fill_signup_credentials = lambda email, password: "profile"
        worker._fill_signup_profile = lambda: None
        worker._submit_signup_profile = lambda: "success"

        worker._register_account("user@example.com", "Secret123!")

        assert worker.page.visited == []

    def test_detects_real_arkose_iframe_by_arks_client_and_verification_title(self):
        class FakeStates:
            is_displayed = True

        class FakeIframe:
            states = FakeStates()

            def __init__(self, src, title):
                self._src = src
                self._title = title

            def attr(self, name):
                return {"src": self._src, "title": self._title}.get(name, "")

        class FakePage:
            def ele(self, selector, timeout=0.5):
                return None

            def eles(self, selector, timeout=1):
                if selector == "iframe":
                    return [FakeIframe("https://arks-client.adobe.com/frame", "Verification challenge")]
                return []

        worker = AdobeBrowserRegisterSubscribe(log_fn=lambda message: None)
        worker.page = FakePage()

        assert worker._is_arkose_visible() is True

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
    def test_pro_trial_selector_does_not_match_pro_plus_before_exact_pro_trial(self):
        class FakeStates:
            is_displayed = True

        class FakeButton:
            states = FakeStates()

            def __init__(self, label, clicks):
                self.label = label
                self.clicks = clicks

            def click(self):
                self.clicks.append(self.label)

        class FakeFrame:
            def __init__(self):
                self.clicks = []

            def ele(self, selector, timeout=1):
                if selector == 'button[aria-label="免費試用, Adobe Firefly Pro"]':
                    return FakeButton("pro", self.clicks)
                if selector == 'button[aria-label*="Adobe Firefly Pro"]':
                    return FakeButton("pro-plus", self.clicks)
                return None

        frame = FakeFrame()
        worker = AdobeBrowserRegisterSubscribe(log_fn=lambda message: None)
        worker._find_paywall_frame = lambda timeout=20: frame
        worker._delay = lambda lo=0.5, hi=1.5: None

        assert worker._open_firefly_pro_trial_checkout() is True
        assert frame.clicks == ["pro"]

    def test_checkout_address_uses_checkout_frame_not_top_level_page(self):
        worker = AdobeBrowserRegisterSubscribe(log_fn=lambda message: None)
        calls = []

        class FakeFrame:
            pass

        checkout_frame = FakeFrame()
        worker._find_checkout_frame = lambda timeout=10: checkout_frame

        def fill(context, selectors, value, label):
            calls.append((context, label))
            return True

        worker._fill_context_input = fill

        result = worker._fill_checkout_address()

        assert result is None
        assert calls
        assert all(context is checkout_frame for context, label in calls)

    def test_checkout_card_continues_when_cvc_field_is_absent(self):
        class Card:
            card_number = "4111111111111111"
            exp_month = "01"
            exp_year = "2030"
            cvc = "123"

        worker = AdobeBrowserRegisterSubscribe(log_fn=lambda message: None)
        worker._find_credit_tokenizer_frame = lambda timeout=45: object()
        calls = []

        def fill(frame, selectors, value, label):
            calls.append(label)
            return label in {"卡号", "有效期"}

        worker._fill_frame_input = fill

        assert worker._fill_checkout_card(Card()) is None
        assert calls == ["卡号", "有效期", "CVC"]

    def test_submit_subscription_clicks_traditional_chinese_cta_inside_checkout_frame(self, monkeypatch):
        monkeypatch.setattr(time, "sleep", lambda seconds: None)

        class FakeStates:
            is_displayed = True

        class FakeButton:
            states = FakeStates()

            def __init__(self):
                self.clicked = False

            class scroll:
                @staticmethod
                def to_see():
                    return None

            def click(self, by_js=False):
                self.clicked = True

        class FakeFrame:
            html = "<html><body>thank you</body></html>"

            def __init__(self):
                self.button = FakeButton()

            def ele(self, selector, timeout=0.5):
                if selector == 'button[data-testid="action-container-cta-summary-panel-inline"]':
                    return self.button
                return None

        frame = FakeFrame()
        worker = AdobeBrowserRegisterSubscribe(log_fn=lambda message: None)
        worker._find_checkout_frame = lambda timeout=10: frame
        worker._delay = lambda lo=0.5, hi=1.5: None

        result = worker._submit_subscription()

        assert result.success is True
        assert frame.button.clicked is True

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

    def test_checkout_card_requires_expiration_but_not_cvc(self):
        class Card:
            card_number = "4111111111111111"
            exp_month = "01"
            exp_year = "2030"
            cvc = "123"

        worker = AdobeBrowserRegisterSubscribe(log_fn=lambda message: None)
        worker._find_credit_tokenizer_frame = lambda timeout=45: object()
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
        checkout_frame = object()
        worker._find_checkout_frame = lambda timeout=10: checkout_frame

        def fill(context, selectors, value, label):
            calls.append((context, label))
            return label != "账单姓"

        worker._fill_context_input = fill

        result = worker._fill_checkout_address()

        assert result is not None
        assert result.success is False
        assert result.error == "billing_last_name_not_found"
        assert calls == [(checkout_frame, "账单邮箱"), (checkout_frame, "账单名"), (checkout_frame, "账单姓")]

    def test_submit_subscription_does_not_treat_plain_firefly_redirect_as_success(self, monkeypatch):
        monkeypatch.setattr(time, "sleep", lambda seconds: None)

        class FakePage:
            url = "https://firefly.adobe.com/"
            html = "<html><body>Firefly home</body></html>"

        class FakeStates:
            is_displayed = True

        class FakeButton:
            states = FakeStates()

            class scroll:
                @staticmethod
                def to_see():
                    return None

            def click(self, by_js=False):
                return None

        class FakeFrame:
            html = "<html><body>Firefly home</body></html>"

            def ele(self, selector, timeout=0.5):
                if selector == 'button[data-testid="action-container-cta-summary-panel-inline"]':
                    return FakeButton()
                return None

        worker = AdobeBrowserRegisterSubscribe(log_fn=lambda message: None)
        worker.page = FakePage()
        worker._find_checkout_frame = lambda timeout=10: FakeFrame()
        worker._delay = lambda lo=0.5, hi=1.5: None

        result = worker._submit_subscription()

        assert result.success is False
        assert result.error == "result_timeout"

