# -*- coding: utf-8 -*-
"""sau-web：局域网 Web 管理界面入口。

启动方式：
    sau-web                          # 默认 0.0.0.0:8010
    sau-web --host 0.0.0.0 --port 8010
    python -m sau_webapp             # 与 sau-web 等价

并发控制（环境变量）：
    SAU_WEB_UPLOAD_CONCURRENCY   同时执行的发布任务数，默认 1（每个任务一个浏览器实例）
    SAU_WEB_TOKEN                设置后 /api/* 需要 X-API-Token 头（供局域网 agent 调用时启用）
"""
from __future__ import annotations

import argparse
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from . import verify_code
from .routes import router
from .tasks import manager

STATIC_DIR = Path(__file__).parent / "static"
DEFAULT_HOST = "0.0.0.0"
DEFAULT_PORT = 8010


class TokenAuthMiddleware:
    """可选的 API Token 鉴权：设置环境变量 SAU_WEB_TOKEN 后，/api/* 请求须携带
    X-API-Token 头（或 Authorization: Bearer）。/api/health 保持开放用于探活。
    页面静态资源不受影响（浏览器界面本身无鉴权，面向可信局域网）。"""

    def __init__(self, app, token: str):
        self.app = app
        self.token = token

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or not scope["path"].startswith("/api") or scope["path"] == "/api/health":
            await self.app(scope, receive, send)
            return
        headers = {key.decode("latin-1").lower(): value.decode("latin-1") for key, value in scope.get("headers", [])}
        provided = headers.get("x-api-token") or ""
        if not provided and headers.get("authorization", "").startswith("Bearer "):
            provided = headers["authorization"][7:].strip()
        if provided != self.token:
            response = JSONResponse({"detail": "无效或缺失的 API Token（X-API-Token 头）"}, status_code=401)
            await response(scope, receive, send)
            return
        await self.app(scope, receive, send)


@asynccontextmanager
async def lifespan(app: FastAPI):
    await manager.start_workers()
    yield
    await manager.stop_workers()


async def _static_no_cache(request, call_next):
    """静态资源禁用启发式缓存：允许浏览器本地存副本，但每次须带 etag 回源校验，
    保证界面更新后局域网用户刷新即得新版（304 响应开销极小）。"""
    response = await call_next(request)
    if not request.url.path.startswith("/api"):
        response.headers["Cache-Control"] = "no-cache"
    return response


def create_app() -> FastAPI:
    verify_code.install_hook()
    app = FastAPI(title="social-auto-upload Web", lifespan=lifespan)
    # 局域网工具：允许任意来源访问（无鉴权，仅在可信内网使用）
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )
    token = os.environ.get("SAU_WEB_TOKEN", "").strip()
    if token:
        app.add_middleware(TokenAuthMiddleware, token=token)
    app.include_router(router)
    app.middleware("http")(_static_no_cache)
    if STATIC_DIR.exists():
        app.mount("/", StaticFiles(directory=str(STATIC_DIR), html=True), name="webui")
    return app


app = create_app()


def main() -> None:
    parser = argparse.ArgumentParser(prog="sau-web", description="social-auto-upload 局域网 Web 管理界面")
    parser.add_argument("--host", default=os.environ.get("SAU_WEB_HOST", DEFAULT_HOST))
    parser.add_argument("--port", type=int, default=int(os.environ.get("SAU_WEB_PORT", DEFAULT_PORT)))
    args = parser.parse_args()

    import uvicorn

    uvicorn.run(app, host=args.host, port=args.port, log_level="info")


if __name__ == "__main__":
    main()
