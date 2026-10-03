# -*- coding: utf-8 -*-
"""sau-web API 的最小 HTTP 客户端（MCP 工具层的唯一出口）。"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import httpx


class SauWebError(RuntimeError):
    """sau-web 返回非 2xx 或网络失败。message 直接面向 Agent 展示。"""

    def __init__(self, message: str, status_code: int = 0):
        super().__init__(message)
        self.status_code = status_code


def default_base_url() -> str:
    """默认指向本机 sau-web：显式 SAU_WEB_URL 优先，否则跟随服务的 HOST/PORT 变量。"""
    explicit = os.environ.get("SAU_WEB_URL")
    if explicit:
        return explicit.rstrip("/")
    host = os.environ.get("SAU_WEB_HOST", "127.0.0.1")
    port = os.environ.get("SAU_WEB_PORT", "8010")
    return f"http://{host}:{port}"


def default_token() -> str:
    return os.environ.get("SAU_WEB_TOKEN", "").strip()


class SauWebClient:
    def __init__(self, base_url: str | None = None, token: str | None = None, timeout: float = 30.0):
        self.base_url = (base_url or default_base_url()).rstrip("/")
        self.token = (token if token is not None else default_token())
        headers = {"X-API-Token": self.token} if self.token else {}
        self._client = httpx.Client(base_url=self.base_url, timeout=timeout, headers=headers)

    # ---- 基础请求 -----------------------------------------------------------

    def _request(self, method: str, path: str, **kwargs) -> Any:
        try:
            response = self._client.request(method, path, **kwargs)
        except httpx.HTTPError as exc:
            raise SauWebError(f"无法连接 sau-web（{self.base_url}）: {exc.__class__.__name__}: {exc}") from exc
        if response.status_code >= 400:
            try:
                detail = response.json().get("detail") or response.text
            except Exception:
                detail = response.text
            raise SauWebError(f"sau-web {response.status_code}: {detail}", response.status_code)
        if not response.content:
            return {}
        return response.json()

    def get(self, path: str, params: dict | None = None) -> Any:
        return self._request("GET", path, params=params)

    def post(self, path: str, json: dict | None = None, params: dict | None = None) -> Any:
        return self._request("POST", path, json=json, params=params)

    def delete(self, path: str) -> Any:
        return self._request("DELETE", path)

    def upload_file(self, path: str, file_path: str) -> Any:
        file = Path(file_path)
        if not file.is_file():
            raise SauWebError(f"本地文件不存在: {file_path}")
        with file.open("rb") as handle:
            return self._request("POST", path, files={"file": (file.name, handle)})
