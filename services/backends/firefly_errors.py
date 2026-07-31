"""Firefly 上游错误分类，供 client 与集成层映射。

对应 adobe2api / GPT2Image-Pro firefly-direct/errors：
- taste_exhausted → 配额耗尽（可换号）
- 401/403 其它 → 鉴权失效（可换号，先尝试 cookie 刷新）
- 429/451/5xx → 上游临时错误（可换号重试）
- 其它 4xx/业务失败 → 请求错误（换号无用）
"""

from __future__ import annotations


class FireflyError(Exception):
    """Firefly 渠道异常基类。"""

    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        error_type: str = "",
        user_message: str = "",
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.error_type = str(error_type or "").strip().lower()
        self.user_message = (
            str(user_message or "").strip() or str(message or "").strip()
        )


class FireflyQuotaExhausted(FireflyError):
    """账号额度耗尽（header x-access-error: taste_exhausted）→ 对外 429。"""


class FireflyAuthError(FireflyError):
    """Token 失效/过期（401/403 且非 taste_exhausted）。"""


class FireflyUpstreamTemporary(FireflyError):
    """上游临时错误（429/451/5xx 或网络层），可重试。"""


class FireflyRequestError(FireflyError):
    """其它 4xx / 业务失败 / 超时等，换号通常无用。"""


# 可重试的 HTTP 状态码（含 451 地区/合规）
RETRYABLE_STATUS_CODES = {429, 451, 500, 502, 503, 504}


def is_retryable_status(status: int) -> bool:
    """HTTP 状态是否属于上游临时错误。"""
    code = int(status or 0)
    return code in RETRYABLE_STATUS_CODES or code >= 500


def is_rotatable_error(e: Exception) -> bool:
    """该错误是否应换号重试。

    配额耗尽、鉴权失效、上游临时错误都属于账号/凭据级问题——
    同一后端下换一个账号可能成功。请求本身 4xx/内容拒绝等换号无用。
    """
    return isinstance(
        e,
        (FireflyQuotaExhausted, FireflyAuthError, FireflyUpstreamTemporary),
    )
