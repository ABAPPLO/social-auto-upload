# -*- coding: utf-8 -*-
"""social-auto-upload MCP Server。

工具面整体复刻 sau-web 控制台能力：平台/账号查询、扫码登录（二维码内联成
MCP 图片内容）、素材管理、视频/图文发布、任务轮询。发布类工具要求显式
confirm=True，给 Agent 触发的公开发布加一道防误触闸门。

运行方式：
    sau-mcp                          # stdio（默认，配到本机 Agent）
    sau-mcp --transport http --port 8808   # streamable-http，远程 Agent 按URL接入
环境变量：
    SAU_WEB_URL    sau-web 地址（默认 http://127.0.0.1:8010）
    SAU_WEB_TOKEN  可选 API Token（未启用鉴权时留空）
"""
from __future__ import annotations

import argparse
import base64
import json
import time
from typing import Any

try:  # mcp 2.x：FastMCP 改名为 MCPServer
    from mcp.server.mcpserver import MCPServer as ServerClass, Image
except ImportError:  # mcp 1.x
    from mcp.server.fastmcp import FastMCP as ServerClass, Image

from . import __version__
from .client import SauWebClient, SauWebError

mcp = ServerClass(
    "social-auto-upload",
    instructions=(
        "多平台自媒体发布助手。常用流：list_platforms 看能力 → list_accounts 看已登录账号 → "
        "未登录则 start_login（把返回的二维码给用户扫，wait_task 等结果）→ "
        "upload_material 上传素材 → publish_video/publish_note 发布（必须 confirm=true）→ "
        "wait_task 等待发布完成。发布任务的 message 里会有进度提示。"
    ),
)

_client = SauWebClient()

_TERMINAL_STATUSES = ("success", "failed")


def _compact_task(task: dict) -> dict:
    """任务快照精简：去掉巨大的二维码 data URL（图片走 Image 内容单独给）。"""
    compact = {k: v for k, v in task.items() if k != "qrcode_data_url"}
    compact["has_qrcode"] = bool(task.get("qrcode_data_url"))
    return compact


def _qr_image(task: dict) -> Image | None:
    data_url = str(task.get("qrcode_data_url") or "")
    if not data_url.startswith("data:image/"):
        return None
    try:
        header, b64 = data_url.split(",", 1)
        fmt = header.split("/")[1].split(";")[0] or "png"
        return Image(data=base64.b64decode(b64), format=fmt)
    except Exception:
        return None


def _login_result_content(task: dict) -> list:
    """登录任务的返回：精简 JSON 文本 + 二维码图片（Claude Desktop 可直接渲染）。"""
    parts = [
        json.dumps({"task": _compact_task(task), "hint": "请把上面的二维码给用户扫描；用 get_task 可拿刷新后的二维码，wait_task 等待登录结果"}, ensure_ascii=False)
    ]
    image = _qr_image(task)
    if image is not None:
        parts.append(image)
    return parts


@mcp.tool()
def server_status() -> str:
    """sau-web 服务状态：健康、版本、上传并发数。排查连接问题先用这个。"""
    health = _client.get("/api/health")
    meta = _client.get("/api/meta")
    return json.dumps(
        {
            "health": health,
            "version": meta.get("version"),
            "upload_concurrency": meta.get("upload_concurrency"),
            "mcp_version": __version__,
            "web_base": _client.base_url,
        },
        ensure_ascii=False,
    )


@mcp.tool()
def list_platforms() -> str:
    """列出全部平台及能力：登录方式、是否支持图文/定时/本地浏览器登录、发布附加字段（extras）。
    发布前调用以确认平台能力和需要填的字段。"""
    meta = _client.get("/api/meta")
    platforms = [
        {
            "key": p["key"],
            "name": p["name"],
            "login_mode": p["login_mode"],
            "supports_note": p.get("supports_note", False),
            "supports_schedule": p.get("supports_schedule", False),
            "supports_cdp": p.get("supports_cdp", False),
            "extra_fields": p.get("extra_fields", []),
        }
        for p in meta.get("platforms", [])
    ]
    return json.dumps({"platforms": platforms}, ensure_ascii=False, indent=1)


@mcp.tool()
def list_accounts() -> str:
    """列出已保存登录态的账号（platform / account / 文件信息）。"""
    return json.dumps(_client.get("/api/accounts"), ensure_ascii=False, indent=1)


@mcp.tool()
def check_account(platform: str, account: str) -> str:
    """检查某平台账号的登录态是否有效。会阻塞到检查完成（最长 90 秒）。"""
    data = _client.post(f"/api/accounts/{platform}/{account}/check")
    task_id = data["task"]["id"]
    task = _wait_until_terminal(task_id, timeout=90)
    return json.dumps(
        {
            "platform": platform,
            "account": account,
            "valid": task.get("status") == "success",
            "message": task.get("message"),
        },
        ensure_ascii=False,
    )


@mcp.tool()
def start_login(platform: str, account: str, cdp_url: str = "") -> list:
    """发起扫码登录，返回任务与二维码图片（给用户扫）。

    cdp_url 留空 = 服务器无头浏览器扫码；填 http://127.0.0.1:9222 =
    本地浏览器模式（用户本机 Chrome + ssh -R 隧道，详见控制台三步指引）。
    之后用 wait_task 等待登录结果；二维码刷新后用 get_task 重新获取图片。
    """
    body: dict[str, Any] = {"account_name": account}
    if cdp_url:
        body["cdp_url"] = cdp_url
    data = _client.post(f"/api/accounts/{platform}/login", json=body)
    return _login_result_content(data["task"])


@mcp.tool()
def get_task(task_id: str, include_qrcode: bool = True) -> list:
    """查询单个任务状态（登录/检查/发布）。include_qrcode=True 时附带最新二维码图片。"""
    task = _client.get(f"/api/tasks/{task_id}")["task"]
    parts = [json.dumps({"task": _compact_task(task)}, ensure_ascii=False, indent=1)]
    if include_qrcode:
        image = _qr_image(task)
        if image is not None:
            parts.append(image)
    return parts


@mcp.tool()
def wait_task(task_id: str, timeout_seconds: int = 300) -> str:
    """阻塞等待任务到终态（success/failed）或超时，返回最终任务快照。
    发布/登录耗时较长，Agent 应使用本工具而不是反复调 get_task。"""
    task = _wait_until_terminal(task_id, timeout=min(max(timeout_seconds, 5), 600))
    task.pop("qrcode_data_url", None)
    return json.dumps({"task": task, "hint": "" if task.get("status") in _TERMINAL_STATUSES else "仍在执行，可继续 wait_task"}, ensure_ascii=False, indent=1)


@mcp.tool()
def submit_sms_code(task_id: str, code: str) -> str:
    """提交抖音发布过程中触发的短信验证码（4-8 位数字）。提交后发布流程自动继续。"""
    return json.dumps(_client.post(f"/api/tasks/{task_id}/verify-code", json={"code": code}), ensure_ascii=False)


@mcp.tool()
def list_materials() -> str:
    """列出素材库（uploadFile/ 下的视频和图片，按时间倒序）。"""
    return json.dumps(_client.get("/api/materials"), ensure_ascii=False, indent=1)


@mcp.tool()
def upload_material(file_path: str) -> str:
    """把本机文件上传到素材库（MCP 运行机上的路径）。返回素材名，发布时引用它。同名会被拒绝。"""
    return json.dumps(_client.upload_file("/api/materials", file_path), ensure_ascii=False)


def _publish(confirm: bool, payload: dict, kind: str) -> str:
    if not confirm:
        raise SauWebError(f"发布是公开操作：请与用户确认后以 confirm=true 再次调用 publish_{kind}")
    data = _client.post("/api/publish", json=payload)
    task = data["task"]
    return json.dumps(
        {
            "task": _compact_task(task),
            "hint": "已入队（上传队列串行执行）。用 wait_task 等待结果；抖音发布可能需要短信验证码（submit_sms_code）。",
        },
        ensure_ascii=False,
    )


@mcp.tool()
def publish_video(
    confirm: bool,
    platform: str,
    account: str,
    file: str,
    title: str,
    desc: str = "",
    tags: str = "",
    publish_date: str = "",
    thumbnail: str = "",
    headless: bool = True,
    extras: dict | None = None,
) -> str:
    """发布视频（公开发布，必须 confirm=true）。

    file/thumbnail 填素材名（先 upload_material）或服务器绝对路径；
    tags 逗号分隔；publish_date 定时发布，格式如 2026-09-29 10:00（至少两小时后），
    留空立即发布；平台附加字段放 extras（用 list_platforms 查各平台 extra_fields）。
    """
    payload = {
        "platform": platform,
        "content_type": "video",
        "account_name": account,
        "file": file,
        "title": title,
        "desc": desc,
        "tags": tags,
        "publish_date": publish_date,
        "thumbnail": thumbnail,
        "headless": headless,
        "extras": extras or {},
    }
    return _publish(confirm, payload, "video")


@mcp.tool()
def publish_note(
    confirm: bool,
    platform: str,
    account: str,
    images: list[str],
    title: str,
    note: str = "",
    tags: str = "",
    publish_date: str = "",
    headless: bool = True,
    extras: dict | None = None,
) -> str:
    """发布图文（小红书/抖音/快手等，必须 confirm=true）。images 是素材名列表。"""
    payload = {
        "platform": platform,
        "content_type": "note",
        "account_name": account,
        "images": images,
        "title": title,
        "note": note,
        "tags": tags,
        "publish_date": publish_date,
        "headless": headless,
        "extras": extras or {},
    }
    return _publish(confirm, payload, "note")


def _wait_until_terminal(task_id: str, timeout: float, interval: float = 2.0) -> dict:
    deadline = time.time() + timeout
    task: dict = {}
    while True:
        task = _client.get(f"/api/tasks/{task_id}")["task"]
        if task.get("status") in _TERMINAL_STATUSES:
            return task
        if time.time() >= deadline:
            return task
        time.sleep(interval)


def main() -> None:
    parser = argparse.ArgumentParser(prog="sau-mcp", description="social-auto-upload MCP Server")
    parser.add_argument("--transport", choices=["stdio", "http"], default="stdio", help="stdio=本地 Agent 进程拉起；http=远程 Agent 按 URL 接入")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8808)
    parser.add_argument("--web-url", default="", help="覆盖 SAU_WEB_URL（sau-web API 地址）")
    args = parser.parse_args()

    global _client
    if args.web_url:
        _client = SauWebClient(base_url=args.web_url.rstrip("/"))

    if args.transport == "http":
        # streamable-http：远程 Agent 通过 http://<host>:<port>/mcp 接入
        mcp.run(transport="streamable-http", host=args.host, port=args.port)
    else:
        mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
