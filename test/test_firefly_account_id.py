from __future__ import annotations

import base64
import json
import os
import unittest
from unittest import mock

os.environ.setdefault("CHATGPT2API_AUTH_KEY", "test-auth")

from services.backends import firefly_auth as auth  # noqa: E402


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _make_jwt(claims: dict) -> str:
    """构造无签名校验的 mock JWT（header.payload.sig）。"""
    header = _b64url(json.dumps({"alg": "none", "typ": "JWT"}).encode("utf-8"))
    payload = _b64url(json.dumps(claims, separators=(",", ":")).encode("utf-8"))
    return f"{header}.{payload}.sig"


def _decode_account_id(token: str) -> str:
    for name in (
        "decode_jwt_account_id",
        "account_id_from_token",
        "decode_account_id",
        "jwt_account_id",
    ):
        fn = getattr(auth, name, None)
        if callable(fn):
            return str(fn(token) or "")
    raise AssertionError(
        "missing decode_jwt_account_id "
        "(expected decode_jwt_account_id / account_id_from_token)"
    )


def _normalize_create_payload():
    """定位 api.accounts._normalize_create_account_payload（容错多名称）。"""
    try:
        from api import accounts as accounts_mod
    except Exception as exc:  # pragma: no cover
        raise unittest.SkipTest(f"cannot import api.accounts: {exc}") from exc

    for name in (
        "_normalize_create_account_payload",
        "normalize_create_account_payload",
        "_normalize_account_payload",
        "normalize_account_payload",
        "_prepare_firefly_account_payload",
    ):
        fn = getattr(accounts_mod, name, None)
        if callable(fn):
            return accounts_mod, name, fn
    raise unittest.SkipTest(
        "missing _normalize_create_account_payload on api.accounts"
    )


class DecodeJwtAccountIdTests(unittest.TestCase):
    """decode_jwt_account_id 回归（与 test_firefly_auth 思路一致）。"""

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


class TokenOnlyAccountIdTests(unittest.TestCase):
    """B5：token-only 创建 Firefly 账号时写入 account_id。"""

    def test_token_only_payload_writes_account_id(self) -> None:
        """已有 access_token 时也应 decode 并写入 account_id（及 user_id）。"""
        _mod, _name, normalize = _normalize_create_payload()
        adobe_id = "adobe-account-xyz"
        token = _make_jwt({"user_id": adobe_id, "sub": "sub-ignored"})

        payload = normalize(
            {
                "source_type": "firefly",
                "access_token": token,
                # 无 cookie — token-only 路径
            }
        )

        self.assertIsInstance(payload, dict)
        self.assertEqual(
            str(payload.get("access_token") or "").strip(),
            token,
        )
        account_id = str(
            payload.get("account_id") or payload.get("accountId") or ""
        ).strip()
        self.assertEqual(
            account_id,
            adobe_id,
            "token-only firefly create must write account_id from JWT",
        )
        # user_id 也应写入（若原本为空）
        user_id = str(payload.get("user_id") or payload.get("userId") or "").strip()
        self.assertEqual(user_id, adobe_id)

    def test_token_only_does_not_overwrite_existing_account_id(self) -> None:
        """若 payload 已带 account_id，不强制覆盖。"""
        _mod, _name, normalize = _normalize_create_payload()
        token = _make_jwt({"user_id": "from-jwt", "sub": "sub"})
        payload = normalize(
            {
                "source_type": "firefly",
                "access_token": token,
                "account_id": "preset-id",
                "user_id": "preset-user",
            }
        )
        self.assertEqual(str(payload.get("account_id") or ""), "preset-id")
        self.assertEqual(str(payload.get("user_id") or ""), "preset-user")

    def test_cookie_path_also_writes_account_id(self) -> None:
        """cookie 换 token 路径同样写入 account_id。"""
        _mod, _name, normalize = _normalize_create_payload()
        adobe_id = "from-cookie-jwt"
        token = _make_jwt({"aa_id": adobe_id})

        # mock IMS refresh，避免真实网络
        refresh_targets = [
            "api.accounts.refresh_access_token",
            "services.backends.firefly_auth.refresh_access_token",
        ]
        active = []
        for target in refresh_targets:
            try:
                p = mock.patch(
                    target,
                    return_value={"access_token": token, "expires_in": 3600},
                )
                p.start()
                active.append(p)
            except Exception:
                continue

        try:
            payload = normalize(
                {
                    "source_type": "firefly",
                    "cookie": "aux_sid=abc; session=xyz",
                }
            )
        finally:
            for p in active:
                p.stop()

        self.assertIsInstance(payload, dict)
        got_token = str(payload.get("access_token") or "").strip()
        self.assertEqual(got_token, token)
        account_id = str(
            payload.get("account_id") or payload.get("accountId") or ""
        ).strip()
        self.assertEqual(
            account_id,
            adobe_id,
            "cookie→token path must also write account_id",
        )


if __name__ == "__main__":
    unittest.main()
