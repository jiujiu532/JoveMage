from __future__ import annotations

import os
import unittest

os.environ.setdefault("CHATGPT2API_AUTH_KEY", "test-auth")

from services.backends.firefly_errors import (  # noqa: E402
    RETRYABLE_STATUS_CODES,
    FireflyAuthError,
    FireflyQuotaExhausted,
    FireflyRequestError,
    FireflyUpstreamTemporary,
    is_rotatable_error,
)


def _make(exc_cls: type, message: str = "test"):
    """兼容不同构造签名的异常类。"""
    try:
        return exc_cls(message)
    except TypeError:
        try:
            return exc_cls(message, status_code=500)
        except TypeError:
            return exc_cls()


class IsRotatableErrorTests(unittest.TestCase):
    """is_rotatable_error：账号/凭据级错误可换号，请求本身错误不可换号。"""

    def test_quota_exhausted_is_rotatable(self) -> None:
        """额度耗尽（taste_exhausted）应允许换号。"""
        self.assertTrue(is_rotatable_error(_make(FireflyQuotaExhausted)))

    def test_auth_error_is_rotatable(self) -> None:
        """鉴权失败应允许换号（或先刷新 cookie）。"""
        self.assertTrue(is_rotatable_error(_make(FireflyAuthError)))

    def test_upstream_temporary_is_rotatable(self) -> None:
        """上游临时错误（429/451/5xx）应允许换号重试。"""
        self.assertTrue(is_rotatable_error(_make(FireflyUpstreamTemporary)))

    def test_request_error_is_not_rotatable(self) -> None:
        """普通请求错误（内容拒绝/参数问题等）换号无用。"""
        self.assertFalse(is_rotatable_error(_make(FireflyRequestError)))


class RetryableStatusCodesTests(unittest.TestCase):
    """RETRYABLE_STATUS_CODES：可重试的 HTTP 状态集合。"""

    def test_contains_expected_codes(self) -> None:
        """应包含 429 / 451 / 5xx 常见网关与服务端错误码。"""
        codes = set(RETRYABLE_STATUS_CODES)
        for code in (429, 451, 500, 502, 503, 504):
            self.assertIn(
                code,
                codes,
                f"RETRYABLE_STATUS_CODES missing {code}; got={sorted(codes)}",
            )


if __name__ == "__main__":
    unittest.main()
