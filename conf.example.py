from pathlib import Path

BASE_DIR = Path(__file__).parent.resolve()
XHS_SERVER = "http://127.0.0.1:11901"  # only used by xhs-related flows
LOCAL_CHROME_PATH = ""  # optional, e.g. C:/Program Files/Google/Chrome/Application/chrome.exe
LOCAL_CHROME_HEADLESS = True  # default headless behavior for uploader/examples
DEBUG_MODE = True  # default debug behavior
# Optional proxy for overseas platforms (YouTube/TikTok/Instagram/Facebook/X).
# Where they are blocked, direct connections time out and the (patchright)
# chromium does NOT use the system proxy, so set it explicitly, e.g.
# "http://<proxy-host>:7890" (a LAN proxy machine works for all uploaders).
# Resolution order: PROXY_MAP per-platform > legacy YT_PROXY/TK_PROXY >
# DEFAULT_PROXY fallback. Before every upload the proxy is preflight-checked:
# unreachable proxies fail fast, and exit-IP changes are logged as a warning
# (exit-IP drift is a high-risk signal for account anti-abuse).
YT_PROXY = None
TK_PROXY = None
# Example:
#   DEFAULT_PROXY = "http://<proxy-host>:7890"
#   PROXY_MAP = {"instagram": "http://<other-proxy>:7890"}
DEFAULT_PROXY = None
PROXY_MAP = {}
