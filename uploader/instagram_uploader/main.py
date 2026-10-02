# -*- coding: utf-8 -*-
"""Instagram（Reels/帖子）上传——浏览器自动化。

被墙环境必须在 conf.py 配置代理（DEFAULT_PROXY 或 PROXY_MAP["instagram"]）。

选择器说明：Meta 系页面改版频繁，全部集中在 LOCATORS，标注「待实测校准」的
选择器基于已知页面结构编写，首次真实使用后如失效只需改这里。
"""
from __future__ import annotations

import asyncio
import os

from patchright.async_api import Playwright, async_playwright

from conf import LOCAL_CHROME_PATH
from utils.base_social_media import set_init_script
from utils.log import instagram_logger
from utils.network import get_platform_proxy

LAUNCH_ARGS = ["--no-sandbox", "--disable-blink-features=AutomationControlled", "--lang en-GB"]

# 会话 cookie：Instagram 登录成功后会出现 sessionid
SESSION_COOKIE = "sessionid"

LOCATORS = {
    # 登录态判断：登录表单出现即未登录（待实测校准）
    "login_form": 'form[id="loginForm"], form[action*="login"]',
    # 创作入口：直接进选择文件页
    "create_url": "https://www.instagram.com/create/select/",
    "select_from_computer": 'button:has-text("Select from computer"), button:has-text("从计算机中选择")',
    # 步骤跳转按钮
    "next_button": 'button:has-text("Next"), button:has-text("下一步")',
    "share_button": 'button:has-text("Share"), button:has-text("分享")',
    # 文案输入：新版本是 contenteditable，旧版本是 textarea（待实测校准）
    "caption_input": 'div[contenteditable="true"][aria-label*="caption" i], textarea[aria-label*="caption" i]',
}


def _build_login_result(success: bool, status: str, message: str, account_file: str) -> dict:
    return {"success": success, "status": status, "message": message, "account_file": str(account_file)}


def _launch_kwargs(headless: bool) -> dict:
    proxy = get_platform_proxy("instagram")
    return {
        "headless": headless,
        "channel": None if LOCAL_CHROME_PATH else "chromium",
        "executable_path": LOCAL_CHROME_PATH or None,
        "args": LAUNCH_ARGS,
        "proxy": {"server": proxy} if proxy else None,
    }


async def _is_logged_out(page) -> bool:
    if "/accounts/login" in page.url:
        return True
    try:
        return bool(await page.locator(LOCATORS["login_form"]).count())
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
                await page.goto("https://www.instagram.com/", wait_until="domcontentloaded", timeout=90000)
                await page.wait_for_timeout(3000)
                if await _is_logged_out(page):
                    instagram_logger.error("[+] cookie expired")
                    return False
                instagram_logger.success("[+] cookie valid")
                return True
            except Exception:
                pass
            finally:
                await browser.close()
    return False


async def instagram_setup(account_file, handle=False, return_detail=False, qrcode_callback=None, headless: bool = False):
    if not os.path.exists(account_file) or not await cookie_auth(account_file):
        if not handle:
            result = _build_login_result(False, "cookie_invalid", "cookie文件不存在或已失效", account_file)
            return result if return_detail else False
        result = await get_instagram_cookie(account_file, headless=headless)
        return result if return_detail else result["success"]

    result = _build_login_result(True, "cookie_valid", "cookie有效", account_file)
    return result if return_detail else True


async def get_instagram_cookie(account_file, headless: bool = False):
    """交互式登录：本地有显示器的环境弹出浏览器，用户手动完成（含 2FA），轮询 sessionid。"""
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(**_launch_kwargs(headless=headless))
        try:
            context = await browser.new_context()
            context = await set_init_script(context)
            page = await context.new_page()
            await page.goto("https://www.instagram.com/accounts/login/", wait_until="domcontentloaded", timeout=90000)
            instagram_logger.info("[+] 请在打开的浏览器窗口里完成 Instagram 登录（最长等待 5 分钟）…")
            for _ in range(150):
                await asyncio.sleep(2)
                cookies = await context.cookies()
                if any(c["name"] == SESSION_COOKIE and c.get("value") for c in cookies):
                    await context.storage_state(path=account_file)
                    instagram_logger.success("[+] 登录成功，cookie 已保存")
                    return _build_login_result(True, "login_success", "登录成功，cookie已保存", account_file)
            return _build_login_result(False, "login_timeout", "等待登录超时（5分钟）", account_file)
        except Exception as exc:
            return _build_login_result(False, "login_error", f"登录过程出错: {exc}", account_file)
        finally:
            await browser.close()


class InstagramVideo:
    def __init__(self, title, file_path, tags, account_file, thumbnail_path=None,
                 debug: bool = True, headless: bool = True):
        self.title = title
        self.file_path = file_path
        self.tags = tags or []
        self.thumbnail_path = thumbnail_path
        self.account_file = account_file
        self.debug = debug
        self.headless = headless

    async def _caption_text(self) -> str:
        parts = [self.title]
        if self.tags:
            parts.append(" ".join(f"#{tag}" for tag in self.tags))
        return "\n".join(p for p in parts if p)

    async def _fill_caption(self, page):
        caption = await self._caption_text()
        box = page.locator(LOCATORS["caption_input"]).first
        await box.wait_for(state="visible", timeout=20000)
        await box.click()
        await page.keyboard.insert_text(caption)

    async def upload(self, playwright: Playwright) -> None:
        browser = await playwright.chromium.launch(**_launch_kwargs(headless=self.headless))
        context = await browser.new_context(storage_state=self.account_file)
        page = await context.new_page()

        instagram_logger.info(f"[+] 开始上传: {self.title}")
        await page.goto(LOCATORS["create_url"], wait_until="domcontentloaded", timeout=90000)

        # 选择文件
        select_button = page.locator(LOCATORS["select_from_computer"]).first
        await select_button.wait_for(state="visible", timeout=30000)
        async with page.expect_file_chooser() as fc_info:
            await select_button.click()
        file_chooser = await fc_info.value
        await file_chooser.set_files(self.file_path)

        # 裁剪/滤镜步骤：连续点 Next 直到出现文案输入或 Share
        for _ in range(4):
            await page.wait_for_timeout(2000)
            if await page.locator(LOCATORS["caption_input"]).count():
                break
            if await page.locator(LOCATORS["share_button"]).count():
                break
            next_button = page.locator(LOCATORS["next_button"]).last
            if await next_button.count() and await next_button.is_enabled():
                await next_button.click()
            else:
                break

        # 填文案（标题 + 话题标签）
        if await page.locator(LOCATORS["caption_input"]).count():
            await self._fill_caption(page)

        # 发布
        share_button = page.locator(LOCATORS["share_button"]).first
        await share_button.wait_for(state="visible", timeout=30000)
        async with page.expect_navigation(wait_until="domcontentloaded", timeout=60000):
            await share_button.click()
        instagram_logger.success("[+] 发布流程完成（请到 App 内确认实际状态）")

        await context.storage_state(path=self.account_file)
        await asyncio.sleep(2)
        await context.close()
        await browser.close()

    async def main(self):
        async with async_playwright() as playwright:
            await self.upload(playwright)
