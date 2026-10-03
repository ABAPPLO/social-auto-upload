# -*- coding: utf-8 -*-
"""远程人工协助（登录滑块/验证的手动通道）纯逻辑测试，不启动浏览器。"""
import asyncio
import unittest
from unittest.mock import AsyncMock

from sau_webapp import assist as assist_mod
from sau_webapp.tasks import manager
from utils import web_assist


class FakeMouse:
    def __init__(self):
        self.moves = []
        self.clicks = []
        self.downs = 0
        self.ups = 0

    async def move(self, x, y, steps=1):
        self.moves.append((x, y))

    async def click(self, x, y):
        self.clicks.append((x, y))

    async def down(self):
        self.downs += 1

    async def up(self):
        self.ups += 1


def make_fake_page(viewport=None, verify_selectors=(), verify_texts=()):
    """构造最小可用的 page 替身：locator/get_by_text 返回可控的假定位器。"""
    page = AsyncMock()
    page.viewport_size = viewport
    page.mouse = FakeMouse()

    class FakeLocator:
        def __init__(self, visible):
            self._visible = visible

        async def count(self):
            return 1 if self._visible else 0

        async def is_visible(self):
            return self._visible

        def nth(self, index):
            return self

        @property
        def first(self):
            return self

    visible_locator = FakeLocator(True)
    hidden_locator = FakeLocator(False)

    def locator(selector):
        return visible_locator if selector in verify_selectors else hidden_locator

    def get_by_text(text, exact=False):
        return visible_locator if text in verify_texts else hidden_locator

    page.locator = locator
    page.get_by_text = get_by_text
    return page


class ClampAndCoordTests(unittest.TestCase):
    def test_clamp_within_range(self):
        self.assertEqual(web_assist.clamp_coord(50, 1280), 50)

    def test_clamp_out_of_range(self):
        self.assertEqual(web_assist.clamp_coord(-5, 1280), 0)
        self.assertEqual(web_assist.clamp_coord(9999, 1280), 1280)

    def test_clamp_unknown_viewport_passes_through(self):
        self.assertEqual(web_assist.clamp_coord(9999, 0), 9999)

    def test_viewport_size_from_property(self):
        page = make_fake_page(viewport={"width": 1440, "height": 900})
        self.assertEqual(asyncio.run(web_assist.viewport_size(page)), (1440, 900))

    def test_viewport_size_falls_back_to_evaluate(self):
        page = make_fake_page(viewport=None)
        page.evaluate = AsyncMock(return_value=[1024, 768])
        self.assertEqual(asyncio.run(web_assist.viewport_size(page)), (1024, 768))


class DetectVerificationTests(unittest.TestCase):
    def test_detects_captcha_selector(self):
        page = make_fake_page(verify_selectors=('[class*="captcha" i]',))
        needed, hit = asyncio.run(web_assist.detect_verification(page))
        self.assertTrue(needed)
        self.assertIn("captcha", hit)

    def test_detects_verify_text(self):
        page = make_fake_page(verify_texts=("拖动滑块",))
        needed, hit = asyncio.run(web_assist.detect_verification(page))
        self.assertTrue(needed)
        self.assertEqual(hit, "拖动滑块")

    def test_no_verification_on_clean_page(self):
        page = make_fake_page()
        needed, hit = asyncio.run(web_assist.detect_verification(page))
        self.assertFalse(needed)
        self.assertEqual(hit, "")

    def test_locator_error_is_swallowed(self):
        page = make_fake_page()

        def boom(_):
            raise RuntimeError("page navigated")

        page.locator = boom
        needed, _ = asyncio.run(web_assist.detect_verification(page))
        self.assertFalse(needed)


class HumanInputTests(unittest.TestCase):
    def test_human_click_uses_real_mouse_and_dispatches_events(self):
        page = make_fake_page()
        ok = asyncio.run(web_assist.human_click(page, 120, 80))
        self.assertTrue(ok)
        self.assertEqual(page.mouse.clicks, [(120, 80)])
        page.evaluate.assert_awaited_once()

    def test_human_click_failure_returns_false(self):
        page = make_fake_page()
        page.mouse.click = AsyncMock(side_effect=RuntimeError("closed"))
        self.assertFalse(asyncio.run(web_assist.human_click(page, 1, 1)))
        page.evaluate.assert_not_awaited()

    def test_human_drag_presses_releases_and_ends_at_target(self):
        page = make_fake_page()
        ok = asyncio.run(web_assist.human_drag(page, 10, 20, 300, 20))
        self.assertTrue(ok)
        self.assertEqual(page.mouse.downs, 1)
        self.assertEqual(page.mouse.ups, 1)
        self.assertEqual(page.mouse.moves[-1], (300, 20))

    def test_human_drag_failure_returns_false(self):
        page = make_fake_page()
        page.mouse.move = AsyncMock(side_effect=RuntimeError("closed"))
        self.assertFalse(asyncio.run(web_assist.human_drag(page, 1, 1, 2, 2)))

    def test_human_type_clicks_then_types(self):
        page = make_fake_page()
        page.keyboard = AsyncMock()
        ok = asyncio.run(web_assist.human_type(page, 30, 40, "123456"))
        self.assertTrue(ok)
        self.assertEqual(page.mouse.clicks, [(30, 40)])
        page.keyboard.type.assert_awaited_once_with("123456", delay=45)

    def test_human_type_empty_text_returns_false(self):
        page = make_fake_page()
        self.assertFalse(asyncio.run(web_assist.human_type(page, 1, 1, "")))


class TaskAssistBindingTests(unittest.TestCase):
    def test_task_assist_updates_task_state(self):
        task = manager.create("login", "douyin", "main")
        manager._tasks[task["id"]]["status"] = "running"
        binding = assist_mod.TaskAssist(task["id"])

        asyncio.run(binding.on_frame("data:image/jpeg;base64,QUJD", "https://creator.douyin.com/"))
        snapshot = manager.get(task["id"])
        self.assertEqual(snapshot["assist_frame_url"], "data:image/jpeg;base64,QUJD")
        self.assertEqual(snapshot["assist_page_url"], "https://creator.douyin.com/")

        asyncio.run(binding.on_verify_state(True, "拖动滑块"))
        snapshot = manager.get(task["id"])
        self.assertTrue(snapshot["assist_needs_verify"])
        self.assertEqual(snapshot["assist_verify_hint"], "拖动滑块")
        self.assertIn("人工验证", snapshot["message"])

        asyncio.run(binding.on_verify_state(False, ""))
        self.assertFalse(manager.get(task["id"])["assist_needs_verify"])

    def test_frame_not_overwritten_after_task_finished(self):
        task = manager.create("login", "douyin", "main")
        manager._tasks[task["id"]]["status"] = "running"
        manager.set_assist_frame(task["id"], "data:image/jpeg;base64,RklOQUw=", "url-1")
        manager._tasks[task["id"]]["status"] = "failed"
        manager.set_assist_frame(task["id"], "data:image/jpeg;base64,TkVX", "url-2")
        snapshot = manager.get(task["id"])
        self.assertEqual(snapshot["assist_frame_url"], "data:image/jpeg;base64,RklOQUw=")

    def test_attach_page_registers_and_detach_removes(self):
        task = manager.create("login", "douyin", "main")
        binding = assist_mod.TaskAssist(task["id"])
        page = make_fake_page()
        binding.attach_page(page)
        self.assertIs(assist_mod.LIVE.get(task["id"]), binding)
        self.assertIs(binding.page, page)
        binding.detach_page()
        self.assertIsNone(assist_mod.LIVE.get(task["id"]))
        self.assertIsNone(binding.page)

    def test_list_snapshot_does_not_carry_frame(self):
        task = manager.create("login", "douyin", "main")
        manager._tasks[task["id"]]["status"] = "running"
        manager.set_assist_frame(task["id"], "data:image/jpeg;base64,QUJD")
        listed = [t for t in manager.list("login") if t["id"] == task["id"]]
        self.assertEqual(len(listed), 1)
        self.assertNotIn("assist_frame_url", listed[0])
        self.assertIn("assist_frame_url", manager.get(task["id"]))


if __name__ == "__main__":
    unittest.main()
