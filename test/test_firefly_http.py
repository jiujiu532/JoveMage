"""Firefly HTTP 分类单测：header_get / taste_exhausted / entities 路径。"""

from __future__ import annotations

import os
import unittest

os.environ.setdefault("CHATGPT2API_AUTH_KEY", "test-auth")

from services.backends import firefly_entities as entities  # noqa: E402
from services.backends.firefly_errors import (  # noqa: E402
    FireflyAuthError,
    FireflyQuotaExhausted,
    FireflyRequestError,
    FireflyUpstreamTemporary,
)
from services.backends.firefly_http import (  # noqa: E402
    header_get,
    raise_for_firefly_http,
)


class HeaderGetTests(unittest.TestCase):
    def test_case_insensitive_and_multi_name(self) -> None:
        headers = {"X-Access-Error": "taste_exhausted", "ETag": "abc"}
        self.assertEqual(header_get(headers, "x-access-error"), "taste_exhausted")
        self.assertEqual(header_get(headers, "missing", "etag"), "abc")
        self.assertEqual(header_get(None, "x"), "")


class RaiseForFireflyHttpTests(unittest.TestCase):
    def test_taste_exhausted_is_quota(self) -> None:
        with self.assertRaises(FireflyQuotaExhausted):
            raise_for_firefly_http(
                401,
                {"x-access-error": "taste_exhausted"},
                "nope",
                "submit failed",
            )

    def test_plain_401_is_auth(self) -> None:
        with self.assertRaises(FireflyAuthError):
            raise_for_firefly_http(401, {}, "nope", "submit failed")

    def test_retryable_is_upstream_temporary(self) -> None:
        with self.assertRaises(FireflyUpstreamTemporary):
            raise_for_firefly_http(503, {}, "busy", "poll failed")

    def test_other_4xx_is_request_error(self) -> None:
        with self.assertRaises(FireflyRequestError):
            raise_for_firefly_http(400, {}, "bad", "submit failed")


class EntitiesTasteExhaustedTests(unittest.TestCase):
    """entities 路径原先无 taste 分支，401+taste 会误标 Auth；应改为 Quota。"""

    def test_entities_raise_for_http_taste_exhausted_is_quota(self) -> None:
        with self.assertRaises(FireflyQuotaExhausted) as ctx:
            entities._raise_for_http(
                401,
                "quota body",
                "create entity failed",
                headers={"x-access-error": "taste_exhausted"},
            )
        self.assertEqual(ctx.exception.status_code, 401)

    def test_entities_raise_for_http_plain_401_is_auth(self) -> None:
        with self.assertRaises(FireflyAuthError):
            entities._raise_for_http(
                401,
                "auth body",
                "create entity failed",
                headers={},
            )


if __name__ == "__main__":
    unittest.main()
