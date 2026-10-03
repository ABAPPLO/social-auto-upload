# -*- coding: utf-8 -*-
"""Web 端人工协助绑定：TaskAssist 把 uploader 事件写入任务状态，LIVE 登记可交互页面。

uploader 登录等待循环持有一个 ManualAssist（utils.web_assist 协议）；
Web 端用 TaskAssist 实现它：推帧 → 任务快照（前端轮询展示），
attach_page → LIVE 表（路由层把前端点击/拖拽转发到对应页面）。
"""
from __future__ import annotations

from utils import web_assist

from .tasks import manager

# task_id -> TaskAssist（仅登录等待期间有绑定；页面关闭后自动摘除）
LIVE: dict[str, "TaskAssist"] = {}


class TaskAssist(web_assist.ManualAssist):
    def __init__(self, task_id: str):
        self.task_id = task_id
        self.page = None

    async def on_frame(self, data_url: str, page_url: str = "") -> None:
        manager.set_assist_frame(self.task_id, data_url, page_url)

    async def on_verify_state(self, needed: bool, hint: str = "") -> None:
        manager.set_assist_verify(self.task_id, needed, hint)

    def attach_page(self, page) -> None:
        self.page = page
        LIVE[self.task_id] = self

    def detach_page(self) -> None:
        self.page = None
        if LIVE.get(self.task_id) is self:
            LIVE.pop(self.task_id, None)
