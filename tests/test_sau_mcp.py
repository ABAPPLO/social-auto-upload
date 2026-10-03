# -*- coding: utf-8 -*-
"""MCP 适配层纯逻辑测试（mock 掉 sau-web HTTP，不启动 MCP 会话）。"""
import unittest
from unittest.mock import patch

from sau_mcp import server
from sau_mcp.client import SauWebError


def _task(status="running", qrcode="", **extra):
    return {"id": "t1", "status": status, "qrcode_data_url": qrcode, "message": "m", **extra}


class CompactTaskTests(unittest.TestCase):
    def test_compact_strips_qrcode_and_flags(self):
        compact = server._compact_task(_task(qrcode="data:image/png;base64,QUJD"))
        self.assertNotIn("qrcode_data_url", compact)
        self.assertTrue(compact["has_qrcode"])

    def test_qr_image_decodes_data_url(self):
        image = server._qr_image(_task(qrcode="data:image/png;base64,QUJD"))
        self.assertIsNotNone(image)

    def test_qr_image_none_without_qrcode(self):
        self.assertIsNone(server._qr_image(_task()))


class PublishConfirmGateTests(unittest.TestCase):
    def test_publish_without_confirm_is_rejected(self):
        with patch.object(server, "_client") as fake:
            with self.assertRaises(SauWebError) as ctx:
                server.publish_video(
                    confirm=False, platform="douyin", account="main",
                    file="demo.mp4", title="标题",
                )
            self.assertIn("confirm", str(ctx.exception))
            fake.post.assert_not_called()

    def test_note_without_confirm_is_rejected(self):
        with patch.object(server, "_client") as fake:
            with self.assertRaises(SauWebError):
                server.publish_note(confirm=False, platform="xiaohongshu",
                                    account="main", images=["a.jpg"], title="标题")
            fake.post.assert_not_called()

    def test_publish_video_payload_shape(self):
        with patch.object(server, "_client") as fake:
            fake.post.return_value = {"task": _task(status="pending")}
            out = server.publish_video(
                confirm=True, platform="douyin", account="main",
                file="demo.mp4", title="标题", desc="简介", tags="a,b",
                publish_date="2026-10-05 10:00",
            )
            payload = fake.post.call_args.kwargs["json"]
            self.assertEqual(payload["content_type"], "video")
            self.assertEqual(payload["account_name"], "main")
            self.assertEqual(payload["tags"], "a,b")
            self.assertEqual(payload["publish_date"], "2026-10-05 10:00")
            self.assertIn("task", out)


class WaitTaskTests(unittest.TestCase):
    def test_wait_polls_until_terminal(self):
        with patch.object(server, "_client") as fake:
            fake.get.side_effect = [
                {"task": _task(status="running")},
                {"task": _task(status="running")},
                {"task": _task(status="success", message="完成")},
            ]
            with patch.object(server.time, "sleep"):
                out = server.wait_task(task_id="t1", timeout_seconds=30)
            self.assertEqual(fake.get.call_count, 3)
            self.assertIn('"status": "success"', out)

    def test_check_account_returns_verdict(self):
        with patch.object(server, "_client") as fake:
            fake.post.return_value = {"task": {"id": "t9"}}
            fake.get.return_value = {"task": _task(status="success")}
            with patch.object(server.time, "sleep"):
                out = server.check_account(platform="douyin", account="main")
            self.assertIn('"valid": true', out)


if __name__ == "__main__":
    unittest.main()
