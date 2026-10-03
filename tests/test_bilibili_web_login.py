# -*- coding: utf-8 -*-
"""Bilibili Web 扫码登录（PTY 驱动 biliup）纯逻辑测试。"""
import tempfile
import unittest
from pathlib import Path

from uploader.bilibili_uploader.web_login import _login_result, _stable_png_data_url


class LoginResultTests(unittest.TestCase):
    def test_result_shape_matches_webapp_contract(self):
        result = _login_result(True, "success", "ok", "/tmp/acc.json", "data:image/png;base64,QUJD")
        self.assertTrue(result["success"])
        self.assertEqual(result["qrcode"]["image_data_url"], "data:image/png;base64,QUJD")
        self.assertEqual(result["account_file"], "/tmp/acc.json")


class StablePngTests(unittest.TestCase):
    def test_pushes_once_when_file_stable(self):
        import base64

        with tempfile.TemporaryDirectory() as tmp:
            workdir = Path(tmp)
            png = workdir / "qrcode.png"
            raw = b"\x89PNG fake-qrcode-bytes"
            png.write_bytes(raw)
            url, mtime = _stable_png_data_url(workdir, None)
            self.assertEqual(url, "data:image/png;base64," + base64.b64encode(raw).decode("ascii"))
            # mtime 相同的第二轮不再推送
            url2, _ = _stable_png_data_url(workdir, mtime)
            self.assertEqual(url2, "")

    def test_missing_file_returns_empty(self):
        with tempfile.TemporaryDirectory() as tmp:
            url, mtime = _stable_png_data_url(Path(tmp), None)
            self.assertEqual(url, "")
            self.assertIsNone(mtime)


if __name__ == "__main__":
    unittest.main()
