"""Tests for mailbox provider selection order."""
from __future__ import annotations


def test_create_mailbox_uses_only_requested_provider_without_implicit_fallback(monkeypatch):
    import core.base_mailbox as mod

    class FakeDefinition:
        enabled = True
        driver_type = "fake_driver"

        def get_metadata(self):
            return {}

    class FakeDefinitionsRepo:
        def get_by_key(self, provider_type, provider_key):
            assert provider_type == "mailbox"
            return FakeDefinition()

    class FakeSettingsRepo:
        def list_enabled(self, provider_type):
            raise AssertionError("create_mailbox must not append all enabled providers implicitly")

        def resolve_runtime_settings(self, provider_type, provider_key, extra):
            return {"provider_key": provider_key}

    created: list[str] = []

    def fake_factory(extra, proxy):
        created.append(extra["provider_key"])
        return object()

    monkeypatch.setattr(
        "infrastructure.provider_definitions_repository.ProviderDefinitionsRepository",
        lambda: FakeDefinitionsRepo(),
    )
    monkeypatch.setattr(
        "infrastructure.provider_settings_repository.ProviderSettingsRepository",
        lambda: FakeSettingsRepo(),
    )
    monkeypatch.setitem(mod.MAILBOX_FACTORY_REGISTRY, "fake_driver", fake_factory)

    mod.create_mailbox("private_api", extra={}, proxy=None)

    assert created == ["private_api"]


def test_create_mailbox_honors_explicit_fallbacks(monkeypatch):
    import core.base_mailbox as mod

    class FakeDefinition:
        enabled = True
        driver_type = "fake_driver"

        def get_metadata(self):
            return {}

    class FakeDefinitionsRepo:
        def get_by_key(self, provider_type, provider_key):
            return FakeDefinition()

    class FakeSettingsRepo:
        def resolve_runtime_settings(self, provider_type, provider_key, extra):
            return {"provider_key": provider_key}

    created: list[str] = []

    def fake_factory(extra, proxy):
        created.append(extra["provider_key"])
        return object()

    monkeypatch.setattr(
        "infrastructure.provider_definitions_repository.ProviderDefinitionsRepository",
        lambda: FakeDefinitionsRepo(),
    )
    monkeypatch.setattr(
        "infrastructure.provider_settings_repository.ProviderSettingsRepository",
        lambda: FakeSettingsRepo(),
    )
    monkeypatch.setitem(mod.MAILBOX_FACTORY_REGISTRY, "fake_driver", fake_factory)

    mailbox = mod.create_mailbox(
        "private_api",
        extra={"mail_provider_fallbacks": "cfworker,tempmail_lol"},
        proxy=None,
    )

    assert isinstance(mailbox, mod.FallbackMailbox)
    assert created == ["private_api", "cfworker", "tempmail_lol"]
