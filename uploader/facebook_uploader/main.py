# -*- coding: utf-8 -*-
"""Facebook（Reels）上传——浏览器自动化。

被墙环境必须在 conf.py 配置代理（DEFAULT_PROXY 或 PROXY_MAP["facebook"]）。

选择器说明：Meta 系页面改版频繁，全部集中在 LOCATORS，标注「待实测校准」的
选择器基于已知页面结构编写，首次真实使用后如失效只需改这里。
"""
from __future__ import annotations

import asyncio
import os

from patchright.async_api import Playwright, async_playwright

from conf import LOCAL_CHROME_PATH
from utils.base_social_media import set_init_script
from utils.log import facebook_logger
from utils.network import get_platform_proxy

LAUNCH_ARGS = ["--no-sandbox", "--disable-blink-features=AutomationControlled", "--lang en-GB"]

# 登录态 cookie：c_user（用户 id）与 xs（会话签名）同时存在视为已登录
SESSION_COOKIES = ("c_user", "xs")

LOCATORS = {
    # 登录态判断：登录表单出现即未登录（待实测校准）
    "login_form": 'form[action*="login"], input#email',
    # Reels 创作入口
    "composer_url": "https://www.facebook.com/reels/composer/",
    # composer 里的隐藏文件输入（FB 系惯用 input[type=file]，无需文件对话框）
    "file_input": 'input[type="file"][accept*="video"], input[type="file"]',
    # 文案输入（contenteditable，aria-label 多语言，宽松匹配）
    "caption_input": 'div[role="textbox"][contenteditable="true"]',
    # 发布按钮（待实测校准）
    "post_button": 'div[role="button"][aria-label*="Post" i]:not([aria-disabled="true"]), div[role="dialog"] div[role="button"]:has-text("Post")',
}


def _build_login_result(success: bool, status: str, message: str, account_file: str) -> dict:
    return {"success": success, "status": status, "message": message, "account_file": str(account_file)}


def _launch_kwargs(headless: bool) -> dict:
    proxy = get_platform_proxy("facebook")
    return {
        "headless": headless,
        "channel": None if LOCAL_CHROME_PATH else "chromium",
        "executable_path": LOCAL_CHROME_PATH or None,
        "args": LAUNCH_ARGS,
        "proxy": {"server": proxy} if proxy else None,
    }


async def _is_logged_out(page) -> bool:
    if "login" in page.url and "facebook.com/login" in page.url:
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
                await page.goto("https://www.facebook.com/", wait_until="domcontentloaded", timeout=90000)
                await page.wait_for_timeout(3000)
                if await _is_logged_out(page):
                    facebook_logger.error("[+] cookie expired")
                    return False
                facebook_logger.success("[+] cookie valid")
                return True
            except Exception:
                pass
            finally:
                await browser.close()
    return False


async def facebook_setup(account_file, handle=False, return_detail=False, qrcode_callback=None, headless: bool = False):
    if not os.path.exists(account_file) or not await cookie_auth(account_file):
        if not handle:
            result = _build_login_result(False, "cookie_invalid", "cookie文件不存在或已失效", account_file)
            return result if return_detail else False
        result = await get_facebook_cookie(account_file, headless=headless)
        return result if return_detail else result["success"]

    result = _build_login_result(True, "cookie_valid", "cookie有效", account_file)
    return result if return_detail else True


async def get_facebook_cookie(account_file, headless: bool = False):
    """交互式登录：本地有显示器的环境弹出浏览器，用户手动完成（含 2FA），轮询会话 cookie。"""
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(**_launch_kwargs(headless=headless))
        try:
            context = await browser.new_context()
            context = await set_init_script(context)
            page = await context.new_page()
            await page.goto("https://www.facebook.com/login", wait_until="domcontentloaded", timeout=90000)
            facebook_logger.info("[+] 请在打开的浏览器窗口里完成 Facebook 登录（最长等待 5 分钟）…")
            for _ in range(150):
                await asyncio.sleep(2)
                cookies = await context.cookies()
                names = {c["name"] for c in cookies}
                if all(name in names for name in SESSION_COOKIES):
                    await context.storage_state(path=account_file)
                    facebook_logger.success("[+] 登录成功，cookie 已保存")
                    return _build_login_result(True, "login_success", "登录成功，cookie已保存", account_file)
            return _build_login_result(False, "login_timeout", "等待登录超时（5分钟）", account_file)
        except Exception as exc:
            return _build_login_result(False, "login_error", f"登录过程出错: {exc}", account_file)
        finally:
            await browser.close()


class FacebookReel:
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

        facebook_logger.info(f"[+] 开始上传 Reel: {self.title}")
        await page.goto(LOCATORS["composer_url"], wait_until="domcontentloaded", timeout=90000)
        await page.wait_for_timeout(3000)

        # 文件直传：composer 里的隐藏 input[type=file]
        file_input = page.locator(LOCATORS["file_input"]).first
        await file_input.wait_for(state="attached", timeout=30000)
        await file_input.set_input_files(self.file_path)

        # 等待上传完成（进度条消失/预览出现，宽松等待）
        for _ in range(90):
            await page.wait_for_timeout(2000)
            caption_box = page.locator(LOCATORS["caption_input"])
            if await caption_box.count():
                break
        else:
            raise RuntimeError("等待 Facebook 上传预览超时（3 分钟）")

        # 填文案
        caption = self.title + ("\n" + " ".join(f"#{t}" for t in self.tags) if self.tags else "")
        await caption_box.first.click()
        await page.keyboard.insert_text(caption)

        # 发布（Post 按钮在上传完成前是禁用的，等待其可用）
        for _ in range(60):
            post_button = page.locator(LOCATORS["post_button"]).first
            if await post_button.count() and await post_button.is_enabled():
                break
            await page.wait_for_timeout(2000)
        else:
            raise RuntimeError("等待 Facebook 发布按钮可用超时（2 分钟）")
        await post_button.click()
        facebook_logger.success("[+] 发布流程完成（请到 App 内确认实际状态）")

        await context.storage_state(path=self.account_file)
        await asyncio.sleep(2)
        await context.close()
        await browser.close()

    async def main(self):
        async with async_playwright() as playwright:
            await self.upload(playwright)
