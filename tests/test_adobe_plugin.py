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
