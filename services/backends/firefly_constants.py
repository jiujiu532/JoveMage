"""Firefly 共享常量与 headers/proxy 工具。

UA / chrome124 / Express origin 等只在此维护；
CREDITS_API_KEY（余额 SunbreakWebUI1）与 GENERATE_API_KEY（生成 projectx_webapp）
用途不同，禁止合并。
"""

from __future__ import annotations

from typing import Any

DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/145.0.0.0 Safari/537.36"
)
DEFAULT_SEC_CH_UA = (
    '"Not:A-Brand";v="99", "Google Chrome";v="145", "Chromium";v="145"'
)
IMPERSONATE = "chrome124"

EXPRESS_ORIGIN = "https://new.express.adobe.com"
EXPRESS_REFERER = "https://new.express.adobe.com/"

# 生成接口用 projectx_webapp；余额专用 SunbreakWebUI1，勿混用
GENERATE_API_KEY = "projectx_webapp"
CREDITS_API_KEY = "SunbreakWebUI1"


def proxy_mapping(proxy: str | None) -> dict[str, str] | None:
    """proxy URL → curl_cffi/requests 的 proxies 映射；空则 None。"""
    text = str(proxy or "").strip()
    if not text:
        return None
    return {"http": text, "https": text}


def browser_headers() -> dict[str, str]:
    """浏览器伪装公共头（不含 Authorization / x-api-key）。"""
    return {
        "user-agent": DEFAULT_USER_AGENT,
        "origin": EXPRESS_ORIGIN,
        "referer": EXPRESS_REFERER,
        "accept-language": "en-US,en;q=0.9",
        "sec-ch-ua": DEFAULT_SEC_CH_UA,
        "sec-ch-ua-mobile": "?0",
        "sec-ch-ua-platform": '"Windows"',
        "sec-fetch-site": "cross-site",
        "sec-fetch-mode": "cors",
        "sec-fetch-dest": "empty",
    }


def auth_headers(
    token: str,
    *,
    api_key: str,
    content_type: str | None = None,
    extra: dict[str, str] | None = None,
) -> dict[str, str]:
    """browser_headers + Bearer + x-api-key；可选 content_type / extra 覆盖。"""
    headers = browser_headers()
    headers.update(
        {
            "Authorization": f"Bearer {str(token or '').strip()}",
            "x-api-key": str(api_key or ""),
            "accept": "*/*",
        }
    )
    if content_type is not None:
        headers["content-type"] = content_type
    if extra:
        headers.update(extra)
    return headers
