"""Unit tests for Adobe platform action wiring."""
from __future__ import annotations

from core.base_platform import Account, RegisterConfig


class FakeMailbox:
    def __init__(self):
        self.calls = []

    def wait_for_code(self, account, **kwargs):
        self.calls.append((account, kwargs))
        return "123456"


class TestAdobeSubscribeOtpCallback:
    def test_builds_otp_callback_from_account_mailbox_metadata(self):
        from platforms.adobe.plugin import AdobePlatform

        mailbox = FakeMailbox()
        platform = AdobePlatform(config=RegisterConfig(executor_type="headed"), mailbox=mailbox)
        account = Account(
            platform="adobe",
            email="user@example.com",
            password="Secret123!",
            extra={
                "verification_mailbox": {
                    "provider": "testmail_api",
                    "email": "user@example.com",
                    "account_id": "acct_1",
                },
                "provider_account": {"id": "acct_1"},
                "provider_resource": {"tag": "adobe"},
            },
        )

        callback = platform._build_subscribe_otp_callback(account)

        assert callback is not None
        assert callback() == "123456"
        mailbox_account, kwargs = mailbox.calls[0]
        assert mailbox_account.email == "user@example.com"
        assert mailbox_account.account_id == "acct_1"
        assert mailbox_account.extra["mailbox_provider_key"] == "testmail_api"
        assert kwargs["keyword"] == "Adobe"
        assert kwargs["timeout"] == 120
        assert "code_pattern" in kwargs

    def test_returns_none_without_mailbox_provider(self):
        from platforms.adobe.plugin import AdobePlatform

        platform = AdobePlatform(config=RegisterConfig(executor_type="headed"), mailbox=None)
        account = Account(platform="adobe", email="user@example.com", password="Secret123!")

        assert platform._build_subscribe_otp_callback(account) is None

    def test_subscribe_action_declares_keep_browser_open_param(self):
        from platforms.adobe.plugin import AdobePlatform

        platform = AdobePlatform(config=RegisterConfig(executor_type="headed"), mailbox=None)

        actions = platform.get_platform_actions()
        subscribe_action = next(item for item in actions if item["id"] == "subscribe_pro_plus")

        assert any(param["key"] == "keep_browser_open" and param["type"] == "checkbox" for param in subscribe_action["params"])


class TestAdobeAutoSubscribeConfig:
    def test_maps_subscription_success_to_subscribed_status(self):
        from platforms.adobe.plugin import AdobePlatform

        platform = AdobePlatform(config=RegisterConfig(executor_type="headed"), mailbox=None)
        result = platform._map_mailbox_result({
            "email": "user@example.com",
            "password": "Secret123!",
            "token": "sid=1",
            "extra": {"subscription": {"success": True}},
        })

        assert result.status.value == "subscribed"

    def test_auto_subscribe_requires_card_id(self):
        from platforms.adobe.plugin import AdobePlatform

        platform = AdobePlatform(
            config=RegisterConfig(executor_type="headed", extra={"auto_subscribe": True}),
            mailbox=None,
        )

        try:
            platform._load_auto_subscribe_card()
        except RuntimeError as exc:
            assert "card_id" in str(exc)
        else:
            raise AssertionError("Expected missing card_id to fail")

    def test_auto_subscribe_string_true_is_enabled(self):
        from platforms.adobe.plugin import AdobePlatform

        platform = AdobePlatform(
            config=RegisterConfig(executor_type="headed", extra={"auto_subscribe": "true"}),
            mailbox=None,
        )

        assert platform._should_auto_subscribe() is True


    def test_auto_subscribe_rejects_invalid_card_id(self):
        from platforms.adobe.plugin import AdobePlatform

        platform = AdobePlatform(
            config=RegisterConfig(executor_type="headed", extra={"auto_subscribe": True, "card_id": "abc"}),
            mailbox=None,
        )

        try:
            platform._load_auto_subscribe_card()
        except RuntimeError as exc:
            assert "虚拟卡配置无效" in str(exc)
        else:
            raise AssertionError("Expected invalid card_id to fail")
