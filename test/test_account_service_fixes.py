"""Regression tests for account_service B3/B4/B5/B18/B20.

B3: mark_image_result 在 RT 旋转后仍记账（不因 expected_refresh_token 硬 CAS 丢扣额）
B4: refresh_access_token 瞬时失败 re-raise，不静默返回旧 token
B5: _record_refresh_success 必须落盘
B18: 自动移除限流账号时清理 inflight 并 notify
B20: JWT exp 解析失败（remaining=None）时 _token_needs_refresh 为 True
"""
from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

os.environ.setdefault("CHATGPT2API_AUTH_KEY", "test-auth")

from services.account_service import (
    AccountService,
    OAuthRefreshError,
    TerminalRefreshTokenError,
)
from services.storage.json_storage import JSONStorageBackend


def _make_service(tmp_dir: str) -> AccountService:
    return AccountService(JSONStorageBackend(Path(tmp_dir) / "accounts.json"))


class B3MarkImageResultRefreshTokenCasTests(unittest.TestCase):
    """RT 旋转后 expected_refresh_token 不匹配，仍应按 access_token 记账。"""

    def test_rt_rotation_still_accounts_quota(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            service = _make_service(tmp)
            service.add_account_items([{
                "access_token": "at-1",
                "refresh_token": "rt-new",
                "quota": 3,
                "status": "正常",
                "success": 0,
            }])
            with service._image_slot_condition:
                service._image_inflight["at-1"] = 1

            result = service.mark_image_result(
                "at-1",
                success=True,
                quota_consumed=True,
                expected_access_token="at-1",
                expected_refresh_token="rt-old",  # 已被 keepalive/force refresh 旋转
            )

            self.assertIsNotNone(result)
            account = service.get_account("at-1")
            self.assertIsNotNone(account)
            assert account is not None
            self.assertEqual(account["quota"], 2)
            self.assertEqual(account["success"], 1)
            self.assertEqual(int(service._image_inflight.get("at-1", 0)), 0)

    def test_expected_access_token_mismatch_still_skips(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            service = _make_service(tmp)
            service.add_account_items([
                {"access_token": "at-1", "refresh_token": "rt-1", "quota": 3, "status": "正常"},
                {"access_token": "at-2", "refresh_token": "rt-2", "quota": 5, "status": "正常"},
            ])
            result = service.mark_image_result(
                "at-1",
                success=True,
                quota_consumed=True,
                expected_access_token="at-2",
            )
            self.assertIsNotNone(result)
            account = service.get_account("at-1")
            assert account is not None
            self.assertEqual(account["quota"], 3)


class B4RefreshAccessTokenFailureTests(unittest.TestCase):
    """瞬时失败不得静默返回旧 token；终态仍返回旧 token。"""

    def test_transient_oauth_error_is_reraised(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            service = _make_service(tmp)
            service.add_account_items([{
                "access_token": "at-1",
                "refresh_token": "rt-1",
                "status": "正常",
            }])
            with mock.patch.object(
                service,
                "_request_access_token_refresh",
                side_effect=OAuthRefreshError(503, "server_error", "busy"),
            ), mock.patch.object(AccountService, "_token_needs_refresh", return_value=True), mock.patch.object(
                AccountService, "_recent_token_refresh_error", return_value=False
            ):
                with self.assertRaises(OAuthRefreshError):
                    service.refresh_access_token("at-1", force=True, event="test_transient")

            account = service.get_account("at-1")
            assert account is not None
            self.assertTrue(str(account.get("last_token_refresh_error") or ""))

    def test_terminal_refresh_returns_old_token(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            service = _make_service(tmp)
            service.add_account_items([{
                "access_token": "at-1",
                "refresh_token": "rt-1",
                "status": "正常",
            }])
            with mock.patch.object(
                service,
                "_request_access_token_refresh",
                side_effect=TerminalRefreshTokenError(400, "invalid_grant", "revoked"),
            ), mock.patch.object(AccountService, "_token_needs_refresh", return_value=True), mock.patch(
                "services.account_service.config"
            ) as cfg:
                cfg.auto_remove_invalid_accounts = False
                returned = service.refresh_access_token("at-1", force=True, event="test_terminal")
            self.assertEqual(returned, "at-1")
            account = service.get_account("at-1")
            assert account is not None
            self.assertEqual(account.get("status"), "异常")


class B5RecordRefreshSuccessPersistTests(unittest.TestCase):
    def test_record_refresh_success_calls_save(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            service = _make_service(tmp)
            service.add_account_items([{
                "access_token": "at-1",
                "refresh_token": "rt-1",
                "status": "正常",
            }])
            with mock.patch.object(service, "_save_accounts") as save_mock:
                service._record_refresh_success("at-1", "unit_test")
                save_mock.assert_called()
            account = service.get_account("at-1")
            assert account is not None
            self.assertEqual(account.get("last_remote_check_result"), "ok")
            self.assertIsNotNone(account.get("last_remote_checked_at"))


class B18AutoRemoveRateLimitedCleanupTests(unittest.TestCase):
    def test_auto_remove_clears_inflight_and_notifies(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            service = _make_service(tmp)
            service.add_account_items([{
                "access_token": "at-1",
                "refresh_token": "rt-1",
                "status": "正常",
                "quota": 0,
            }])
            with service._image_slot_condition:
                service._image_inflight["at-1"] = 2

            with mock.patch("services.account_service.config") as cfg, mock.patch.object(
                service._image_slot_condition, "notify_all"
            ) as notify_mock:
                cfg.auto_remove_rate_limited_accounts = True
                result = service.update_account("at-1", {"status": "限流", "quota": 0}, quiet=True)

            self.assertIsNone(result)
            self.assertIsNone(service.get_account("at-1"))
            self.assertNotIn("at-1", service._image_inflight)
            notify_mock.assert_called()


class B20TokenNeedsRefreshNoneRemainingTests(unittest.TestCase):
    def test_none_remaining_needs_refresh(self) -> None:
        self.assertTrue(AccountService._token_needs_refresh("not-a-jwt"))
        self.assertTrue(AccountService._token_needs_refresh("a.b.c"))

    def test_force_always_true(self) -> None:
        self.assertTrue(AccountService._token_needs_refresh("not-a-jwt", force=True))

    def test_fresh_jwt_does_not_need_refresh(self) -> None:
        import base64
        import json
        import time

        payload = base64.urlsafe_b64encode(
            json.dumps({"exp": int(time.time()) + 7 * 24 * 3600}).encode("utf-8")
        ).decode("ascii").rstrip("=")
        token = f"hdr.{payload}.sig"
        self.assertFalse(AccountService._token_needs_refresh(token))


if __name__ == "__main__":
    unittest.main()
