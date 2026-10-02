import asyncio
import time
from functools import wraps


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
        DEFAULT_PROXY = "http://127.0.0.1:7890"          # 所有海外平台默认
        PROXY_MAP = {"instagram": "http://127.0.0.1:7891"}  # 个别平台单独覆盖
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
