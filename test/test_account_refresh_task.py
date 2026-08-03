"""account_refresh 任务：分批、cancel 批边界停止、tier 判定、batch_remaining。"""
from __future__ import annotations

import os
import unittest
from unittest import mock

os.environ.setdefault("CHATGPT2API_AUTH_KEY", "test-auth")

from api import accounts as accounts_api
from services.task_manager import BackgroundTask


class ResolveTierTests(unittest.TestCase):
    def test_explicit_tier_wins(self) -> None:
        self.assertEqual(
            accounts_api._resolve_account_task_tier(["a"] * 3, scope="all", tier="light"),
            "light",
        )
        self.assertEqual(
            accounts_api._resolve_account_task_tier(["a"], scope="selected", tier="heavy"),
            "heavy",
        )

    def test_scope_filter_channel_all_is_heavy(self) -> None:
        for scope in ("filter", "channel", "all"):
            self.assertEqual(
                accounts_api._resolve_account_task_tier(["a"], scope=scope),
                "heavy",
                msg=scope,
            )

    def test_count_over_50_is_heavy(self) -> None:
        tokens = [f"t{i}" for i in range(51)]
        self.assertEqual(accounts_api._resolve_account_task_tier(tokens), "heavy")

    def test_count_le_50_selected_is_light(self) -> None:
        tokens = [f"t{i}" for i in range(50)]
        self.assertEqual(
            accounts_api._resolve_account_task_tier(tokens, scope="selected"),
            "light",
        )
        self.assertEqual(accounts_api._resolve_account_task_tier(tokens), "light")


class AccountRefreshTaskBodyTests(unittest.TestCase):
    def test_batches_by_20_and_reports_progress(self) -> None:
        tokens = [f"tok-{i}" for i in range(45)]
        calls: list[list[str]] = []

        def fake_refresh(batch, progress_id=None, remove_invalid=None):
            calls.append(list(batch))
            return {"refreshed": len(batch), "errors": [], "items": []}

        task = BackgroundTask("t-refresh", "account_refresh", total=len(tokens))
        with mock.patch.object(
            accounts_api.account_service, "refresh_accounts", side_effect=fake_refresh
        ), mock.patch.object(accounts_api.log_service, "add"):
            accounts_api._run_account_refresh(task, tokens, scope="selected")

        self.assertEqual(task.status, "completed")
        self.assertEqual([len(c) for c in calls], [20, 20, 5])
        self.assertEqual(task.progress, 45)
        self.assertEqual(task.result.get("refreshed"), 45)
        self.assertEqual(task.result.get("processed"), 45)
        self.assertFalse(task.result.get("stopped"))
        # 批结束后 batch_remaining 属性应为 0
        self.assertEqual(task.batch_remaining, 0)
        self.assertEqual(task.current_batch_done, task.current_batch_size)

    def test_cancel_before_first_batch_stops(self) -> None:
        tokens = [f"tok-{i}" for i in range(30)]
        calls: list[list[str]] = []

        def fake_refresh(batch, progress_id=None, remove_invalid=None):
            calls.append(list(batch))
            return {"refreshed": len(batch), "errors": []}

        task = BackgroundTask("t-cancel", "account_refresh", total=len(tokens))
        task.request_cancel()
        with mock.patch.object(
            accounts_api.account_service, "refresh_accounts", side_effect=fake_refresh
        ), mock.patch.object(accounts_api.log_service, "add"):
            accounts_api._run_account_refresh(task, tokens, scope="all")

        self.assertEqual(task.status, "cancelled")
        self.assertEqual(calls, [])
        self.assertEqual(task.result.get("stopped"), True)
        self.assertEqual(task.result.get("processed"), 0)

    def test_cancel_at_batch_boundary_after_first_batch(self) -> None:
        tokens = [f"tok-{i}" for i in range(45)]
        calls: list[list[str]] = []

        def fake_refresh(batch, progress_id=None, remove_invalid=None):
            calls.append(list(batch))
            # 第一批完成后请求停止
            if len(calls) == 1:
                task.request_cancel()
            return {"refreshed": len(batch), "errors": []}

        task = BackgroundTask("t-mid-cancel", "account_refresh", total=len(tokens))
        with mock.patch.object(
            accounts_api.account_service, "refresh_accounts", side_effect=fake_refresh
        ), mock.patch.object(accounts_api.log_service, "add"):
            accounts_api._run_account_refresh(task, tokens, scope="selected")

        self.assertEqual(task.status, "cancelled")
        self.assertEqual(len(calls), 1)
        self.assertEqual(len(calls[0]), 20)
        self.assertEqual(task.progress, 20)
        self.assertEqual(task.result.get("stopped"), True)
        self.assertEqual(task.result.get("processed"), 20)

    def test_batch_remaining_set_at_batch_start(self) -> None:
        """批开始时 batch_remaining=len(batch)，批结束清零。"""
        tokens = [f"tok-{i}" for i in range(5)]
        seen_remaining: list[int] = []

        def fake_refresh(batch, progress_id=None, remove_invalid=None):
            # 批开始后、本函数调用时 task.batch_remaining 应为 len(batch)
            seen_remaining.append(int(task.batch_remaining))
            return {"refreshed": len(batch), "errors": []}

        task = BackgroundTask("t-br", "account_refresh", total=5)
        with mock.patch.object(
            accounts_api.account_service, "refresh_accounts", side_effect=fake_refresh
        ), mock.patch.object(accounts_api.log_service, "add"):
            accounts_api._run_account_refresh(task, tokens)

        self.assertEqual(seen_remaining, [5])
        self.assertEqual(task.batch_remaining, 0)


if __name__ == "__main__":
    unittest.main()
