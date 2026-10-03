# -*- coding: utf-8 -*-
"""异步任务管理：扫码登录 / 账号检查 / 发布上传。

- 上传任务走队列串行执行（默认并发 1，可通过环境变量 SAU_WEB_UPLOAD_CONCURRENCY 调整），
  每个上传任务会启动一个浏览器实例，避免同时开太多把服务器内存打爆。
- 登录/检查任务即时启动，用信号量限制并发（默认 2）。
- 任务记录仅存内存，服务重启后清空（cookie/素材都在磁盘上，不受影响）。
"""
from __future__ import annotations

import asyncio
import os
import time
import uuid
from contextvars import ContextVar
from datetime import datetime
from typing import Any, Awaitable, Callable

MAX_TASKS_KEPT = 300

# 当前协程内正在执行的任务 id（供 uploader 层的验证码钩子回写任务状态）
current_task_id: ContextVar[str] = ContextVar("sau_web_current_task", default="")

# 验证码等待标记的失效窗口：uploader 每轮重试都会刷新 verify_last_poll，
# 超过该秒数未刷新视为 SMS 弹窗已消失（避免任务结束后标记残留）
VERIFY_WAIT_STALE_SECONDS = 30


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def new_task_id() -> str:
    return uuid.uuid4().hex[:12]


class TaskManager:
    def __init__(self, upload_concurrency: int = 1, login_concurrency: int = 2):
        self._tasks: dict[str, dict[str, Any]] = {}
        self._upload_queue: asyncio.Queue[str] = asyncio.Queue()
        self._upload_concurrency = max(1, upload_concurrency)
        self._upload_sem = asyncio.Semaphore(self._upload_concurrency)
        self._login_sem = asyncio.Semaphore(max(1, login_concurrency))
        self._workers: list[asyncio.Task] = []
        self._factories: dict[str, Callable[[], Awaitable[dict]]] = {}

    # ---- 任务生命周期 -----------------------------------------------------

    def create(self, task_type: str, platform: str, account: str, summary: str = "", file: str = "") -> dict:
        task_id = new_task_id()
        task = {
            "id": task_id,
            "type": task_type,  # login | check | upload
            "platform": platform,
            "account": account,
            "summary": summary,
            "file": file,  # 发布任务关联的素材名（用于封面缩略图）
            "status": "pending",
            "message": "排队中",
            "qrcode_data_url": "",
            "error": "",
            "waiting_verify_code": False,  # 计算字段：是否正在等短信验证码
            "verify_last_poll": 0.0,  # uploader 验证码钩子最近一次轮询时间戳
            "created_at": _now(),
            "started_at": "",
            "finished_at": "",
        }
        self._tasks[task_id] = task
        self._gc()
        return dict(task)

    def _gc(self) -> None:
        if len(self._tasks) <= MAX_TASKS_KEPT:
            return
        for old_id in list(self._tasks.keys())[: len(self._tasks) - MAX_TASKS_KEPT]:
            self._tasks.pop(old_id, None)
            self._factories.pop(old_id, None)

    # ---- 执行调度 ---------------------------------------------------------

    def start_now(self, task_id: str, factory: Callable[[], Awaitable[dict]]) -> None:
        """登录/检查类任务：立即后台执行（受登录并发信号量约束）。"""
        self._factories[task_id] = factory
        asyncio.create_task(self._run_with_sem(self._login_sem, task_id))

    def enqueue(self, task_id: str, factory: Callable[[], Awaitable[dict]]) -> None:
        """上传类任务：进入队列，由 worker 逐个执行。"""
        self._factories[task_id] = factory
        self._upload_queue.put_nowait(task_id)

    async def _run_with_sem(self, sem: asyncio.Semaphore, task_id: str) -> None:
        async with sem:
            await self._execute(task_id)

    async def _execute(self, task_id: str) -> None:
        task = self._tasks.get(task_id)
        factory = self._factories.pop(task_id, None)
        if task is None or factory is None:
            return
        task["status"] = "running"
        task["message"] = "执行中"
        task["started_at"] = _now()
        ctx_token = current_task_id.set(task_id)
        try:
            result = await factory()
            # 登录/检查任务的协程返回 dict（setup/bool 结果在 routes 层包装）
            if isinstance(result, dict):
                task["message"] = str(result.get("message") or task["message"])
                qrcode = result.get("qrcode") or {}
                data_url = qrcode.get("image_data_url") or ""
                if data_url:
                    task["qrcode_data_url"] = data_url
                success = bool(result.get("success"))
            else:
                success = bool(result)
            task["status"] = "success" if success else "failed"
            if not success and not task["error"]:
                task["error"] = task["message"]
        except Exception as exc:  # noqa: BLE001 - 任务级兜底，任何失败都要落到任务记录
            task["status"] = "failed"
            task["error"] = str(exc) or exc.__class__.__name__
            task["message"] = f"失败: {task['error'][:300]}"
        finally:
            current_task_id.reset(ctx_token)
            task["finished_at"] = _now()

    # ---- worker -----------------------------------------------------------

    async def start_workers(self) -> None:
        if self._workers:
            return
        for _ in range(self._upload_concurrency):
            self._workers.append(asyncio.create_task(self._worker_loop()))

    async def stop_workers(self) -> None:
        for worker in self._workers:
            worker.cancel()
        self._workers.clear()

    async def _worker_loop(self) -> None:
        while True:
            task_id = await self._upload_queue.get()
            try:
                await self._run_with_sem(self._upload_sem, task_id)
            finally:
                self._upload_queue.task_done()

    # ---- 查询 -------------------------------------------------------------

    @property
    def upload_concurrency(self) -> int:
        return self._upload_concurrency

    def _snapshot(self, task: dict) -> dict:
        snap = dict(task)
        # 等待验证码是"活跃"状态：仅执行中 + 钩子最近仍在轮询才算
        snap["waiting_verify_code"] = bool(
            task.get("status") == "running"
            and task.get("verify_last_poll", 0) > 0
            and time.time() - task["verify_last_poll"] < VERIFY_WAIT_STALE_SECONDS
        )
        return snap

    def get(self, task_id: str) -> dict | None:
        task = self._tasks.get(task_id)
        return self._snapshot(task) if task else None

    def list(self, task_type: str | None = None, limit: int = 100) -> list[dict]:
        tasks = [
            self._snapshot(task)
            for task in self._tasks.values()
            if task_type is None or task["type"] == task_type
        ]
        tasks.sort(key=lambda item: item["created_at"], reverse=True)
        return tasks[: min(limit, 200)]

    def mark_verify_waiting(self, task_id: str) -> None:
        """uploader 的验证码钩子每轮轮询时调用：刷新时间戳并更新任务提示。"""
        task = self._tasks.get(task_id)
        if task is None or task.get("status") != "running":
            return
        task["verify_last_poll"] = time.time()
        task["message"] = "📱 等待短信验证码——请在页面上提交手机收到的验证码"

    def set_qrcode(self, task_id: str, data_url: str) -> None:
        task = self._tasks.get(task_id)
        if task is None:
            return
        task["qrcode_data_url"] = data_url
        task["message"] = "二维码已生成，请使用平台APP扫码确认"


manager = TaskManager(
    upload_concurrency=int(os.environ.get("SAU_WEB_UPLOAD_CONCURRENCY", "1")),
)
