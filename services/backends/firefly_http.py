"""Firefly HTTP 错误分类与响应头读取（client / entities 共用）。

统一 401/403 下 taste_exhausted → FireflyQuotaExhausted，避免 entities
路径把额度耗尽误标为 Auth。
"""

from __future__ import annotations

from typing import Any

from services.backends.firefly_errors import (
    FireflyAuthError,
    FireflyQuotaExhausted,
    FireflyRequestError,
    FireflyUpstreamTemporary,
    is_retryable_status,
)
from utils.diagnostics import redact_auth_diagnostic


def header_get(headers: Any, *names: str) -> str:
    """兼容 curl_cffi / requests 响应头大小写；按 names 顺序取首个非空值。"""
    if headers is None:
        return ""
    for name in names:
        try:
            value = (
                headers.get(name)
                or headers.get(name.lower())
                or headers.get(name.title())
            )
        except Exception:
            value = None
        if value is None and hasattr(headers, "items"):
            target = name.lower()
            for key, val in headers.items():
                if str(key).lower() == target:
                    value = val
                    break
        text = str(value or "").strip()
        if text:
            return text
    return ""


def classify_auth_or_quota(
    status_code: int,
    headers: Any,
    body: str,
    context: str,
) -> None:
    """401/403 → FireflyQuotaExhausted（taste_exhausted）或 FireflyAuthError。

    始终 raise，不返回。
    """
    access_error = header_get(headers, "x-access-error").lower()
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


def raise_for_firefly_http(
    status_code: int,
    headers: Any,
    body: str,
    context: str,
) -> None:
    """非 2xx 时按状态分类抛异常。

    - 401/403 + x-access-error: taste_exhausted → FireflyQuotaExhausted
    - 401/403 其它 → FireflyAuthError
    - 429/451/5xx → FireflyUpstreamTemporary
    - 其它 → FireflyRequestError
    """
    if status_code in (401, 403):
        classify_auth_or_quota(status_code, headers, body, context)
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
