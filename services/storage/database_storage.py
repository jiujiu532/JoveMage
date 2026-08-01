from __future__ import annotations

import json
from typing import Any

from sqlalchemy import Column, Float, Integer, String, Text, create_engine, text
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker

from services.storage.base import (
    CHANNEL_USAGE_DAILY_AGGREGATE_NOTE,
    StorageBackend,
    aggregate_channel_usage_rows,
    is_channel_usage_aggregate_row,
)
from services.storage.channel_usage import normalize_channel_usage_entry

Base = declarative_base()


class AccountModel(Base):
    """账号数据模型"""
    __tablename__ = "accounts"

    id = Column(Integer, primary_key=True, autoincrement=True)
    access_token = Column(String(2048), unique=True, nullable=False, index=True)
    data = Column(Text, nullable=False)  # JSON 格式存储完整账号数据


class AuthKeyModel(Base):
    """鉴权密钥数据模型"""
    __tablename__ = "auth_keys"

    id = Column(Integer, primary_key=True, autoincrement=True)
    key_id = Column(String(255), unique=True, nullable=False, index=True)
    data = Column(Text, nullable=False)


class ChannelUsageModel(Base):
    """渠道用量流水（只增不改）"""
    __tablename__ = "channel_usage"

    id = Column(String(64), primary_key=True)
    ts = Column(Float, nullable=False, index=True)
    trace_id = Column(String(128), nullable=False, index=True)
    channel = Column(String(64), nullable=False, index=True)
    account_id = Column(String(512), nullable=False, index=True)
    action = Column(String(32), nullable=False)
    model = Column(String(255), nullable=False, default="")
    cost = Column(Text, nullable=False, default="{}")
    result = Column(String(32), nullable=False)
    upstream_id = Column(String(255), nullable=True)
    note = Column(Text, nullable=True)
    attempt_seq = Column(Integer, nullable=True)
    elapsed_ms = Column(Integer, nullable=True)
    data = Column(Text, nullable=False)  # 完整 JSON 备份，便于扩展字段


class DatabaseStorageBackend(StorageBackend):
    """数据库存储后端（支持 SQLite、PostgreSQL、MySQL 等）"""

    def __init__(self, database_url: str):
        self.database_url = database_url
        self.engine = create_engine(
            database_url,
            pool_pre_ping=True,  # 自动检测连接是否有效
            pool_recycle=3600,   # 1小时回收连接
        )
        Base.metadata.create_all(self.engine)
        self.Session = sessionmaker(bind=self.engine)

    def load_accounts(self) -> list[dict[str, Any]]:
        """从数据库加载账号数据"""
        session = self.Session()
        try:
            accounts = []
            for row in session.query(AccountModel).all():
                try:
                    account_data = json.loads(row.data)
                    if isinstance(account_data, dict):
                        accounts.append(account_data)
                except json.JSONDecodeError:
                    continue
            return accounts
        finally:
            session.close()

    def save_accounts(self, accounts: list[dict[str, Any]]) -> None:
        """保存账号数据到数据库"""
        self._save_rows(AccountModel, accounts, "access_token")

    def load_auth_keys(self) -> list[dict[str, Any]]:
        """从数据库加载鉴权密钥数据"""
        return self._load_rows(AuthKeyModel)

    def save_auth_keys(self, auth_keys: list[dict[str, Any]]) -> None:
        """保存鉴权密钥数据到数据库"""
        self._save_rows(AuthKeyModel, auth_keys, "id", "key_id")

    def append_channel_usage(self, entry: dict[str, Any]) -> dict[str, Any]:
        """追加一条 channel_usage 流水。"""
        normalized = normalize_channel_usage_entry(entry)
        if normalized is None:
            raise ValueError("invalid channel_usage entry")
        session = self.Session()
        try:
            session.add(
                ChannelUsageModel(
                    id=str(normalized["id"]),
                    ts=float(normalized["ts"]),
                    trace_id=str(normalized["trace_id"]),
                    channel=str(normalized["channel"]),
                    account_id=str(normalized["account_id"]),
                    action=str(normalized["action"]),
                    model=str(normalized.get("model") or ""),
                    cost=json.dumps(normalized.get("cost") or {}, ensure_ascii=False),
                    result=str(normalized["result"]),
                    upstream_id=normalized.get("upstream_id"),
                    note=normalized.get("note"),
                    attempt_seq=normalized.get("attempt_seq"),
                    elapsed_ms=normalized.get("elapsed_ms"),
                    data=json.dumps(normalized, ensure_ascii=False),
                )
            )
            session.commit()
            return dict(normalized)
        except Exception as e:
            session.rollback()
            raise e
        finally:
            session.close()

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
        session = self.Session()
        try:
            q = session.query(ChannelUsageModel)
            if account_id is not None:
                q = q.filter(ChannelUsageModel.account_id == str(account_id))
            if trace_id is not None:
                q = q.filter(ChannelUsageModel.trace_id == str(trace_id))
            if channel is not None:
                q = q.filter(ChannelUsageModel.channel == str(channel))
            if ts_from is not None:
                q = q.filter(ChannelUsageModel.ts >= float(ts_from))
            if ts_to is not None:
                q = q.filter(ChannelUsageModel.ts <= float(ts_to))
            cap = max(1, min(int(limit or 100), 1000))
            rows = q.order_by(ChannelUsageModel.ts.desc()).limit(cap).all()
            items: list[dict[str, Any]] = []
            for row in rows:
                try:
                    payload = json.loads(row.data)
                    if isinstance(payload, dict):
                        items.append(payload)
                        continue
                except (TypeError, json.JSONDecodeError):
                    pass
                # data 损坏时回退列字段
                try:
                    cost = json.loads(row.cost) if row.cost else {}
                except (TypeError, json.JSONDecodeError):
                    cost = {}
                items.append({
                    "id": row.id,
                    "ts": row.ts,
                    "trace_id": row.trace_id,
                    "channel": row.channel,
                    "account_id": row.account_id,
                    "action": row.action,
                    "model": row.model or "",
                    "cost": cost if isinstance(cost, dict) else {},
                    "result": row.result,
                    "upstream_id": row.upstream_id,
                    "note": row.note,
                    "attempt_seq": row.attempt_seq,
                    "elapsed_ms": row.elapsed_ms,
                })
            return items
        finally:
            session.close()

    def delete_channel_usage_before(self, ts: float) -> int:
        """删除 ts 之前的明细行；跳过 note=daily_aggregate 的冷数据。"""
        cutoff = float(ts)
        session = self.Session()
        try:
            # 先查再删：SQLAlchemy 1.x 对复杂 OR 的 bulk delete 在部分方言上不友好
            candidates = (
                session.query(ChannelUsageModel)
                .filter(ChannelUsageModel.ts < cutoff)
                .all()
            )
            deleted = 0
            for row in candidates:
                if self._row_is_aggregate(row):
                    continue
                session.delete(row)
                deleted += 1
            if deleted:
                session.commit()
            return deleted
        except Exception as e:
            session.rollback()
            raise e
        finally:
            session.close()

    def aggregate_channel_usage_daily(
        self,
        day_start_ts: float,
        day_end_ts: float,
    ) -> list[dict[str, Any]]:
        """SQL 侧拉一天明细后按 (channel, account_id, action, result) 聚合。"""
        start = float(day_start_ts)
        end = float(day_end_ts)
        session = self.Session()
        try:
            rows = (
                session.query(ChannelUsageModel)
                .filter(ChannelUsageModel.ts >= start)
                .filter(ChannelUsageModel.ts < end)
                .all()
            )
            items: list[dict[str, Any]] = []
            for row in rows:
                payload = self._row_to_entry(row)
                if payload is not None:
                    items.append(payload)
            return aggregate_channel_usage_rows(
                items,
                day_start_ts=start,
                day_end_ts=end,
            )
        finally:
            session.close()

    def export_channel_usage(self) -> list[dict[str, Any]]:
        """导出全部 channel_usage 流水（备份用，无 limit）。"""
        session = self.Session()
        try:
            rows = session.query(ChannelUsageModel).order_by(ChannelUsageModel.ts.asc()).all()
            items: list[dict[str, Any]] = []
            for row in rows:
                payload = self._row_to_entry(row)
                if payload is not None:
                    items.append(payload)
            return items
        finally:
            session.close()

    @staticmethod
    def _row_is_aggregate(row: ChannelUsageModel) -> bool:
        if str(row.note or "").strip() == CHANNEL_USAGE_DAILY_AGGREGATE_NOTE:
            return True
        try:
            payload = json.loads(row.data) if row.data else {}
        except (TypeError, json.JSONDecodeError):
            payload = {}
        return is_channel_usage_aggregate_row(payload if isinstance(payload, dict) else None)

    @staticmethod
    def _row_to_entry(row: ChannelUsageModel) -> dict[str, Any] | None:
        try:
            payload = json.loads(row.data) if row.data else None
            if isinstance(payload, dict):
                return payload
        except (TypeError, json.JSONDecodeError):
            pass
        try:
            cost = json.loads(row.cost) if row.cost else {}
        except (TypeError, json.JSONDecodeError):
            cost = {}
        return {
            "id": row.id,
            "ts": row.ts,
            "trace_id": row.trace_id,
            "channel": row.channel,
            "account_id": row.account_id,
            "action": row.action,
            "model": row.model or "",
            "cost": cost if isinstance(cost, dict) else {},
            "result": row.result,
            "upstream_id": row.upstream_id,
            "note": row.note,
            "attempt_seq": row.attempt_seq,
            "elapsed_ms": row.elapsed_ms,
        }

    def _load_rows(self, model: type[AccountModel] | type[AuthKeyModel]) -> list[dict[str, Any]]:
        session = self.Session()
        try:
            items = []
            for row in session.query(model).all():
                try:
                    item_data = json.loads(row.data)
                    if isinstance(item_data, dict):
                        items.append(item_data)
                except json.JSONDecodeError:
                    continue
            return items
        finally:
            session.close()

    def _save_rows(
        self,
        model: type[AccountModel] | type[AuthKeyModel],
        items: list[dict[str, Any]],
        source_key: str,
        target_key: str | None = None,
    ) -> None:
        session = self.Session()
        try:
            session.query(model).delete()
            for item in items:
                if not isinstance(item, dict):
                    continue
                key_value = str(item.get(source_key) or "").strip()
                if not key_value:
                    continue
                session.add(
                    model(
                        **{target_key or source_key: key_value},
                        data=json.dumps(item, ensure_ascii=False),
                    )
                )
            session.commit()
        except Exception as e:
            session.rollback()
            raise e
        finally:
            session.close()

    def health_check(self) -> dict[str, Any]:
        """健康检查"""
        try:
            session = self.Session()
            try:
                # 尝试执行简单查询
                session.execute(text("SELECT 1"))
                count = session.query(AccountModel).count()
                auth_key_count = session.query(AuthKeyModel).count()
                usage_count = session.query(ChannelUsageModel).count()
                return {
                    "status": "healthy",
                    "backend": "database",
                    "database_url": self._mask_password(self.database_url),
                    "account_count": count,
                    "auth_key_count": auth_key_count,
                    "channel_usage_count": usage_count,
                }
            finally:
                session.close()
        except Exception as e:
            return {
                "status": "unhealthy",
                "backend": "database",
                "error": str(e),
            }

    def get_backend_info(self) -> dict[str, Any]:
        """获取存储后端信息"""
        db_type = "unknown"
        if "sqlite" in self.database_url:
            db_type = "sqlite"
        elif "postgresql" in self.database_url or "postgres" in self.database_url:
            db_type = "postgresql"
        elif "mysql" in self.database_url:
            db_type = "mysql"
        
        return {
            "type": "database",
            "db_type": db_type,
            "description": f"数据库存储 ({db_type})",
            "database_url": self._mask_password(self.database_url),
        }

    @staticmethod
    def _mask_password(url: str) -> str:
        """隐藏数据库连接字符串中的密码"""
        if "://" not in url:
            return url
        try:
            protocol, rest = url.split("://", 1)
            if "@" in rest:
                credentials, host = rest.split("@", 1)
                if ":" in credentials:
                    username, _ = credentials.split(":", 1)
                    return f"{protocol}://{username}:****@{host}"
            return url
        except Exception:
            return url
