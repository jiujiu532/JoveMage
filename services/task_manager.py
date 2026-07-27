"""后台任务管理器 — 内存中存储任务状态，供长时间操作使用。"""

from __future__ import annotations

import threading
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Callable


class BackgroundTask:
    __slots__ = ("task_id", "task_type", "status", "progress", "total", "result", "error", "created_at", "updated_at")

    def __init__(self, task_id: str, task_type: str, total: int = 0) -> None:
        self.task_id = task_id
        self.task_type = task_type
        self.status: str = "running"  # running | completed | failed
        self.progress: int = 0
        self.total: int = total
        self.result: dict[str, Any] = {}
        self.error: str = ""
        self.created_at: str = datetime.now(timezone.utc).isoformat()
        self.updated_at: str = self.created_at

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "task_type": self.task_type,
            "status": self.status,
            "progress": self.progress,
            "total": self.total,
            "result": self.result,
            "error": self.error,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    def bump(self, progress: int | None = None, **result_updates: Any) -> None:
        if progress is not None:
            self.progress = progress
        if result_updates:
            self.result.update(result_updates)
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
    """全局唯一的后台任务管理器。同一时间同类型只能跑一个任务。"""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._tasks: dict[str, BackgroundTask] = {}
        self._running: dict[str, str] = {}  # task_type -> task_id

    def submit(self, task_type: str, total: int, fn: Callable[[BackgroundTask], None]) -> BackgroundTask:
        """提交后台任务。同类型任务互斥。

        fn 签名: fn(task: BackgroundTask) -> None
            fn 内部通过 task.bump() 更新进度，最后调 task.complete() 或 task.fail()。
        """
        with self._lock:
            existing_id = self._running.get(task_type)
            if existing_id:
                existing = self._tasks.get(existing_id)
                if existing and existing.status == "running":
                    raise RuntimeError(f"已有同类型任务正在运行: {existing_id}")

            task_id = uuid.uuid4().hex[:12]
            task = BackgroundTask(task_id, task_type, total)
            self._tasks[task_id] = task
            self._running[task_type] = task_id

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

    def is_running(self, task_type: str) -> bool:
        with self._lock:
            existing_id = self._running.get(task_type)
            if not existing_id:
                return False
            existing = self._tasks.get(existing_id)
            return existing is not None and existing.status == "running"

    def list_running(self) -> list[BackgroundTask]:
        with self._lock:
            return [t for t in self._tasks.values() if t.status == "running"]


task_manager = TaskManager()
