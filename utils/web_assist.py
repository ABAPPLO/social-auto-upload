# -*- coding: utf-8 -*-
"""远程人工协助：把登录等待页面的实时画面推给 Web 控制台，并转发点击/拖拽。

背景：服务器端 headless 登录时，平台经常在扫码确认后追加滑块/安全验证，
没人能看到和操作就只会等超时。uploader 在登录等待循环里持有 ManualAssist
并推帧上报验证状态；Web 后端（sau_webapp.assist.TaskAssist）实现该接口，
把前端画面上收到的点击/拖拽坐标转成真实鼠标事件打回页面。

依赖方向：uploader 只 import 本模块（协议 + 工具函数），不依赖 sau_webapp。
CLI 直接跑时不传 assist（NULL_ASSIST），全部方法为空操作。
"""
from __future__ import annotations

import asyncio
import base64
import random

# 推帧最小间隔（秒）。等待循环里按此节奏截图，局域网下 55 质量 JPEG 足够流畅。
FRAME_INTERVAL = 0.9

# 验证浮层的启发式特征：任一可见即认为"需要人工验证"。
VERIFY_SELECTORS = (
    '[class*="captcha" i]',
    '[id*="captcha" i]',
    'iframe[src*="captcha"]',
    '[class*="verification" i]',
    '[id*="verification" i]',
)
VERIFY_TEXTS = ("拖动滑块", "滑动验证", "请完成验证", "安全验证", "点击验证", "身份验证")

# 抖音身份验证组件（uc_verification_component）只认完整的 pointer/mouse 事件序列，
# 不认单纯 click；与 douyin_uploader._native_click 保持同一套派发脚本。
_POINT_EVENTS_SCRIPT = """({x, y}) => {
    const el = document.elementFromPoint(x, y);
    if (!el) return;
    const opts = {bubbles:true,cancelable:true,composed:true,clientX:x,clientY:y,view:window,pointerId:1,pointerType:'mouse',isPrimary:true,button:0,buttons:1};
    for (const t of ['pointerover','pointerenter','pointerdown','mousedown','pointerup','mouseup','click']) {
        const C = t.startsWith('pointer') ? PointerEvent : MouseEvent;
        try { el.dispatchEvent(new C(t, opts)); } catch(e){ try{ el.dispatchEvent(new MouseEvent(t,opts)); }catch(_){} }
    }
}"""


class ManualAssist:
    """uploader → Web 控制台的事件接口。默认实现全部为空操作（CLI 场景）。"""

    async def on_frame(self, data_url: str, page_url: str = "") -> None:
        """登录等待期间周期性上报页面截图（JPEG data URL）。"""

    async def on_verify_state(self, needed: bool, hint: str = "") -> None:
        """上报是否检测到滑块/安全验证浮层。"""

    def attach_page(self, page) -> None:
        """等待开始时把可交互的页面交给协助通道（供输入转发）。"""

    def detach_page(self) -> None:
        """等待结束（成功/超时/异常）时解除页面绑定。"""


class NullAssist(ManualAssist):
    """CLI 默认空实现：所有方法都是 no-op，等待循环零额外开销。"""


NULL_ASSIST = NullAssist()


async def capture_frame(page) -> str:
    """视口截图转 JPEG data URL。失败返回空串，调用方直接跳过这一帧。"""
    try:
        raw = await page.screenshot(type="jpeg", quality=55)
    except Exception:
        return ""
    if not raw:
        return ""
    return "data:image/jpeg;base64," + base64.b64encode(raw).decode("ascii")


async def viewport_size(page) -> tuple[int, int]:
    """取页面视口尺寸，用于把前端坐标夹取到合法范围。取不到返回 (0, 0)（不夹取）。"""
    size = getattr(page, "viewport_size", None) or {}
    width, height = size.get("width"), size.get("height")
    if width and height:
        return int(width), int(height)
    try:
        width, height = await page.evaluate("() => [window.innerWidth, window.innerHeight]")
        return int(width), int(height)
    except Exception:
        return 0, 0


def clamp_coord(value: float, maximum: int) -> float:
    """把前端送来的坐标夹进 [0, maximum]；maximum<=0 表示未知尺寸，原样放行。"""
    if maximum <= 0:
        return value
    return max(0.0, min(float(value), float(maximum)))


async def detect_verification(page) -> tuple[bool, str]:
    """启发式检测滑块/安全验证浮层，返回 (是否需要人工验证, 命中特征)。

    任何一步异常都当作"未检出"处理——检测只是给前端加提示，不能影响登录流程。
    """
    for selector in VERIFY_SELECTORS:
        try:
            locator = page.locator(selector)
            count = min(await locator.count(), 8)
        except Exception:
            continue
        for index in range(count):
            try:
                if await locator.nth(index).is_visible():
                    return True, selector
            except Exception:
                continue
    for text in VERIFY_TEXTS:
        try:
            marker = page.get_by_text(text, exact=False).first
            if await marker.count() and await marker.is_visible():
                return True, text
        except Exception:
            continue
    return False, ""


async def human_click(page, x: float, y: float) -> bool:
    """真人级点击：真实鼠标事件 + 完整 pointer 派发序列。返回是否成功。"""
    try:
        await page.mouse.move(x, y)
        await asyncio.sleep(0.12)
        await page.mouse.click(x, y)
        await asyncio.sleep(0.15)
        await page.evaluate(_POINT_EVENTS_SCRIPT, {"x": x, "y": y})
        return True
    except Exception:
        return False


async def human_drag(page, x1: float, y1: float, x2: float, y2: float) -> bool:
    """真人级拖拽：按 ease 曲线分步移动并带随机抖动，用于人工指定端点的滑块拖动。"""
    try:
        await page.mouse.move(x1, y1)
        await asyncio.sleep(0.15 + random.random() * 0.15)
        await page.mouse.down()
        steps = random.randint(18, 26)
        for index in range(1, steps + 1):
            t = index / steps
            ease = t * t * (3 - 2 * t)  # smoothstep：先加速后减速
            await page.mouse.move(
                x1 + (x2 - x1) * ease + random.uniform(-1.6, 1.6),
                y1 + (y2 - y1) * ease + random.uniform(-1.2, 1.2),
                steps=1,
            )
            await asyncio.sleep(random.uniform(0.008, 0.03))
        await page.mouse.move(x2, y2)
        await asyncio.sleep(random.uniform(0.05, 0.12))
        await page.mouse.up()
        return True
    except Exception:
        return False
