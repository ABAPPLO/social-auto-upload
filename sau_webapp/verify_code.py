# -*- coding: utf-8 -*-
"""抖音短信验证码的 Web 通道。

uploader 在发布重试循环里反复调用 `_read_verify_code`（文件 → 终端），
这里把它替换为 Web 版：每次调用刷新任务的"等待验证码"状态，并在单次调用内
轮询 verify_code.txt 一小段时间（等网页/API 写入），超时返回空串交给外层
重试循环再次进入。uploader 收到验证码并提交成功后会自行删除该文件。

替换私有函数是无奈之举：uploader 没有提供公开回调；调用点按模块全局名解析，
运行期替换可靠（Python 在调用时才查名字）。
"""
from __future__ import annotations

import asyncio
import os

from conf import BASE_DIR

from .tasks import current_task_id, manager

VERIFY_CODE_FILE = os.path.join(BASE_DIR, "verify_code.txt")

# 单次调用的文件轮询时长：略小于任务快照的 30s 失效窗口即可
POLL_SECONDS = 10
POLL_INTERVAL = 2


def _read_file_code(code_file: str = VERIFY_CODE_FILE) -> str:
    try:
        with open(code_file, encoding="utf-8") as file_obj:
            return file_obj.read().strip()
    except OSError:
        return ""


async def web_read_verify_code(code_file: str, poll_seconds: float = POLL_SECONDS) -> str:
    task_id = current_task_id.get()
    if task_id:
        manager.mark_verify_waiting(task_id)
    deadline = asyncio.get_running_loop().time() + poll_seconds
    while True:
        code = _read_file_code(code_file)
        if code:
            return code
        if asyncio.get_running_loop().time() >= deadline:
            return ""
        await asyncio.sleep(POLL_INTERVAL)


def submit_verify_code(code: str) -> None:
    """把用户提交的验证码写入约定文件，等待发布循环的下一轮读取。"""
    with open(VERIFY_CODE_FILE, "w", encoding="utf-8") as file_obj:
        file_obj.write(code.strip())


def install_hook() -> None:
    import uploader.douyin_uploader.main as douyin_main

    if getattr(douyin_main._read_verify_code, "_sau_web_hook", False):
        return
    original = douyin_main._read_verify_code

    async def _hook(code_file: str) -> str:
        # 只在 Web 任务上下文内接管；直接跑 CLI（sau 命令）时保持原行为
        if not current_task_id.get():
            return await original(code_file)
        return await web_read_verify_code(code_file)

    _hook._sau_web_hook = True
    douyin_main._read_verify_code = _hook
