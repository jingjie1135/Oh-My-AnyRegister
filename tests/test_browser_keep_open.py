"""Unit tests for headed browser keep-open configuration."""
from __future__ import annotations

from core.base_platform import RegisterConfig
from core.executors.playwright import PlaywrightExecutor


def test_register_config_defaults_to_closing_browser():
    config = RegisterConfig(executor_type="headed")

    assert config.keep_browser_open is False


def test_playwright_keep_open_only_applies_to_headed_mode():
    original_init = PlaywrightExecutor._init
    PlaywrightExecutor._init = lambda self: None
    try:
        headed = PlaywrightExecutor(proxy=None, headless=False, keep_open=True)
        headless = PlaywrightExecutor(proxy=None, headless=True, keep_open=True)
    finally:
        PlaywrightExecutor._init = original_init

    assert headed.keep_open is True
    assert headless.keep_open is False


def test_playwright_close_skips_browser_when_keep_open():
    headed = PlaywrightExecutor.__new__(PlaywrightExecutor)
    headed.headless = False
    headed.keep_open = True
    headed._browser = object()
    headed._pw = object()

    headed.close()

    assert headed._browser is not None
