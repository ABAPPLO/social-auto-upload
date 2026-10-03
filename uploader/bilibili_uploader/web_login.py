# -*- coding: utf-8 -*-
"""Bilibili 的 Web 扫码登录：用伪终端（PTY）驱动 biliup 的交互式登录。

biliup 只有终端交互（菜单选择 + 终端二维码），但选中"扫码登录"后会把二维码
写成工作目录下的 qrcode.png。这里在 PTY 里代答菜单、监视该文件并推给 Web
控制台——用户在网页上扫码即可，全程不需要终端。cookie 文件由 biliup 自己写
入，格式天然匹配后续的 renew / upload。
"""
from __future__ import annotations

import asyncio
import base64
import os
import pty
import select
import shutil
import signal
import subprocess
import tempfile
import time
from pathlib import Path

from uploader.bilibili_uploader.runtime import ensure_biliup_binary, run_biliup_command

_LOGIN_TIMEOUT_SECONDS = 300  # 与其他平台的扫码等待时长对齐（5 分钟）


def _login_result(success: bool, status: str, message: str, account_file, data_url: str = "") -> dict:
    return {
        "success": success,
        "status": status,
        "message": message,
        "account_file": str(account_file),
        "qrcode": {"image_path": "", "image_data_url": data_url},
    }


def _png_data_url(path: Path) -> str:
    return "data:image/png;base64," + base64.b64encode(path.read_bytes()).decode("ascii")


def _stable_png_data_url(workdir: Path, pushed_mtime: float | None) -> tuple[str, float | None]:
    """qrcode.png 写完整（两次采样大小一致）才推送，返回 (data_url, mtime)。

    mtime 未变化时返回空串，避免每轮循环重复推送同一张图。
    """
    path = workdir / "qrcode.png"
    try:
        stat = path.stat()
    except OSError:
        return "", pushed_mtime
    if stat.st_mtime == pushed_mtime:
        return "", pushed_mtime
    first_size = stat.st_size
    time.sleep(0.4)
    try:
        stat_again = path.stat()
    except OSError:
        return "", pushed_mtime
    if stat_again.st_size != first_size or stat_again.st_mtime != stat.st_mtime:
        return "", pushed_mtime  # 仍在写入，下一轮再看
    return _png_data_url(path), stat.st_mtime


def _kill_process_group(proc: subprocess.Popen) -> None:
    try:
        os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
    except Exception:
        proc.kill()


def _drive_biliup_login(account_file: str, workdir: Path, qrcode_callback) -> dict:
    """在 PTY 中完成 biliup 登录的完整交互（阻塞，供线程调用）。"""
    binary = ensure_biliup_binary(force_check=False)
    master, slave = pty.openpty()
    env = {**os.environ, "TERM": "xterm-256color"}
    proc = subprocess.Popen(
        [str(binary), "-u", str(account_file), "login"],
        stdin=slave,
        stdout=slave,
        stderr=slave,
        cwd=str(workdir),
        env=env,
        preexec_fn=os.setsid,
        close_fds=True,
    )
    os.close(slave)
    output = b""
    pushed_mtime: float | None = None
    selected = False
    deadline = time.time() + _LOGIN_TIMEOUT_SECONDS
    timed_out = False
    try:
        while True:
            if proc.poll() is not None:
                break
            if time.time() > deadline:
                timed_out = True
                _kill_process_group(proc)
                break
            readable, _, _ = select.select([master], [], [], 0.5)
            if readable:
                try:
                    chunk = os.read(master, 65536)
                except OSError:
                    chunk = b""
                if chunk:
                    output += chunk

            if not selected:
                text = output.decode("utf-8", "replace")
                if "扫码登录" in text and "❯" in text:
                    # 菜单默认停在"短信登录"：下移一项选中"扫码登录"，回车确认
                    time.sleep(0.3)
                    os.write(master, b"\x1b[B")
                    time.sleep(0.2)
                    os.write(master, b"\r")
                    selected = True

            if selected:
                data_url, pushed_mtime = _stable_png_data_url(workdir, pushed_mtime)
                if data_url and qrcode_callback:
                    try:
                        qrcode_callback({"image_path": "", "image_data_url": data_url})
                    except Exception:
                        pass  # 二维码推送失败不致命：biliup 终端里也有一份
    finally:
        if proc.poll() is None:
            _kill_process_group(proc)
        try:
            os.close(master)
        except OSError:
            pass
        proc.wait()

    if timed_out:
        return _login_result(False, "timeout", "等待 Bilibili 扫码登录超时", account_file)
    if proc.returncode == 0 and Path(account_file).exists():
        return _login_result(True, "success", "Bilibili 扫码登录成功", account_file)
    tail = output.decode("utf-8", "replace")[-200:].replace("\n", " ").strip()
    return _login_result(False, "failed", f"biliup 登录失败({tail})" if tail else "biliup 登录失败", account_file)


async def bilibili_setup(account_file, handle=False, return_detail=False, qrcode_callback=None, headless=True):
    """统一登录入口：renew 校验 cookie → 无效且 handle=True 则 PTY 驱动扫码登录。"""
    account_path = Path(account_file)
    if account_path.exists():
        result = run_biliup_command(["-u", str(account_path), "renew"])
        if result.returncode == 0:
            ok = _login_result(True, "cookie_valid", "cookie 有效", account_file)
            return ok if return_detail else True

    if not handle:
        invalid = _login_result(False, "cookie_invalid", "cookie 文件不存在或已失效", account_file)
        return invalid if return_detail else False

    workdir = Path(tempfile.mkdtemp(prefix="biliup-login-"))
    try:
        result = await asyncio.to_thread(_drive_biliup_login, str(account_path), workdir, qrcode_callback)
    finally:
        shutil.rmtree(workdir, ignore_errors=True)
    return result if return_detail else result["success"]
