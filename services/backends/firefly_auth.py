"""Adobe IMS 认证：cookie → access_token + profile/credits + JWT 工具。

移植自 adobe2api refresh_mgr / token_mgr 与 GPT2Image-Pro firefly-direct/auth.ts。
HTTP 走 curl_cffi impersonate=chrome124；余额接口 x-api-key 必须用 SunbreakWebUI1，
与生成用的 projectx_webapp 不同，勿混用。
"""

from __future__ import annotations

import base64
import json
import time
from typing import Any

from curl_cffi import requests as curl_requests

from utils.diagnostics import redact_auth_diagnostic
from utils.log import logger

IMS_CLIENT_ID = "projectx_webapp"
IMS_DEFAULT_SCOPE = "AdobeID,firefly_api,openid"
IMS_CHECK_URL = (
    "https://adobeid-na1.services.adobe.com/ims/check/v6/token"
    "?jslVersion=v2-v0.48.0-1-g1e322cb"
)
IMS_PROFILE_URLS = (
    "https://ims-na1.adobelogin.com/ims/profile/v1",
    "https://adobeid-na1.services.adobe.com/ims/profile/v1",
)
CREDITS_URL = "https://firefly.adobe.io/v1/credits/balance"

# 生成接口用 projectx_webapp；余额专用 SunbreakWebUI1
GENERATE_API_KEY = "projectx_webapp"
CREDITS_API_KEY = "SunbreakWebUI1"

_DEFAULT_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/145.0.0.0 Safari/537.36"
)
_IMPERSONATE = "chrome124"


def _proxy_kwargs(proxy: str | None) -> dict[str, Any]:
    text = str(proxy or "").strip()
    if not text:
        return {}
    return {"proxies": {"http": text, "https": text}}


def normalize_cookie(cookie: Any) -> str:
    """多种 cookie 输入归一为 "k=v; k=v" 串。

    支持：纯字符串、"Cookie: ..." 前缀、{cookies:[...]} / {cookie:...}、
    [{name,value}, ...] 数组。
    """
    if isinstance(cookie, str):
        text = cookie.strip()
        if text.lower().startswith("cookie:"):
            text = text.split(":", 1)[1].strip()
        return text

    value: Any = cookie
    if isinstance(cookie, dict):
        if isinstance(cookie.get("cookies"), list):
            value = cookie.get("cookies")
        elif cookie.get("cookie") is not None:
            value = cookie.get("cookie")
        else:
            return ""

    if isinstance(value, str):
        return value.strip()

    if isinstance(value, list):
        pairs: list[str] = []
        for item in value:
            if isinstance(item, str):
                txt = item.strip()
                if txt:
                    pairs.append(txt)
                continue
            if not isinstance(item, dict):
                continue
            name = str(item.get("name") or "").strip()
            val = str(item.get("value") or "").strip()
            if not name:
                continue
            pairs.append(f"{name}={val}")
        return "; ".join(pairs)

    return ""


def decode_jwt_payload(token: str) -> dict[str, Any]:
    """base64url 解 JWT 第二段；失败返回 {}。"""
    raw = str(token or "").strip()
    if not raw:
        return {}
    parts = raw.split(".")
    if len(parts) < 2:
        return {}
    payload_part = parts[1].strip()
    if not payload_part:
        return {}
    padding = (-len(payload_part)) % 4
    if padding:
        payload_part += "=" * padding
    try:
        decoded = base64.urlsafe_b64decode(payload_part.encode("ascii"))
        data = json.loads(decoded.decode("utf-8"))
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def decode_jwt_account_id(token: str) -> str:
    """JWT claims → user_id || aa_id || sub。"""
    claims = decode_jwt_payload(token)
    return str(
        claims.get("user_id") or claims.get("aa_id") or claims.get("sub") or ""
    ).strip()


def decode_jwt_exp(token: str) -> int | None:
    """JWT exp 或 created_at+expires_in（含毫秒归一）→ 秒级时间戳。"""
    claims = decode_jwt_payload(token)
    if not claims:
        return None

    exp = claims.get("exp")
    if isinstance(exp, (int, float)) and exp > 0:
        return int(exp)

    try:
        created_at = int(str(claims.get("created_at") or "").strip())
        expires_in = int(str(claims.get("expires_in") or "").strip())
    except (TypeError, ValueError):
        return None
    if created_at <= 0 or expires_in <= 0:
        return None

    # 毫秒 → 秒
    if created_at > 10_000_000_000:
        created_at = created_at // 1000
    if expires_in > 86400 * 2:
        expires_in = expires_in // 1000
    return created_at + expires_in


def is_token_expired(token: str, *, skew_seconds: int = 300) -> bool:
    """token 是否已过期（默认提前 300s）。无法判定 exp 时按未过期。"""
    exp = decode_jwt_exp(token)
    if exp is None:
        return False
    return exp - int(skew_seconds) <= int(time.time())


def refresh_access_token(cookie: str, *, proxy: str | None = None) -> dict[str, Any]:
    """Cookie → IMS access_token。返回 {access_token, expires_in, raw}。"""
    cookie_str = normalize_cookie(cookie)
    if not cookie_str:
        raise ValueError("cookie is required")

    headers = {
        "Accept": "*/*",
        "Accept-Language": "en-US,en;q=0.9",
        "Content-Type": "application/x-www-form-urlencoded;charset=UTF-8",
        "Cookie": cookie_str,
        "Origin": "https://new.express.adobe.com",
        "Referer": "https://new.express.adobe.com/",
        "User-Agent": _DEFAULT_UA,
    }
    form = {
        "client_id": IMS_CLIENT_ID,
        "guest_allowed": "true",
        "scope": IMS_DEFAULT_SCOPE,
    }

    try:
        resp = curl_requests.post(
            IMS_CHECK_URL,
            headers=headers,
            data=form,
            timeout=30,
            impersonate=_IMPERSONATE,
            **_proxy_kwargs(proxy),
        )
    except Exception as exc:
        logger.warning(
            "firefly IMS refresh network error: %s",
            redact_auth_diagnostic(str(exc))[:300],
        )
        raise RuntimeError(f"refresh request network error: {exc}") from exc

    if resp.status_code != 200:
        body = redact_auth_diagnostic((resp.text or "")[:200])
        raise RuntimeError(f"refresh request failed: {resp.status_code} {body}")

    try:
        data = resp.json()
    except Exception as exc:
        raise RuntimeError("refresh response is not valid json") from exc
    if not isinstance(data, dict):
        raise RuntimeError("refresh response is not valid json")

    access_token = str(data.get("access_token") or "").strip()
    if not access_token:
        raise RuntimeError("refresh response missing access_token")

    expires_raw = data.get("expires_in")
    try:
        expires_in = int(expires_raw) if expires_raw is not None else None
    except (TypeError, ValueError):
        expires_in = None

    return {
        "access_token": access_token,
        "expires_in": expires_in,
        "raw": data,
    }


def fetch_profile(
    access_token: str, *, proxy: str | None = None
) -> dict[str, str]:
    """GET ims/profile/v1 → {displayName, email, userId}；失败返回空字段 dict。"""
    token = str(access_token or "").strip()
    if not token:
        return {"displayName": "", "email": "", "userId": ""}

    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/json",
        "User-Agent": _DEFAULT_UA,
    }
    for url in IMS_PROFILE_URLS:
        try:
            resp = curl_requests.get(
                url,
                headers=headers,
                timeout=15,
                impersonate=_IMPERSONATE,
                **_proxy_kwargs(proxy),
            )
        except Exception:
            continue
        if resp.status_code != 200:
            continue
        try:
            data = resp.json()
        except Exception:
            continue
        if not isinstance(data, dict):
            continue
        display_name = str(
            data.get("displayName") or data.get("name") or data.get("fullName") or ""
        ).strip()
        email = str(data.get("email") or "").strip()
        user_id = str(data.get("userId") or data.get("authId") or "").strip()
        if display_name or email or user_id:
            return {
                "displayName": display_name,
                "email": email,
                "userId": user_id,
            }
    return {"displayName": "", "email": "", "userId": ""}


def fetch_credits(
    access_token: str,
    account_id: str,
    *,
    proxy: str | None = None,
) -> dict[str, Any]:
    """GET firefly credits/balance → {total, used, available, available_until}。

    x-api-key 必须是 SunbreakWebUI1（非 projectx_webapp）。
    """
    token = str(access_token or "").strip()
    aid = str(account_id or "").strip() or decode_jwt_account_id(token)
    if not token:
        raise RuntimeError("empty access token")
    if not aid:
        raise RuntimeError("missing account id")

    headers = {
        "Authorization": f"Bearer {token}",
        "x-api-key": CREDITS_API_KEY,
        "x-account-id": aid,
        "Origin": "https://new.express.adobe.com",
        "Referer": "https://new.express.adobe.com/",
        "Accept": "application/json",
        "Content-Type": "application/json",
        "User-Agent": _DEFAULT_UA,
    }
    try:
        resp = curl_requests.get(
            CREDITS_URL,
            headers=headers,
            timeout=20,
            impersonate=_IMPERSONATE,
            **_proxy_kwargs(proxy),
        )
    except Exception as exc:
        logger.warning(
            "firefly credits network error: %s",
            redact_auth_diagnostic(str(exc))[:300],
        )
        raise RuntimeError(f"credits request network error: {exc}") from exc

    if resp.status_code != 200:
        body = redact_auth_diagnostic((resp.text or "")[:200])
        raise RuntimeError(f"credits request failed: {resp.status_code} {body}")

    try:
        payload = resp.json()
    except Exception as exc:
        raise RuntimeError("credits response invalid json") from exc

    total_info = payload.get("total", {}) if isinstance(payload, dict) else {}
    quota = total_info.get("quota", {}) if isinstance(total_info, dict) else {}
    return {
        "total": quota.get("total"),
        "used": quota.get("used"),
        "available": quota.get("available"),
        "available_until": total_info.get("availableUntil"),
    }
