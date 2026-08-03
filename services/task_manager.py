"""后台任务管理器 — 内存中存储任务状态，供长时间操作使用。"""

from __future__ import annotations

import threading
import uuid
from datetime import datetime, timezone
from typing import Any, Callable, Literal

TaskTier = Literal["light", "heavy"]
_VALID_TIERS: frozenset[str] = frozenset({"light", "heavy"})


class BackgroundTask:
    __slots__ = (
        "task_id",
        "task_type",
        "tier",
        "status",
        "progress",
        "total",
        "current_batch_size",
        "current_batch_done",
        "result",
        "error",
        "created_at",
        "updated_at",
        "_cancel_event",
    )

    def __init__(
        self,
        task_id: str,
        task_type: str,
        total: int = 0,
        *,
        tier: str = "heavy",
    ) -> None:
        if tier not in _VALID_TIERS:
            raise ValueError(f"invalid tier: {tier!r}, expected light|heavy")
        self.task_id = task_id
        self.task_type = task_type
        self.tier: str = tier
        self.status: str = "running"  # running | completed | failed | cancelled
        self.progress: int = 0
        self.total: int = total
        # 当前执行批次进度（用于停止中展示「本批剩余」）
        self.current_batch_size: int = 0
        self.current_batch_done: int = 0
        self.result: dict[str, Any] = {}
        self.error: str = ""
        self.created_at: str = datetime.now(timezone.utc).isoformat()
        self.updated_at: str = self.created_at
        self._cancel_event = threading.Event()

    @property
    def cancel_requested(self) -> bool:
        return self._cancel_event.is_set()

    @property
    def batch_remaining(self) -> int:
        """当前批剩余未完成账号数；无批次时为 0。"""
        remaining = self.current_batch_size - self.current_batch_done
        return remaining if remaining > 0 else 0

    def request_cancel(self) -> None:
        self._cancel_event.set()

    def cancel(self) -> None:
        """任务体检测到 cancel_requested 后主动收尾调用。"""
        self.status = "cancelled"
        self.updated_at = datetime.now(timezone.utc).isoformat()

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "task_type": self.task_type,
            "type": self.task_type,
            "tier": self.tier,
            "status": self.status,
            "progress": self.progress,
            "total": self.total,
            "current_batch_size": self.current_batch_size,
            "current_batch_done": self.current_batch_done,
            "batch_remaining": self.batch_remaining,
            "cancel_requested": self.cancel_requested,
            "result": self.result,
            "error": self.error,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    def to_active_dict(self) -> dict[str, Any]:
        """GET /api/account-tasks/active 用的精简快照。"""
        return {
            "task_id": self.task_id,
            "type": self.task_type,
            "tier": self.tier,
            "status": self.status,
            "progress": self.progress,
            "total": self.total,
            "batch_remaining": self.batch_remaining,
            "cancel_requested": self.cancel_requested,
        }

    def bump(self, progress: int | None = None, **result_updates: Any) -> None:
        if progress is not None:
            self.progress = progress
        if result_updates:
            self.result.update(result_updates)
        self.updated_at = datetime.now(timezone.utc).isoformat()

    def bump_batch_progress(
        self,
        current_batch_size: int,
        current_batch_done: int,
    ) -> None:
        """更新当前批进度；每完成一个账号调用一次，batch_remaining 随之递减。"""
        self.current_batch_size = max(0, int(current_batch_size))
        self.current_batch_done = max(0, int(current_batch_done))
        if self.current_batch_done > self.current_batch_size:
            self.current_batch_done = self.current_batch_size
        self.updated_at = datetime.now(timezone.utc).isoformat()

    def complete(self, **result_updates: Any) -> None:
        self.status = "completed"
        if result_updates:
            self.result.update(result_updates)
        self.updated_at = datetime.now(timezone.utc).isoformat()

    def fail(self, error: str) -> None:
        self.status = "failed"
        self.error = error
        self.updated_at = datetime.now(timezone.utc).isoformat()


class TaskManager:
    """全局唯一的后台任务管理器。

    锁按档位（tier: light | heavy）互斥：
    - 同 tier 同时只能有一个 running（含 stopping=cancel_requested）任务
    - 不同 tier 可并行
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._tasks: dict[str, BackgroundTask] = {}
        # tier -> task_id；stopping 仍占锁（status 仍为 running）
        self._running: dict[str, str] = {}

    def submit(
        self,
        task_type: str,
        total: int,
        fn: Callable[[BackgroundTask], None],
        *,
        tier: str = "heavy",
    ) -> BackgroundTask:
        """提交后台任务。同档位互斥。

        fn 签名: fn(task: BackgroundTask) -> None
            fn 内部通过 task.bump() / bump_batch_progress() 更新进度，
            最后调 task.complete() / task.cancel() / task.fail()。
        """
        if tier not in _VALID_TIERS:
            raise ValueError(f"invalid tier: {tier!r}, expected light|heavy")

        with self._lock:
            existing_id = self._running.get(tier)
            if existing_id:
                existing = self._tasks.get(existing_id)
                # running（含 cancel_requested 的 stopping）仍占锁
                if existing and existing.status == "running":
                    raise RuntimeError(
                        f"已有同档位({tier})任务正在运行: {existing_id}"
                        f" type={existing.task_type}"
                    )

            task_id = uuid.uuid4().hex[:12]
            task = BackgroundTask(task_id, task_type, total, tier=tier)
            self._tasks[task_id] = task
            self._running[tier] = task_id

            # 清理旧任务（保留最近 20 个）
            if len(self._tasks) > 20:
                sorted_ids = sorted(self._tasks, key=lambda k: self._tasks[k].created_at)
                for old_id in sorted_ids[: len(self._tasks) - 20]:
                    if self._tasks[old_id].status != "running":
                        del self._tasks[old_id]

        def _wrapper() -> None:
            try:
                fn(task)
                if task.status == "running":
                    task.complete()
            except Exception as e:
                task.fail(str(e)[:500])

        thread = threading.Thread(target=_wrapper, name=f"task-{task_type}-{task_id}", daemon=True)
        thread.start()
        return task

    def get(self, task_id: str) -> BackgroundTask | None:
        return self._tasks.get(task_id)

    def request_cancel(self, task_id: str) -> BackgroundTask | None:
        """请求取消任务；返回任务（不存在或已结束返回 None）。仅置标志，由任务体在每批边界自行收尾。"""
        task = self._tasks.get(task_id)
        if task is None or task.status != "running":
            return None
        task.request_cancel()
        return task

    def is_running(self, task_type: str) -> bool:
        """是否有指定 task_type 的 running 任务（兼容旧调用）。"""
        with self._lock:
            for task in self._tasks.values():
                if task.task_type == task_type and task.status == "running":
                    return True
            return False

    def is_tier_running(self, tier: str) -> bool:
        """指定档位是否有 running/stopping 任务。"""
        with self._lock:
            existing_id = self._running.get(tier)
            if not existing_id:
                return False
            existing = self._tasks.get(existing_id)
            return existing is not None and existing.status == "running"

    def list_running(self) -> list[BackgroundTask]:
        with self._lock:
            return [t for t in self._tasks.values() if t.status == "running"]

    def list_active_by_tier(self) -> dict[str, BackgroundTask | None]:
        """返回 heavy/light 各一条进行中任务（含 stopping）。"""
        with self._lock:
            out: dict[str, BackgroundTask | None] = {"heavy": None, "light": None}
            for tier in ("heavy", "light"):
                task_id = self._running.get(tier)
                if not task_id:
                    continue
                task = self._tasks.get(task_id)
                if task is not None and task.status == "running":
                    out[tier] = task
            return out


task_manager = TaskManager()
