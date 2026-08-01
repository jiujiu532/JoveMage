from __future__ import annotations

import threading
from pathlib import Path
from typing import Any

from services.json_file import read_json_file, write_json_file
from services.storage.base import (
    StorageBackend,
    aggregate_channel_usage_rows,
    is_channel_usage_aggregate_row,
)
from services.storage.channel_usage import match_channel_usage, normalize_channel_usage_entry


class JSONStorageBackend(StorageBackend):
    """本地 JSON 文件存储后端"""

    def __init__(
        self,
        file_path: Path,
        auth_keys_path: Path | None = None,
        channel_usage_path: Path | None = None,
    ):
        self.file_path = file_path
        self.auth_keys_path = auth_keys_path or file_path.with_name("auth_keys.json")
        self.channel_usage_path = channel_usage_path or file_path.with_name("channel_usage.json")
        self.file_path.parent.mkdir(parents=True, exist_ok=True)
        self.auth_keys_path.parent.mkdir(parents=True, exist_ok=True)
        self.channel_usage_path.parent.mkdir(parents=True, exist_ok=True)
        self._channel_usage_lock = threading.RLock()

    @staticmethod
    def _load_json_list(file_path: Path) -> list[dict[str, Any]]:
        data = read_json_file(
            file_path,
            name=file_path.name,
            default_factory=list,
            expected_types=list,
        )
        return data if isinstance(data, list) else []

    @staticmethod
    def _save_json_list(file_path: Path, items: list[dict[str, Any]]) -> None:
        write_json_file(file_path, items)

    def load_accounts(self) -> list[dict[str, Any]]:
        """从 JSON 文件加载账号数据"""
        return self._load_json_list(self.file_path)

    def save_accounts(self, accounts: list[dict[str, Any]]) -> None:
        """保存账号数据到 JSON 文件"""
        self._save_json_list(self.file_path, accounts)

    def load_auth_keys(self) -> list[dict[str, Any]]:
        """从 JSON 文件加载鉴权密钥数据"""
        data = read_json_file(
            self.auth_keys_path,
            name="auth_keys.json",
            default_factory=list,
            expected_types=(dict, list),
        )
        if isinstance(data, dict):
            data = data.get("items")
        return data if isinstance(data, list) else []

    def save_auth_keys(self, auth_keys: list[dict[str, Any]]) -> None:
        """保存鉴权密钥数据到 JSON 文件"""
        write_json_file(self.auth_keys_path, {"items": auth_keys})

    def append_channel_usage(self, entry: dict[str, Any]) -> dict[str, Any]:
        """追加 channel_usage 流水到 data/channel_usage.json（原子写）。"""
        normalized = normalize_channel_usage_entry(entry)
        if normalized is None:
            raise ValueError("invalid channel_usage entry")
        with self._channel_usage_lock:
            items = self._load_json_list(self.channel_usage_path)
            items.append(normalized)
            # 防止无限膨胀：保留最近 5 万条
            if len(items) > 50000:
                items = items[-50000:]
            write_json_file(self.channel_usage_path, items)
        return dict(normalized)

    def query_channel_usage(
        self,
        *,
        account_id: str | None = None,
        trace_id: str | None = None,
        channel: str | None = None,
        ts_from: float | None = None,
        ts_to: float | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        with self._channel_usage_lock:
            items = self._load_json_list(self.channel_usage_path)
        matched = [
            dict(item)
            for item in items
            if isinstance(item, dict)
            and match_channel_usage(
                item,
                account_id=account_id,
                trace_id=trace_id,
                channel=channel,
                ts_from=ts_from,
                ts_to=ts_to,
            )
        ]
        matched.sort(key=lambda row: float(row.get("ts") or 0), reverse=True)
        cap = max(1, min(int(limit or 100), 1000))
        return matched[:cap]

    def delete_channel_usage_before(self, ts: float) -> int:
        """删除 ts 之前的明细行；日聚合冷数据永久保留。"""
        cutoff = float(ts)
        with self._channel_usage_lock:
            items = self._load_json_list(self.channel_usage_path)
            kept: list[dict[str, Any]] = []
            deleted = 0
            for item in items:
                if not isinstance(item, dict):
                    continue
                if is_channel_usage_aggregate_row(item):
                    kept.append(item)
                    continue
                try:
                    row_ts = float(item.get("ts") or 0)
                except (TypeError, ValueError):
                    row_ts = 0.0
                if row_ts < cutoff:
                    deleted += 1
                    continue
                kept.append(item)
            if deleted:
                write_json_file(self.channel_usage_path, kept)
            return deleted

    def aggregate_channel_usage_daily(
        self,
        day_start_ts: float,
        day_end_ts: float,
    ) -> list[dict[str, Any]]:
        with self._channel_usage_lock:
            items = self._load_json_list(self.channel_usage_path)
        return aggregate_channel_usage_rows(
            items,
            day_start_ts=day_start_ts,
            day_end_ts=day_end_ts,
        )

    def export_channel_usage(self) -> list[dict[str, Any]]:
        """导出全部 channel_usage 流水（备份用）。"""
        with self._channel_usage_lock:
            items = self._load_json_list(self.channel_usage_path)
        return [dict(item) for item in items if isinstance(item, dict)]

    def health_check(self) -> dict[str, Any]:
        """健康检查"""
        try:
            # 检查文件是否可读写
            if self.file_path.exists():
                self.file_path.read_text(encoding="utf-8")
            return {
                "status": "healthy",
                "backend": "json",
                "file_exists": self.file_path.exists(),
                "file_path": str(self.file_path),
                "auth_keys_file_exists": self.auth_keys_path.exists(),
                "auth_keys_file_path": str(self.auth_keys_path),
                "channel_usage_file_exists": self.channel_usage_path.exists(),
                "channel_usage_file_path": str(self.channel_usage_path),
            }
        except Exception as e:
            return {
                "status": "unhealthy",
                "backend": "json",
                "error": str(e),
            }

    def get_backend_info(self) -> dict[str, Any]:
        """获取存储后端信息"""
        return {
            "type": "json",
            "description": "本地 JSON 文件存储",
            "file_path": str(self.file_path),
            "file_exists": self.file_path.exists(),
            "auth_keys_file_path": str(self.auth_keys_path),
            "auth_keys_file_exists": self.auth_keys_path.exists(),
            "channel_usage_file_path": str(self.channel_usage_path),
            "channel_usage_file_exists": self.channel_usage_path.exists(),
        }
