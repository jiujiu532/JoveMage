from __future__ import annotations

import json
import os
import time
import unittest
from unittest import mock
from urllib.parse import parse_qs

os.environ.setdefault("CHATGPT2API_AUTH_KEY", "test-auth")

from services.backends import firefly_auth as auth  # noqa: E402
from test._firefly_helpers import (  # noqa: E402
    first_callable,
    make_jwt as _make_jwt,
    patch_firefly_http,
    stop_patches,
)


def _normalize_cookie(value):
    fn = first_callable(
        auth,
        "normalize_cookie",
        "normalize_cookie_string",
        "cookie_string_from_input",
    )
    return fn(value)


def _decode_account_id(token: str) -> str:
    fn = first_callable(
        auth,
        "decode_jwt_account_id",
        "account_id_from_token",
        "decode_account_id",
    )
    return str(fn(token) or "")


def _is_token_expired(token: str, *args, **kwargs) -> bool:
    fn = first_callable(auth, "is_token_expired")
    return bool(fn(token, *args, **kwargs))


def _refresh_access_token(cookie, **kwargs):
    fn = first_callable(
        auth,
        "refresh_access_token",
        "refresh_access_token_from_cookie",
    )
    return fn(cookie, **kwargs)


class NormalizeCookieTests(unittest.TestCase):
    """normalize_cookie：字符串 / 列表 / dict 多种输入归一。"""

    def test_string_input(self) -> None:
        """纯 cookie 字符串原样（去空白）返回。"""
        raw = "  aux_sid=abc; session=xyz  "
        result = _normalize_cookie(raw)
        self.assertEqual(result.strip(), "aux_sid=abc; session=xyz")

    def test_string_with_cookie_prefix(self) -> None:
        """支持 'Cookie: k=v' 前缀剥离。"""
        result = _normalize_cookie("Cookie: aux_sid=abc; foo=bar")
        self.assertEqual(result, "aux_sid=abc; foo=bar")

    def test_list_of_pairs(self) -> None:
        """[{name,value}, ...] 应拼成 k=v; k=v。"""
        result = _normalize_cookie(
            [
                {"name": "aux_sid", "value": "abc"},
                {"name": "session", "value": "xyz"},
            ]
        )
        self.assertIn("aux_sid=abc", result)
        self.assertIn("session=xyz", result)
        self.assertIn(";", result)

    def test_dict_with_cookies_list(self) -> None:
        """dict.cookies 列表输入应能解析。"""
        result = _normalize_cookie(
            {
                "cookies": [
                    {"name": "a", "value": "1"},
                    {"name": "b", "value": "2"},
                ]
            }
        )
        self.assertIn("a=1", result)
        self.assertIn("b=2", result)

    def test_dict_with_cookie_string(self) -> None:
        """dict.cookie 字符串输入应能解析。"""
        result = _normalize_cookie({"cookie": "foo=bar; baz=qux"})
        self.assertIn("foo=bar", result)
        self.assertIn("baz=qux", result)


class DecodeJwtAccountIdTests(unittest.TestCase):
    """decode_jwt_account_id：从 JWT claims 提取账号 id。"""

    def test_prefers_user_id(self) -> None:
        """优先 user_id。"""
        token = _make_jwt({"user_id": "user-42", "aa_id": "aa-1", "sub": "sub-1"})
        self.assertEqual(_decode_account_id(token), "user-42")

    def test_falls_back_to_aa_id(self) -> None:
        """无 user_id 时回退 aa_id。"""
        token = _make_jwt({"aa_id": "aa-99", "sub": "sub-1"})
        self.assertEqual(_decode_account_id(token), "aa-99")

    def test_falls_back_to_sub(self) -> None:
        """无 user_id/aa_id 时回退 sub。"""
        token = _make_jwt({"sub": "sub-only"})
        self.assertEqual(_decode_account_id(token), "sub-only")

    def test_invalid_token_returns_empty(self) -> None:
        """非法 token 应返回空串。"""
        self.assertEqual(_decode_account_id("not-a-jwt"), "")
        self.assertEqual(_decode_account_id(""), "")


class IsTokenExpiredTests(unittest.TestCase):
    """is_token_expired：过期 / 未过期判定。"""

    def test_expired_token(self) -> None:
        """exp 在过去 → 已过期。"""
        token = _make_jwt({"exp": int(time.time()) - 3600, "user_id": "u1"})
        self.assertTrue(_is_token_expired(token))

    def test_not_expired_token(self) -> None:
        """exp 在足够远的未来 → 未过期。"""
        token = _make_jwt({"exp": int(time.time()) + 7200, "user_id": "u1"})
        self.assertFalse(_is_token_expired(token))

    def test_created_at_expires_in_milliseconds(self) -> None:
        """兼容 created_at + expires_in（毫秒）字段。"""
        now_ms = int(time.time() * 1000)
        # 已过期：created 2 小时前，expires_in 1 小时（毫秒）
        expired = _make_jwt(
            {
                "created_at": now_ms - 2 * 3600 * 1000,
                "expires_in": 3600 * 1000,
                "user_id": "u1",
            }
        )
        self.assertTrue(_is_token_expired(expired))

        # 未过期：刚刚创建，24h 有效
        fresh = _make_jwt(
            {
                "created_at": now_ms,
                "expires_in": 86400 * 1000,
                "user_id": "u1",
            }
        )
        self.assertFalse(_is_token_expired(fresh))


class RefreshAccessTokenTests(unittest.TestCase):
    """refresh_access_token：IMS 请求参数（client_id / scope / origin）。"""

    def test_refresh_posts_expected_ims_form_and_headers(self) -> None:
        """应 POST IMS check/v6/token，带 projectx_webapp + firefly scope + Express origin。"""
        fake_response = mock.Mock()
        fake_response.status_code = 200
        fake_response.text = json.dumps(
            {"access_token": "access-token-xyz", "expires_in": 3600}
        )
        fake_response.json.return_value = {
            "access_token": "access-token-xyz",
            "expires_in": 3600,
        }
        fake_response.headers = {}

        post_calls: list[dict] = []

        def _capture_post(*args, **kwargs):
            post_calls.append({"args": args, "kwargs": kwargs})
            return fake_response

        # 兼容 curl_cffi.requests.post / Session.post / 模块内 requests 封装
        session_post = mock.Mock(side_effect=_capture_post)
        fake_session = mock.Mock()
        fake_session.post = session_post
        fake_session.close = mock.Mock()
        fake_session.__enter__ = mock.Mock(return_value=fake_session)
        fake_session.__exit__ = mock.Mock(return_value=False)

        # 同时 patch 模块级 post 与 Session，哪个被调用就捕获哪个
        active_patches = patch_firefly_http(
            "services.backends.firefly_auth.requests.post",
            "services.backends.firefly_auth.curl_cffi.requests.post",
            "curl_cffi.requests.post",
            side_effect=_capture_post,
        )
        active_patches.extend(
            patch_firefly_http(
                "services.backends.firefly_auth.requests.Session",
                "services.backends.firefly_auth.curl_cffi.requests.Session",
                return_value=fake_session,
            )
        )

        try:
            result = _refresh_access_token(
                "aux_sid=abc; session=xyz",
                fetch_account=False,
            )
        finally:
            stop_patches(active_patches)

        # 结果应含 access_token
        if isinstance(result, dict):
            token = result.get("access_token") or result.get("accessToken")
        else:
            token = getattr(result, "access_token", None) or getattr(
                result, "accessToken", None
            )
        self.assertEqual(str(token or ""), "access-token-xyz")

        # 至少有一次 POST（模块级 post 或 Session.post）
        all_calls = list(post_calls)
        if session_post.called:
            for call in session_post.call_args_list:
                all_calls.append({"args": call.args, "kwargs": call.kwargs})

        self.assertTrue(all_calls, "expected at least one IMS POST call")

        call = all_calls[0]
        args = call["args"]
        kwargs = call["kwargs"]
        url = kwargs.get("url") or (args[0] if args else "")
        self.assertIn("ims/check/v6/token", str(url))

        headers = kwargs.get("headers") or {}
        # Origin 必须是 Express
        origin = headers.get("Origin") or headers.get("origin") or ""
        self.assertIn("new.express.adobe.com", origin)

        # form：client_id / scope
        data = kwargs.get("data") or kwargs.get("json") or {}
        if isinstance(data, (bytes, bytearray)):
            data = data.decode("utf-8", errors="ignore")
        if isinstance(data, str):
            form = {k: v[0] for k, v in parse_qs(data, keep_blank_values=True).items()}
        elif isinstance(data, dict):
            form = {str(k): str(v) for k, v in data.items()}
        else:
            form = {}

        client_id = form.get("client_id") or form.get("clientId") or ""
        scope = form.get("scope") or ""
        self.assertEqual(client_id, "projectx_webapp")
        self.assertIn("AdobeID", scope)
        self.assertIn("firefly_api", scope)
        self.assertIn("openid", scope)

        cookie_header = headers.get("Cookie") or headers.get("cookie") or ""
        self.assertIn("aux_sid=abc", cookie_header)


if __name__ == "__main__":
    unittest.main()
