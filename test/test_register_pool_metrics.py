from __future__ import annotations

import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

os.environ.setdefault("CHATGPT2API_AUTH_KEY", "test-auth")

from services.account_service import AccountService
from services.openai_backend_api import InvalidAccessTokenError
from services.register_service import RegisterService
from services.storage.json_storage import JSONStorageBackend


NOW = datetime(2026, 7, 11, 12, 0, 0, tzinfo=timezone.utc)


def _pool_metrics(**updates: object) -> dict[str, object]:
    metrics: dict[str, object] = {
        "current_quota": 0,
        "current_available": 0,
        "estimated_quota": 0,
        "estimated_available": 0,
        "unconfirmed_available": 0,
        "unknown_quota_count": 0,
        "pool_freshness_seconds": 300,
        "pool_last_checked_at": None,
        "pool_refreshed": 0,
        "pool_refresh_errors": [],
    }
    metrics.update(updates)
    return metrics


def _require_mapping(value: dict | None) -> dict:
    if value is None:
        raise AssertionError("expected a persisted account")
    return value


class ConfirmedPoolMetricTests(unittest.TestCase):
    def _service(self, directory: str) -> AccountService:
        return AccountService(JSONStorageBackend(Path(directory) / "accounts.json"))

    def _evaluate_at(
        self,
        service: AccountService,
        *,
        refresh_stale: bool = False,
        freshness_seconds: object = 300,
        target_quota: int | None = None,
        target_available: int | None = None,
    ) -> dict[str, object]:
        evaluate = getattr(service, "evaluate_account_pool")
        with mock.patch("services.account_service.datetime", wraps=datetime) as clock:
            clock.now.return_value = NOW
            return evaluate(
                refresh_stale=refresh_stale,
                freshness_seconds=freshness_seconds,
                target_quota=target_quota,
                target_available=target_available,
            )

    def _record_refreshed_batch(
        self,
        service: AccountService,
        access_tokens: list[str],
        progress_id: str | None = None,
        remove_invalid: bool | None = None,
    ) -> dict[str, object]:
        self.assertIsNone(progress_id)
        self.assertFalse(remove_invalid)
        for access_token in access_tokens:
            service.update_account(
                access_token,
                {
                    "status": "正常",
                    "quota": 1,
                    "image_quota_unknown": False,
                    "last_remote_checked_at": NOW.isoformat(),
                    "last_remote_check_attempt_at": NOW.isoformat(),
                    "last_remote_check_error": None,
                    "last_remote_check_error_at": None,
                    "last_remote_check_event": "refresh_accounts",
                    "last_remote_check_result": "ok",
                },
                quiet=True,
            )
        return {
            "refreshed": len(access_tokens),
            "errors": [],
            "items": service.list_accounts(),
        }

    def test_unconfirmed_local_account_is_estimated_only(self) -> None:
        # Given
        with tempfile.TemporaryDirectory() as tmp_dir:
            service = self._service(tmp_dir)
            service.add_account_items(
                [
                    {
                        "access_token": "token-1",
                        "status": "正常",
                        "quota": 10,
                    }
                ]
            )

            # When
            metrics = self._evaluate_at(service)

        # Then
        self.assertEqual(metrics["current_available"], 0)
        self.assertEqual(metrics["current_quota"], 0)
        self.assertEqual(metrics["estimated_available"], 1)
        self.assertEqual(metrics["estimated_quota"], 10)
        self.assertEqual(metrics["unconfirmed_available"], 1)

    def test_fresh_remote_account_is_counted(self) -> None:
        # Given
        with tempfile.TemporaryDirectory() as tmp_dir:
            service = self._service(tmp_dir)
            service.add_account_items(
                [
                    {
                        "access_token": "token-1",
                        "status": "正常",
                        "quota": 7,
                        "last_remote_checked_at": NOW.isoformat(),
                    }
                ]
            )

            # When
            metrics = self._evaluate_at(service)

        # Then
        self.assertEqual(metrics["current_available"], 1)
        self.assertEqual(metrics["current_quota"], 7)
        self.assertEqual(metrics["unconfirmed_available"], 0)

    def test_missing_remote_metadata_defaults_to_none(self) -> None:
        # Given
        with tempfile.TemporaryDirectory() as tmp_dir:
            service = self._service(tmp_dir)
            service.add_accounts(["token-1"])

            # When
            account = service.get_account("token-1")

        # Then
        account = _require_mapping(account)
        self.assertIsNone(account["last_remote_checked_at"])
        self.assertIsNone(account["last_remote_check_attempt_at"])
        self.assertIsNone(account["last_remote_check_error"])
        self.assertIsNone(account["last_remote_check_error_at"])
        self.assertIsNone(account["last_remote_check_event"])
        self.assertIsNone(account["last_remote_check_result"])

    def test_explicit_freshness_is_truncated_and_clamped(self) -> None:
        # Given
        cases = (("59.9", 60), ("120.9", 120))

        # When
        for value, expected in cases:
            with self.subTest(value=value), tempfile.TemporaryDirectory() as tmp_dir:
                service = self._service(tmp_dir)
                metrics = self._evaluate_at(service, freshness_seconds=value)

                # Then
                self.assertEqual(metrics["pool_freshness_seconds"], expected)

    def test_default_freshness_uses_configured_refresh_interval(self) -> None:
        # Given
        with tempfile.TemporaryDirectory() as tmp_dir:
            service = self._service(tmp_dir)

            # When
            with mock.patch("services.account_service.config") as config:
                config.refresh_account_interval_minute = 7
                metrics = self._evaluate_at(service, freshness_seconds=None)

        # Then
        self.assertEqual(metrics["pool_freshness_seconds"], 420)

    def test_freshness_boundary_is_closed_and_invalid_timestamps_are_stale(self) -> None:
        # Given
        boundary = (NOW - timedelta(seconds=60)).isoformat()
        outside = (NOW - timedelta(seconds=60, microseconds=1)).isoformat()
        with tempfile.TemporaryDirectory() as tmp_dir:
            service = self._service(tmp_dir)
            service.add_account_items(
                [
                    {"access_token": "boundary", "status": "正常", "quota": 3, "last_remote_checked_at": boundary},
                    {"access_token": "outside", "status": "正常", "quota": 5, "last_remote_checked_at": outside},
                    {"access_token": "invalid", "status": "正常", "quota": 7, "last_remote_checked_at": "not-a-time"},
                ]
            )

            # When
            metrics = self._evaluate_at(service, freshness_seconds=60)

        # Then
        self.assertEqual(metrics["current_available"], 1)
        self.assertEqual(metrics["current_quota"], 3)
        self.assertEqual(metrics["unconfirmed_available"], 2)

    def test_future_remote_checked_at_is_estimated_only(self) -> None:
        # Given
        cases = (timedelta(seconds=1), timedelta(days=1))

        for offset in cases:
            with self.subTest(offset=offset), tempfile.TemporaryDirectory() as tmp_dir:
                service = self._service(tmp_dir)
                service.add_account_items(
                    [
                        {
                            "access_token": "future",
                            "status": "正常",
                            "quota": 11,
                            "last_remote_checked_at": (NOW + offset).isoformat(),
                        }
                    ]
                )

                # When
                metrics = self._evaluate_at(service, freshness_seconds=300)

                # Then
                self.assertEqual(metrics["current_available"], 0)
                self.assertEqual(metrics["current_quota"], 0)
                self.assertEqual(metrics["estimated_available"], 1)
                self.assertEqual(metrics["estimated_quota"], 11)
                self.assertEqual(metrics["unconfirmed_available"], 1)

    def test_future_remote_attempt_at_does_not_suppress_stale_refresh(self) -> None:
        # Given
        cases = (timedelta(seconds=1), timedelta(days=1))

        for offset in cases:
            with self.subTest(offset=offset), tempfile.TemporaryDirectory() as tmp_dir:
                service = self._service(tmp_dir)
                service.add_account_items(
                    [
                        {
                            "access_token": "stale",
                            "status": "正常",
                            "last_remote_checked_at": (NOW - timedelta(hours=2)).isoformat(),
                            "last_remote_check_attempt_at": (NOW + offset).isoformat(),
                        }
                    ]
                )

                # When
                with mock.patch.object(
                    service,
                    "refresh_accounts",
                    side_effect=lambda tokens, progress_id=None, remove_invalid=None: self._record_refreshed_batch(
                        service, tokens, progress_id, remove_invalid
                    ),
                ) as refresh:
                    self._evaluate_at(service, refresh_stale=True, freshness_seconds=300)

                # Then
                refresh.assert_called_once_with(["stale"], remove_invalid=False)

    def test_current_metrics_require_fresh_normal_accounts_and_exclude_unknown_quota(self) -> None:
        # Given
        stale = (NOW - timedelta(minutes=10)).isoformat()
        with tempfile.TemporaryDirectory() as tmp_dir:
            service = self._service(tmp_dir)
            service.add_account_items(
                [
                    {"access_token": "known", "status": "正常", "quota": 7, "last_remote_checked_at": NOW.isoformat()},
                    {
                        "access_token": "unknown",
                        "status": "正常",
                        "quota": 99,
                        "image_quota_unknown": True,
                        "last_remote_checked_at": NOW.isoformat(),
                    },
                    {"access_token": "stale", "status": "正常", "quota": 50, "last_remote_checked_at": stale},
                    {"access_token": "limited", "status": "限流", "quota": 100, "last_remote_checked_at": NOW.isoformat()},
                ]
            )

            # When
            metrics = self._evaluate_at(service)

        # Then
        self.assertEqual(metrics["current_available"], 2)
        self.assertEqual(metrics["current_quota"], 7)
        self.assertEqual(metrics["estimated_available"], 3)
        self.assertEqual(metrics["estimated_quota"], 57)
        self.assertEqual(metrics["unknown_quota_count"], 1)
        self.assertEqual(metrics["unconfirmed_available"], 1)

    def test_pool_last_checked_at_is_latest_valid_confirmation(self) -> None:
        # Given
        older = (NOW - timedelta(minutes=4)).isoformat()
        latest = (NOW - timedelta(minutes=2)).isoformat()
        with tempfile.TemporaryDirectory() as tmp_dir:
            service = self._service(tmp_dir)
            service.add_account_items(
                [
                    {"access_token": "older", "status": "正常", "last_remote_checked_at": older},
                    {"access_token": "latest", "status": "正常", "last_remote_checked_at": latest},
                    {"access_token": "invalid", "status": "正常", "last_remote_checked_at": "invalid"},
                ]
            )

            # When
            metrics = self._evaluate_at(service)

        # Then
        self.assertEqual(metrics["pool_last_checked_at"], latest)

    def test_refresh_orders_missing_then_oldest_and_skips_recent_attempts(self) -> None:
        # Given
        old = (NOW - timedelta(hours=3)).isoformat()
        newer = (NOW - timedelta(hours=2)).isoformat()
        recent_attempt = NOW.isoformat()
        with tempfile.TemporaryDirectory() as tmp_dir:
            service = self._service(tmp_dir)
            service.add_account_items(
                [
                    {"access_token": "newer", "status": "正常", "last_remote_checked_at": newer},
                    {"access_token": "recent", "status": "正常", "last_remote_checked_at": old, "last_remote_check_attempt_at": recent_attempt},
                    {"access_token": "missing", "status": "正常"},
                    {"access_token": "oldest", "status": "正常", "last_remote_checked_at": old},
                    {"access_token": "limited", "status": "限流"},
                ]
            )

            # When
            with mock.patch.object(
                service,
                "refresh_accounts",
                side_effect=lambda tokens, progress_id=None, remove_invalid=None: self._record_refreshed_batch(
                    service, tokens, progress_id, remove_invalid
                ),
            ) as refresh:
                self._evaluate_at(service, refresh_stale=True)

        # Then
        refresh.assert_called_once_with(["missing", "oldest", "newer"], remove_invalid=False)

    def test_refreshes_twelve_stale_accounts_in_ten_then_two_batches(self) -> None:
        # Given
        tokens = [f"token-{index:02d}" for index in range(12)]
        with tempfile.TemporaryDirectory() as tmp_dir:
            service = self._service(tmp_dir)
            service.add_account_items([{"access_token": token, "status": "正常"} for token in tokens])

            # When
            with mock.patch.object(
                service,
                "refresh_accounts",
                side_effect=lambda batch, progress_id=None, remove_invalid=None: self._record_refreshed_batch(
                    service, batch, progress_id, remove_invalid
                ),
            ) as refresh:
                metrics = self._evaluate_at(service, refresh_stale=True)

        # Then
        self.assertEqual(
            refresh.call_args_list,
            [
                mock.call(tokens[:10], remove_invalid=False),
                mock.call(tokens[10:], remove_invalid=False),
            ],
        )
        self.assertEqual(metrics["pool_refreshed"], 12)

    def test_refresh_stops_when_either_remote_target_is_reached(self) -> None:
        # Given
        cases = (
            {"target_quota": 5, "target_available": 999},
            {"target_quota": 999, "target_available": 1},
        )

        # When
        for targets in cases:
            with self.subTest(targets=targets), tempfile.TemporaryDirectory() as tmp_dir:
                service = self._service(tmp_dir)
                tokens = [f"token-{index:02d}" for index in range(12)]
                service.add_account_items([{"access_token": token, "status": "正常", "quota": 0} for token in tokens])

                def record_target_batch(batch, progress_id=None, remove_invalid=None):
                    result = self._record_refreshed_batch(service, batch, progress_id, remove_invalid)
                    service.update_account(batch[0], {"quota": 5}, quiet=True)
                    return result

                with mock.patch.object(service, "refresh_accounts", side_effect=record_target_batch) as refresh:
                    self._evaluate_at(service, refresh_stale=True, **targets)

                # Then
                refresh.assert_called_once_with(tokens[:10], remove_invalid=False)


class RemoteConfirmationRecordingTests(unittest.TestCase):
    def _service(self, directory: str) -> AccountService:
        return AccountService(JSONStorageBackend(Path(directory) / "accounts.json"))

    def _backend(self, *, result: dict[str, object] | None = None, error: Exception | None = None) -> mock.MagicMock:
        backend = mock.MagicMock()
        get_user_info = backend.__enter__.return_value.get_user_info
        if error is not None:
            get_user_info.side_effect = error
        else:
            get_user_info.return_value = result
        return backend

    def test_passwordless_forced_refresh_rotates_token_and_preserves_empty_password(self) -> None:
        # Given
        with tempfile.TemporaryDirectory() as tmp_dir:
            service = self._service(tmp_dir)
            service.add_account_items(
                [
                    {
                        "access_token": "old-token",
                        "refresh_token": "refresh-token",
                        "password": "",
                    }
                ]
            )
            refreshed_tokens = {
                "access_token": "rotated-token",
                "refresh_token": "rotated-refresh-token",
                "id_token": "rotated-id-token",
            }

            # When
            with mock.patch.object(
                service,
                "_request_access_token_refresh",
                return_value=refreshed_tokens,
            ) as refresh_request, mock.patch("services.account_service.datetime", wraps=datetime) as clock:
                clock.now.return_value = NOW
                rotated_token = service.refresh_access_token("old-token", force=True)

            # Then
            account = service.get_account("rotated-token")

        self.assertEqual(rotated_token, "rotated-token")
        self.assertNotIn("old-token", service.list_tokens())
        account = _require_mapping(account)
        self.assertEqual(account["password"], "")
        refresh_request.assert_called_once()
        self.assertEqual(refresh_request.call_args.args[0], "refresh-token")

    def test_refresh_error_is_redacted_in_persistence_and_account_log(self) -> None:
        # Given
        secret = "refresh-error-secret"
        with tempfile.TemporaryDirectory() as tmp_dir:
            service = self._service(tmp_dir)
            service.add_account_items(
                [{"access_token": "stored-access", "refresh_token": "stored-refresh"}]
            )

            # When
            with mock.patch("services.account_service.log_service.add") as add_log:
                service._record_token_refresh_error(
                    "stored-access",
                    "keepalive",
                    f"oauth_refresh_http_401: refresh_token={secret} request_id=req-safe",
                )
            account = service.get_account("stored-access")

        # Then
        account = _require_mapping(account)
        persisted_error = str(account["last_token_refresh_error"])
        logged_error = str(add_log.call_args.args[2]["error"])
        self.assertNotIn(secret, persisted_error)
        self.assertNotIn(secret, logged_error)
        self.assertIn("oauth_refresh_http_401", persisted_error)
        self.assertIn("req-safe", persisted_error)
        self.assertEqual(account["access_token"], "stored-access")
        self.assertEqual(account["refresh_token"], "stored-refresh")

    def test_remote_and_invalid_errors_are_redacted_before_persistence_and_logging(self) -> None:
        # Given
        secret = "remote-error-secret"
        with tempfile.TemporaryDirectory() as tmp_dir:
            service = self._service(tmp_dir)
            service.add_account_items([{"access_token": "stored-access", "status": "正常"}])

            # When
            service._record_remote_check_error(
                "stored-access",
                "remote-check",
                f"HTTP 503 Authorization: Bearer {secret} path=/backend/me",
            )
            remote_account = _require_mapping(service.get_account("stored-access"))
            with mock.patch("services.account_service.log_service.add") as add_log:
                service._record_invalid_token_seen(
                    "stored-access",
                    "remote-check",
                    f"HTTP 401 Cookie={secret} path=/backend/me",
                )
            invalid_account = service.get_account("stored-access")

        # Then
        invalid_account = _require_mapping(invalid_account)
        values = (
            str(remote_account["last_remote_check_error"]),
            str(invalid_account["last_refresh_error"]),
            str(invalid_account["last_remote_check_error"]),
            str(add_log.call_args.args[2]["error"]),
        )
        self.assertTrue(all(secret not in value for value in values))
        self.assertTrue(all("/backend/me" in value for value in values))

    def test_oauth_refresh_response_detail_is_redacted_without_altering_rotated_tokens(self) -> None:
        # Given
        secret = "response-refresh-secret"
        response = mock.Mock()
        response.status_code = 401
        response.text = f'{{"error":"invalid_grant","access_token":"{secret}"}}'
        response.json.return_value = {"error": "invalid_grant", "access_token": secret}
        session = mock.Mock()
        session.post.return_value = response
        with tempfile.TemporaryDirectory() as tmp_dir:
            service = self._service(tmp_dir)

            # When
            with mock.patch("curl_cffi.requests.Session", return_value=session), self.assertRaises(RuntimeError) as raised:
                service._request_access_token_refresh("real-refresh-input")

        # Then
        self.assertNotIn(secret, str(raised.exception))
        self.assertIn("oauth_refresh_http_401", str(raised.exception))
        self.assertEqual(session.post.call_args.kwargs["data"]["refresh_token"], "real-refresh-input")

    def test_passwordless_remote_success_stores_quota_status_and_preserves_empty_password(self) -> None:
        # Given
        with tempfile.TemporaryDirectory() as tmp_dir:
            service = self._service(tmp_dir)
            service.add_account_items(
                [{"access_token": "token-1", "password": "", "status": "正常", "quota": 0}]
            )
            backend = self._backend(
                result={"status": "正常", "quota": 9, "image_quota_unknown": False}
            )

            # When
            with mock.patch("services.openai_backend_api.OpenAIBackendAPI", return_value=backend):
                service.fetch_remote_info("token-1", event="passwordless_remote_check", remove_invalid=False)

            # Then
            account = service.get_account("token-1")

        account = _require_mapping(account)
        self.assertEqual(account["quota"], 9)
        self.assertEqual(account["status"], "正常")
        self.assertEqual(account["password"], "")

    def test_success_records_remote_confirmation(self) -> None:
        # Given
        with tempfile.TemporaryDirectory() as tmp_dir:
            service = self._service(tmp_dir)
            service.add_account_items([{"access_token": "token-1", "status": "正常"}])
            backend = self._backend(
                result={"status": "正常", "quota": 9, "image_quota_unknown": False}
            )

            # When
            with mock.patch("services.openai_backend_api.OpenAIBackendAPI", return_value=backend), mock.patch(
                "services.account_service.datetime", wraps=datetime
            ) as clock:
                clock.now.return_value = NOW
                service.fetch_remote_info("token-1", event="pool_confirmation", remove_invalid=False)
            account = service.get_account("token-1")

        # Then
        account = _require_mapping(account)
        self.assertEqual(account["last_remote_checked_at"], NOW.isoformat())
        self.assertEqual(account["last_remote_check_attempt_at"], NOW.isoformat())
        self.assertIsNone(account["last_remote_check_error"])
        self.assertIsNone(account["last_remote_check_error_at"])
        self.assertEqual(account["last_remote_check_event"], "pool_confirmation")
        self.assertEqual(account["last_remote_check_result"], "ok")
        self.assertEqual(account["status"], "正常")
        self.assertEqual(account["quota"], 9)

    def test_remote_error_records_attempt_without_overwriting_last_confirmation(self) -> None:
        # Given
        prior = (NOW - timedelta(hours=1)).isoformat()
        with tempfile.TemporaryDirectory() as tmp_dir:
            service = self._service(tmp_dir)
            service.add_account_items(
                [
                    {
                        "access_token": "token-1",
                        "status": "正常",
                        "quota": 4,
                        "last_remote_checked_at": prior,
                    }
                ]
            )
            backend = self._backend(error=RuntimeError("upstream unavailable"))

            # When
            with mock.patch("services.openai_backend_api.OpenAIBackendAPI", return_value=backend), mock.patch(
                "services.account_service.datetime", wraps=datetime
            ) as clock:
                clock.now.return_value = NOW
                with self.assertRaisesRegex(RuntimeError, "upstream unavailable"):
                    service.fetch_remote_info("token-1", event="pool_confirmation", remove_invalid=False)
            account = service.get_account("token-1")

        # Then
        account = _require_mapping(account)
        self.assertEqual(account["last_remote_checked_at"], prior)
        self.assertEqual(account["last_remote_check_attempt_at"], NOW.isoformat())
        self.assertEqual(account["last_remote_check_error"], "upstream unavailable")
        self.assertEqual(account["last_remote_check_error_at"], NOW.isoformat())
        self.assertEqual(account["last_remote_check_event"], "pool_confirmation")
        self.assertEqual(account["last_remote_check_result"], "error")
        self.assertEqual(account["status"], "正常")
        self.assertEqual(account["quota"], 4)

    def test_invalid_remote_token_records_unavailable_without_removal(self) -> None:
        # Given
        with tempfile.TemporaryDirectory() as tmp_dir:
            service = self._service(tmp_dir)
            service.add_account_items([{"access_token": "invalid-token", "status": "正常", "quota": 8}])
            backend = self._backend(error=InvalidAccessTokenError("HTTP 401"))

            # When
            with mock.patch("services.openai_backend_api.OpenAIBackendAPI", return_value=backend), mock.patch(
                "services.account_service.datetime", wraps=datetime
            ) as clock:
                clock.now.return_value = NOW
                with self.assertRaises(InvalidAccessTokenError):
                    service.fetch_remote_info("invalid-token", event="pool_confirmation", remove_invalid=False)
            account = service.get_account("invalid-token")

        # Then
        account = _require_mapping(account)
        self.assertEqual(account["last_remote_check_attempt_at"], NOW.isoformat())
        self.assertIn("HTTP 401", account["last_remote_check_error"])
        self.assertEqual(account["last_remote_check_error_at"], NOW.isoformat())
        self.assertEqual(account["last_remote_check_event"], "pool_confirmation")
        self.assertEqual(account["last_remote_check_result"], "invalid")
        self.assertEqual(account["status"], "异常")
        self.assertEqual(account["quota"], 0)

    def test_success_after_invalid_token_rotation_records_on_rotated_account(self) -> None:
        # Given
        with tempfile.TemporaryDirectory() as tmp_dir:
            service = self._service(tmp_dir)
            service.add_account_items(
                [{"access_token": "old-token", "refresh_token": "refresh-old", "status": "正常"}]
            )
            first_backend = self._backend(error=InvalidAccessTokenError("HTTP 401"))
            second_backend = self._backend(
                result={"status": "正常", "quota": 6, "image_quota_unknown": False}
            )
            refreshed_tokens = {
                "access_token": "rotated-token",
                "refresh_token": "refresh-new",
                "id_token": "id-new",
            }

            # When
            with mock.patch(
                "services.openai_backend_api.OpenAIBackendAPI",
                side_effect=[first_backend, second_backend],
            ) as backend_api, mock.patch.object(
                service, "_request_access_token_refresh", return_value=refreshed_tokens
            ) as refresh_request, mock.patch("services.account_service.datetime", wraps=datetime) as clock:
                clock.now.return_value = NOW
                result = service.fetch_remote_info("old-token", event="pool_confirmation", remove_invalid=False)
            account = service.get_account("rotated-token")

        # Then
        result = _require_mapping(result)
        self.assertEqual(result["access_token"], "rotated-token")
        self.assertNotIn("old-token", service.list_tokens())
        account = _require_mapping(account)
        self.assertEqual(account["last_remote_check_result"], "ok")
        self.assertEqual(account["last_remote_check_event"], "pool_confirmation")
        self.assertEqual(account["status"], "正常")
        self.assertEqual(account["quota"], 6)
        self.assertEqual(
            backend_api.call_args_list,
            [mock.call("old-token"), mock.call("rotated-token")],
        )
        refresh_request.assert_called_once()
        self.assertEqual(refresh_request.call_args.args[0], "refresh-old")


class RegisterTargetDecisionTests(unittest.TestCase):
    def test_register_update_preserves_zero_max_relogin_retries(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            register = RegisterService(Path(tmp_dir) / "register.json")

            updated = register.update({"max_relogin_retries": 0})

        self.assertEqual(updated["max_relogin_retries"], 0)

    def test_quota_target_requests_fresh_remote_metrics(self) -> None:
        # Given
        with tempfile.TemporaryDirectory() as tmp_dir:
            register = RegisterService(Path(tmp_dir) / "register.json")
            metrics = _pool_metrics(
                current_quota=5,
                current_available=1,
                estimated_quota=5,
                estimated_available=1,
                pool_last_checked_at=NOW.isoformat(),
                pool_refreshed=1,
            )

            # When
            with mock.patch(
                "services.register_service.account_service.evaluate_account_pool",
                return_value=metrics,
                create=True,
            ) as evaluate:
                reached = register._target_reached(
                    {"mode": "quota", "target_quota": 5},
                    submitted=0,
                )

        # Then
        self.assertTrue(reached)
        evaluate.assert_called_once_with(
            refresh_stale=True,
            target_quota=5,
            target_available=None,
        )

    def test_available_target_requests_fresh_remote_metrics(self) -> None:
        # Given
        with tempfile.TemporaryDirectory() as tmp_dir:
            register = RegisterService(Path(tmp_dir) / "register.json")
            metrics = _pool_metrics(current_quota=3, current_available=2)

            # When
            with mock.patch(
                "services.register_service.account_service.evaluate_account_pool",
                return_value=metrics,
                create=True,
            ) as evaluate:
                reached = register._target_reached(
                    {"mode": "available", "target_available": 2},
                    submitted=0,
                )

        # Then
        self.assertTrue(reached)
        evaluate.assert_called_once_with(
            refresh_stale=True,
            target_quota=None,
            target_available=2,
        )

    def test_total_target_does_not_request_remote_metrics(self) -> None:
        # Given
        with tempfile.TemporaryDirectory() as tmp_dir:
            register = RegisterService(Path(tmp_dir) / "register.json")

            # When
            with mock.patch(
                "services.register_service.account_service.evaluate_account_pool",
                create=True,
            ) as evaluate:
                reached = register._target_reached({"mode": "total", "total": 3}, submitted=3)

        # Then
        self.assertTrue(reached)
        evaluate.assert_not_called()

    def test_quota_target_rejects_estimated_quota(self) -> None:
        # Given
        with tempfile.TemporaryDirectory() as tmp_dir:
            register = RegisterService(Path(tmp_dir) / "register.json")
            metrics = _pool_metrics(current_quota=0, estimated_quota=100)

            # When
            with mock.patch(
                "services.register_service.account_service.evaluate_account_pool",
                return_value=metrics,
                create=True,
            ):
                reached = register._target_reached({"mode": "quota", "target_quota": 10}, submitted=0)

        # Then
        self.assertFalse(reached)

    def test_available_target_rejects_estimated_availability(self) -> None:
        # Given
        with tempfile.TemporaryDirectory() as tmp_dir:
            register = RegisterService(Path(tmp_dir) / "register.json")
            metrics = _pool_metrics(current_available=0, estimated_available=100)

            # When
            with mock.patch(
                "services.register_service.account_service.evaluate_account_pool",
                return_value=metrics,
                create=True,
            ):
                reached = register._target_reached(
                    {"mode": "available", "target_available": 10},
                    submitted=0,
                )

        # Then
        self.assertFalse(reached)


if __name__ == "__main__":
    unittest.main()
