from __future__ import annotations

"""渠道用量账本服务：append / query，note 强制脱敏。"""

import threading
import time
from typing import Any

from services.config import config
from services.storage.channel_usage import normalize_channel_usage_entry
from utils.diagnostics import redact_auth_diagnostic
from utils.helper import anonymize_token
from utils.log import logger


def resolve_account_id(account: dict[str, Any] | None, access_token: str = "") -> str:
    """从账号记录解析账本 account_id（优先 account_id / user_id / email）。"""
    if isinstance(account, dict):
        for key in ("account_id", "user_id", "email"):
            value = str(account.get(key) or "").strip()
            if value:
                return value
    token = str(access_token or "").strip()
    if token:
        return anonymize_token(token) or token[:16]
    return "unknown"


class ChannelUsageService:
    """channel_usage 可插拔存储的业务门面。"""

    def __init__(self) -> None:
        self._lock = threading.RLock()

    def append(
        self,
        *,
        trace_id: str,
        channel: str,
        account_id: str,
        action: str,
        model: str = "",
        cost: dict[str, Any] | None = None,
        result: str,
        upstream_id: str | None = None,
        note: str | None = None,
        attempt_seq: int | None = None,
        elapsed_ms: int | None = None,
        ts: float | None = None,
    ) -> dict[str, Any] | None:
        """追加一条用量流水；note 先脱敏。失败只打日志，不抛到主链路。"""
        redacted_note = None
        if note not in (None, ""):
            redacted_note = redact_auth_diagnostic(note, 1000)

        raw = {
            "ts": float(ts if ts is not None else time.time()),
            "trace_id": str(trace_id or "").strip(),
            "channel": str(channel or "").strip(),
            "account_id": str(account_id or "").strip(),
            "action": str(action or "").strip().lower(),
            "model": str(model or "").strip(),
            "cost": dict(cost or {}),
            "result": str(result or "").strip().lower(),
            "upstream_id": str(upstream_id or "").strip() or None,
            "note": redacted_note,
            "attempt_seq": attempt_seq,
            "elapsed_ms": elapsed_ms,
        }
        entry = normalize_channel_usage_entry(raw)
        if entry is None:
            return None
        try:
            with self._lock:
                return config.get_storage_backend().append_channel_usage(entry)
        except Exception as exc:
            logger.warning({
                "event": "channel_usage_append_failed",
                "trace_id": entry.get("trace_id"),
                "channel": entry.get("channel"),
                "error": redact_auth_diagnostic(exc, 500),
            })
            return None

    def query(
        self,
        *,
        account_id: str | None = None,
        trace_id: str | None = None,
        channel: str | None = None,
        ts_from: float | None = None,
        ts_to: float | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        try:
            with self._lock:
                return config.get_storage_backend().query_channel_usage(
                    account_id=account_id,
                    trace_id=trace_id,
                    channel=channel,
                    ts_from=ts_from,
                    ts_to=ts_to,
                    limit=limit,
                )
        except Exception as exc:
            logger.warning({
                "event": "channel_usage_query_failed",
                "error": redact_auth_diagnostic(exc, 500),
            })
            return []

    def record_image_result(
        self,
        *,
        trace_id: str,
        channel: str,
        account: dict[str, Any] | None,
        access_token: str,
        action: str,
        model: str,
        success: bool,
        quota_consumed: bool | None = None,
        failure: Any = None,
        upstream_id: str | None = None,
        attempt_seq: int | None = None,
        elapsed_ms: int | None = None,
        cost: dict[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        """图片/视频结果记账入口：从 finalize 路径调用。"""
        if not str(trace_id or "").strip():
            return None

        account_id = resolve_account_id(account, access_token)
        result = "success" if success else "failed"
        note = None
        if failure is not None:
            code = str(getattr(failure, "code", "") or "").strip()
            raw_detail = getattr(failure, "raw_detail", None)
            public_detail = getattr(failure, "public_detail", None)
            parts = [p for p in (code, str(raw_detail or public_detail or "").strip()) if p]
            note = " | ".join(parts) if parts else str(failure)

        if cost is None:
            cost = _default_cost(channel=channel, action=action, success=success, quota_consumed=quota_consumed)

        return self.append(
            trace_id=trace_id,
            channel=channel,
            account_id=account_id,
            action=action,
            model=model,
            cost=cost,
            result=result,
            upstream_id=upstream_id,
            note=note,
            attempt_seq=attempt_seq,
            elapsed_ms=elapsed_ms,
        )


def _default_cost(
    *,
    channel: str,
    action: str,
    success: bool,
    quota_consumed: bool | None,
) -> dict[str, Any]:
    channel_key = str(channel or "").strip().lower()
    action_key = str(action or "image").strip().lower()
    if channel_key == "firefly":
        # Firefly 按 credits 原生口径；失败是否返还由后续 refunded 冲正行表达
        kind = "video" if action_key == "video" else "image"
        if success:
            return {"credits": 1, "kind": kind}
        return {"credits": 0, "kind": kind}
    # ChatGPT 等：成功且扣额度记 quota=1
    consumed = success if quota_consumed is None else bool(quota_consumed)
    return {"quota": 1 if consumed else 0}


channel_usage_service = ChannelUsageService()
