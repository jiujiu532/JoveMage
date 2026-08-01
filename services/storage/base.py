from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

# 日聚合冷数据标记（写在 note / cost，避免改 P0 的 action 枚举）
CHANNEL_USAGE_DAILY_AGGREGATE_NOTE = "daily_aggregate"


def is_channel_usage_aggregate_row(entry: dict[str, Any] | None) -> bool:
    """判断是否为日聚合行（永久保留，prune 时跳过）。"""
    if not isinstance(entry, dict):
        return False
    if str(entry.get("note") or "").strip() == CHANNEL_USAGE_DAILY_AGGREGATE_NOTE:
        return True
    cost = entry.get("cost")
    return isinstance(cost, dict) and bool(cost.get("aggregated"))


class StorageBackend(ABC):
    """抽象存储后端基类"""

    @abstractmethod
    def load_accounts(self) -> list[dict[str, Any]]:
        """加载所有账号数据"""
        pass

    @abstractmethod
    def save_accounts(self, accounts: list[dict[str, Any]]) -> None:
        """保存所有账号数据"""
        pass

    @abstractmethod
    def load_auth_keys(self) -> list[dict[str, Any]]:
        """加载所有鉴权密钥数据"""
        pass

    @abstractmethod
    def save_auth_keys(self, auth_keys: list[dict[str, Any]]) -> None:
        """保存所有鉴权密钥数据"""
        pass

    @abstractmethod
    def append_channel_usage(self, entry: dict[str, Any]) -> dict[str, Any]:
        """追加一条 channel_usage 流水（只增不改），返回归一化后的条目。"""
        pass

    @abstractmethod
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
        """按 account_id / trace_id / channel / ts 查询用量流水（新→旧）。"""
        pass

    @abstractmethod
    def delete_channel_usage_before(self, ts: float) -> int:
        """删除 ts 之前的明细行（跳过日聚合冷数据），返回删除条数。"""
        pass

    @abstractmethod
    def aggregate_channel_usage_daily(
        self,
        day_start_ts: float,
        day_end_ts: float,
    ) -> list[dict[str, Any]]:
        """按 (channel, account_id, action, result) 聚合一天的明细用量。

        返回聚合行（尚未落库），字段含 count 与 cost.credits/quota 求和。
        不包含已有日聚合行。
        """
        pass

    def export_channel_usage(self) -> list[dict[str, Any]]:
        """导出全部 channel_usage（备份用）。默认走 query 上限，子类应覆盖为全量。"""
        return self.query_channel_usage(limit=1000)

    @abstractmethod
    def health_check(self) -> dict[str, Any]:
        """健康检查，返回存储后端状态"""
        pass

    @abstractmethod
    def get_backend_info(self) -> dict[str, Any]:
        """获取存储后端信息"""
        pass


def aggregate_channel_usage_rows(
    items: list[dict[str, Any]],
    *,
    day_start_ts: float,
    day_end_ts: float,
) -> list[dict[str, Any]]:
    """对明细列表做日聚合（json/git 与 database 回退共用）。"""
    start = float(day_start_ts)
    end = float(day_end_ts)
    buckets: dict[tuple[str, str, str, str], dict[str, Any]] = {}
    for item in items:
        if not isinstance(item, dict) or is_channel_usage_aggregate_row(item):
            continue
        try:
            ts = float(item.get("ts") or 0)
        except (TypeError, ValueError):
            continue
        if ts < start or ts >= end:
            continue
        channel = str(item.get("channel") or "").strip()
        account_id = str(item.get("account_id") or "").strip()
        action = str(item.get("action") or "").strip().lower()
        result = str(item.get("result") or "").strip().lower()
        if not channel or not account_id or not action or not result:
            continue
        key = (channel, account_id, action, result)
        bucket = buckets.get(key)
        if bucket is None:
            bucket = {
                "channel": channel,
                "account_id": account_id,
                "action": action,
                "result": result,
                "count": 0,
                "cost": {"credits": 0.0, "quota": 0.0},
            }
            buckets[key] = bucket
        bucket["count"] = int(bucket["count"]) + 1
        cost = item.get("cost") if isinstance(item.get("cost"), dict) else {}
        try:
            bucket["cost"]["credits"] = float(bucket["cost"]["credits"]) + float(cost.get("credits") or 0)
        except (TypeError, ValueError):
            pass
        try:
            bucket["cost"]["quota"] = float(bucket["cost"]["quota"]) + float(cost.get("quota") or 0)
        except (TypeError, ValueError):
            pass

    rows: list[dict[str, Any]] = []
    for bucket in buckets.values():
        credits = float(bucket["cost"]["credits"])
        quota = float(bucket["cost"]["quota"])
        # 尽量保持整型观感（1.0 → 1）
        credits_out: float | int = int(credits) if credits == int(credits) else credits
        quota_out: float | int = int(quota) if quota == int(quota) else quota
        rows.append(
            {
                "channel": bucket["channel"],
                "account_id": bucket["account_id"],
                "action": bucket["action"],
                "result": bucket["result"],
                "count": int(bucket["count"]),
                "cost": {
                    "credits": credits_out,
                    "quota": quota_out,
                },
            }
        )
    rows.sort(key=lambda r: (r["channel"], r["account_id"], r["action"], r["result"]))
    return rows
