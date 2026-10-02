# -*- coding: utf-8 -*-
"""Web 管理 API：平台元信息 / 账号 / 素材 / 发布任务 / 任务查询。"""
from __future__ import annotations

import json
import re
import shutil
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from fastapi import APIRouter, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.responses import FileResponse, StreamingResponse
from starlette.concurrency import run_in_threadpool

from conf import BASE_DIR
from utils.network import check_proxy, get_platform_proxy, load_proxy_exit_state

from . import __version__, media, registry
from .registry import LOGIN_MODE_TERMINAL, PublishPayloadError
from .tasks import manager

router = APIRouter(prefix="/api")

MATERIAL_DIR = BASE_DIR / "uploadFile"
COOKIES_DIR = BASE_DIR / "cookies"
MATERIAL_DIR.mkdir(exist_ok=True)

VIDEO_EXTS = {".mp4", ".mov", ".avi", ".mkv", ".m4v", ".webm", ".flv", ".wmv"}
IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".bmp"}
MATERIAL_EXTS = VIDEO_EXTS | IMAGE_EXTS
# 上传文件名单字符白名单（含中文），拒绝路径分隔符与控制字符
SAFE_NAME_RE = re.compile(r"^[\w\u4e00-\u9fff\-. ()\[\]]+$")


def _bad_request(message: str) -> HTTPException:
    return HTTPException(status_code=400, detail=message)


def _platform_or_400(platform: str):
    try:
        return registry.get_platform(platform)
    except registry.PublishPayloadError as exc:
        raise _bad_request(str(exc)) from exc


# ---------------------------------------------------------------------------
# 元信息
# ---------------------------------------------------------------------------

@router.get("/meta")
def get_meta() -> dict:
    return {
        "version": __version__,
        "platforms": registry.meta_for_frontend(),
        "zones": registry.zone_options(),
        "material_dir": str(MATERIAL_DIR),
        "upload_concurrency": manager.upload_concurrency,
    }


@router.get("/health")
def health() -> dict:
    return {"ok": True}


# ---------------------------------------------------------------------------
# 代理状态（海外平台）
# ---------------------------------------------------------------------------

_PROXY_PLATFORMS = ("youtube", "tiktok", "instagram", "facebook", "x")
_PROXY_STATUS_TTL = 60.0
_proxy_status_cache: dict[str, Any] = {"data": None, "at": 0.0}


@router.get("/proxy-status")
def get_proxy_status(refresh: bool = Query(False)) -> dict:
    """海外平台的代理解析 + 出口 IP 实测（60s 缓存，refresh=1 强制刷新）。

    只读不落盘：出口 IP 只在上传预检（ensure_proxy_ready）时记录；
    这里把实测出口与「上次上传记录的出口」对比，供前端提示漂移。
    """
    now = time.time()
    cached = _proxy_status_cache["data"]
    if cached is not None and not refresh and now - _proxy_status_cache["at"] < _PROXY_STATUS_TTL:
        return cached

    state = load_proxy_exit_state()
    rows: list[dict[str, Any]] = []
    futures: dict[str, Any] = {}
    with ThreadPoolExecutor(max_workers=len(_PROXY_PLATFORMS)) as pool:
        for platform in _PROXY_PLATFORMS:
            proxy = get_platform_proxy(platform)
            if not proxy:
                rows.append({
                    "platform": platform, "proxy": None, "ok": True,
                    "exit_ip": None, "error": None,
                    "last_upload_exit_ip": None, "differs_from_last_upload": False,
                })
                continue
            futures[platform] = (proxy, pool.submit(check_proxy, proxy, 4.0))
        for platform, (proxy, future) in futures.items():
            result = future.result()
            recorded = state.get(proxy, {}) if isinstance(state.get(proxy), dict) else {}
            last_ip = recorded.get("exit_ip")
            rows.append({
                "platform": platform, "proxy": proxy, "ok": result.reachable,
                "exit_ip": result.exit_ip, "error": result.error,
                "last_upload_exit_ip": last_ip,
                "differs_from_last_upload": bool(
                    result.reachable and result.exit_ip and last_ip and result.exit_ip != last_ip
                ),
            })

    data = {
        "ok": True,
        "checked_at": datetime.now().isoformat(timespec="seconds"),
        "platforms": rows,
    }
    _proxy_status_cache["data"] = data
    _proxy_status_cache["at"] = now
    return data


# ---------------------------------------------------------------------------
# 账号
# ---------------------------------------------------------------------------

def _list_cookie_files() -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    if not COOKIES_DIR.exists():
        return items
    for file in sorted(COOKIES_DIR.glob("*.json")):
        stem = file.stem
        platform, _, account = stem.partition("_")
        if not account or platform not in registry.PLATFORM_SPECS:
            continue
        stat = file.stat()
        items.append(
            {
                "platform": platform,
                "platform_name": registry.PLATFORM_SPECS[platform].name,
                "account": account,
                "file": str(file),
                "size": stat.st_size,
                "updated_at": datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M:%S"),
            }
        )
    return items


@router.get("/accounts")
def list_accounts() -> dict:
    return {"accounts": _list_cookie_files()}


def _validate_account_name(account_name: str) -> str:
    account_name = (account_name or "").strip()
    if not account_name:
        raise _bad_request("账号名不能为空")
    if not re.fullmatch(r"[\w\u4e00-\u9fff\-.]+", account_name):
        raise _bad_request("账号名仅支持中英文、数字、下划线、连字符和点")
    return account_name


@router.post("/accounts/{platform}/login")
async def start_login(platform: str, body: dict) -> dict:
    spec = _platform_or_400(platform)
    account_name = _validate_account_name(str(body.get("account_name") or ""))
    if spec.login_mode == LOGIN_MODE_TERMINAL:
        raise _bad_request(spec.terminal_login_hint)
    if spec.setup is None:
        raise _bad_request(f"{spec.name}暂不支持网页扫码登录")

    account_file = registry.account_file_path(platform, account_name)

    def on_qrcode(payload: dict) -> None:
        data_url = str(payload.get("image_data_url") or "")
        if data_url:
            manager.set_qrcode(task_id, data_url)

    async def run_login() -> dict:
        result = await spec.setup(
            str(account_file),
            handle=True,
            return_detail=True,
            qrcode_callback=on_qrcode,
            headless=True,
        )
        return dict(result or {})

    task = manager.create("login", platform, account_name, summary="扫码登录")
    task_id = task["id"]
    manager.start_now(task_id, run_login)
    return {"task": task}


@router.post("/accounts/{platform}/{account}/check")
async def start_check(platform: str, account: str) -> dict:
    spec = _platform_or_400(platform)
    account_name = _validate_account_name(account)

    async def run_check() -> dict:
        valid = await spec.check(account_name)
        message = "登录态有效" if valid else "登录态已失效，请重新登录"
        return {"success": valid, "message": message}

    task = manager.create("check", platform, account_name, summary="检查登录态")
    manager.start_now(task["id"], run_check)
    return {"task": task}


@router.delete("/accounts/{platform}/{account}")
def delete_account(platform: str, account: str) -> dict:
    _platform_or_400(platform)
    account_name = _validate_account_name(account)
    account_file = registry.account_file_path(platform, account_name)
    if not account_file.exists():
        raise _bad_request(f"账号文件不存在: {account_file}")
    account_file.unlink()
    return {"ok": True}


MAX_COOKIE_BYTES = 10 * 1024 * 1024


@router.post("/accounts/upload-cookie")
async def upload_cookie(
    platform: str = Form(...),
    account_name: str = Form(...),
    file: UploadFile = File(...),
) -> dict:
    """上传 cookie 文件（Bilibili / YouTube 等无法网页扫码的平台，或跨机迁移登录态）。

    文件须是有效 JSON（Playwright storage_state 或 biliup 的账号文件均可），
    保存为 cookies/<platform>_<account_name>.json，已有同名账号会被覆盖。
    """
    _platform_or_400(platform)
    account_name = _validate_account_name(account_name)
    raw = await file.read()
    if not raw:
        raise _bad_request("cookie 文件为空")
    if len(raw) > MAX_COOKIE_BYTES:
        raise _bad_request("cookie 文件过大（超过 10MB）")
    try:
        json.loads(raw)
    except ValueError as exc:
        raise _bad_request("cookie 文件不是有效的 JSON（应为 storage_state 或 biliup 账号文件）") from exc

    account_file = registry.account_file_path(platform, account_name)
    account_file.write_bytes(raw)
    return {
        "ok": True,
        "platform": platform,
        "account": account_name,
        "file": str(account_file),
        "message": "cookie 已保存，建议立即执行一次「检查」验证登录态",
    }


# ---------------------------------------------------------------------------
# 素材库
# ---------------------------------------------------------------------------

def _material_info(file: Path, with_meta: bool = True) -> dict[str, Any]:
    stat = file.stat()
    ext = file.suffix.lower()
    is_video = ext in VIDEO_EXTS
    info = {
        "name": file.name,
        "type": "video" if is_video else "image",
        "size": stat.st_size,
        "updated_at": datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M:%S"),
    }
    if with_meta and is_video:
        meta = media.ensure_video_meta(file, MATERIAL_DIR)
        info["duration"] = meta.get("duration", 0)
        info["width"] = meta.get("width", 0)
        info["height"] = meta.get("height", 0)
    return info


@router.get("/materials")
async def list_materials() -> dict:
    def _scan() -> list[dict[str, Any]]:
        files = [f for f in MATERIAL_DIR.iterdir() if f.is_file() and f.suffix.lower() in MATERIAL_EXTS]
        files.sort(key=lambda f: f.stat().st_mtime, reverse=True)
        return [_material_info(f) for f in files]

    materials = await run_in_threadpool(_scan)
    return {"materials": materials}


def _safe_material_file(name: str) -> Path:
    target = (MATERIAL_DIR / name).resolve()
    if not target.is_relative_to(MATERIAL_DIR.resolve()):
        raise _bad_request("非法的素材路径")
    return target


@router.post("/materials")
async def upload_material(file: UploadFile = File(...)) -> dict:
    raw_name = Path(file.filename or "").name
    if not raw_name or not SAFE_NAME_RE.fullmatch(raw_name):
        raise _bad_request(f"不合法的文件名: {raw_name!r}")
    if Path(raw_name).suffix.lower() not in MATERIAL_EXTS:
        raise _bad_request("仅支持视频（mp4/mov/avi/mkv/m4v/webm/flv/wmv）或图片（jpg/jpeg/png/webp/bmp）")

    target = MATERIAL_DIR / raw_name
    if target.exists():
        raise _bad_request(f"同名素材已存在: {raw_name}")

    def _write() -> None:
        with target.open("wb") as out:
            shutil.copyfileobj(file.file, out, length=1024 * 1024)

    await run_in_threadpool(_write)
    return {"material": _material_info(target)}


@router.delete("/materials/{name}")
def delete_material(name: str) -> dict:
    target = _safe_material_file(name)
    if not target.exists():
        raise _bad_request(f"素材不存在: {name}")
    target.unlink()
    # 同步清理缓存的封面与元信息
    for cached in (media.poster_file(MATERIAL_DIR, name), media.meta_file(MATERIAL_DIR, name)):
        cached.unlink(missing_ok=True)
    return {"ok": True}


CHUNK_SIZE = 1024 * 512


def _file_chunks(path: Path, start: int, length: int):
    with path.open("rb") as handle:
        handle.seek(start)
        remaining = length
        while remaining > 0:
            chunk = handle.read(min(CHUNK_SIZE, remaining))
            if not chunk:
                break
            remaining -= len(chunk)
            yield chunk


@router.get("/materials/{name}/file")
def get_material_file(name: str, request: Request) -> StreamingResponse:
    """素材文件流，支持 HTTP Range（视频拖动进度条必需）。"""
    target = _safe_material_file(name)
    if not target.exists():
        raise _bad_request(f"素材不存在: {name}")
    size = target.stat().st_size

    start, end = 0, size - 1
    range_header = request.headers.get("range")
    if range_header:
        match = re.match(r"bytes=(\d*)-(\d*)$", range_header.strip())
        if not match:
            raise HTTPException(status_code=416, detail="无效的 Range 请求")
        raw_start, raw_end = match.groups()
        if raw_start:
            start = int(raw_start)
        if raw_end:
            end = min(int(raw_end), size - 1)
        elif not raw_start:
            start, end = 0, 0  # bytes=-N 结尾范围暂不支持，退化为全量
        if start > end or start >= size:
            raise HTTPException(
                status_code=416,
                detail="请求范围越界",
                headers={"Content-Range": f"bytes */{size}"},
            )

    headers = {
        "Accept-Ranges": "bytes",
        "Content-Length": str(end - start + 1),
        "Content-Type": "application/octet-stream",
    }
    status_code = 200
    if range_header:
        status_code = 206
        headers["Content-Range"] = f"bytes {start}-{end}/{size}"
    return StreamingResponse(_file_chunks(target, start, end - start + 1), status_code=status_code, headers=headers)


@router.get("/materials/{name}/poster")
async def get_material_poster(name: str) -> FileResponse:
    """视频封面帧（首次访问时提取并缓存）；图片素材直接返回原图。"""
    target = _safe_material_file(name)
    if not target.exists():
        raise _bad_request(f"素材不存在: {name}")
    if target.suffix.lower() in IMAGE_EXTS:
        return FileResponse(str(target))
    poster = media.poster_file(MATERIAL_DIR, target.name)
    if not poster.exists():
        await run_in_threadpool(media.ensure_video_meta, target, MATERIAL_DIR)
    if not poster.exists():
        raise _bad_request(f"无法提取封面（文件可能损坏）: {name}")
    return FileResponse(str(poster))


# ---------------------------------------------------------------------------
# 发布
# ---------------------------------------------------------------------------

@router.post("/publish")
async def create_publish_task(body: dict) -> dict:
    platform = str(body.get("platform") or "").strip()
    content_type = str(body.get("content_type") or "video").strip()
    try:
        upload_callable, request = registry.build_upload_request(platform, content_type, body, MATERIAL_DIR)
    except PublishPayloadError as exc:
        raise _bad_request(str(exc)) from exc

    account_name = str(body.get("account_name") or "").strip()
    file_label = str(body.get("file") or (", ".join(body.get("images") or [])))
    title = str(body.get("title") or "").strip()
    schedule = str(body.get("publish_date") or "").strip()
    summary = f"{'图文' if content_type == 'note' else '视频'} · {file_label} · {title}" + (
        f" · 定时 {schedule}" if schedule else ""
    )

    async def run_upload() -> dict:
        await upload_callable(request)
        return {"success": True, "message": "发布流程已完成"}

    task = manager.create("upload", platform, account_name, summary=summary, file=file_label)
    manager.enqueue(task["id"], run_upload)
    return {"task": task}


@router.post("/publish/batch")
async def create_batch_publish_tasks(body: dict) -> dict:
    """一次提交多个发布目标（多平台 / 多账号），全部校验通过才入队。"""
    try:
        results = registry.build_batch_requests(body, MATERIAL_DIR)
    except PublishPayloadError as exc:
        raise _bad_request(str(exc)) from exc

    content_type = str(body.get("content_type") or "video").strip()
    file_label = str(body.get("file") or (", ".join(body.get("images") or [])))
    title = str(body.get("title") or "").strip()
    schedule = str(body.get("publish_date") or "").strip()
    summary = f"批量 · {'图文' if content_type == 'note' else '视频'} · {file_label} · {title}" + (
        f" · 定时 {schedule}" if schedule else ""
    )

    tasks = []
    for platform, account_name, upload_callable, request in results:
        async def run_upload(fn=upload_callable, req=request) -> dict:
            await fn(req)
            return {"success": True, "message": "发布流程已完成"}

        task = manager.create("upload", platform, account_name, summary=summary, file=file_label)
        manager.enqueue(task["id"], run_upload)
        tasks.append(task)
    return {"tasks": tasks}


# ---------------------------------------------------------------------------
# 统计（仪表盘图表数据）
# ---------------------------------------------------------------------------

@router.get("/stats")
def get_stats() -> dict:
    accounts_by_platform: dict[str, int] = {key: 0 for key in registry.PLATFORM_SPECS}
    for item in _list_cookie_files():
        accounts_by_platform[item["platform"]] = accounts_by_platform.get(item["platform"], 0) + 1

    materials_video = sum(1 for f in MATERIAL_DIR.iterdir() if f.is_file() and f.suffix.lower() in VIDEO_EXTS)
    materials_image = sum(1 for f in MATERIAL_DIR.iterdir() if f.is_file() and f.suffix.lower() in IMAGE_EXTS)

    tasks = manager.list(limit=200)
    by_day: dict[str, dict[str, int]] = {}
    by_platform: dict[str, int] = {}
    success = failed = 0
    for task in tasks:
        day = (task.get("created_at") or "")[:10]
        if day:
            bucket = by_day.setdefault(day, {"success": 0, "failed": 0, "other": 0})
            status = task.get("status")
            if status == "success":
                bucket["success"] += 1
                success += 1
            elif status == "failed":
                bucket["failed"] += 1
                failed += 1
            else:
                bucket["other"] += 1
        platform = task.get("platform") or ""
        if platform:
            by_platform[platform] = by_platform.get(platform, 0) + 1

    # 补齐最近 7 天（含无任务的日期），按日期升序
    days: list[dict[str, Any]] = []
    today = datetime.now().date()
    for offset in range(6, -1, -1):
        day = (today - timedelta(days=offset)).isoformat()
        bucket = by_day.pop(day, {"success": 0, "failed": 0, "other": 0})
        days.append({"day": day, **bucket})

    return {
        "accounts_by_platform": accounts_by_platform,
        "materials": {"video": materials_video, "image": materials_image},
        "tasks_by_day": days,
        "tasks_by_platform": by_platform,
        "tasks_total": len(tasks),
        "tasks_success": success,
        "tasks_failed": failed,
    }


# ---------------------------------------------------------------------------
# 任务
# ---------------------------------------------------------------------------

@router.get("/tasks")
def list_tasks(
    type: str | None = Query(default=None),
    platform: str | None = Query(default=None),
    status: str | None = Query(default=None),
    account: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=200),
) -> dict:
    # 先取较大池再做过滤，避免同秒批量创建的任务被 limit 截断后过滤为空
    tasks = manager.list(task_type=type, limit=200)
    if platform:
        tasks = [t for t in tasks if t["platform"] == platform]
    if status:
        tasks = [t for t in tasks if t["status"] == status]
    if account:
        tasks = [t for t in tasks if t["account"] == account]
    return {"tasks": tasks[:limit]}


@router.get("/tasks/{task_id}")
def get_task(task_id: str) -> dict:
    task = manager.get(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="任务不存在或已被清理")
    return {"task": task}


@router.post("/tasks/{task_id}/verify-code")
def submit_task_verify_code(task_id: str, body: dict) -> dict:
    """提交抖音发布过程中触发的短信验证码（写入 verify_code.txt，由发布循环读取）。"""
    task = manager.get(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="任务不存在或已被清理")
    if task["type"] != "upload" or task["platform"] != "douyin":
        raise _bad_request("只有抖音发布任务会需要短信验证码")
    if task["status"] not in ("running", "pending"):
        raise _bad_request(f"任务已结束（{task['status']}），无需再提交验证码")
    code = str(body.get("code") or "").strip()
    if not re.fullmatch(r"\d{4,8}", code):
        raise _bad_request("验证码应为 4-8 位数字")

    from .verify_code import submit_verify_code

    submit_verify_code(code)
    return {"ok": True, "message": "验证码已提交，发布流程将继续"}
