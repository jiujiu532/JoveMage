from __future__ import annotations

"""channel_usage 账本字段契约与归一化。

字段契约（与 .trellis/spec/backend/multi-channel/02-ledger-tracing.md §3.1 对齐）：
- ts: float — Unix 秒
- trace_id: str — 全链路关联键
- channel: str — 渠道 id（chatgpt / firefly / …）
- account_id: str — 账号标识
- action: image | video | edit | chat | refresh
- model: str
- cost: object — 原生计量（如 {"quota": 1} / {"credits": 1, "kind": "image"}）
- result: success | failed | refunded
- upstream_id: str | None
- note: str | None — 须已脱敏
可选扩展（attempt 轨迹）：
- attempt_seq: int | None
- elapsed_ms: int | None
- id: str — 行唯一 id
"""

import time
from typing import Any
from uuid import uuid4

CHANNEL_USAGE_ACTIONS = frozenset({"image", "video", "edit", "chat", "refresh", "circuit"})
CHANNEL_USAGE_RESULTS = frozenset({"success", "failed", "refunded", "open"})

# 熔断事件动作：审计用，不计入 credits/quota 求和，也不计账号成功率
CHANNEL_USAGE_CIRCUIT_ACTION = "circuit"


def normalize_channel_usage_entry(raw: dict[str, Any] | None) -> dict[str, Any] | None:
    """归一化一条 channel_usage 流水；非法必填字段返回 None。"""
    if not isinstance(raw, dict):
        return None

    trace_id = str(raw.get("trace_id") or "").strip()
    channel = str(raw.get("channel") or "").strip()
    account_id = str(raw.get("account_id") or "").strip()
    action = str(raw.get("action") or "").strip().lower()
    result = str(raw.get("result") or "").strip().lower()
    model = str(raw.get("model") or "").strip()

    if not trace_id or not channel or not account_id:
        return None
    if action not in CHANNEL_USAGE_ACTIONS:
        return None
    if result not in CHANNEL_USAGE_RESULTS:
        return None

    try:
        ts = float(raw.get("ts") if raw.get("ts") is not None else time.time())
    except (TypeError, ValueError):
        ts = time.time()

    cost = raw.get("cost")
    if not isinstance(cost, dict):
        cost = {}

    entry: dict[str, Any] = {
        "id": str(raw.get("id") or "").strip() or uuid4().hex,
        "ts": ts,
        "trace_id": trace_id,
        "channel": channel,
        "account_id": account_id,
        "action": action,
        "model": model,
        "cost": dict(cost),
        "result": result,
        "upstream_id": str(raw.get("upstream_id") or "").strip() or None,
        "note": str(raw.get("note") or "").strip() or None,
    }

    attempt_seq = raw.get("attempt_seq")
    if attempt_seq is not None and attempt_seq != "":
        try:
            entry["attempt_seq"] = int(attempt_seq)
        except (TypeError, ValueError):
            pass

    elapsed_ms = raw.get("elapsed_ms")
    if elapsed_ms is not None and elapsed_ms != "":
        try:
            entry["elapsed_ms"] = int(elapsed_ms)
        except (TypeError, ValueError):
            pass

    return entry


def match_channel_usage(
    entry: dict[str, Any],
    *,
    account_id: str | None = None,
    trace_id: str | None = None,
    channel: str | None = None,
    ts_from: float | None = None,
    ts_to: float | None = None,
) -> bool:
    """按查询条件过滤一条流水。"""
    if account_id is not None and str(entry.get("account_id") or "") != str(account_id):
        return False
    if trace_id is not None and str(entry.get("trace_id") or "") != str(trace_id):
        return False
    if channel is not None and str(entry.get("channel") or "") != str(channel):
        return False
    try:
        ts = float(entry.get("ts") or 0)
    except (TypeError, ValueError):
        ts = 0.0
    if ts_from is not None and ts < float(ts_from):
        return False
    if ts_to is not None and ts > float(ts_to):
        return False
    return True
