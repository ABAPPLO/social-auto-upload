# -*- coding: utf-8 -*-
"""系统 Chrome 缺失时退回内置 Chromium 的启动兜底测试（不启动真浏览器）。"""
import asyncio
import unittest
from unittest.mock import AsyncMock, MagicMock

from utils.base_social_media import chromium_launch_with_fallback, direct_chromium_launch

CHROME_MISSING = (
    "BrowserType.launch: Chromium distribution 'chrome' is not found at "
    "/opt/google/chrome/chrome Run \"playwright install chrome\""
)


def make_playwright(side_effect):
    playwright = MagicMock()
    launch = AsyncMock(side_effect=side_effect)
    playwright.chromium.launch = launch
    return playwright, launch


class ChromeFallbackTests(unittest.TestCase):
    def test_missing_chrome_falls_back_to_bundled_chromium(self):
        browser = object()
        playwright, launch = make_playwright([RuntimeError(CHROME_MISSING), browser])
        result = asyncio.run(chromium_launch_with_fallback(playwright, headless=True, channel="chrome"))
        self.assertIs(result, browser)
        self.assertEqual(launch.await_count, 2)
        second_call = launch.await_args_list[1]
        self.assertEqual(second_call.kwargs.get("channel"), "chromium")
        self.assertTrue(second_call.kwargs.get("headless"))

    def test_other_launch_errors_propagate(self):
        playwright, launch = make_playwright(RuntimeError("Target page, context or browser has been closed"))
        with self.assertRaises(RuntimeError):
            asyncio.run(chromium_launch_with_fallback(playwright, headless=True, channel="chrome"))
        self.assertEqual(launch.await_count, 1)

    def test_no_fallback_for_non_chrome_channel(self):
        # channel=chromium（自带内核）启动失败不该触发降级重试
        playwright, launch = make_playwright(RuntimeError(CHROME_MISSING))
        with self.assertRaises(RuntimeError):
            asyncio.run(chromium_launch_with_fallback(playwright, channel="chromium"))
        self.assertEqual(launch.await_count, 1)

    def test_direct_launch_keeps_no_proxy_arg_through_fallback(self):
        browser = object()
        playwright, launch = make_playwright([RuntimeError(CHROME_MISSING), browser])
        result = asyncio.run(direct_chromium_launch(playwright, headless=True, channel="chrome", args=["--foo"]))
        self.assertIs(result, browser)
        second_args = launch.await_args_list[1].kwargs.get("args")
        self.assertIn("--no-proxy-server", second_args)
        self.assertIn("--foo", second_args)


if __name__ == "__main__":
    unittest.main()
