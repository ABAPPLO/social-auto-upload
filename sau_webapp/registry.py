# -*- coding: utf-8 -*-
"""平台注册表：Web 后端与主线 uploader/CLI 之间的桥接层。

所有上传能力直接复用 sau_cli 里已有的协程函数和数据类，
保证 Web 与 CLI 行为一致；登录复用各平台 setup() 的 qrcode_callback 机制。
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from uploader.base_video import BaseVideoUploader
from uploader.facebook_uploader.main import facebook_setup
from uploader.instagram_uploader.main import instagram_setup
from uploader.baijiahao_uploader.main import baijiahao_setup
from uploader.alipay_uploader.main import alipay_setup
from uploader.douyin_uploader.main import douyin_setup
from uploader.ks_uploader.main import ks_setup
from uploader.tencent_uploader.main import tencent_setup
from uploader.weibo_uploader.main import weibo_setup
from uploader.hupu_uploader.main import hupu_setup
from uploader.tk_uploader.main_chrome import tiktok_setup
from uploader.x_uploader.main import x_setup
from uploader.xiaohongshu_uploader.main import xiaohongshu_setup
from uploader.youtube_uploader.main import youtube_setup
from utils.constant import TencentZoneTypes, VideoZoneTypes

import sau_cli

LOGIN_MODE_QRCODE = "qrcode"
LOGIN_MODE_TERMINAL = "terminal"


class PublishPayloadError(ValueError):
    """发布参数不合法（前端展示用中文消息）。"""


@dataclass(frozen=True)
class PlatformSpec:
    key: str
    name: str
    login_mode: str
    terminal_login_hint: str = ""
    supports_note: bool = False
    # 平台侧定时发布（uploader 在发布页设置平台自己的定时，到点由平台发出）
    supports_schedule: bool = False
    # 扫码登录（bilibili 走 biliup 交互、youtube 走 Google 交互，均只给终端指引）
    setup: Callable | None = None
    # 账号有效性检查：统一复用 sau_cli.check_*_account(account_name) -> bool
    check: Callable | None = None
    # 上传函数与请求类型（全部来自 sau_cli，与 CLI 同源）
    upload_video: Callable | None = None
    upload_note: Callable | None = None
    video_request: type | None = None
    note_request: type | None = None
    # 各平台 Web 表单附加字段
    extra_fields: tuple[str, ...] = ()


PLATFORM_SPECS: dict[str, PlatformSpec] = {
    "douyin": PlatformSpec(
        key="douyin",
        name="抖音",
        login_mode=LOGIN_MODE_QRCODE,
        supports_note=True,
        supports_schedule=True,
        setup=douyin_setup,
        check=sau_cli.check_douyin_account,
        upload_video=sau_cli.upload_video,
        upload_note=sau_cli.upload_note,
        extra_fields=("collection_name", "bgm", "declaration", "product_link", "product_title"),
    ),
    "kuaishou": PlatformSpec(
        key="kuaishou",
        name="快手",
        login_mode=LOGIN_MODE_QRCODE,
        supports_note=True,
        supports_schedule=True,
        setup=ks_setup,
        check=sau_cli.check_kuaishou_account,
        upload_video=sau_cli.upload_kuaishou_video,
        upload_note=sau_cli.upload_kuaishou_note,
        extra_fields=("collection_name",),
    ),
    "xiaohongshu": PlatformSpec(
        key="xiaohongshu",
        name="小红书",
        login_mode=LOGIN_MODE_QRCODE,
        supports_note=True,
        supports_schedule=True,
        setup=xiaohongshu_setup,
        check=sau_cli.check_xiaohongshu_account,
        upload_video=sau_cli.upload_xiaohongshu_video,
        upload_note=sau_cli.upload_xiaohongshu_note,
    ),
    "bilibili": PlatformSpec(
        key="bilibili",
        name="Bilibili",
        login_mode=LOGIN_MODE_TERMINAL,
        supports_schedule=True,
        terminal_login_hint=(
            "Bilibili 登录依赖 biliup 命令行交互：在任意装有本项目的电脑终端执行 "
            "sau bilibili login --account <账号名>（二维码显示不全时打开项目目录 qrcode.png），"
            "然后把生成的 cookies/bilibili_<账号名>.json 通过本页「上传cookie」推送到服务器。"
        ),
        check=sau_cli.check_bilibili_account,
        upload_video=sau_cli.upload_bilibili_video,
        extra_fields=("tid",),
    ),
    "tencent": PlatformSpec(
        key="tencent",
        name="视频号",
        login_mode=LOGIN_MODE_QRCODE,
        supports_schedule=True,
        setup=tencent_setup,
        check=sau_cli.check_tencent_account,
        upload_video=sau_cli.upload_tencent_video,
        extra_fields=("short_title", "category", "is_draft", "collection_name"),
    ),
    "baijiahao": PlatformSpec(
        key="baijiahao",
        name="百家号",
        login_mode=LOGIN_MODE_QRCODE,
        setup=baijiahao_setup,
        check=sau_cli.check_baijiahao_account,
        upload_video=sau_cli.upload_baijiahao_video,
        extra_fields=("collection_name",),
    ),
    "alipay": PlatformSpec(
        key="alipay",
        name="支付宝生活号",
        login_mode=LOGIN_MODE_QRCODE,
        setup=alipay_setup,
        check=sau_cli.check_alipay_account,
        upload_video=sau_cli.upload_alipay_video,
        extra_fields=("collection_name",),
    ),
    "weibo": PlatformSpec(
        key="weibo",
        name="微博",
        login_mode=LOGIN_MODE_QRCODE,
        setup=weibo_setup,
        check=sau_cli.check_weibo_account,
        upload_video=sau_cli.upload_weibo_video,
        extra_fields=("collection_name",),
    ),
    "hupu": PlatformSpec(
        key="hupu",
        name="虎扑",
        login_mode=LOGIN_MODE_QRCODE,
        setup=hupu_setup,
        check=sau_cli.check_hupu_account,
        upload_video=sau_cli.upload_hupu_video,
    ),
    "youtube": PlatformSpec(
        key="youtube",
        name="YouTube",
        login_mode=LOGIN_MODE_TERMINAL,
        terminal_login_hint=(
            "YouTube 登录是 Google 账号交互式流程（无二维码）：在任意装有本项目的电脑终端执行 "
            "sau youtube login --account <账号名>，然后把生成的 cookies/youtube_<账号名>.json "
            "通过本页「上传cookie」推送到服务器。"
        ),
        setup=youtube_setup,
        check=sau_cli.check_youtube_account,
        upload_video=sau_cli.upload_youtube_video,
        extra_fields=("visibility", "playlist"),
    ),
    "tiktok": PlatformSpec(
        key="tiktok",
        name="TikTok",
        login_mode=LOGIN_MODE_TERMINAL,
        terminal_login_hint=(
            "TikTok 登录是交互式流程（无二维码回调）：在装有本项目的本地电脑终端执行 "
            "sau tiktok login --account <账号名>（弹出浏览器手动登录），然后把 cookies/tiktok_<账号名>.json "
            "通过「上传cookie」推送到服务器。被墙网络需在服务器 conf.py 配置 TK_PROXY。"
        ),
        supports_schedule=True,
        setup=tiktok_setup,
        check=sau_cli.check_tiktok_account,
        upload_video=sau_cli.upload_tiktok_video,
    ),
    "instagram": PlatformSpec(
        key="instagram",
        name="Instagram",
        login_mode=LOGIN_MODE_TERMINAL,
        terminal_login_hint=(
            "Instagram 登录是 Meta 账号交互式流程（无二维码）：在本地电脑终端执行 "
            "sau instagram login --account <账号名>（弹出浏览器手动登录，含 2FA），"
            "然后把 cookies/instagram_<账号名>.json 通过「上传cookie」推送到服务器。"
            "被墙网络需在服务器 conf.py 配置代理（DEFAULT_PROXY 或 PROXY_MAP）。"
        ),
        setup=instagram_setup,
        check=sau_cli.check_instagram_account,
        upload_video=sau_cli.upload_instagram_video,
    ),
    "facebook": PlatformSpec(
        key="facebook",
        name="Facebook",
        login_mode=LOGIN_MODE_TERMINAL,
        terminal_login_hint=(
            "Facebook 登录是 Meta 账号交互式流程（无二维码）：在本地电脑终端执行 "
            "sau facebook login --account <账号名>，然后把 cookies/facebook_<账号名>.json "
            "通过「上传cookie」推送到服务器。被墙网络需配置代理（DEFAULT_PROXY）。"
        ),
        setup=facebook_setup,
        check=sau_cli.check_facebook_account,
        upload_video=sau_cli.upload_facebook_video,
    ),
    "x": PlatformSpec(
        key="x",
        name="X（Twitter）",
        login_mode=LOGIN_MODE_TERMINAL,
        terminal_login_hint=(
            "X 登录是交互式流程（无二维码）：在本地电脑终端执行 "
            "sau x login --account <账号名>（用户名/密码 + 2FA），然后把 cookies/x_<账号名>.json "
            "通过「上传cookie」推送到服务器。非 Premium 账号视频上限约 2 分 20 秒；需配置代理。"
        ),
        setup=x_setup,
        check=sau_cli.check_x_account,
        upload_video=sau_cli.upload_x_video,
    ),
}


def get_platform(key: str) -> PlatformSpec:
    spec = PLATFORM_SPECS.get(key)
    if spec is None:
        raise PublishPayloadError(f"不支持的平台: {key}")
    return spec


def account_file_path(platform: str, account_name: str) -> Path:
    return sau_cli.resolve_account_file(platform, account_name)


def _setup_supports_cdp(spec: "PlatformSpec") -> bool:
    """该平台的 setup() 是否接受 cdp_url（可改在用户本机 Chrome 里登录）。"""
    import inspect

    if spec.setup is None:
        return False
    return "cdp_url" in inspect.signature(spec.setup).parameters


def meta_for_frontend() -> list[dict[str, Any]]:
    """给前端渲染表单用的平台元信息。"""
    return [
        {
            "key": spec.key,
            "name": spec.name,
            "login_mode": spec.login_mode,
            "terminal_login_hint": spec.terminal_login_hint,
            "supports_note": spec.supports_note,
            "supports_schedule": spec.supports_schedule,
            "supports_cdp": _setup_supports_cdp(spec),
            "extra_fields": list(spec.extra_fields),
        }
        for spec in PLATFORM_SPECS.values()
    ]


def zone_options() -> dict[str, list[dict[str, Any]]]:
    """Bilibili 分区 / 视频号分类选项。"""
    return {
        "bilibili_tid": [
            {"value": member.value, "label": f"{name}（{member.value}）"}
            for name, member in VideoZoneTypes.__members__.items()
        ],
        "tencent_category": [
            {"value": member.value, "label": member.value}
            for member in TencentZoneTypes.__members__.values()
        ],
    }


# ---------------------------------------------------------------------------
# 发布参数 → sau_cli 请求对象
# ---------------------------------------------------------------------------

def _require_text(payload: dict, field: str, label: str) -> str:
    value = str(payload.get(field) or "").strip()
    if not value:
        raise PublishPayloadError(f"{label}不能为空")
    return value


def _parse_tags(payload: dict) -> list[str]:
    raw = payload.get("tags")
    if isinstance(raw, str):
        return sau_cli.parse_tags(raw)
    if isinstance(raw, list):
        return [str(item).strip().lstrip("#") for item in raw if str(item).strip()]
    return []


def _parse_publish_date(payload: dict) -> datetime | int:
    raw = str(payload.get("publish_date") or "").strip()
    if not raw:
        return 0
    try:
        parsed = datetime.strptime(raw, sau_cli.SCHEDULE_FORMAT)
    except ValueError as exc:
        raise PublishPayloadError(
            f"定时时间格式错误，应为 {sau_cli.SCHEDULE_FORMAT}（如 2026-09-29 10:00）"
        ) from exc
    try:
        return BaseVideoUploader.validate_publish_date(parsed)
    except ValueError as exc:
        raise PublishPayloadError(str(exc)) from exc


def _resolve_material_path(raw: str, kind: str, material_dir: Path) -> Path:
    """素材引用：素材库名称（uploadFile/ 下）或服务器绝对路径（可信局域网约定）。"""
    name = str(raw or "").strip()
    if not name:
        raise PublishPayloadError("素材路径不能为空")
    path = Path(name)
    if not path.is_absolute():
        path = (material_dir / name).resolve()
        if not path.is_relative_to(material_dir.resolve()):
            raise PublishPayloadError("非法的素材路径")
    validate = (
        BaseVideoUploader.validate_video_file if kind == "video" else BaseVideoUploader.validate_image_file
    )
    try:
        return validate(path)
    except (FileNotFoundError, ValueError) as exc:
        raise PublishPayloadError(str(exc)) from exc


def _validate_image(path_text: str, material_dir: Path) -> Path:
    return _resolve_material_path(path_text, "image", material_dir)


def build_upload_request(
    platform: str,
    content_type: str,
    payload: dict,
    material_dir: Path,
):
    """把 Web 发布参数规范化为 sau_cli 的请求对象，返回 (upload_callable, request_obj)。"""
    spec = get_platform(platform)
    account_name = _require_text(payload, "account_name", "账号名")
    title = _require_text(payload, "title", "标题")
    tags = _parse_tags(payload)
    publish_date = _parse_publish_date(payload)
    if publish_date != 0 and not spec.supports_schedule:
        raise PublishPayloadError(f"{spec.name} 不支持定时发布（仅支持平台：抖音、快手、小红书、Bilibili、视频号），请改为立即发布")
    desc = str(payload.get("desc") or "").strip()
    note_text = str(payload.get("note") or "").strip()
    extras: dict = payload.get("extras") or {}
    thumbnail = (
        _validate_image(payload["thumbnail"], material_dir)
        if str(payload.get("thumbnail") or "").strip()
        else None
    )
    thumbnail_landscape = (
        _validate_image(payload["thumbnail_landscape"], material_dir)
        if str(payload.get("thumbnail_landscape") or "").strip()
        else None
    )
    thumbnail_portrait = (
        _validate_image(payload["thumbnail_portrait"], material_dir)
        if str(payload.get("thumbnail_portrait") or "").strip()
        else None
    )
    headless = bool(payload.get("headless", True))

    if content_type == "video":
        if spec.upload_video is None:
            raise PublishPayloadError(f"{spec.name}暂不支持视频上传")
        video_file = _resolve_material_path(str(payload.get("file") or ""), "video", material_dir)

        if platform == "douyin":
            request = sau_cli.DouyinVideoUploadRequest(
                account_name=account_name,
                video_file=video_file,
                title=title,
                description=desc,
                tags=tags,
                publish_date=publish_date,
                thumbnail_landscape_file=thumbnail_landscape,
                thumbnail_portrait_file=thumbnail_portrait or thumbnail,
                product_link=str(extras.get("product_link") or "").strip(),
                product_title=str(extras.get("product_title") or "").strip(),
                declaration=str(extras.get("declaration") or "").strip() or None,
                collection_name=str(extras.get("collection_name") or "").strip() or None,
                headless=headless,
            )
        elif platform == "kuaishou":
            request = sau_cli.KuaishouVideoUploadRequest(
                account_name=account_name,
                video_file=video_file,
                title=title,
                description=desc,
                tags=tags,
                publish_date=publish_date,
                thumbnail_file=thumbnail,
                collection_name=str(extras.get("collection_name") or "").strip() or None,
                headless=headless,
            )
        elif platform == "xiaohongshu":
            request = sau_cli.XiaohongshuVideoUploadRequest(
                account_name=account_name,
                video_file=video_file,
                title=title,
                description=desc,
                tags=tags,
                publish_date=publish_date,
                thumbnail_file=thumbnail,
                headless=headless,
            )
        elif platform == "bilibili":
            try:
                tid = int(extras.get("tid"))
            except (TypeError, ValueError) as exc:
                raise PublishPayloadError("Bilibili 分区ID(tid) 不能为空，请在表单中选择分区") from exc
            request = sau_cli.BilibiliVideoUploadRequest(
                account_name=account_name,
                video_file=video_file,
                title=title,
                description=desc,
                tid=tid,
                tags=tags,
                publish_date=publish_date,
                thumbnail_file=thumbnail,
            )
        elif platform == "tencent":
            request = sau_cli.TencentVideoUploadRequest(
                account_name=account_name,
                video_file=video_file,
                title=title,
                description=desc,
                tags=tags,
                publish_date=publish_date,
                thumbnail_file=thumbnail,
                thumbnail_landscape_file=thumbnail_landscape,
                thumbnail_portrait_file=thumbnail_portrait,
                short_title=str(extras.get("short_title") or "").strip() or None,
                category=str(extras.get("category") or "").strip() or None,
                is_draft=bool(extras.get("is_draft", False)),
                collection_name=str(extras.get("collection_name") or "").strip() or None,
                headless=headless,
            )
        elif platform == "baijiahao":
            request = sau_cli.BaijiahaoVideoUploadRequest(
                account_name=account_name,
                video_file=video_file,
                title=title,
                description=desc,
                tags=tags,
                thumbnail_file=thumbnail,
                collection_name=str(extras.get("collection_name") or "").strip() or None,
                headless=headless,
            )
        elif platform == "alipay":
            request = sau_cli.AlipayVideoUploadRequest(
                account_name=account_name,
                video_file=video_file,
                title=title,
                description=desc,
                tags=tags,
                thumbnail_file=thumbnail,
                collection_name=str(extras.get("collection_name") or "").strip() or None,
                headless=headless,
            )
        elif platform == "weibo":
            request = sau_cli.WeiboVideoUploadRequest(
                account_name=account_name,
                video_file=video_file,
                title=title,
                description=desc,
                tags=tags,
                thumbnail_file=thumbnail,
                collection_name=str(extras.get("collection_name") or "").strip() or None,
                headless=headless,
            )
        elif platform == "hupu":
            request = sau_cli.HupuVideoUploadRequest(
                account_name=account_name,
                video_file=video_file,
                title=title,
                description=desc,
                tags=tags,
                thumbnail_file=thumbnail,
                headless=headless,
            )
        elif platform == "youtube":
            visibility = str(extras.get("visibility") or "public").strip()
            if visibility not in ("public", "unlisted", "private"):
                raise PublishPayloadError("YouTube 可见性仅支持 public/unlisted/private")
            request = sau_cli.YouTubeVideoUploadRequest(
                account_name=account_name,
                video_file=video_file,
                title=title,
                description=desc,
                tags=tags,
                thumbnail_file=thumbnail,
                playlist=str(extras.get("playlist") or "").strip() or None,
                visibility=visibility,
                headless=headless,
            )
        elif platform == "tiktok":
            request = sau_cli.TiktokVideoUploadRequest(
                account_name=account_name,
                video_file=video_file,
                title=title,
                description=desc,
                tags=tags,
                publish_date=publish_date,
                thumbnail_file=thumbnail,
                headless=headless,
            )
        elif platform in ("instagram", "facebook", "x"):
            request = sau_cli.OverseasVideoUploadRequest(
                platform=platform,
                account_name=account_name,
                video_file=video_file,
                title=title,
                description=desc,
                tags=tags,
                thumbnail_file=thumbnail if platform == "instagram" else None,
                headless=headless,
            )
        else:  # pragma: no cover - 注册表受限，理论上不可达
            raise PublishPayloadError(f"平台 {platform} 未接入视频上传")
        return spec.upload_video, request

    if content_type == "note":
        if not spec.supports_note or spec.upload_note is None:
            raise PublishPayloadError(f"{spec.name}暂不支持图文上传")
        raw_images = payload.get("images") or []
        if not raw_images:
            raise PublishPayloadError("图文发布至少需要一张图片")
        image_files = [_validate_image(str(item), material_dir) for item in raw_images]
        note_body = note_text or desc
        if not note_body.strip():
            raise PublishPayloadError("图文正文不能为空（填写 正文 或 简介）")

        if platform == "douyin":
            request = sau_cli.DouyinNoteUploadRequest(
                account_name=account_name,
                image_files=image_files,
                title=title,
                note=note_body,
                tags=tags,
                publish_date=publish_date,
                headless=headless,
                bgm=str(extras.get("bgm") or "").strip(),
            )
        elif platform == "kuaishou":
            request = sau_cli.KuaishouNoteUploadRequest(
                account_name=account_name,
                image_files=image_files,
                title=title,
                note=note_body,
                tags=tags,
                publish_date=publish_date,
                headless=headless,
            )
        else:  # xiaohongshu
            request = sau_cli.XiaohongshuNoteUploadRequest(
                account_name=account_name,
                image_files=image_files,
                title=title,
                note=note_body,
                tags=tags,
                publish_date=publish_date,
                headless=headless,
            )
        return spec.upload_note, request

    raise PublishPayloadError("内容类型必须是 video 或 note")


def build_batch_requests(payload: dict, material_dir: Path) -> list[tuple[str, str, Callable, Any]]:
    """批量发布：公共字段 + 多目标（platform/account/extras 覆盖）。

    返回 [(platform, account_name, upload_callable, request), ...]。
    任一目标校验失败则整体拒绝（PublishPayloadError 消息含每个目标的错误），
    保证 agent 不会遇到"一半目标已入队"的部分成功状态。
    """
    raw_targets = payload.get("targets")
    if not isinstance(raw_targets, list) or not raw_targets:
        raise PublishPayloadError("targets 必须是非空数组，每项含 platform 和 account_name")

    content_type = str(payload.get("content_type") or "video").strip()
    common_extras: dict = payload.get("extras") or {}
    errors: list[str] = []
    results: list[tuple[str, str, Callable, Any]] = []

    for index, target in enumerate(raw_targets, start=1):
        target = target if isinstance(target, dict) else {}
        platform = str(target.get("platform") or "").strip()
        label = f"目标{index}({platform or '未填平台'})"
        try:
            merged = {**payload}
            merged.pop("targets", None)
            merged["platform"] = platform
            merged["content_type"] = content_type
            account_name = str(target.get("account_name") or "").strip()
            merged["account_name"] = account_name
            target_extras: dict = target.get("extras") or {}
            merged["extras"] = {**common_extras, **target_extras}
            # 目标级可覆盖定时时间（如：抖音定时发、微博立即发的组合）
            if "publish_date" in target:
                merged["publish_date"] = target["publish_date"]
            upload_callable, request = build_upload_request(platform, content_type, merged, material_dir)
            results.append((platform, account_name, upload_callable, request))
        except PublishPayloadError as exc:
            errors.append(f"{label}: {exc}")

    if errors:
        raise PublishPayloadError("；".join(errors))
    return results
