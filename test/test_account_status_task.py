"""账号启停/重置/重登任务：分批、cancel、tier、batch_remaining 单测。"""
from __future__ import annotations

import os
import unittest
from unittest import mock

os.environ.setdefault("CHATGPT2API_AUTH_KEY", "test-auth")

import api.accounts as accounts_api
from services.task_manager import BackgroundTask


def _acct(token: str, *, status: str = "异常", email: str = "u@example.com") -> dict:
    return {
        "access_token": token,
        "status": status,
        "email": email,
        "password": "",
        "proxy": "",
    }


class ResolveStatusActionTests(unittest.TestCase):
    def test_action_priority(self) -> None:
        action, status = accounts_api._resolve_status_action(action="disable", status="正常")
        self.assertEqual(action, "disable")
        self.assertEqual(status, "禁用")

        action, status = accounts_api._resolve_status_action(action="reset", status=None)
        self.assertEqual(action, "reset")
        self.assertEqual(status, "正常")

    def test_status_fallback(self) -> None:
        action, status = accounts_api._resolve_status_action(action=None, status="禁用")
        self.assertEqual(action, "disable")
        self.assertEqual(status, "禁用")

        action, status = accounts_api._resolve_status_action(action=None, status="正常")
        self.assertEqual(action, "enable")
        self.assertEqual(status, "正常")

    def test_missing_raises(self) -> None:
        with self.assertRaises(ValueError):
            accounts_api._resolve_status_action(action=None, status=None)


class ResolveTierTests(unittest.TestCase):
    def test_explicit_tier(self) -> None:
        self.assertEqual(
            accounts_api._resolve_account_task_tier(["a"] * 3, tier="heavy"),
            "heavy",
        )
        self.assertEqual(
            accounts_api._resolve_account_task_tier(["a"] * 60, tier="light"),
            "light",
        )

    def test_count_threshold(self) -> None:
        self.assertEqual(
            accounts_api._resolve_account_task_tier(["a"] * 50, scope="selected"),
            "light",
        )
        self.assertEqual(
            accounts_api._resolve_account_task_tier(["a"] * 51, scope="selected"),
            "heavy",
        )


class AccountStatusTaskBodyTests(unittest.TestCase):
    def test_batches_of_20_and_batch_remaining(self) -> None:
        tokens = [f"tok-{i}" for i in range(45)]
        store = {t: _acct(t, status="禁用") for t in tokens}
        seen_batch_remaining: list[int] = []
        seen_batch_sizes: list[int] = []
        updated_tokens: list[str] = []

        def update_account(token: str, updates: dict, quiet: bool = False):
            updated_tokens.append(token)
            item = dict(store[token])
            item.update(updates)
            store[token] = item
            return dict(item)

        real_bump = accounts_api._bump_task_batch_progress

        def tracking_bump(task, *, progress, batch_remaining, current_batch_size=0, current_batch_done=0, **kw):
            seen_batch_remaining.append(int(batch_remaining))
            seen_batch_sizes.append(int(current_batch_size or 0))
            return real_bump(
                task,
                progress=progress,
                batch_remaining=batch_remaining,
                current_batch_size=current_batch_size,
                current_batch_done=current_batch_done,
                **kw,
            )

        task = BackgroundTask("status-batch", "account_enable", total=45, tier="light")
        with mock.patch.object(accounts_api.account_service, "update_account", side_effect=update_account), mock.patch.object(
            accounts_api.log_service, "add"
        ), mock.patch.object(accounts_api, "_bump_task_batch_progress", side_effect=tracking_bump):
            accounts_api._run_account_status(task, tokens, status="正常", action="enable")

        self.assertEqual(task.status, "completed")
        self.assertEqual(task.result.get("updated"), 45)
        self.assertEqual(task.result.get("processed"), 45)
        self.assertEqual(task.result.get("stopped"), False)
        self.assertEqual(len(updated_tokens), 45)
        # 分三批：20 / 20 / 5
        self.assertIn(20, seen_batch_sizes)
        self.assertIn(5, seen_batch_sizes)
        # batch_remaining 曾从 20 递减到 0
        self.assertTrue(any(r == 20 for r in seen_batch_remaining))
        self.assertTrue(any(r == 0 for r in seen_batch_remaining))
        self.assertEqual(task.batch_remaining, 0)

    def test_cancel_before_first_batch_stops(self) -> None:
        tokens = [f"tok-{i}" for i in range(25)]
        calls = []

        def update_account(token: str, updates: dict, quiet: bool = False):
            calls.append(token)
            return _acct(token, status=updates.get("status", "正常"))

        task = BackgroundTask("status-cancel", "account_disable", total=25, tier="light")
        task.request_cancel()
        with mock.patch.object(accounts_api.account_service, "update_account", side_effect=update_account), mock.patch.object(
            accounts_api.log_service, "add"
        ):
            accounts_api._run_account_status(task, tokens, status="禁用", action="disable")

        self.assertEqual(task.status, "cancelled")
        self.assertEqual(task.result.get("stopped"), True)
        self.assertEqual(task.result.get("processed"), 0)
        self.assertEqual(calls, [])

    def test_cancel_midway_keeps_processed(self) -> None:
        tokens = [f"tok-{i}" for i in range(45)]
        calls: list[str] = []

        def update_account(token: str, updates: dict, quiet: bool = False):
            calls.append(token)
            # 第一批跑完后请求停止
            if len(calls) == 20:
                task.request_cancel()
            return _acct(token, status=updates.get("status", "正常"))

        task = BackgroundTask("status-mid-cancel", "account_reset", total=45, tier="light")
        with mock.patch.object(accounts_api.account_service, "update_account", side_effect=update_account), mock.patch.object(
            accounts_api.log_service, "add"
        ):
            accounts_api._run_account_status(task, tokens, status="正常", action="reset")

        self.assertEqual(task.status, "cancelled")
        self.assertEqual(task.result.get("stopped"), True)
        self.assertEqual(task.result.get("processed"), 20)
        self.assertEqual(task.result.get("updated"), 20)
        self.assertEqual(len(calls), 20)

    def test_not_found_counted_as_error(self) -> None:
        tokens = ["tok-ok", "tok-missing"]

        def update_account(token: str, updates: dict, quiet: bool = False):
            if token == "tok-missing":
                return None
            return _acct(token, status="正常")

        task = BackgroundTask("status-err", "account_enable", total=2, tier="light")
        with mock.patch.object(accounts_api.account_service, "update_account", side_effect=update_account), mock.patch.object(
            accounts_api.log_service, "add"
        ):
            accounts_api._run_account_status(task, tokens, status="正常", action="enable")

        self.assertEqual(task.status, "completed")
        self.assertEqual(task.result.get("updated"), 1)
        self.assertEqual(task.result.get("processed"), 2)
        self.assertTrue(task.result.get("errors"))


class ReloginBatchTaskBodyTests(unittest.TestCase):
    def test_cancel_before_first_account_stops(self) -> None:
        tokens = [f"tok-{i}" for i in range(3)]
        relogin_calls = []

        task = BackgroundTask("relogin-cancel", "account_relogin", total=3, tier="light")
        task.request_cancel()
        with mock.patch.object(accounts_api.account_service, "get_account", return_value=_acct("x")), mock.patch.object(
            accounts_api, "_openai_relogin", side_effect=lambda *a, **k: relogin_calls.append(1) or {}
        ), mock.patch.object(accounts_api.log_service, "add"):
            accounts_api._run_relogin_batch(task, tokens)

        self.assertEqual(task.status, "cancelled")
        self.assertEqual(task.result.get("stopped"), True)
        self.assertEqual(task.result.get("processed"), 0)
        self.assertEqual(relogin_calls, [])

    def test_success_and_batch_remaining_unit(self) -> None:
        tokens = ["tok-a", "tok-b"]
        store = {t: _acct(t, email=f"{t}@example.com") for t in tokens}
        applied: list[str] = []

        def get_account(token: str):
            item = store.get(token)
            return dict(item) if item else None

        def relogin(email, password, proxy, fp):
            return {
                "access_token": f"new-{email}",
                "refresh_token": "rt",
                "token_expires_at": "",
            }

        def apply_relogin_tokens(old_token, token_data):
            applied.append(old_token)
            return token_data["access_token"]

        remainings: list[int] = []
        sizes: list[int] = []
        real_bump = accounts_api._bump_task_batch_progress

        def tracking_bump(task, *, progress, batch_remaining, current_batch_size=0, current_batch_done=0, **kw):
            remainings.append(int(batch_remaining))
            sizes.append(int(current_batch_size or 0))
            return real_bump(
                task,
                progress=progress,
                batch_remaining=batch_remaining,
                current_batch_size=current_batch_size,
                current_batch_done=current_batch_done,
                **kw,
            )

        task = BackgroundTask("relogin-ok", "account_relogin", total=2, tier="light")
        with mock.patch.object(accounts_api.account_service, "get_account", side_effect=get_account), mock.patch.object(
            accounts_api, "_openai_relogin", side_effect=relogin
        ), mock.patch.object(
            accounts_api.account_service, "apply_relogin_tokens", side_effect=apply_relogin_tokens
        ), mock.patch.object(accounts_api.log_service, "add"), mock.patch.object(
            accounts_api, "_bump_task_batch_progress", side_effect=tracking_bump
        ):
            accounts_api._run_relogin_batch(task, tokens)

        self.assertEqual(task.status, "completed")
        self.assertEqual(task.result.get("success"), 2)
        self.assertEqual(task.result.get("failed"), 0)
        self.assertEqual(task.result.get("processed"), 2)
        self.assertEqual(applied, tokens)
        # 逐条批=1：出现过 remaining=1 与 0
        self.assertIn(1, remainings)
        self.assertIn(0, remainings)
        self.assertTrue(all(s in (0, 1) for s in sizes))
        self.assertEqual(task.current_batch_size, 1)

    def test_missing_email_counts_failed(self) -> None:
        tokens = ["tok-no-email"]
        task = BackgroundTask("relogin-fail", "account_relogin", total=1, tier="light")
        with mock.patch.object(
            accounts_api.account_service,
            "get_account",
            return_value=_acct("tok-no-email", email=""),
        ), mock.patch.object(accounts_api.log_service, "add"):
            accounts_api._run_relogin_batch(task, tokens)

        self.assertEqual(task.status, "completed")
        self.assertEqual(task.result.get("success"), 0)
        self.assertEqual(task.result.get("failed"), 1)
        self.assertTrue(task.result.get("errors"))


class StatusTaskTierSubmitTests(unittest.TestCase):
    def test_submit_account_task_passes_tier(self) -> None:
        captured = {}

        def fake_submit(task_type, total, fn, *, tier="heavy"):
            captured["task_type"] = task_type
            captured["total"] = total
            captured["tier"] = tier
            task = BackgroundTask("x", task_type, total, tier=tier)
            return task

        with mock.patch.object(accounts_api.task_manager, "submit", side_effect=fake_submit):
            task = accounts_api._submit_account_task(
                "account_enable",
                3,
                lambda t: t.complete(),
                tier="light",
            )
        self.assertEqual(captured["task_type"], "account_enable")
        self.assertEqual(captured["tier"], "light")
        self.assertEqual(task.tier, "light")


if __name__ == "__main__":
    unittest.main()
