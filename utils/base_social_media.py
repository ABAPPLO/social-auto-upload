from pathlib import Path
from typing import List

from conf import BASE_DIR

SOCIAL_MEDIA_DOUYIN = "douyin"
SOCIAL_MEDIA_TENCENT = "tencent"
SOCIAL_MEDIA_TIKTOK = "tiktok"
SOCIAL_MEDIA_BILIBILI = "bilibili"
SOCIAL_MEDIA_KUAISHOU = "kuaishou"


def get_supported_social_media() -> List[str]:
    return [SOCIAL_MEDIA_DOUYIN, SOCIAL_MEDIA_TENCENT, SOCIAL_MEDIA_TIKTOK, SOCIAL_MEDIA_KUAISHOU]


def get_cli_action() -> List[str]:
    return ["upload", "login", "watch"]


async def set_init_script(context):
    stealth_js_path = Path(BASE_DIR / "utils/stealth.min.js")
    await context.add_init_script(path=stealth_js_path)
    # 与 new_browser_context 的 Windows UA 配套：JS 层把 navigator.platform 同步为
    # Win32。注意 patchright 1.58 实测 add_init_script 不执行（本段与其中的
    # stealth.min.js 均只在标准 playwright 下生效）；patchright 场景的 platform
    # 一致性由 _WindowsUaContext 的 CDP 覆盖保证，这里作为非 patchright 环境的兜底。
    await context.add_init_script(script=(
        "try{Object.defineProperty(Navigator.prototype,'platform',"
        "{get:()=>'Win32',configurable:true});}catch(e){}"
    ))
    return context


async def direct_chromium_launch(playwright, **kwargs):
    """国内平台专用：启动 chromium 并强制直连。

    Linux 上 chromium 默认读桌面代理设置（GNOME 手动代理/KDE/环境变量），
    若部署机恰好配置了系统代理，国内平台流量会从境外出口——这是明确的
    风控红旗。--no-proxy-server 让国内上传与桌面代理状态彻底解耦；
    海外平台不走此助手，由 get_platform_proxy 显式指定代理。
    """
    kwargs["args"] = [*kwargs.pop("args", []), "--no-proxy-server"]
    return await playwright.chromium.launch(**kwargs)


# 用浏览器真实版本号 + Windows 平台段生成 UA：UA 声称的 Chrome 版本与实际
# JS 引擎特征一致，避免"UA 版本穿帮"这一经典检测点。
_WINDOWS_UA_TEMPLATE = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/{version} Safari/537.36"
)


class _WindowsUaContext:
    """包装 BrowserContext：每个新页面经 CDP 原生覆盖 UA 与 navigator.platform。

    实测 patchright 1.58 的 add_init_script 不会执行（stealth.min.js 实际从未
    注入过），JS 层改 navigator.platform 行不通；CDP Emulation.setUserAgentOverride
    是浏览器原生级覆盖，UA 与 platform 同时一致生效，且先于任何导航应用。
    """

    def __init__(self, context, user_agent: str):
        self._context = context
        self._user_agent = user_agent

    def __getattr__(self, name):
        return getattr(self._context, name)

    async def new_page(self, **kwargs):
        page = await self._context.new_page(**kwargs)
        try:
            cdp = await self._context.new_cdp_session(page)
            await cdp.send(
                "Emulation.setUserAgentOverride",
                {"userAgent": self._user_agent, "platform": "Win32"},
            )
        except Exception:
            pass  # CDP 会话不可用时退回 new_context 的 UA 覆盖，仅 platform 保持原生
        return page


async def new_browser_context(browser, **kwargs):
    """统一的浏览器上下文：默认伪装为 Windows Chrome。

    部署机多为 Linux 服务器，原生 UA 的 "X11; Linux x86_64" 在各平台的设备
    管理里是罕见特征（抖音扫码确认页会直接显示 Linux）。固定为常见 Windows
    UA + Win32 platform 可降低异常度。
    重要：UA 一旦启用就长期固定，不要再更换——环境跳变本身是风控信号。
    """
    version = getattr(browser, "version", "")
    if isinstance(version, str) and version and "user_agent" not in kwargs:
        kwargs["user_agent"] = _WINDOWS_UA_TEMPLATE.format(version=version)
    context = await browser.new_context(**kwargs)
    if "user_agent" in kwargs:
        context = _WindowsUaContext(context, kwargs["user_agent"])
    return context
