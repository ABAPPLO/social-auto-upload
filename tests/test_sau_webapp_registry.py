# -*- coding: utf-8 -*-
"""sau_webapp.registry 发布参数映射的纯逻辑测试（不启动浏览器）。"""
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path

from sau_cli import (
    BilibiliVideoUploadRequest,
    DouyinNoteUploadRequest,
    DouyinVideoUploadRequest,
    YouTubeVideoUploadRequest,
)
from sau_webapp.registry import (
    PublishPayloadError,
    build_batch_requests,
    build_upload_request,
    get_platform,
)


class RegistryMappingTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.material_dir = Path(self._tmp.name)
        self.video = self.material_dir / "demo.mp4"
        self.video.write_bytes(b"x")
        self.image = self.material_dir / "cover.jpg"
        self.image.write_bytes(b"x")

    def tearDown(self):
        self._tmp.cleanup()

    def _payload(self, **overrides):
        base = {
            "platform": "douyin",
            "content_type": "video",
            "account_name": "main",
            "file": "demo.mp4",
            "title": "标题",
            "desc": "简介",
            "tags": "vlog, 日常",
            "publish_date": "",
            "thumbnail": "",
        }
        base.update(overrides)
        return base

    def test_douyin_video_mapping(self):
        fn, request = build_upload_request(
            "douyin", "video", self._payload(thumbnail="cover.jpg"), self.material_dir
        )
        self.assertEqual(fn.__name__, "upload_video")
        self.assertIsInstance(request, DouyinVideoUploadRequest)
        self.assertEqual(request.account_name, "main")
        self.assertEqual(request.tags, ["vlog", "日常"])
        self.assertEqual(request.publish_date, 0)
        self.assertEqual(request.thumbnail_portrait_file, self.image)
        self.assertIsNone(request.collection_name)

    def test_douyin_advanced_fields_mapping(self):
        payload = self._payload(
            thumbnail="cover.jpg",
            thumbnail_landscape="cover.jpg",
            thumbnail_portrait="cover.jpg",
            extras={
                "declaration": "内容由AI生成",
                "product_link": "https://example.com/item",
                "product_title": "测试商品",
            },
        )
        _, request = build_upload_request("douyin", "video", payload, self.material_dir)
        self.assertEqual(request.declaration, "内容由AI生成")
        self.assertEqual(request.product_link, "https://example.com/item")
        self.assertEqual(request.product_title, "测试商品")
        self.assertEqual(request.thumbnail_landscape_file, self.image)
        # 竖版显式指定时优先于通用封面
        self.assertEqual(request.thumbnail_portrait_file, self.image)

    def test_douyin_declaration_defaults_to_none(self):
        _, request = build_upload_request("douyin", "video", self._payload(), self.material_dir)
        self.assertIsNone(request.declaration)
        self.assertEqual(request.product_link, "")

    def test_tencent_dual_thumbnail_mapping(self):
        payload = self._payload(
            platform="tencent",
            thumbnail="cover.jpg",
            thumbnail_landscape="cover.jpg",
            thumbnail_portrait="cover.jpg",
        )
        _, request = build_upload_request("tencent", "video", payload, self.material_dir)
        self.assertEqual(request.thumbnail_file, self.image)
        self.assertEqual(request.thumbnail_landscape_file, self.image)
        self.assertEqual(request.thumbnail_portrait_file, self.image)

    def test_note_requires_images(self):
        with self.assertRaises(PublishPayloadError):
            build_upload_request("douyin", "note", self._payload(content_type="note"), self.material_dir)

    def test_note_body_falls_back_to_desc(self):
        payload = self._payload(
            content_type="note",
            images=["cover.jpg"],
            note="",
            desc="简介兜底",
        )
        fn, request = build_upload_request("douyin", "note", payload, self.material_dir)
        self.assertIsInstance(request, DouyinNoteUploadRequest)
        self.assertEqual(request.note, "简介兜底")

    def test_kuaishou_note_mapping(self):
        payload = self._payload(
            platform="kuaishou",
            content_type="note",
            images=["cover.jpg"],
            note="正文",
        )
        fn, request = build_upload_request("kuaishou", "note", payload, self.material_dir)
        from sau_cli import KuaishouNoteUploadRequest

        self.assertIsInstance(request, KuaishouNoteUploadRequest)

    def test_bilibili_tid_required(self):
        payload = self._payload(platform="bilibili")
        with self.assertRaises(PublishPayloadError):
            build_upload_request("bilibili", "video", payload, self.material_dir)

    def test_bilibili_tid_mapping(self):
        payload = self._payload(platform="bilibili", extras={"tid": 21})
        fn, request = build_upload_request("bilibili", "video", payload, self.material_dir)
        self.assertIsInstance(request, BilibiliVideoUploadRequest)
        self.assertEqual(request.tid, 21)

    def test_youtube_visibility_validation(self):
        payload = self._payload(platform="youtube", extras={"visibility": "wrong"})
        with self.assertRaises(PublishPayloadError):
            build_upload_request("youtube", "video", payload, self.material_dir)

    def test_youtube_mapping(self):
        payload = self._payload(
            platform="youtube",
            extras={"visibility": "unlisted", "playlist": "系列"},
        )
        fn, request = build_upload_request("youtube", "video", payload, self.material_dir)
        self.assertIsInstance(request, YouTubeVideoUploadRequest)
        self.assertEqual(request.visibility, "unlisted")
        self.assertEqual(request.playlist, "系列")

    def test_schedule_validation(self):
        past = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d %H:%M")
        with self.assertRaises(PublishPayloadError):
            build_upload_request("douyin", "video", self._payload(publish_date=past), self.material_dir)

        soon = (datetime.now() + timedelta(minutes=30)).strftime("%Y-%m-%d %H:%M")
        with self.assertRaises(PublishPayloadError):
            build_upload_request("douyin", "video", self._payload(publish_date=soon), self.material_dir)

    def test_schedule_too_soon_format(self):
        with self.assertRaises(PublishPayloadError):
            build_upload_request(
                "douyin", "video", self._payload(publish_date="明天上午"), self.material_dir
            )

    def test_schedule_unsupported_platform_rejected(self):
        future = (datetime.now() + timedelta(hours=3)).strftime("%Y-%m-%d %H:%M")
        payload = self._payload(platform="weibo", publish_date=future)
        with self.assertRaises(PublishPayloadError) as ctx:
            build_upload_request("weibo", "video", payload, self.material_dir)
        self.assertIn("不支持定时发布", str(ctx.exception))

    def test_schedule_supported_platform_accepted(self):
        future = (datetime.now() + timedelta(hours=3)).strftime("%Y-%m-%d %H:%M")
        _, request = build_upload_request(
            "douyin", "video", self._payload(publish_date=future), self.material_dir
        )
        self.assertIsInstance(request.publish_date, datetime)

    def test_material_path_traversal_rejected(self):
        with self.assertRaises(PublishPayloadError):
            build_upload_request(
                "douyin", "video", self._payload(file="../../etc/passwd"), self.material_dir
            )

    def test_missing_video_file(self):
        with self.assertRaises(PublishPayloadError):
            build_upload_request("douyin", "video", self._payload(file="nope.mp4"), self.material_dir)

    def test_unknown_platform(self):
        with self.assertRaises(PublishPayloadError):
            get_platform("nonexistent")

    def test_tags_list_input(self):
        _, request = build_upload_request(
            "douyin", "video", self._payload(tags=["#a", " b"]), self.material_dir
        )
        self.assertEqual(request.tags, ["a", "b"])


class BatchPublishTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.material_dir = Path(self._tmp.name)
        (self.material_dir / "demo.mp4").write_bytes(b"x")
        (self.material_dir / "cover.jpg").write_bytes(b"x")

    def tearDown(self):
        self._tmp.cleanup()

    def _payload(self, **overrides):
        base = {
            "content_type": "video",
            "file": "demo.mp4",
            "title": "批量标题",
            "desc": "简介",
            "tags": ["批量"],
            "publish_date": "",
            "thumbnail": "",
        }
        base.update(overrides)
        return base

    def test_batch_builds_one_request_per_target(self):
        payload = self._payload(
            targets=[
                {"platform": "douyin", "account_name": "main"},
                {"platform": "bilibili", "account_name": "main", "extras": {"tid": 21}},
                {"platform": "xiaohongshu", "account_name": "second"},
            ]
        )
        results = build_batch_requests(payload, self.material_dir)
        self.assertEqual(len(results), 3)
        by_platform = {platform: request for platform, _, _, request in results}
        self.assertIsInstance(by_platform["douyin"], DouyinVideoUploadRequest)
        self.assertEqual(by_platform["douyin"].account_name, "main")
        self.assertEqual(by_platform["bilibili"].tid, 21)

    def test_batch_extras_merge_target_overrides_common(self):
        payload = self._payload(
            extras={"collection_name": "公共合集"},
            targets=[
                {"platform": "douyin", "account_name": "a"},
                {"platform": "kuaishou", "account_name": "b", "extras": {"collection_name": "快手合集"}},
            ],
        )
        results = dict((platform, request) for platform, _, _, request in build_batch_requests(payload, self.material_dir))
        self.assertEqual(results["douyin"].collection_name, "公共合集")
        self.assertEqual(results["kuaishou"].collection_name, "快手合集")

    def test_batch_rejects_all_when_any_target_invalid(self):
        payload = self._payload(
            targets=[
                {"platform": "douyin", "account_name": "ok"},
                {"platform": "bilibili", "account_name": "no-tid"},  # 缺 tid
                {"platform": "weibo", "account_name": "x", "publish_date": "2099-01-01 10:00"},  # 不支持定时
            ]
        )
        with self.assertRaises(PublishPayloadError) as ctx:
            build_batch_requests(payload, self.material_dir)
        message = str(ctx.exception)
        self.assertIn("bilibili", message.lower())
        self.assertIn("tid", message)
        self.assertIn("微博", message)

    def test_batch_requires_targets(self):
        with self.assertRaises(PublishPayloadError):
            build_batch_requests(self._payload(targets=[]), self.material_dir)


if __name__ == "__main__":
    unittest.main()
