from __future__ import annotations

"""渠道用量账本服务：append / query / 保留策略，note 强制脱敏。"""

import threading
import time
from datetime import datetime, timedelta, timezone
from typing import Any

from services.config import config
from services.storage.base import CHANNEL_USAGE_DAILY_AGGREGATE_NOTE, is_channel_usage_aggregate_row
from services.storage.channel_usage import normalize_channel_usage_entry
from utils.diagnostics import redact_auth_diagnostic
from utils.helper import anonymize_token
from utils.log import logger

# 明细默认保留天数（03-backend-governance §4）
DEFAULT_CHANNEL_USAGE_RETENTION_DAYS = 30


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
            # 日聚合标记是内部常量，跳过 redact 以免被截断
            if str(note).strip() == CHANNEL_USAGE_DAILY_AGGREGATE_NOTE:
                redacted_note = CHANNEL_USAGE_DAILY_AGGREGATE_NOTE
            else:
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

    def prune_before(self, ts: float) -> int:
        """删除 ts 之前的明细行；异常吞掉打 warning，返回删除条数（失败为 0）。"""
        try:
            with self._lock:
                deleted = int(config.get_storage_backend().delete_channel_usage_before(float(ts)))
            logger.info({
                "event": "channel_usage_prune",
                "cutoff_ts": float(ts),
                "deleted": deleted,
            })
            return deleted
        except Exception as exc:
            logger.warning({
                "event": "channel_usage_prune_failed",
                "cutoff_ts": float(ts),
                "error": redact_auth_diagnostic(exc, 500),
            })
            return 0

    def aggregate_daily(self, day_start_ts: float, day_end_ts: float) -> list[dict[str, Any]]:
        """门面：按天聚合明细（不落库）。异常吞掉，返回 []。"""
        try:
            with self._lock:
                return list(
                    config.get_storage_backend().aggregate_channel_usage_daily(
                        float(day_start_ts),
                        float(day_end_ts),
                    )
                )
        except Exception as exc:
            logger.warning({
                "event": "channel_usage_aggregate_failed",
                "day_start_ts": float(day_start_ts),
                "day_end_ts": float(day_end_ts),
                "error": redact_auth_diagnostic(exc, 500),
            })
            return []

    def run_retention_maintenance(self, retention_days: int = DEFAULT_CHANNEL_USAGE_RETENTION_DAYS) -> dict[str, Any]:
        """明细保留策略：先对过期天做日聚合落库，再删除明细。

        账本只增不改：
        - 聚合行是新增行（action 仍用原 action 枚举，note=daily_aggregate，
          cost 带 aggregated/count/credits/quota 汇总；trace_id 形如 daily-agg:YYYY-MM-DD:...）
        - 明细删除仅在聚合成功后执行（冷数据允许删）
        幂等：同一天同一 (channel, account_id, action, result) 若已有聚合行则跳过追加。
        异常全部吞掉，绝不抛到调用方。
        """
        result: dict[str, Any] = {
            "retention_days": int(retention_days),
            "cutoff_ts": 0.0,
            "days_processed": 0,
            "aggregate_rows_written": 0,
            "deleted": 0,
            "ok": True,
        }
        try:
            days = max(1, int(retention_days or DEFAULT_CHANNEL_USAGE_RETENTION_DAYS))
            now = datetime.now(timezone.utc)
            # 保留最近 N 个完整 UTC 日 + 当天：cutoff = 今天 00:00 UTC 往前 N 天
            today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
            cutoff_dt = today_start - timedelta(days=days)
            cutoff_ts = cutoff_dt.timestamp()
            result["cutoff_ts"] = cutoff_ts

            backend = config.get_storage_backend()
            # 找最老明细，决定从哪一天开始聚合（避免无脑扫 30 天空窗）
            oldest_ts = self._find_oldest_detail_ts(backend, before_ts=cutoff_ts)
            if oldest_ts is None:
                # 扫描失败（None 也可能来自异常）时按「失败不 prune」处理：
                # 区分「真的没有过期明细」与「扫描出错」——出错则本轮不删，防误删未聚合明细。
                if getattr(self, "_oldest_scan_failed", False):
                    result["ok"] = False
                    result["scan_error"] = True
                    logger.warning({"event": "channel_usage_retention_abort", "reason": "oldest_scan_failed"})
                    return result
                # 真的没有可聚合的过期明细，仍执行一次 prune（幂等清理）
                result["deleted"] = self.prune_before(cutoff_ts)
                return result

            day_cursor = datetime.fromtimestamp(oldest_ts, tz=timezone.utc).replace(
                hour=0, minute=0, second=0, microsecond=0
            )
            written = 0
            days_processed = 0
            while day_cursor < cutoff_dt:
                day_start = day_cursor.timestamp()
                day_end = (day_cursor + timedelta(days=1)).timestamp()
                day_key = day_cursor.strftime("%Y-%m-%d")
                agg_rows = self.aggregate_daily(day_start, day_end)
                days_processed += 1
                for row in agg_rows:
                    if self._daily_aggregate_exists(
                        backend,
                        day_key=day_key,
                        channel=str(row.get("channel") or ""),
                        account_id=str(row.get("account_id") or ""),
                        action=str(row.get("action") or ""),
                        result=str(row.get("result") or ""),
                    ):
                        continue
                    cost_src = row.get("cost") if isinstance(row.get("cost"), dict) else {}
                    cost = {
                        "aggregated": True,
                        "count": int(row.get("count") or 0),
                        "credits": cost_src.get("credits", 0),
                        "quota": cost_src.get("quota", 0),
                        "day": day_key,
                    }
                    # 聚合行 trace_id 稳定，便于幂等识别
                    trace_id = (
                        f"daily-agg:{day_key}:"
                        f"{row.get('channel')}:{row.get('account_id')}:"
                        f"{row.get('action')}:{row.get('result')}"
                    )
                    written_entry = self.append(
                        trace_id=trace_id,
                        channel=str(row.get("channel") or ""),
                        account_id=str(row.get("account_id") or ""),
                        action=str(row.get("action") or "chat"),
                        model="",
                        cost=cost,
                        result=str(row.get("result") or "success"),
                        note=CHANNEL_USAGE_DAILY_AGGREGATE_NOTE,
                        # 锚定在当天中午，避免边界歧义
                        ts=day_start + 12 * 3600,
                    )
                    if written_entry is not None:
                        written += 1
                day_cursor += timedelta(days=1)

            result["days_processed"] = days_processed
            result["aggregate_rows_written"] = written
            # 聚合完成后再删明细（聚合行 note=daily_aggregate，prune 会跳过）
            result["deleted"] = self.prune_before(cutoff_ts)
            logger.info({
                "event": "channel_usage_retention_done",
                "retention_days": days,
                "cutoff_ts": cutoff_ts,
                "days_processed": days_processed,
                "aggregate_rows_written": written,
                "deleted": result["deleted"],
            })
            return result
        except Exception as exc:
            result["ok"] = False
            logger.warning({
                "event": "channel_usage_retention_failed",
                "error": redact_auth_diagnostic(exc, 500),
            })
            return result

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

    def export_all(self) -> list[dict[str, Any]]:
        """导出全部流水（备份用）；失败返回 []。"""
        try:
            with self._lock:
                backend = config.get_storage_backend()
                export = getattr(backend, "export_channel_usage", None)
                if callable(export):
                    return list(export())
                return list(backend.query_channel_usage(limit=1000))
        except Exception as exc:
            logger.warning({
                "event": "channel_usage_export_failed",
                "error": redact_auth_diagnostic(exc, 500),
            })
            return []

    def account_profile(
        self,
        account_id: str,
        *,
        recent_limit: int = 20,
        channel: str | None = None,
        now_ts: float | None = None,
    ) -> dict[str, Any]:
        """账号行为档案：今日次数/成功率/credits + 最近 N 条 + 失败/跳过原因分组。

        数据源：channel_usage 按 account_id 查询后在内存聚合（KISS，避免各后端重写 SQL）。
        聚合行（daily_aggregate）不计入今日明细统计，但仍可出现在 recent 之外的历史查询中——
        本接口 recent 也跳过聚合行，只回明细。
        """
        account_key = str(account_id or "").strip()
        if not account_key:
            return {
                "account_id": "",
                "today": {
                    "calls": 0,
                    "success": 0,
                    "failed": 0,
                    "success_rate": 0.0,
                    "credits": 0.0,
                    "quota": 0.0,
                },
                "failure_reasons": [],
                "recent": [],
            }

        now = float(now_ts if now_ts is not None else time.time())
        day_start = datetime.fromtimestamp(now, tz=timezone.utc).replace(
            hour=0, minute=0, second=0, microsecond=0
        ).timestamp()

        # 今日统计单独按 ts_from 拉全（避免今日明细被近期历史挤出窗口导致少计）；
        # 最近 N 条仍按窗口另查，两路互不影响。
        try:
            today_rows = self.query(
                account_id=account_key,
                channel=channel,
                ts_from=day_start,
                limit=1000,
            )
        except Exception:
            today_rows = []
        # 最近 N：拉一个较宽窗口，覆盖失败原因统计与 recent
        limit = max(50, int(recent_limit or 20) * 5, 200)
        try:
            rows = self.query(
                account_id=account_key,
                channel=channel,
                limit=limit,
            )
        except Exception:
            rows = []

        today_details: list[dict[str, Any]] = []
        for row in today_rows:
            if not isinstance(row, dict):
                continue
            if is_channel_usage_aggregate_row(row):
                continue
            if str(row.get("action") or "").strip().lower() == "circuit":
                continue
            today_details.append(row)

        details: list[dict[str, Any]] = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            if is_channel_usage_aggregate_row(row):
                continue
            # 熔断事件（action=circuit）是审计，不算账号真实调用，不进档案统计/明细
            if str(row.get("action") or "").strip().lower() == "circuit":
                continue
            details.append(row)

        today_calls = 0
        today_success = 0
        today_failed = 0
        today_credits = 0.0
        today_quota = 0.0
        reason_counter: dict[str, int] = {}

        # 今日计数走 today_details（已按 ts_from=day_start 过滤，无需再判 ts）
        for row in today_details:
            result = str(row.get("result") or "").strip().lower()
            cost = row.get("cost") if isinstance(row.get("cost"), dict) else {}
            today_calls += 1
            if result == "success":
                today_success += 1
            elif result == "failed":
                today_failed += 1
            try:
                today_credits += float(cost.get("credits") or 0)
            except (TypeError, ValueError):
                pass
            try:
                today_quota += float(cost.get("quota") or 0)
            except (TypeError, ValueError):
                pass

        # 失败原因统计仍走 details（窗口内历史 + 今日）
        for row in details:
            result = str(row.get("result") or "").strip().lower()

            # 失败/跳过原因：failed 行按 note 或 result 分组
            if result == "failed":
                note = str(row.get("note") or "").strip()
                key = note or result or "failed"
                # 截断过长 note，避免展示爆炸
                if len(key) > 200:
                    key = key[:200]
                reason_counter[key] = int(reason_counter.get(key, 0)) + 1

        success_rate = (
            float(today_success) / float(today_calls) if today_calls > 0 else 0.0
        )
        # 最近 N：按 ts 倒序（query 已大致新→旧，再稳妥排一次）
        recent_sorted = sorted(
            details,
            key=lambda r: float(r.get("ts") or 0),
            reverse=True,
        )
        recent_n = max(1, min(int(recent_limit or 20), 200))
        recent = recent_sorted[:recent_n]

        failure_reasons = [
            {"reason": reason, "count": count}
            for reason, count in sorted(
                reason_counter.items(),
                key=lambda item: (-item[1], item[0]),
            )
        ]

        return {
            "account_id": account_key,
            "today": {
                "calls": today_calls,
                "success": today_success,
                "failed": today_failed,
                "success_rate": round(success_rate, 4),
                "credits": today_credits,
                "quota": today_quota,
                "day_start_ts": day_start,
            },
            "failure_reasons": failure_reasons,
            "recent": recent,
        }

    def _find_oldest_detail_ts(self, backend: Any, *, before_ts: float) -> float | None:
        """找 cutoff 之前最老的明细 ts；没有则 None。扫描异常时置 _oldest_scan_failed。"""
        self._oldest_scan_failed = False
        try:
            export = getattr(backend, "export_channel_usage", None)
            if callable(export):
                items = list(export())
            else:
                items = list(backend.query_channel_usage(ts_to=before_ts, limit=1000))
        except Exception as exc:
            self._oldest_scan_failed = True
            logger.warning({
                "event": "channel_usage_oldest_scan_failed",
                "error": redact_auth_diagnostic(exc, 500),
            })
            return None
        oldest: float | None = None
        for item in items:
            if not isinstance(item, dict) or is_channel_usage_aggregate_row(item):
                continue
            try:
                ts = float(item.get("ts") or 0)
            except (TypeError, ValueError):
                continue
            if ts >= float(before_ts):
                continue
            if oldest is None or ts < oldest:
                oldest = ts
        return oldest

    def _daily_aggregate_exists(
        self,
        backend: Any,
        *,
        day_key: str,
        channel: str,
        account_id: str,
        action: str,
        result: str,
    ) -> bool:
        """幂等：同一天同一维度是否已有聚合行。"""
        trace_id = f"daily-agg:{day_key}:{channel}:{account_id}:{action}:{result}"
        try:
            found = backend.query_channel_usage(trace_id=trace_id, limit=1)
            if found:
                return True
        except Exception:
            # 查询失败时保守返回 True（视为已存在、跳过写入），避免重复聚合行导致对账双计；
            # 宁可本次少写（下轮 retention 再补），不可多写。
            return True
        return False


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

# 明细保留维护的默认运行间隔（秒）：每天一次
_CHANNEL_USAGE_RETENTION_INTERVAL_SEC = 24 * 3600


def _retention_worker(stop_event: threading.Event) -> None:
    """后台定时跑 channel_usage 明细保留维护（聚合 + 删除）。

    复用现有 daemon 线程调度模式（同 start_log_cleanup_scheduler）。
    首次延迟一个间隔再跑，避免启动期抢资源；之后每天一次。异常全部吞掉。
    """
    while not stop_event.wait(_CHANNEL_USAGE_RETENTION_INTERVAL_SEC):
        try:
            result = channel_usage_service.run_retention_maintenance()
            logger.info({"event": "channel_usage_retention_done", **result})
        except Exception as exc:  # 防御：service 内部已吞，这里兜底
            logger.warning({
                "event": "channel_usage_retention_failed",
                "error": redact_auth_diagnostic(exc, 500),
            })


def start_channel_usage_retention_scheduler(stop_event: threading.Event) -> threading.Thread:
    """启动 channel_usage 保留维护后台线程。"""
    thread = threading.Thread(
        target=_retention_worker,
        args=(stop_event,),
        daemon=True,
        name="channel-usage-retention",
    )
    thread.start()
    return thread
