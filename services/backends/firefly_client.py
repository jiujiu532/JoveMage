"""Adobe Firefly 3P 图像客户端：提交 → 轮询 → 下载；图生图参考图上传。

移植自 adobe2api adobe_client.generate 与 GPT2Image-Pro firefly-direct/client.ts。
Phase 1 文生图；Phase 2 增加 upload_image（storage/image）。
"""

from __future__ import annotations

import time
from typing import Any

from curl_cffi import requests as curl_requests

from services.backends.firefly_errors import (
    FireflyAuthError,
    FireflyQuotaExhausted,
    FireflyRequestError,
    FireflyUpstreamTemporary,
    is_retryable_status,
)
from utils.diagnostics import redact_auth_diagnostic
from utils.log import logger

GENERATE_URL = "https://firefly-3p.ff.adobe.io/v2/3p-images/generate-async"
UPLOAD_URL = "https://firefly-3p.ff.adobe.io/v2/storage/image"

DEFAULT_API_KEY = "projectx_webapp"
DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/145.0.0.0 Safari/537.36"
)
DEFAULT_SEC_CH_UA = (
    '"Not:A-Brand";v="99", "Google Chrome";v="145", "Chromium";v="145"'
)
_IMPERSONATE = "chrome124"

# 上传参考图允许的 Content-Type
ALLOWED_UPLOAD_MIMES = frozenset({"image/png", "image/jpeg", "image/webp"})
# 上传体积上限，与 fetch_image_bytes 默认 10MB 对齐
MAX_UPLOAD_IMAGE_BYTES = 10 * 1024 * 1024

# 451 回落用标准 requests（可选依赖；没有则继续 curl_cffi）
try:
    import requests as std_requests  # type: ignore
except Exception:  # pragma: no cover
    std_requests = None  # type: ignore


def _proxy_dict(proxy: str | None) -> dict[str, str] | None:
    text = str(proxy or "").strip()
    if not text:
        return None
    return {"http": text, "https": text}


def browser_headers() -> dict[str, str]:
    return {
        "user-agent": DEFAULT_USER_AGENT,
        "origin": "https://new.express.adobe.com",
        "referer": "https://new.express.adobe.com/",
        "accept-language": "en-US,en;q=0.9",
        "sec-ch-ua": DEFAULT_SEC_CH_UA,
        "sec-ch-ua-mobile": "?0",
        "sec-ch-ua-platform": '"Windows"',
        "sec-fetch-site": "cross-site",
        "sec-fetch-mode": "cors",
        "sec-fetch-dest": "empty",
    }


def submit_headers(access_token: str) -> dict[str, str]:
    headers = browser_headers()
    headers.update(
        {
            "Authorization": f"Bearer {access_token}",
            "x-api-key": DEFAULT_API_KEY,
            "content-type": "application/json",
            "accept": "*/*",
        }
    )
    return headers


def poll_headers(access_token: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {access_token}",
        "accept": "*/*",
        "referer": "https://new.express.adobe.com/",
        "origin": "https://new.express.adobe.com",
        "user-agent": DEFAULT_USER_AGENT,
        "x-api-key": DEFAULT_API_KEY,
        "content-type": "application/json",
    }


def _header_get(headers: Any, name: str) -> str:
    """兼容 curl_cffi / requests 响应头大小写。"""
    if headers is None:
        return ""
    # CaseInsensitiveDict 或普通 dict
    try:
        value = headers.get(name) or headers.get(name.lower()) or headers.get(name.title())
    except Exception:
        value = None
    if value is None and hasattr(headers, "items"):
        target = name.lower()
        for key, val in headers.items():
            if str(key).lower() == target:
                value = val
                break
    return str(value or "").strip()


def extract_result_link(headers: Any, submit_data: Any) -> str:
    """优先 header x-override-status-link，否则 body links.result。"""
    header_link = _header_get(headers, "x-override-status-link")
    if header_link:
        return header_link

    if not isinstance(submit_data, dict):
        return ""
    links = submit_data.get("links")
    if not isinstance(links, dict):
        return ""
    result_link = links.get("result")
    if isinstance(result_link, str):
        return result_link.strip()
    if isinstance(result_link, dict):
        return str(result_link.get("href") or "").strip()
    return ""


def _classify_auth_or_quota(status_code: int, headers: Any, body: str, context: str):
    """401/403 → Quota 或 Auth。"""
    access_error = _header_get(headers, "x-access-error").lower()
    if access_error == "taste_exhausted":
        raise FireflyQuotaExhausted(
            "Adobe quota exhausted for this account",
            status_code=status_code,
            error_type="status",
        )
    raise FireflyAuthError(
        f"{context}: token invalid or expired",
        status_code=status_code,
    )


def _raise_for_http(
    status_code: int,
    headers: Any,
    body: str,
    context: str,
) -> None:
    """非 200 时按状态分类抛异常。"""
    if status_code in (401, 403):
        _classify_auth_or_quota(status_code, headers, body, context)
    safe_body = redact_auth_diagnostic((body or "")[:300])
    if is_retryable_status(status_code):
        raise FireflyUpstreamTemporary(
            f"{context}: {status_code} {safe_body}",
            status_code=status_code,
            error_type="status",
        )
    raise FireflyRequestError(
        f"{context}: {status_code} {safe_body}",
        status_code=status_code,
    )


def _post_json(
    url: str,
    headers: dict[str, str],
    payload: dict[str, Any],
    *,
    proxy: str | None,
    timeout: float,
):
    """curl_cffi POST；遇 451 回落标准 requests（对齐 adobe2api）。"""
    proxies = _proxy_dict(proxy)
    try:
        resp = curl_requests.post(
            url,
            headers=headers,
            json=payload,
            timeout=timeout,
            impersonate=_IMPERSONATE,
            proxies=proxies,
        )
    except Exception as exc:
        logger.warning(
            "firefly submit network error: %s",
            redact_auth_diagnostic(str(exc))[:300],
        )
        raise FireflyUpstreamTemporary(
            f"submit network error: {exc}",
            error_type="network",
        ) from exc

    if resp.status_code == 451 and std_requests is not None:
        try:
            return std_requests.post(
                url,
                headers=headers,
                json=payload,
                timeout=timeout,
                proxies=proxies,
            )
        except Exception as exc:
            raise FireflyUpstreamTemporary(
                f"submit fallback network error: {exc}",
                status_code=451,
                error_type="network",
            ) from exc
    return resp


def _get(
    url: str,
    headers: dict[str, str],
    *,
    proxy: str | None,
    timeout: float,
    impersonate: bool = True,
):
    proxies = _proxy_dict(proxy)
    try:
        kwargs: dict[str, Any] = {
            "headers": headers,
            "timeout": timeout,
            "proxies": proxies,
        }
        if impersonate:
            kwargs["impersonate"] = _IMPERSONATE
        return curl_requests.get(url, **kwargs)
    except Exception as exc:
        logger.warning(
            "firefly GET network error: %s",
            redact_auth_diagnostic(str(exc))[:300],
        )
        raise FireflyUpstreamTemporary(
            f"get network error: {exc}",
            error_type="network",
        ) from exc


def generate_image(
    access_token: str,
    payload: dict[str, Any],
    *,
    proxy: str | None = None,
    timeout: float = 180,
    poll_interval: float = 3,
) -> bytes:
    """提交 generate-async → 轮询 → 下载 presign → 返回图片字节。

    错误分类：
    - taste_exhausted → FireflyQuotaExhausted
    - 401/403 → FireflyAuthError
    - 429/451/5xx / 网络 / 超时 → FireflyUpstreamTemporary
    - 其它 → FireflyRequestError
    """
    token = str(access_token or "").strip()
    if not token:
        raise FireflyAuthError("empty access token", status_code=401)
    if not isinstance(payload, dict) or not payload:
        raise FireflyRequestError("empty payload")

    # 1. 提交
    resp = _post_json(
        GENERATE_URL,
        headers=submit_headers(token),
        payload=payload,
        proxy=proxy,
        timeout=min(60.0, float(timeout)),
    )
    body_text = ""
    try:
        body_text = resp.text or ""
    except Exception:
        body_text = ""

    if resp.status_code != 200:
        logger.warning(
            "firefly submit failed status=%s body=%s",
            resp.status_code,
            redact_auth_diagnostic(body_text)[:300],
        )
        _raise_for_http(resp.status_code, resp.headers, body_text, "submit failed")

    try:
        submit_data = resp.json()
    except Exception:
        submit_data = {}

    poll_url = extract_result_link(resp.headers, submit_data)
    if not poll_url:
        raise FireflyRequestError("submit succeeded but no poll url returned")

    # 2. 轮询
    deadline = time.time() + float(timeout)
    interval = max(0.5, float(poll_interval))
    latest: dict[str, Any] = {}

    while True:
        poll_resp = _get(
            poll_url,
            headers=poll_headers(token),
            proxy=proxy,
            timeout=60,
            impersonate=True,
        )
        if poll_resp.status_code != 200:
            poll_body = ""
            try:
                poll_body = poll_resp.text or ""
            except Exception:
                poll_body = ""
            logger.warning(
                "firefly poll failed status=%s body=%s",
                poll_resp.status_code,
                redact_auth_diagnostic(poll_body)[:300],
            )
            _raise_for_http(
                poll_resp.status_code,
                poll_resp.headers,
                poll_body,
                "poll failed",
            )

        try:
            parsed = poll_resp.json()
            latest = parsed if isinstance(parsed, dict) else {}
        except Exception:
            latest = {}

        status_header = _header_get(poll_resp.headers, "x-task-status").upper()
        status_val = str(latest.get("status") or "").upper() or status_header

        outputs = latest.get("outputs") or []
        if isinstance(outputs, list) and outputs:
            first = outputs[0] if isinstance(outputs[0], dict) else {}
            image = first.get("image") if isinstance(first, dict) else None
            image_url = ""
            if isinstance(image, dict):
                image_url = str(image.get("presignedUrl") or "").strip()
            if not image_url:
                raise FireflyRequestError("job finished without image url")
            return _download_bytes(image_url, proxy=proxy)

        if status_val in {"FAILED", "CANCELLED", "ERROR"}:
            detail = redact_auth_diagnostic(str(latest)[:300])
            raise FireflyRequestError(f"image job failed: {detail}")

        if time.time() >= deadline:
            # 超时视为上游临时问题，允许换号重试
            raise FireflyUpstreamTemporary(
                "generation timed out",
                error_type="timeout",
            )
        time.sleep(interval)


def _download_bytes(url: str, *, proxy: str | None = None) -> bytes:
    """下载 presign（无需 TLS 伪装）。"""
    try:
        # 优先无 impersonate 的 curl_cffi；失败再试标准 requests
        resp = curl_requests.get(
            url,
            headers={"accept": "*/*"},
            timeout=60,
            proxies=_proxy_dict(proxy),
        )
    except Exception as exc:
        if std_requests is None:
            raise FireflyUpstreamTemporary(
                f"download network error: {exc}",
                error_type="network",
            ) from exc
        try:
            resp = std_requests.get(
                url,
                headers={"accept": "*/*"},
                timeout=60,
                proxies=_proxy_dict(proxy),
            )
        except Exception as exc2:
            raise FireflyUpstreamTemporary(
                f"download network error: {exc2}",
                error_type="network",
            ) from exc2

    if resp.status_code != 200:
        raise FireflyRequestError(
            f"media download failed: HTTP {resp.status_code}",
            status_code=resp.status_code,
        )
    content = resp.content or b""
    if not content:
        raise FireflyRequestError("media download returned empty body")
    return content


def _normalize_upload_mime(mime: str) -> str:
    """校验并规范化上传 mime；image/jpg → image/jpeg。"""
    normalized = str(mime or "").strip().lower()
    if normalized == "image/jpg":
        normalized = "image/jpeg"
    if normalized not in ALLOWED_UPLOAD_MIMES:
        raise FireflyRequestError(
            f"unsupported image mime: {mime or '(empty)'}; "
            "allowed: image/png, image/jpeg, image/webp"
        )
    return normalized


def upload_image(
    access_token: str,
    image_bytes: bytes,
    mime: str = "image/png",
    *,
    proxy: str | None = None,
    mime_type: str | None = None,
) -> str:
    """上传参考图到 Adobe 存储，返回 image_id。

    POST https://firefly-3p.ff.adobe.io/v2/storage/image
    body: raw bytes；Content-Type 为传入 mime。

    错误分类同 generate_image：
    - taste_exhausted → FireflyQuotaExhausted
    - 401/403 → FireflyAuthError
    - 429/451/5xx → FireflyUpstreamTemporary
    - 其它 → FireflyRequestError

    mime_type 为历史参数名，与 mime 二选一（mime_type 优先若显式传入）。
    """
    token = str(access_token or "").strip()
    if not token:
        raise FireflyAuthError("empty access token", status_code=401)
    if not image_bytes:
        raise FireflyRequestError("image is empty")
    if len(image_bytes) > MAX_UPLOAD_IMAGE_BYTES:
        raise FireflyRequestError(
            f"image too large: {len(image_bytes)} bytes "
            f"(max {MAX_UPLOAD_IMAGE_BYTES})"
        )

    content_type = _normalize_upload_mime(
        mime_type if mime_type is not None else mime
    )

    # headers 与 generate 一致：Bearer + x-api-key + 浏览器伪装
    headers = browser_headers()
    headers.update(
        {
            "Authorization": f"Bearer {token}",
            "x-api-key": DEFAULT_API_KEY,
            "content-type": content_type,
            "accept": "application/json",
        }
    )
    proxies = _proxy_dict(proxy)
    try:
        resp = curl_requests.post(
            UPLOAD_URL,
            headers=headers,
            data=image_bytes,
            timeout=60,
            impersonate=_IMPERSONATE,
            proxies=proxies,
        )
    except Exception as exc:
        logger.warning(
            "firefly upload network error: %s",
            redact_auth_diagnostic(str(exc))[:300],
        )
        raise FireflyUpstreamTemporary(
            f"upload network error: {exc}",
            error_type="network",
        ) from exc

    if resp.status_code != 200:
        body = ""
        try:
            body = resp.text or ""
        except Exception:
            body = ""
        logger.warning(
            "firefly upload failed status=%s body=%s",
            resp.status_code,
            redact_auth_diagnostic(body)[:300],
        )
        _raise_for_http(resp.status_code, resp.headers, body, "upload image failed")

    try:
        data = resp.json()
    except Exception as exc:
        raise FireflyRequestError("upload response invalid json") from exc

    images = (data or {}).get("images") if isinstance(data, dict) else None
    if not isinstance(images, list) or not images:
        raise FireflyRequestError("upload image succeeded but no image id returned")
    image_id = (images[0] or {}).get("id") if isinstance(images[0], dict) else None
    if not image_id:
        raise FireflyRequestError("upload image succeeded but no image id returned")
    return str(image_id)
