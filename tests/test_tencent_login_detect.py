# -*- coding: utf-8 -*-
"""视频号扫码登录完成判定的纯逻辑测试（不启动浏览器）。"""
import asyncio
import unittest

from uploader.tencent_uploader.main import _is_tencent_login_completed


class _FakeLocator:
    async def count(self):
        return 0

    async def is_visible(self):
        return False

    @property
    def first(self):
        return self


class _FakePage:
    def __init__(self, url):
        self.url = url

    def locator(self, _selector):
        return _FakeLocator()


class TencentLoginCompletedTests(unittest.TestCase):
    def _completed(self, url):
        return asyncio.run(_is_tencent_login_completed(_FakePage(url)))

    def test_any_platform_page_counts_as_logged_in(self):
        # 旧白名单只认 post/create 和 post/list；微信改版后跳其他 platform 页会漏判
        for url in (
            "https://channels.weixin.qq.com/platform/post/create",
            "https://channels.weixin.qq.com/platform/post/list",
            "https://channels.weixin.qq.com/platform/home",
            "https://channels.weixin.qq.com/platform/main/index",
        ):
            self.assertTrue(self._completed(url), url)

    def test_login_and_root_pages_are_not_logged_in(self):
        for url in (
            "https://channels.weixin.qq.com/platform/login.html",
            "https://channels.weixin.qq.com/",
            "https://channels.weixin.qq.com",
            "https://open.weixin.qq.com/connect/qrconnect?appid=x",
        ):
            self.assertFalse(self._completed(url), url)


if __name__ == "__main__":
    unittest.main()
