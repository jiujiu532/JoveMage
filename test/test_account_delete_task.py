"""account_delete 任务：分批、cancel 批边界停止、tier 判定、batch_remaining。"""
from __future__ import annotations

import os
import unittest
from unittest import mock

os.environ.setdefault("CHATGPT2API_AUTH_KEY", "test-auth")

from api import accounts as accounts_api
from services.task_manager import BackgroundTask


class AccountDeleteTaskBodyTests(unittest.TestCase):
    def test_batches_by_20_and_reports_removed(self) -> None:
        tokens = [f"tok-{i}" for i in range(45)]
        calls: list[list[str]] = []

        def fake_delete(batch, return_items=False):
            calls.append(list(batch))
            return {"removed": len(batch), "items": []}

        task = BackgroundTask("t-del", "account_delete", total=len(tokens))
        with mock.patch.object(
            accounts_api.account_service, "delete_accounts", side_effect=fake_delete
        ), mock.patch.object(accounts_api.log_service, "add"):
            accounts_api._run_account_delete(task, tokens, scope="selected")

        self.assertEqual(task.status, "completed")
        self.assertEqual([len(c) for c in calls], [20, 20, 5])
        self.assertEqual(task.progress, 45)
        self.assertEqual(task.result.get("removed"), 45)
        self.assertEqual(task.result.get("processed"), 45)
        self.assertFalse(task.result.get("stopped"))
        self.assertEqual(task.batch_remaining, 0)
        self.assertEqual(task.current_batch_done, task.current_batch_size)

    def test_cancel_before_first_batch_stops(self) -> None:
        tokens = [f"tok-{i}" for i in range(25)]
        calls: list[list[str]] = []

        def fake_delete(batch, return_items=False):
            calls.append(list(batch))
            return {"removed": len(batch)}

        task = BackgroundTask("t-del-cancel", "account_delete", total=len(tokens))
        task.request_cancel()
        with mock.patch.object(
            accounts_api.account_service, "delete_accounts", side_effect=fake_delete
        ), mock.patch.object(accounts_api.log_service, "add"):
            accounts_api._run_account_delete(task, tokens, scope="all")

        self.assertEqual(task.status, "cancelled")
        self.assertEqual(calls, [])
        self.assertEqual(task.result.get("stopped"), True)
        self.assertEqual(task.result.get("processed"), 0)

    def test_cancel_at_batch_boundary_after_first_batch(self) -> None:
        tokens = [f"tok-{i}" for i in range(45)]
        calls: list[list[str]] = []

        def fake_delete(batch, return_items=False):
            calls.append(list(batch))
            if len(calls) == 1:
                task.request_cancel()
            return {"removed": len(batch)}

        task = BackgroundTask("t-del-mid", "account_delete", total=len(tokens))
        with mock.patch.object(
            accounts_api.account_service, "delete_accounts", side_effect=fake_delete
        ), mock.patch.object(accounts_api.log_service, "add"):
            accounts_api._run_account_delete(task, tokens, scope="selected")

        self.assertEqual(task.status, "cancelled")
        self.assertEqual(len(calls), 1)
        self.assertEqual(len(calls[0]), 20)
        self.assertEqual(task.progress, 20)
        self.assertEqual(task.result.get("removed"), 20)
        self.assertEqual(task.result.get("stopped"), True)

    def test_batch_remaining_set_at_batch_start(self) -> None:
        tokens = [f"tok-{i}" for i in range(7)]
        seen_remaining: list[int] = []

        def fake_delete(batch, return_items=False):
            seen_remaining.append(int(task.batch_remaining))
            return {"removed": len(batch)}

        task = BackgroundTask("t-del-br", "account_delete", total=7)
        with mock.patch.object(
            accounts_api.account_service, "delete_accounts", side_effect=fake_delete
        ), mock.patch.object(accounts_api.log_service, "add"):
            accounts_api._run_account_delete(task, tokens)

        self.assertEqual(seen_remaining, [7])
        self.assertEqual(task.batch_remaining, 0)

    def test_tier_helpers_shared_with_refresh(self) -> None:
        # 与 refresh 共用同一判定函数
        self.assertEqual(
            accounts_api._resolve_account_task_tier(["x"] * 51),
            "heavy",
        )
        self.assertEqual(
            accounts_api._resolve_account_task_tier(["x"] * 2, scope="filter"),
            "heavy",
        )
        self.assertEqual(
            accounts_api._resolve_account_task_tier(["x"] * 2, scope="selected"),
            "light",
        )


class AccountDeleteSubmitTierTests(unittest.TestCase):
    def test_submit_account_task_fallback_without_tier_kw(self) -> None:
        """基建未合入时 _submit_account_task 应回落旧 submit 签名。"""
        ran = {"ok": False}

        def fn(task):
            ran["ok"] = True
            task.complete(ok=True)

        # 直接测 helper：当前 task_manager.submit 不接受 tier
        task = accounts_api._submit_account_task(
            "account_delete", 1, fn, tier="light"
        )
        # 线程异步，等片刻
        import time

        for _ in range(50):
            if task.status != "running":
                break
            time.sleep(0.02)
        self.assertIn(task.status, ("completed", "failed", "cancelled"))
        self.assertTrue(ran["ok"] or task.status == "completed")


if __name__ == "__main__":
    unittest.main()
