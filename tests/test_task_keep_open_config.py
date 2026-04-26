"""Unit tests for keep_browser_open task payload coercion."""
from __future__ import annotations

from application.tasks import _bool_config


def resolve_keep_open(payload: dict, extra: dict) -> bool:
    value = extra["keep_browser_open"] if "keep_browser_open" in extra else payload.get("keep_browser_open")
    return _bool_config(value, False)


def test_extra_false_overrides_top_level_true():
    assert resolve_keep_open({"keep_browser_open": True}, {"keep_browser_open": False}) is False


def test_top_level_used_when_extra_key_absent():
    assert resolve_keep_open({"keep_browser_open": True}, {}) is True


def test_bool_config_accepts_common_false_strings():
    for value in ["0", "false", "no", "off", "否"]:
        assert _bool_config(value, default=True) is False
