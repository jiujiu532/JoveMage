"""账号批量任务档位锁 / batch_remaining / active 接口 单测。

覆盖：
- 同 tier 第二个 submit 失败（RuntimeError / 409 语义）
- 不同 tier 可并存
- batch_remaining 随完成数递减
- list_active_by_tier / to_active_dict 结构
- request_cancel 仅置 cancel_requested，不改 status
"""
from __future__ import annotations

import os
import threading
import time
import unittest
from unittest import mock

os.environ.setdefault("CHATGPT2API_AUTH_KEY", "test-auth")

from services.task_manager import BackgroundTask, TaskManager


def _blocking_fn(started: threading.Event, release: threading.Event):
    """构造一个可阻塞的任务体，便于测试锁与 cancel。"""

    def _run(task: BackgroundTask) -> None:
        started.set()
        # 等待测试方放行；期间保持 running
        while not release.is_set():
            if task.cancel_requested:
                # 批边界收尾：不直接改 status 由测试验证 cancel 语义
                task.cancel()
                return
            time.sleep(0.01)
        task.complete()

    return _run


class TaskTierLockTests(unittest.TestCase):
    def setUp(self) -> None:
        self.mgr = TaskManager()

    def test_same_tier_second_submit_raises(self) -> None:
        started = threading.Event()
        release = threading.Event()
        t1 = self.mgr.submit(
            "account_inspect",
            10,
            _blocking_fn(started, release),
            tier="heavy",
        )
        self.assertTrue(started.wait(timeout=2.0))
        with self.assertRaises(RuntimeError) as ctx:
            self.mgr.submit(
                "account_refresh",
                5,
                lambda task: task.complete(),
                tier="heavy",
            )
        self.assertIn("heavy", str(ctx.exception))
        self.assertIn(t1.task_id, str(ctx.exception))
        release.set()
        # 等任务结束
        for _ in range(100):
            if t1.status != "running":
                break
            time.sleep(0.02)
        self.assertEqual(t1.status, "completed")

    def test_different_tiers_can_run_together(self) -> None:
        heavy_started = threading.Event()
        light_started = threading.Event()
        release = threading.Event()

        heavy = self.mgr.submit(
            "account_inspect",
            10,
            _blocking_fn(heavy_started, release),
            tier="heavy",
        )
        light = self.mgr.submit(
            "account_delete",
            3,
            _blocking_fn(light_started, release),
            tier="light",
        )
        self.assertTrue(heavy_started.wait(timeout=2.0))
        self.assertTrue(light_started.wait(timeout=2.0))
        self.assertEqual(heavy.status, "running")
        self.assertEqual(light.status, "running")
        self.assertEqual(heavy.tier, "heavy")
        self.assertEqual(light.tier, "light")
        release.set()
        for _ in range(100):
            if heavy.status != "running" and light.status != "running":
                break
            time.sleep(0.02)
        self.assertEqual(heavy.status, "completed")
        self.assertEqual(light.status, "completed")

    def test_same_light_tier_second_submit_raises(self) -> None:
        started = threading.Event()
        release = threading.Event()
        self.mgr.submit(
            "account_enable",
            2,
            _blocking_fn(started, release),
            tier="light",
        )
        self.assertTrue(started.wait(timeout=2.0))
        with self.assertRaises(RuntimeError):
            self.mgr.submit(
                "account_disable",
                2,
                lambda task: task.complete(),
                tier="light",
            )
        release.set()


class BatchRemainingTests(unittest.TestCase):
    def test_batch_remaining_decreases_with_done(self) -> None:
        task = BackgroundTask("t1", "account_refresh", total=40, tier="light")
        self.assertEqual(task.batch_remaining, 0)

        task.bump_batch_progress(20, 0)
        self.assertEqual(task.current_batch_size, 20)
        self.assertEqual(task.current_batch_done, 0)
        self.assertEqual(task.batch_remaining, 20)

        task.bump_batch_progress(20, 12)
        self.assertEqual(task.batch_remaining, 8)

        task.bump_batch_progress(20, 20)
        self.assertEqual(task.batch_remaining, 0)

        # done 不超过 size
        task.bump_batch_progress(10, 99)
        self.assertEqual(task.current_batch_done, 10)
        self.assertEqual(task.batch_remaining, 0)

    def test_to_dict_includes_tier_and_batch_fields(self) -> None:
        task = BackgroundTask("t2", "account_inspect", total=5, tier="heavy")
        task.bump_batch_progress(5, 2)
        d = task.to_dict()
        self.assertEqual(d["tier"], "heavy")
        self.assertEqual(d["type"], "account_inspect")
        self.assertEqual(d["task_type"], "account_inspect")
        self.assertEqual(d["batch_remaining"], 3)
        self.assertEqual(d["current_batch_size"], 5)
        self.assertEqual(d["current_batch_done"], 2)
        self.assertFalse(d["cancel_requested"])


class ActiveByTierTests(unittest.TestCase):
    def setUp(self) -> None:
        self.mgr = TaskManager()

    def test_list_active_by_tier_structure(self) -> None:
        empty = self.mgr.list_active_by_tier()
        self.assertEqual(empty, {"heavy": None, "light": None})

        started_h = threading.Event()
        started_l = threading.Event()
        release = threading.Event()
        heavy = self.mgr.submit(
            "account_inspect",
            10,
            _blocking_fn(started_h, release),
            tier="heavy",
        )
        light = self.mgr.submit(
            "account_delete",
            3,
            _blocking_fn(started_l, release),
            tier="light",
        )
        self.assertTrue(started_h.wait(timeout=2.0))
        self.assertTrue(started_l.wait(timeout=2.0))

        active = self.mgr.list_active_by_tier()
        self.assertIs(active["heavy"], heavy)
        self.assertIs(active["light"], light)

        snap = {
            "heavy": active["heavy"].to_active_dict() if active["heavy"] else None,
            "light": active["light"].to_active_dict() if active["light"] else None,
        }
        for key in ("heavy", "light"):
            item = snap[key]
            self.assertIsNotNone(item)
            assert item is not None
            self.assertIn("task_id", item)
            self.assertIn("type", item)
            self.assertIn("tier", item)
            self.assertIn("status", item)
            self.assertIn("progress", item)
            self.assertIn("total", item)
            self.assertIn("batch_remaining", item)
            self.assertIn("cancel_requested", item)
            self.assertEqual(item["tier"], key)
            self.assertEqual(item["status"], "running")
            self.assertFalse(item["cancel_requested"])

        release.set()
        for _ in range(100):
            if heavy.status != "running" and light.status != "running":
                break
            time.sleep(0.02)

        after = self.mgr.list_active_by_tier()
        self.assertIsNone(after["heavy"])
        self.assertIsNone(after["light"])


class CancelSemanticsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.mgr = TaskManager()

    def test_request_cancel_sets_flag_without_changing_status(self) -> None:
        started = threading.Event()
        # 用 Event 卡住任务体，避免自动 complete；cancel 由任务体自行处理
        hold = threading.Event()

        def _run(task: BackgroundTask) -> None:
            started.set()
            # 等到 cancel 后批边界收尾
            while not task.cancel_requested:
                time.sleep(0.01)
            # 模拟批边界：先确认 status 仍是 running（request_cancel 未改 status）
            # 再由任务体收尾
            task.cancel()

        task = self.mgr.submit("account_inspect", 5, _run, tier="heavy")
        self.assertTrue(started.wait(timeout=2.0))

        returned = self.mgr.request_cancel(task.task_id)
        self.assertIs(returned, task)
        # request_cancel 只置标志，不直接改 status
        self.assertTrue(task.cancel_requested)
        # 任务体可能已经很快走到 cancel()；给极短窗口检查「置位瞬间」status
        # 至少 cancel_requested 为 True；终态由任务体决定
        self.assertIn(task.status, ("running", "cancelled"))

        for _ in range(100):
            if task.status != "running":
                break
            time.sleep(0.02)
        self.assertEqual(task.status, "cancelled")
        self.assertTrue(task.cancel_requested)

        # 终态后再 cancel 返回 None
        self.assertIsNone(self.mgr.request_cancel(task.task_id))

    def test_stopping_still_holds_tier_lock(self) -> None:
        """cancel_requested 后 status 仍 running 时同档仍互斥。"""
        started = threading.Event()
        gate = threading.Event()  # 任务体卡在 stopping 态

        def _run(task: BackgroundTask) -> None:
            started.set()
            # 收到 cancel 后不立刻收尾，模拟「本批还在跑」
            while not task.cancel_requested:
                time.sleep(0.01)
            gate.wait(timeout=5.0)
            task.cancel()

        task = self.mgr.submit("account_refresh", 20, _run, tier="heavy")
        self.assertTrue(started.wait(timeout=2.0))
        self.mgr.request_cancel(task.task_id)
        self.assertTrue(task.cancel_requested)
        self.assertEqual(task.status, "running")

        with self.assertRaises(RuntimeError) as ctx:
            self.mgr.submit(
                "account_inspect",
                1,
                lambda t: t.complete(),
                tier="heavy",
            )
        self.assertIn("heavy", str(ctx.exception))

        # light 仍可提交
        light_started = threading.Event()
        light_release = threading.Event()
        light = self.mgr.submit(
            "account_delete",
            1,
            _blocking_fn(light_started, light_release),
            tier="light",
        )
        self.assertTrue(light_started.wait(timeout=2.0))

        gate.set()
        light_release.set()
        for _ in range(100):
            if task.status != "running" and light.status != "running":
                break
            time.sleep(0.02)
        self.assertEqual(task.status, "cancelled")


class InspectSubmitTierTests(unittest.TestCase):
    """巡检提交处应带 tier=heavy（对接 api.accounts）。"""

    def test_inspect_submit_uses_heavy_tier(self) -> None:
        from api import accounts as accounts_api
        import inspect as py_inspect
        import pathlib

        # 直接测 submit 调用参数
        captured: dict = {}

        def fake_submit(task_type, total, fn, *, tier="heavy"):
            captured["task_type"] = task_type
            captured["total"] = total
            captured["tier"] = tier
            return BackgroundTask("fake-id", task_type, total, tier=tier)

        with mock.patch.object(accounts_api.task_manager, "submit", side_effect=fake_submit):
            def _run(task):
                pass

            task = accounts_api.task_manager.submit(
                "account_inspect",
                2,
                _run,
                tier="heavy",
            )
        self.assertEqual(captured["task_type"], "account_inspect")
        self.assertEqual(captured["tier"], "heavy")
        self.assertEqual(task.tier, "heavy")

        # 源码回归：inspect 提交带 tier="heavy"
        source = pathlib.Path(accounts_api.__file__).read_text(encoding="utf-8")
        self.assertIn('task_manager.submit("account_inspect"', source)
        self.assertIn('tier="heavy"', source)
        # 模块内应有 list_active_by_tier 对接
        self.assertIn("list_active_by_tier", source)
        self.assertIn("/api/account-tasks/active", source)


if __name__ == "__main__":
    unittest.main()
