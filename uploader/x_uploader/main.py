# -*- coding: utf-8 -*-
"""X（Twitter）视频发帖——浏览器自动化。

被墙环境必须在 conf.py 配置代理（DEFAULT_PROXY 或 PROXY_MAP["x"]）。

注意：非 Premium 账号网页上传视频时长上限约 2 分 20 秒，超限会被前端拦截。

选择器说明：X 的 data-testid 相对稳定，集中在 LOCATORS；如改版失效改这里。
"""
from __future__ import annotations

import asyncio
import os

from patchright.async_api import Playwright, async_playwright

from conf import LOCAL_CHROME_PATH
from utils.base_social_media import set_init_script
from utils.log import x_logger
from utils.network import get_platform_proxy

LAUNCH_ARGS = ["--no-sandbox", "--disable-blink-features=AutomationControlled", "--lang en-GB"]

# 登录态 cookie：auth_token 出现即已登录
SESSION_COOKIE = "auth_token"

LOCATORS = {
    # 登录态判断（待实测校准）
    "login_button": '[data-testid="loginButton"]',
    # 发帖入口（直达 compose 页会自动弹出编辑器）
    "compose_url": "https://x.com/compose/post",
    "file_input": 'input[data-testid="fileInput"]',
    "text_box": 'div[data-testid="tweetTextarea_0"]',
    "post_button": '[data-testid="tweetButton"]',
    "schedule_toggle": 'button[data-testid="addButton"]',
}


def _build_login_result(success: bool, status: str, message: str, account_file: str) -> dict:
    return {"success": success, "status": status, "message": message, "account_file": str(account_file)}


def _launch_kwargs(headless: bool) -> dict:
    proxy = get_platform_proxy("x")
    return {
        "headless": headless,
        "channel": None if LOCAL_CHROME_PATH else "chromium",
        "executable_path": LOCAL_CHROME_PATH or None,
        "args": LAUNCH_ARGS,
        "proxy": {"server": proxy} if proxy else None,
    }


async def _is_logged_out(page) -> bool:
    if "x.com/login" in page.url or "twitter.com/login" in page.url:
        return True
    try:
        return bool(await page.locator(LOCATORS["login_button"]).count())
    except Exception:
        return False


async def cookie_auth(account_file):
    for _attempt in range(3):
        async with async_playwright() as playwright:
            browser = await playwright.chromium.launch(**_launch_kwargs(headless=True))
            try:
                context = await browser.new_context(storage_state=account_file)
                context = await set_init_script(context)
                page = await context.new_page()
                await page.goto("https://x.com/home", wait_until="domcontentloaded", timeout=90000)
                await page.wait_for_timeout(3000)
                if await _is_logged_out(page):
                    x_logger.error("[+] cookie expired")
                    return False
                x_logger.success("[+] cookie valid")
                return True
            except Exception:
                pass
            finally:
                await browser.close()
    return False


async def x_setup(account_file, handle=False, return_detail=False, qrcode_callback=None, headless: bool = False):
    if not os.path.exists(account_file) or not await cookie_auth(account_file):
        if not handle:
            result = _build_login_result(False, "cookie_invalid", "cookie文件不存在或已失效", account_file)
            return result if return_detail else False
        result = await get_x_cookie(account_file, headless=headless)
        return result if return_detail else result["success"]

    result = _build_login_result(True, "cookie_valid", "cookie有效", account_file)
    return result if return_detail else True


async def get_x_cookie(account_file, headless: bool = False):
    """交互式登录：本地有显示器的环境弹出浏览器，用户手动完成（用户名/密码 + 2FA），轮询 auth_token。"""
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(**_launch_kwargs(headless=headless))
        try:
            context = await browser.new_context()
            context = await set_init_script(context)
            page = await context.new_page()
            await page.goto("https://x.com/login", wait_until="domcontentloaded", timeout=90000)
            x_logger.info("[+] 请在打开的浏览器窗口里完成 X 登录（最长等待 5 分钟）…")
            for _ in range(150):
                await asyncio.sleep(2)
                cookies = await context.cookies()
                if any(c["name"] == SESSION_COOKIE and c.get("value") for c in cookies):
                    await context.storage_state(path=account_file)
                    x_logger.success("[+] 登录成功，cookie 已保存")
                    return _build_login_result(True, "login_success", "登录成功，cookie已保存", account_file)
            return _build_login_result(False, "login_timeout", "等待登录超时（5分钟）", account_file)
        except Exception as exc:
            return _build_login_result(False, "login_error", f"登录过程出错: {exc}", account_file)
        finally:
            await browser.close()


class XPost:
    def __init__(self, title, file_path, tags, account_file, debug: bool = True, headless: bool = True):
        self.title = title
        self.file_path = file_path
        self.tags = tags or []
        self.account_file = account_file
        self.debug = debug
        self.headless = headless

    async def upload(self, playwright: Playwright) -> None:
        browser = await playwright.chromium.launch(**_launch_kwargs(headless=self.headless))
        context = await browser.new_context(storage_state=self.account_file)
        page = await context.new_page()

        x_logger.info(f"[+] 开始发帖: {self.title}")
        await page.goto(LOCATORS["compose_url"], wait_until="domcontentloaded", timeout=90000)
        await page.wait_for_timeout(3000)

        # 文字（X 无独立标题概念，标题+标签合成正文）
        text_box = page.locator(LOCATORS["text_box"]).first
        await text_box.wait_for(state="visible", timeout=30000)
        await text_box.click()
        text = self.title + ("\n" + " ".join(f"#{t}" for t in self.tags) if self.tags else "")
        await page.keyboard.insert_text(text)

        # 附件视频（隐藏 input[type=file]）
        file_input = page.locator(LOCATORS["file_input"]).first
        await file_input.wait_for(state="attached", timeout=30000)
        await file_input.set_input_files(self.file_path)

        # 等待上传完成：Post 按钮从禁用变为可用（超长视频会被前端拦截，等待中暴露错误）
        for _ in range(90):
            await page.wait_for_timeout(2000)
            post_button = page.locator(LOCATORS["post_button"]).first
            if await post_button.count() and await post_button.is_enabled():
                break
        else:
            raise RuntimeError("等待 X 视频上传超时（3 分钟）")

        await page.locator(LOCATORS["post_button"]).first.click()

        # 等待编辑器关闭 = 发布提交成功
        for _ in range(30):
            await page.wait_for_timeout(1000)
            if not await page.locator(LOCATORS["text_box"]).count():
                x_logger.success("[+] 发布流程完成（请到 App 内确认实际状态）")
                break
        else:
            raise RuntimeError("发布后编辑器未关闭，无法确认发布状态")

        await context.storage_state(path=self.account_file)
        await asyncio.sleep(2)
        await context.close()
        await browser.close()

    async def main(self):
        async with async_playwright() as playwright:
            await self.upload(playwright)
