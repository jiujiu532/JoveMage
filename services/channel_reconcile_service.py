# -*- coding: utf-8 -*-
"""Firefly credits 对账：本地 channel_usage 流水 vs Adobe 远端余额。

设计对齐 .trellis/spec/backend/multi-channel/03-backend-governance.md §9：
手动触发全账号拉取远端 credits，与本地账本累计比对，标出漂移号。
"""

from __future__ import annotations

import time
import uuid
from typing import Any, Callable

from services.account_service import account_service
from services.backends.firefly_auth import fetch_credits
from services.storage.base import is_channel_usage_aggregate_row
from services.channel_usage_service import channel_usage_service, resolve_account_id
from utils.diagnostics import redact_auth_diagnostic
from utils.log import logger

# 默认容差（credits）：绝对值 ≤ 容差视为一致
DEFAULT_RECONCILE_TOLERANCE = 0.0
CHANNEL_FIREFLY = "firefly"


def _coerce_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _pretty_number(value: float) -> float | int:
    """尽量输出整型观感（1.0 → 1）。"""
    if value == int(value):
        return int(value)
    return value


def sum_ledger_credits(
    entries: list[dict[str, Any]],
    *,
    account_id: str,
    channel: str = CHANNEL_FIREFLY,
) -> float:
    """聚合某账号在 channel_usage 中的 cost.credits（含 refunded 负数与日聚合行）。

    明细删除后由日聚合行承接汇总，因此聚合行必须计入，避免历史扣费丢失。
    但若聚合行与对应明细短暂并存（retention 先写聚合再 prune 的间隙），
    同一天的明细须跳过，避免与该天聚合行双计。
    """
    aid = str(account_id or "").strip()
    ch = str(channel or "").strip().lower()
    total = 0.0
    if not aid:
        return 0.0

    def _match(item: dict[str, Any]) -> bool:
        if not isinstance(item, dict):
            return False
        if str(item.get("account_id") or "").strip() != aid:
            return False
        if str(item.get("channel") or "").strip().lower() != ch:
            return False
        # 熔断事件（action=circuit）只是审计，credits=0，不计入扣费求和
        if str(item.get("action") or "").strip().lower() == "circuit":
            return False
        return True

    matched = [it for it in entries if _match(it)]

    # 收集已有聚合行的 (day, action, result) 组合，用于剔除重叠明细
    aggregated_keys: set[tuple[str, str, str]] = set()
    for it in matched:
        if not is_channel_usage_aggregate_row(it):
            continue
        cost = it.get("cost") if isinstance(it.get("cost"), dict) else {}
        day = str(cost.get("day") or "").strip()
        if not day:
            continue
        aggregated_keys.add((
            day,
            str(it.get("action") or "").strip().lower(),
            str(it.get("result") or "").strip().lower(),
        ))

    for item in matched:
        # 明细行：若其所在 (day, action, result) 已有聚合行，跳过防双计
        if not is_channel_usage_aggregate_row(item):
            day = _day_key_of(item.get("ts"))
            if day and (
                day,
                str(item.get("action") or "").strip().lower(),
                str(item.get("result") or "").strip().lower(),
            ) in aggregated_keys:
                continue
        cost = item.get("cost") if isinstance(item.get("cost"), dict) else {}
        amount = _coerce_float(cost.get("credits"))
        if amount is None:
            continue
        total += amount
    return total


def _day_key_of(ts: object) -> str:
    """把 unix 秒转 YYYY-MM-DD（UTC）；非法返回空串。"""
    try:
        from datetime import datetime, timezone

        return datetime.fromtimestamp(float(ts), tz=timezone.utc).strftime("%Y-%m-%d")
    except (TypeError, ValueError, OSError):
        return ""


def estimate_local_remaining(
    *,
    ledger_used: float,
    total: float | None = None,
    cached_available: float | None = None,
) -> float | None:
    """推算本地记剩 credits。

    优先 total - ledger_used（流水推算剩余）；无 total 时回落缓存 available。
    """
    if total is not None:
        return float(total) - float(ledger_used or 0.0)
    if cached_available is not None:
        return float(cached_available)
    return None


def compute_credit_drift(
    local_credits: float | None,
    remote_credits: float | None,
    *,
    tolerance: float = DEFAULT_RECONCILE_TOLERANCE,
) -> dict[str, Any]:
    """漂移判定：drift = local - remote。

    - 正漂移：本地记剩 > 远端 → 远端多扣了 / 有扣费没记上
    - 负漂移：本地记剩 < 远端 → 本地多记了 / 远端有返还未入账
    - |drift| ≤ tolerance → status=ok，否则 status=drift
    """
    if local_credits is None or remote_credits is None:
        return {
            "local_credits": local_credits,
            "remote_credits": remote_credits,
            "drift": None,
            "status": "error",
        }
    local_v = float(local_credits)
    remote_v = float(remote_credits)
    drift = local_v - remote_v
    tol = abs(float(tolerance or 0.0))
    status = "ok" if abs(drift) <= tol else "drift"
    return {
        "local_credits": _pretty_number(local_v),
        "remote_credits": _pretty_number(remote_v),
        "drift": _pretty_number(drift),
        "status": status,
    }


def _account_cached_credits(account: dict[str, Any]) -> dict[str, float | None]:
    raw = account.get("credits")
    if not isinstance(raw, dict):
        raw = account.get("credits_balance")
    if not isinstance(raw, dict):
        raw = {}
    return {
        "total": _coerce_float(raw.get("total")),
        "used": _coerce_float(raw.get("used")),
        "available": _coerce_float(raw.get("available")),
    }


def _list_firefly_accounts() -> list[dict[str, Any]]:
    accounts = account_service.list_accounts() or []
    out: list[dict[str, Any]] = []
    for item in accounts:
        if not isinstance(item, dict):
            continue
        source = str(item.get("source_type") or "").strip().lower()
        if source == CHANNEL_FIREFLY:
            out.append(item)
    return out


def _write_reconcile_audit(
    *,
    account_id: str,
    status: str,
    local_credits: float | None,
    remote_credits: float | None,
    drift: float | int | None,
    note_extra: str = "",
) -> None:
    """轻量审计：记一条 action=refresh 流水（cost.credits=0，不影响对账累加语义外的扣费）。"""
    parts = [
        f"reconcile status={status}",
        f"local={local_credits}",
        f"remote={remote_credits}",
        f"drift={drift}",
    ]
    if note_extra:
        parts.append(note_extra)
    note = " | ".join(parts)
    try:
        channel_usage_service.append(
            trace_id=f"reconcile:{uuid.uuid4().hex}",
            channel=CHANNEL_FIREFLY,
            account_id=account_id,
            action="refresh",
            model="",
            cost={"credits": 0, "kind": "reconcile"},
            result="success" if status in {"ok", "drift"} else "failed",
            note=note,
        )
    except Exception as exc:  # 审计失败不影响主结果
        logger.warning(
            {
                "event": "channel_reconcile_audit_failed",
                "account_id": account_id,
                "error": redact_auth_diagnostic(exc, 300),
            }
        )


def reconcile_firefly_account(
    account: dict[str, Any],
    *,
    ledger_entries: list[dict[str, Any]] | None = None,
    tolerance: float = DEFAULT_RECONCILE_TOLERANCE,
    fetch_credits_fn: Callable[..., dict[str, Any]] | None = None,
    write_audit: bool = True,
    update_account_credits: bool = True,
) -> dict[str, Any]:
    """对单个 Firefly 账号做 credits 对账。"""
    account_id = resolve_account_id(account, str(account.get("access_token") or ""))
    cached = _account_cached_credits(account)
    entries = ledger_entries if ledger_entries is not None else channel_usage_service.export_all()
    ledger_used = sum_ledger_credits(entries, account_id=account_id, channel=CHANNEL_FIREFLY)

    access_token = str(account.get("access_token") or "").strip()
    proxy = str(account.get("proxy") or "").strip() or None
    adobe_id = (
        str(account.get("account_id") or "").strip()
        or str(account.get("adobe_account_id") or "").strip()
        or str(account.get("user_id") or "").strip()
        or account_id
    )

    base: dict[str, Any] = {
        "account_id": account_id,
        "ledger_used": _pretty_number(ledger_used),
        "local_credits": None,
        "remote_credits": None,
        "remote_total": None,
        "remote_used": None,
        "drift": None,
        "status": "error",
        "error": None,
    }

    if not access_token:
        base["error"] = "missing_access_token"
        # 无远端时仍可给出本地推算（仅缓存/流水）
        local_only = estimate_local_remaining(
            ledger_used=ledger_used,
            total=cached["total"],
            cached_available=cached["available"],
        )
        base["local_credits"] = _pretty_number(local_only) if local_only is not None else None
        if write_audit and account_id and account_id != "unknown":
            _write_reconcile_audit(
                account_id=account_id,
                status="error",
                local_credits=base["local_credits"],
                remote_credits=None,
                drift=None,
                note_extra="missing_access_token",
            )
        return base

    fetcher = fetch_credits_fn or fetch_credits
    try:
        remote = fetcher(access_token, adobe_id, proxy=proxy) or {}
    except Exception as exc:
        err = redact_auth_diagnostic(str(exc), 300)
        base["error"] = err
        local_only = estimate_local_remaining(
            ledger_used=ledger_used,
            total=cached["total"],
            cached_available=cached["available"],
        )
        base["local_credits"] = _pretty_number(local_only) if local_only is not None else None
        if write_audit:
            _write_reconcile_audit(
                account_id=account_id,
                status="error",
                local_credits=base["local_credits"],
                remote_credits=None,
                drift=None,
                note_extra=err,
            )
        return base

    remote_total = _coerce_float(remote.get("total"))
    remote_used = _coerce_float(remote.get("used"))
    remote_available = _coerce_float(remote.get("available"))
    base["remote_total"] = _pretty_number(remote_total) if remote_total is not None else None
    base["remote_used"] = _pretty_number(remote_used) if remote_used is not None else None

    # 本地记剩：优先用（远端 total 或缓存 total）- 流水累计；否则回落缓存 available
    total_for_local = remote_total if remote_total is not None else cached["total"]
    local_credits = estimate_local_remaining(
        ledger_used=ledger_used,
        total=total_for_local,
        cached_available=cached["available"],
    )

    judged = compute_credit_drift(local_credits, remote_available, tolerance=tolerance)
    base.update(judged)

    # 可选：把远端余额写回账号缓存，便于账号页展示刷新
    if update_account_credits and remote_available is not None:
        credits_payload = {
            "total": remote.get("total"),
            "used": remote.get("used"),
            "available": remote.get("available"),
            "available_until": remote.get("available_until"),
        }
        try:
            account_service.update_account(
                access_token,
                {
                    "credits": credits_payload,
                    "last_remote_checked_at": time.time(),
                },
                quiet=True,
            )
        except Exception as exc:
            logger.warning(
                {
                    "event": "channel_reconcile_update_credits_failed",
                    "account_id": account_id,
                    "error": redact_auth_diagnostic(exc, 300),
                }
            )

    if write_audit:
        _write_reconcile_audit(
            account_id=account_id,
            status=str(base.get("status") or "error"),
            local_credits=base.get("local_credits"),
            remote_credits=base.get("remote_credits"),
            drift=base.get("drift"),
        )
    return base


def reconcile_firefly_credits(
    *,
    tolerance: float = DEFAULT_RECONCILE_TOLERANCE,
    fetch_credits_fn: Callable[..., dict[str, Any]] | None = None,
    write_audit: bool = True,
    update_account_credits: bool = True,
) -> dict[str, Any]:
    """手动对账入口：遍历全部 Firefly 账号，返回汇总 + 明细。"""
    accounts = _list_firefly_accounts()
    # 一次导出流水，避免每账号重复读存储
    try:
        ledger_entries = channel_usage_service.export_all()
    except Exception as exc:
        logger.warning(
            {
                "event": "channel_reconcile_export_failed",
                "error": redact_auth_diagnostic(exc, 300),
            }
        )
        ledger_entries = []

    items: list[dict[str, Any]] = []
    for account in accounts:
        row = reconcile_firefly_account(
            account,
            ledger_entries=ledger_entries,
            tolerance=tolerance,
            fetch_credits_fn=fetch_credits_fn,
            write_audit=write_audit,
            update_account_credits=update_account_credits,
        )
        items.append(row)

    ok = sum(1 for row in items if row.get("status") == "ok")
    drift = sum(1 for row in items if row.get("status") == "drift")
    error = sum(1 for row in items if row.get("status") == "error")
    return {
        "channel": CHANNEL_FIREFLY,
        "tolerance": _pretty_number(float(tolerance or 0.0)),
        "total": len(items),
        "ok": ok,
        "drift": drift,
        "error": error,
        "accounts": items,
        "ts": time.time(),
    }


__all__ = [
    "DEFAULT_RECONCILE_TOLERANCE",
    "compute_credit_drift",
    "estimate_local_remaining",
    "reconcile_firefly_account",
    "reconcile_firefly_credits",
    "sum_ledger_credits",
]
