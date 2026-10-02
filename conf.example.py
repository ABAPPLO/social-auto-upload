from pathlib import Path

BASE_DIR = Path(__file__).parent.resolve()
XHS_SERVER = "http://127.0.0.1:11901"  # only used by xhs-related flows
LOCAL_CHROME_PATH = ""  # optional, e.g. C:/Program Files/Google/Chrome/Application/chrome.exe
LOCAL_CHROME_HEADLESS = True  # default headless behavior for uploader/examples
DEBUG_MODE = True  # default debug behavior
# Optional proxy for the YouTube uploader. Where youtube.com is blocked, direct
# connections time out and the (patchright) chromium does NOT use the system proxy.
# Point this at your local proxy port, e.g. "http://127.0.0.1:7890". None = no proxy.
YT_PROXY = None
# Same for TikTok where tiktok.com is blocked (TK_PROXY, e.g. "http://127.0.0.1:7890").
TK_PROXY = None
# Overseas platforms proxy (instagram/facebook/x/...): PROXY_MAP per-platform
# overrides > legacy YT_PROXY/TK_PROXY > DEFAULT_PROXY fallback.
# Example:
#   DEFAULT_PROXY = "http://127.0.0.1:7890"
#   PROXY_MAP = {"instagram": "http://127.0.0.1:7891"}
DEFAULT_PROXY = None
PROXY_MAP = {}
