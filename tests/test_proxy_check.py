# -*- coding: utf-8 -*-
"""代理出口 IP 预检（utils/network.py）与上传入口挂钩（sau_cli）的单元测试。"""
import asyncio
import os
import tempfile
import unittest
import urllib.error
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from utils.network import (
    ProxyCheckError,
    ProxyCheckResult,
    check_proxy,
    ensure_proxy_ready,
    load_proxy_exit_state,
    record_exit_ip,
)

IPINFO_URL, IPIFY_URL = "http://ipinfo.io/ip", "https://api.ipify.org"


class _FakeResponse:
    def __init__(self, body: str):
        self._body = body.encode()

    def read(self, n=-1):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class _FakeOpener:
    """按目标 URL 返回预设响应或抛预设异常。"""

    def __init__(self, behavior: dict):
        self.behavior = behavior

    def open(self, url, timeout=None):
        outcome = self.behavior[url]
        if isinstance(outcome, Exception):
            raise outcome
        return _FakeResponse(outcome)


def _patch_opener(behavior: dict):
    return patch("utils.network._proxy_opener", return_value=_FakeOpener(behavior))


def _http_error(code: int) -> urllib.error.HTTPError:
    return urllib.error.HTTPError(IPINFO_URL, code, "err", None, None)


class CheckProxyTests(unittest.TestCase):
    PROXY = "http://10.168.1.105:7890"

    def test_exit_ip_returned_on_success(self):
        with _patch_opener({IPINFO_URL: "67.219.111.233\n"}):
            result = check_proxy(self.PROXY)
        self.assertTrue(result.reachable)
        self.assertEqual(result.exit_ip, "67.219.111.233")
        self.assertIsNone(result.error)

    def test_connection_refused_means_unreachable(self):
        refused = urllib.error.URLError(ConnectionRefusedError(111, "Connection refused"))
        with _patch_opener({IPINFO_URL: refused, IPIFY_URL: refused}):
            result = check_proxy(self.PROXY)
        self.assertFalse(result.reachable)
        self.assertIsNone(result.exit_ip)
        self.assertIn("无法连接代理", result.error)

    def test_proxy_502_means_upstream_dead(self):
        # 代理自身可达但上游节点全部失效（如节点过期），应判定不可用
        with _patch_opener({IPINFO_URL: _http_error(502), IPIFY_URL: _http_error(504)}):
            result = check_proxy(self.PROXY)
        self.assertFalse(result.reachable)
        self.assertIn("上游节点失效", result.error)

    def test_rate_limited_first_source_falls_back_to_second(self):
        with _patch_opener({IPINFO_URL: _http_error(403), IPIFY_URL: "1.2.3.4"}):
            result = check_proxy(self.PROXY)
        self.assertTrue(result.reachable)
        self.assertEqual(result.exit_ip, "1.2.3.4")

    def test_ip_lookup_failure_is_soft_when_proxy_works(self):
        # 两个 IP 服务都限流/异常但不是 502/504：代理可用，仅出口未知
        with _patch_opener({IPINFO_URL: _http_error(403), IPIFY_URL: _http_error(429)}):
            result = check_proxy(self.PROXY)
        self.assertTrue(result.reachable)
        self.assertIsNone(result.exit_ip)
        self.assertIsNotNone(result.error)


class RecordExitIpTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.state_file = Path(self._tmp.name) / "proxy_exit_state.json"

    def tearDown(self):
        self._tmp.cleanup()

    PROXY = "http://10.168.1.105:7890"

    def test_first_record_is_not_a_change(self):
        change = record_exit_ip(self.PROXY, "1.1.1.1", self.state_file)
        self.assertFalse(change["changed"])
        self.assertIsNone(change["previous_ip"])
        self.assertEqual(load_proxy_exit_state(self.state_file)[self.PROXY]["exit_ip"], "1.1.1.1")

    def test_same_ip_is_not_a_change(self):
        record_exit_ip(self.PROXY, "1.1.1.1", self.state_file)
        change = record_exit_ip(self.PROXY, "1.1.1.1", self.state_file)
        self.assertFalse(change["changed"])

    def test_different_ip_flags_change_and_keeps_history(self):
        record_exit_ip(self.PROXY, "1.1.1.1", self.state_file)
        change = record_exit_ip(self.PROXY, "2.2.2.2", self.state_file)
        self.assertTrue(change["changed"])
        self.assertEqual(change["previous_ip"], "1.1.1.1")
        entry = load_proxy_exit_state(self.state_file)[self.PROXY]
        self.assertEqual(entry["exit_ip"], "2.2.2.2")
        self.assertEqual(entry["previous_exit_ip"], "1.1.1.1")
        self.assertIn("changed_at", entry)

    def test_corrupt_state_file_is_tolerated(self):
        self.state_file.write_text("{ not json", encoding="utf-8")
        self.assertEqual(load_proxy_exit_state(self.state_file), {})
        change = record_exit_ip(self.PROXY, "3.3.3.3", self.state_file)
        self.assertFalse(change["changed"])


class EnsureProxyReadyTests(unittest.TestCase):
    def _with_logger(self):
        logger = MagicMock()
        stack = patch("utils.network._platform_logger", return_value=logger)
        return logger, stack

    def test_noop_when_no_proxy_configured(self):
        logger, logger_patch = self._with_logger()
        with logger_patch, patch("utils.network.get_platform_proxy", return_value=None) as resolver:
            with patch("utils.network.check_proxy") as checker:
                result = ensure_proxy_ready("douyin")
        self.assertTrue(result.reachable)
        resolver.assert_called_once_with("douyin")
        checker.assert_not_called()  # 国内平台/直连环境不产生任何网络请求

    def test_unreachable_proxy_raises_with_actionable_message(self):
        logger, logger_patch = self._with_logger()
        failure = ProxyCheckResult(False, None, "无法连接代理: Connection refused")
        with logger_patch, patch("utils.network.get_platform_proxy", return_value="http://p:7890"), \
                patch("utils.network.check_proxy", return_value=failure):
            with self.assertRaises(ProxyCheckError) as ctx:
                ensure_proxy_ready("youtube")
        self.assertIn("youtube", str(ctx.exception))
        self.assertIn("http://p:7890", str(ctx.exception))
        logger.error.assert_called_once()

    def test_exit_ip_change_warns_but_does_not_block(self):
        logger, logger_patch = self._with_logger()
        ok = ProxyCheckResult(True, "2.2.2.2", None)
        with logger_patch, patch("utils.network.get_platform_proxy", return_value="http://p:7890"), \
                patch("utils.network.check_proxy", return_value=ok), \
                patch("utils.network.record_exit_ip", return_value={"changed": True, "previous_ip": "1.1.1.1"}):
            result = ensure_proxy_ready("tiktok")
        self.assertTrue(result.reachable)
        logger.warning.assert_called_once()
        self.assertIn("1.1.1.1", logger.warning.call_args[0][0])

    def test_soft_ip_failure_continues(self):
        logger, logger_patch = self._with_logger()
        soft = ProxyCheckResult(True, None, "http://ipinfo.io/ip 返回 HTTP 403")
        with logger_patch, patch("utils.network.get_platform_proxy", return_value="http://p:7890"), \
                patch("utils.network.check_proxy", return_value=soft), \
                patch("utils.network.record_exit_ip") as recorder:
            result = ensure_proxy_ready("instagram")
        self.assertTrue(result.reachable)
        recorder.assert_not_called()  # 没拿到出口 IP 时不落盘
        logger.warning.assert_called_once()


class UploadPreflightHookTests(unittest.TestCase):
    """三个海外上传入口都必须在启动浏览器前做代理预检。"""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.video = Path(self._tmp.name) / "v.mp4"
        self.video.write_bytes(b"x")

    def tearDown(self):
        self._tmp.cleanup()

    def test_youtube_upload_runs_preflight(self):
        import sau_cli

        request = sau_cli.YouTubeVideoUploadRequest(
            account_name="a", video_file=self.video, title="t", description="", tags=[])
        with patch("sau_cli.ensure_proxy_ready") as preflight, \
                patch("sau_cli.youtube_setup", new=AsyncMock(return_value=True)), \
                patch.object(sau_cli.YouTubeVideo, "main", new=AsyncMock()):
            asyncio.run(sau_cli.upload_youtube_video(request))
        preflight.assert_called_once_with("youtube")

    def test_tiktok_upload_runs_preflight(self):
        import sau_cli

        request = sau_cli.TiktokVideoUploadRequest(
            account_name="a", video_file=self.video, title="t", description="", tags=[],
            publish_date=0)
        with patch("sau_cli.ensure_proxy_ready") as preflight, \
                patch("sau_cli.tiktok_setup", new=AsyncMock(return_value=True)), \
                patch.object(sau_cli.TiktokVideo, "main", new=AsyncMock()):
            asyncio.run(sau_cli.upload_tiktok_video(request))
        preflight.assert_called_once_with("tiktok")

    def test_overseas_upload_runs_preflight_with_platform(self):
        import sau_cli

        request = sau_cli.OverseasVideoUploadRequest(
            platform="instagram", account_name="a", video_file=self.video,
            title="t", description="", tags=[])
        with patch("sau_cli.ensure_proxy_ready") as preflight, \
                patch.dict(sau_cli.OVERSEAS_SETUPS, {"instagram": AsyncMock(return_value=True)}), \
                patch.object(sau_cli.InstagramVideo, "main", new=AsyncMock()):
            asyncio.run(sau_cli.upload_overseas_video(request))
        preflight.assert_called_once_with("instagram")

    def test_preflight_failure_fails_upload_before_browser(self):
        import sau_cli

        request = sau_cli.YouTubeVideoUploadRequest(
            account_name="a", video_file=self.video, title="t", description="", tags=[])
        setup = AsyncMock(return_value=True)
        with patch("sau_cli.ensure_proxy_ready", side_effect=ProxyCheckError("代理不可用")), \
                patch("sau_cli.youtube_setup", new=setup):
            with self.assertRaises(ProxyCheckError):
                asyncio.run(sau_cli.upload_youtube_video(request))
        setup.assert_not_called()  # 预检失败时不该再碰浏览器流程


class ProxyStatusEndpointTests(unittest.TestCase):
    """/api/proxy-status 的行组装与缓存逻辑（不发起真实网络请求）。"""

    def setUp(self):
        from sau_webapp import routes

        self.routes = routes
        routes._proxy_status_cache["data"] = None
        routes._proxy_status_cache["at"] = 0.0
        self._proxies = {"youtube": "http://p:7890", "tiktok": "http://p:7890"}
        self._resolver = lambda platform: self._proxies.get(platform)
        ok = ProxyCheckResult(True, "2.2.2.2", None)
        self._checker = lambda proxy, timeout=5.0: ok

    def test_rows_and_drift_detection(self):
        state = {"http://p:7890": {"exit_ip": "1.1.1.1"}}
        with patch.object(self.routes, "get_platform_proxy", self._resolver), \
                patch.object(self.routes, "check_proxy", self._checker), \
                patch.object(self.routes, "load_proxy_exit_state", return_value=state):
            data = self.routes.get_proxy_status(refresh=True)
        rows = {row["platform"]: row for row in data["platforms"]}
        self.assertEqual(len(rows), 5)
        self.assertEqual(rows["youtube"]["exit_ip"], "2.2.2.2")
        self.assertTrue(rows["youtube"]["differs_from_last_upload"])  # 2.2.2.2 != 上次上传 1.1.1.1
        self.assertFalse(rows["instagram"]["differs_from_last_upload"])  # 无上次记录
        self.assertTrue(rows["instagram"]["ok"])  # 直连视为 ok

    def test_cache_prevents_recheck_within_ttl(self):
        calls = []

        def counting_checker(proxy, timeout=5.0):
            calls.append(proxy)
            return ProxyCheckResult(True, "2.2.2.2", None)

        with patch.object(self.routes, "get_platform_proxy", self._resolver), \
                patch.object(self.routes, "check_proxy", counting_checker), \
                patch.object(self.routes, "load_proxy_exit_state", return_value={}):
            self.routes.get_proxy_status(refresh=True)
            self.routes.get_proxy_status(refresh=False)
        self.assertEqual(len(calls), 2)  # 只有 youtube/tiktok 配了代理，第二次命中缓存


class DirectChromiumLaunchTests(unittest.TestCase):
    """国内平台的 chromium 必须强制直连（--no-proxy-server），与桌面代理状态解耦。"""

    def _fake_playwright(self):
        pw = MagicMock()
        pw.chromium.launch = AsyncMock()
        return pw

    def test_appends_no_proxy_flag_and_keeps_existing_args(self):
        from utils.base_social_media import direct_chromium_launch

        pw = self._fake_playwright()
        existing = ["--no-sandbox"]
        asyncio.run(direct_chromium_launch(pw, headless=True, args=existing))
        pw.chromium.launch.assert_awaited_once_with(
            headless=True, args=["--no-sandbox", "--no-proxy-server"])
        self.assertEqual(existing, ["--no-sandbox"])  # 不原地污染调用方列表

    def test_flag_added_even_without_existing_args(self):
        from utils.base_social_media import direct_chromium_launch

        pw = self._fake_playwright()
        asyncio.run(direct_chromium_launch(pw))
        pw.chromium.launch.assert_awaited_once_with(args=["--no-proxy-server"])


class BiliupEnvScrubTests(unittest.TestCase):
    """B站 biliup 子进程必须剥离代理环境变量（国内平台直连）。"""

    def test_proxy_env_keys_scrubbed(self):
        from uploader.bilibili_uploader.runtime import _PROXY_ENV_KEYS, _biliup_env

        with patch.dict(os.environ, {k: "http://p:1" for k in _PROXY_ENV_KEYS}):
            env = _biliup_env()
        for key in _PROXY_ENV_KEYS:
            self.assertNotIn(key, env)

    def test_run_biliup_command_passes_scrubbed_env(self):
        from uploader.bilibili_uploader import runtime

        with patch.object(runtime, "ensure_biliup_binary", return_value=Path("/fake/biliup")), \
                patch.object(runtime.subprocess, "run") as mock_run, \
                patch.dict(os.environ, {"http_proxy": "http://p:1", "https_proxy": "http://p:1"}):
            runtime.run_biliup_command(["login"])
        env = mock_run.call_args.kwargs["env"]
        self.assertNotIn("http_proxy", env)
        self.assertNotIn("https_proxy", env)
        mock_run.assert_called_once()


class NewBrowserContextTests(unittest.TestCase):
    """所有平台统一伪装 Windows Chrome UA（版本号取自真实浏览器）。"""

    def _fake_inner_context(self):
        context = MagicMock()
        page = MagicMock()
        context.new_page = AsyncMock(return_value=page)
        cdp = MagicMock()
        cdp.send = AsyncMock()
        context.new_cdp_session = AsyncMock(return_value=cdp)
        return context, page, cdp

    def _fake_browser(self, version="140.0.7339.14"):
        browser = MagicMock()
        browser.version = version
        inner, page, cdp = self._fake_inner_context()
        browser.new_context = AsyncMock(return_value=inner)
        return browser, inner, page, cdp

    def test_windows_ua_and_cdp_platform_override(self):
        from utils.base_social_media import new_browser_context

        browser, inner, page, cdp = self._fake_browser()
        context = asyncio.run(new_browser_context(browser, storage_state="cookies.json"))
        # UA 传给了 new_context（决定 HTTP 层与 navigator.userAgent）
        kwargs = browser.new_context.await_args.kwargs
        self.assertIn("Windows NT 10.0; Win64; x64", kwargs["user_agent"])
        self.assertIn("Chrome/140.0.7339.14", kwargs["user_agent"])
        self.assertEqual(kwargs["storage_state"], "cookies.json")
        # 每个新页面还叠加 CDP 原生 platform 覆盖
        result_page = asyncio.run(context.new_page())
        self.assertIs(result_page, page)
        cdp.send.assert_awaited_once()
        cmd, params = cdp.send.await_args.args
        self.assertEqual(cmd, "Emulation.setUserAgentOverride")
        self.assertEqual(params["platform"], "Win32")

    def test_explicit_user_agent_not_overridden(self):
        from utils.base_social_media import new_browser_context

        browser, inner, _, cdp = self._fake_browser()
        context = asyncio.run(new_browser_context(browser, user_agent="custom-ua"))
        self.assertEqual(browser.new_context.await_args.kwargs["user_agent"], "custom-ua")
        asyncio.run(context.new_page())
        self.assertEqual(cdp.send.await_args.kwargs if cdp.send.await_args.kwargs
                         else cdp.send.await_args.args[1]["userAgent"], "custom-ua")

    def test_unreadable_version_skips_ua_and_wrapper(self):
        # MagicMock 假浏览器树（现有测试模式）拿不到字符串版本号时静默跳过，
        # 返回原始 context 不包装，保证旧测试的 fake 树行为不变。
        from utils.base_social_media import new_browser_context

        browser = MagicMock()
        inner = MagicMock()
        browser.new_context = AsyncMock(return_value=inner)
        context = asyncio.run(new_browser_context(browser))
        self.assertIs(context, inner)
        self.assertNotIn("user_agent", browser.new_context.await_args.kwargs)

    def test_cdp_failure_falls_back_gracefully(self):
        from utils.base_social_media import new_browser_context

        browser, inner, page, cdp = self._fake_browser()
        cdp.send = AsyncMock(side_effect=RuntimeError("cdp unavailable"))
        context = asyncio.run(new_browser_context(browser))
        result_page = asyncio.run(context.new_page())
        self.assertIs(result_page, page)  # 覆盖失败不影响页面返回


if __name__ == "__main__":
    unittest.main()
