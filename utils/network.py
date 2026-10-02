import asyncio
import json
import re
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime
from functools import wraps
from pathlib import Path


def async_retry(timeout=60, max_retries=None):
    def decorator(func):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            start_time = time.time()
            attempts = 0
            while True:
                try:
                    return await func(*args, **kwargs)
                except Exception as e:
                    attempts += 1
                    if max_retries is not None and attempts >= max_retries:
                        print(f"Reached maximum retries of {max_retries}.")
                        raise Exception(f"Failed after {max_retries} retries.") from e
                    if time.time() - start_time > timeout:
                        print(f"Function timeout after {timeout} seconds.")
                        raise TimeoutError(f"Function execution exceeded {timeout} seconds timeout.") from e
                    print(f"Attempt {attempts} failed: {e}. Retrying...")
                    await asyncio.sleep(1)  # Sleep to avoid tight loop or provide backoff logic here

        return wrapper

    return decorator

def get_platform_proxy(platform: str):
    """海外平台的代理解析：PROXY_MAP 按平台覆盖 > 旧字段 YT_PROXY/TK_PROXY > DEFAULT_PROXY。

    conf.py 配置示例：
        DEFAULT_PROXY = "http://<代理机IP>:7890"          # 所有海外平台默认
        PROXY_MAP = {"instagram": "http://<代理机IP>:7891"}  # 个别平台单独覆盖
    旧字段 YT_PROXY / TK_PROXY 继续生效（优先级低于 PROXY_MAP）。
    """
    try:
        from conf import PROXY_MAP
    except ImportError:
        PROXY_MAP = {}
    if platform in PROXY_MAP:
        return PROXY_MAP[platform]

    legacy_names = {"youtube": "YT_PROXY", "tiktok": "TK_PROXY"}
    legacy_attr = legacy_names.get(platform)
    if legacy_attr:
        try:
            from conf import BASE_DIR as _BASE  # noqa: F401 - 探测 conf 可导入
            import conf as _conf
            value = getattr(_conf, legacy_attr, None)
            if value:
                return value
        except ImportError:
            pass

    try:
        from conf import DEFAULT_PROXY
        return DEFAULT_PROXY
    except ImportError:
        return None


# ---------------------------------------------------------------------------
# 代理出口 IP 预检：海外平台上传前确认代理可用，并跟踪出口 IP 变化。
# 出口 IP 突变是账号风控的高危信号（平台视为环境跳变），变更时打告警日志。
# ---------------------------------------------------------------------------

IP_CHECK_URLS = ("http://ipinfo.io/ip", "https://api.ipify.org")
# 代理自身返回 502/504 = 代理可达但上游节点全部失效
_PROXY_UPSTREAM_DEAD_CODES = {502, 504}
_IP_RE = re.compile(r"^\d{1,3}(?:\.\d{1,3}){3}$")


class ProxyCheckError(RuntimeError):
    """代理预检失败（连不上代理，或上游节点失效），应在上传前快速失败。"""


@dataclass
class ProxyCheckResult:
    reachable: bool       # 代理是否可用于出海
    exit_ip: str | None   # 本次出口 IP；查询失败时为 None
    error: str | None     # 不可达原因 / 出口 IP 查询失败原因


def _proxy_opener(proxy_url: str):
    # 显式指定代理，不读环境变量里的 http_proxy，避免预检链路与预期不符
    return urllib.request.build_opener(
        urllib.request.ProxyHandler({"http": proxy_url, "https": proxy_url})
    )


def check_proxy(proxy_url: str, timeout: float = 5.0) -> ProxyCheckResult:
    """通过代理请求公网 IP 服务，判断代理可用性并取出口 IP。

    reachable=False 表示代理不可用（连不上，或代理报 502/504 上游失效），
    此时上传必然长时间超时，应立即中止；reachable=True 但 exit_ip=None 表示
    代理可用、只是 IP 服务没查成（如限流），只告警不阻断。
    """
    last_error = None
    for url in IP_CHECK_URLS:
        try:
            with _proxy_opener(proxy_url).open(url, timeout=timeout) as resp:
                body = resp.read(64).decode("utf-8", "ignore").strip()
        except urllib.error.HTTPError as exc:
            if exc.code in _PROXY_UPSTREAM_DEAD_CODES:
                return ProxyCheckResult(False, None, f"代理返回 HTTP {exc.code}（上游节点失效）")
            last_error = f"{url} 返回 HTTP {exc.code}"
            continue
        except urllib.error.URLError as exc:
            return ProxyCheckResult(False, None, f"无法连接代理: {exc.reason}")
        except OSError as exc:
            return ProxyCheckResult(False, None, f"无法连接代理: {exc}")
        candidate = body.split()[0] if body else ""
        if _IP_RE.match(candidate):
            return ProxyCheckResult(True, candidate, None)
        last_error = f"{url} 返回无法识别的内容"
    return ProxyCheckResult(True, None, last_error)


def proxy_state_file() -> Path:
    try:
        from conf import BASE_DIR
        return Path(BASE_DIR) / "proxy_exit_state.json"
    except ImportError:
        return Path("proxy_exit_state.json")


def load_proxy_exit_state(state_file: Path | None = None) -> dict:
    path = Path(state_file) if state_file else proxy_state_file()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _save_proxy_exit_state(state: dict, state_file: Path | None = None) -> None:
    path = Path(state_file) if state_file else proxy_state_file()
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def record_exit_ip(proxy_url: str, exit_ip: str, state_file: Path | None = None) -> dict:
    """记录代理最近一次上传的出口 IP，返回 {"changed": bool, "previous_ip": str | None}。"""
    state = load_proxy_exit_state(state_file)
    entry = state.get(proxy_url, {}) if isinstance(state.get(proxy_url), dict) else {}
    previous_ip = entry.get("exit_ip")
    changed = previous_ip is not None and previous_ip != exit_ip
    now = datetime.now().isoformat(timespec="seconds")
    if changed:
        entry["previous_exit_ip"] = previous_ip
        entry["changed_at"] = now
    entry["exit_ip"] = exit_ip
    entry["updated_at"] = now
    state[proxy_url] = entry
    _save_proxy_exit_state(state, state_file)
    return {"changed": changed, "previous_ip": previous_ip}


def _platform_logger(platform: str):
    names = {
        "youtube": "youtube_logger",
        "tiktok": "tiktok_logger",
        "instagram": "instagram_logger",
        "facebook": "facebook_logger",
        "x": "x_logger",
    }
    attr = names.get(platform)
    if not attr:
        return None
    try:
        from utils import log as _log
        return getattr(_log, attr)
    except Exception:
        return None


def ensure_proxy_ready(platform: str) -> ProxyCheckResult:
    """海外平台上传前预检：代理不可用抛 ProxyCheckError 快速失败；出口 IP 变化打告警。

    未配置代理（国内平台或直连环境）直接返回，不发任何网络请求。
    出口 IP 状态记录在 BASE_DIR/proxy_exit_state.json，按代理地址区分。
    """
    proxy = get_platform_proxy(platform)
    if not proxy:
        return ProxyCheckResult(True, None, None)
    logger = _platform_logger(platform)
    result = check_proxy(proxy)
    if not result.reachable:
        message = (
            f"[{platform}] 代理 {proxy} 不可用：{result.error}。已在启动浏览器前中止，"
            f"请检查代理机是否在线、节点是否可用（curl -x {proxy} http://ipinfo.io/ip）。"
        )
        if logger:
            logger.error(message)
        raise ProxyCheckError(message)
    if result.exit_ip is None:
        if logger:
            logger.warning(f"[{platform}] 代理 {proxy} 可达，但未能获取出口 IP（{result.error}），继续上传")
        return result
    change = record_exit_ip(proxy, result.exit_ip)
    if logger:
        logger.info(f"[{platform}] 代理 {proxy} 出口 IP: {result.exit_ip}")
        if change["changed"]:
            logger.warning(
                f"[{platform}] 代理出口 IP 已变化：{change['previous_ip']} → {result.exit_ip}。"
                "出口 IP 突变是账号风控的高危信号，请固定代理节点，并保证账号登录/养号与上传走同一条链路。"
            )
    return result
