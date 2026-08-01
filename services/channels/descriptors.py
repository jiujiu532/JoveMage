"""渠道描述符组装：注册表静态字段 + 号池运行时统计。"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from services.account_service import AccountService, account_service
from services.channels.registry import ChannelEntry, get_channel, list_channel_entries
from services.channels.runtime import channel_circuit_status
from services.config import config


def _normalize_source_type(value: object) -> str:
    return AccountService._normalize_source_type(value)


def _accounts_for_channel(accounts: list[dict], channel_id: str) -> list[dict]:
    """按渠道 id 切分号池。chatgpt = 非 firefly；firefly = source_type=firefly。"""
    cid = str(channel_id or "").strip().lower()
    if cid == "firefly":
        return [item for item in accounts if _normalize_source_type(item.get("source_type")) == "firefly"]
    if cid == "chatgpt":
        return [item for item in accounts if _normalize_source_type(item.get("source_type")) != "firefly"]
    # 未知渠道：精确匹配 source_type
    return [item for item in accounts if _normalize_source_type(item.get("source_type")) == cid]


def _channel_pool_metrics(accounts: list[dict]) -> dict[str, Any]:
    """复用 evaluate_account_pool 的新鲜度口径，不触发远端 refresh。"""
    freshness = AccountService._pool_health_freshness_seconds(None)
    now = datetime.now(timezone.utc)
    return AccountService._pool_health_metrics_from_accounts(
        accounts,
        now=now,
        freshness_seconds=freshness,
    )


def _coerce_nonneg_int(value: object) -> int | None:
    if value is None or value == "":
        return None
    try:
        return max(0, int(float(value)))
    except (OverflowError, TypeError, ValueError):
        return None


def _firefly_credits_total(accounts: list[dict]) -> int:
    """Firefly credits 汇总：优先 credits.available，其次 credits.total，再回落 quota。"""
    total = 0
    for account in accounts:
        credits = account.get("credits")
        if not isinstance(credits, dict):
            credits = account.get("credits_balance")
        if isinstance(credits, dict):
            for key in ("available", "total"):
                amount = _coerce_nonneg_int(credits.get(key))
                if amount is not None:
                    total += amount
                    break
            else:
                amount = _coerce_nonneg_int(account.get("quota"))
                if amount is not None:
                    total += amount
            continue
        amount = _coerce_nonneg_int(account.get("quota"))
        if amount is not None:
            total += amount
    return total


def _resolve_enabled(entry: ChannelEntry) -> bool:
    if entry.id == "firefly":
        return bool(config.firefly_enabled)
    return bool(entry.enabled)


def _freshness_kind_for_channel(entry: ChannelEntry) -> str:
    """号池 healthy_count 所用新鲜度口径标注（不改统计算法，只说明含义）。

    - token_check：ChatGPT 等，last_remote_checked_at 在 refresh_account_interval_minute 内算 confirmed
    - cookie_refresh：Firefly 等 cookie 凭证，同一套 _pool_health_metrics_from_accounts 数字，
      但运维语义应对照 cookie/IMS 刷新（见 firefly_refresh.compute_cookie_credential_freshness）
    """
    cred = str(entry.credential_type or "").strip().lower()
    if cred == "cookie" or entry.id == "firefly":
        return "cookie_refresh"
    return "token_check"


def build_channel_descriptor(
    entry: ChannelEntry,
    *,
    accounts: list[dict] | None = None,
) -> dict[str, Any]:
    """组装单个渠道描述符（静态字段 + 号池统计）。"""
    all_accounts = accounts if accounts is not None else account_service.list_accounts()
    channel_accounts = _accounts_for_channel(all_accounts, entry.id)
    metrics = _channel_pool_metrics(channel_accounts)
    payload = entry.to_public_dict()
    payload["enabled"] = _resolve_enabled(entry)
    payload["account_count"] = len(channel_accounts)
    # healthy_count：与 evaluate_account_pool 的 current_available 同口径（新鲜 + 正常）
    # 不另造「status==正常」简易统计；仅标注该渠道新鲜度口径来源
    payload["healthy_count"] = int(metrics.get("current_available") or 0)
    payload["freshness_kind"] = _freshness_kind_for_channel(entry)
    # 渠道熔断状态（P1-B）：概览卡可直接展示 open/until/fail_count；主航道恒为关闭态
    try:
        payload["circuit"] = channel_circuit_status(entry.id)
    except Exception:
        payload["circuit"] = {"open": False, "until": 0.0, "fail_count": 0}
    if entry.meter_kind == "credits" or entry.id == "firefly":
        payload["credits_total"] = _firefly_credits_total(channel_accounts)
    return payload


def build_channel_descriptors() -> list[dict[str, Any]]:
    """前端权威数据源：全部渠道描述符。"""
    accounts = account_service.list_accounts()
    return [build_channel_descriptor(entry, accounts=accounts) for entry in list_channel_entries()]


def build_channel_descriptor_by_id(channel_id: str) -> dict[str, Any] | None:
    entry = get_channel(channel_id)
    if entry is None:
        return None
    return build_channel_descriptor(entry)
