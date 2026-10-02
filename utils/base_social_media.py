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
