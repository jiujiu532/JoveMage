from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


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
    def health_check(self) -> dict[str, Any]:
        """健康检查，返回存储后端状态"""
        pass

    @abstractmethod
    def get_backend_info(self) -> dict[str, Any]:
        """获取存储后端信息"""
        pass
