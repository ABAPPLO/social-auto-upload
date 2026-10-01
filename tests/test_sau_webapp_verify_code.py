# -*- coding: utf-8 -*-
"""短信验证码 Web 通道的纯逻辑测试（不启动浏览器）。"""
import asyncio
import tempfile
import unittest
from pathlib import Path

from sau_webapp import verify_code
from sau_webapp.tasks import manager


class VerifyCodePollerTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.code_file = Path(self._tmp.name) / "verify_code.txt"

    def tearDown(self):
        self._tmp.cleanup()

    def test_returns_code_when_file_exists(self):
        self.code_file.write_text("  123456 \n", encoding="utf-8")
        code = asyncio.run(verify_code.web_read_verify_code(str(self.code_file), poll_seconds=1))
        self.assertEqual(code, "123456")

    def test_polls_until_file_appears(self):
        async def scenario():
            async def writer():
                await asyncio.sleep(2.5)
                self.code_file.write_text("998877", encoding="utf-8")

            writer_task = asyncio.create_task(writer())
            code = await verify_code.web_read_verify_code(str(self.code_file), poll_seconds=8)
            await writer_task
            return code

        self.assertEqual(asyncio.run(scenario()), "998877")

    def test_times_out_with_empty_string(self):
        code = asyncio.run(verify_code.web_read_verify_code(str(self.code_file), poll_seconds=1))
        self.assertEqual(code, "")

    def test_marks_task_waiting(self):
        task = manager.create("upload", "douyin", "main")
        manager._tasks[task["id"]]["status"] = "running"

        async def scenario():
            from sau_webapp.tasks import current_task_id

            ctx = current_task_id.set(task["id"])
            try:
                self.code_file.write_text("4321", encoding="utf-8")
                code = await verify_code.web_read_verify_code(str(self.code_file), poll_seconds=1)
            finally:
                current_task_id.reset(ctx)
            return code

        self.assertEqual(asyncio.run(scenario()), "4321")
        snapshot = manager.get(task["id"])
        self.assertIn("验证码", snapshot["message"])
        self.assertTrue(snapshot["waiting_verify_code"])

        # 任务结束后快照不应再显示等待中
        manager._tasks[task["id"]]["status"] = "success"
        self.assertFalse(manager.get(task["id"])["waiting_verify_code"])


if __name__ == "__main__":
    unittest.main()
