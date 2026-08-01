from __future__ import annotations

"""载荷快照与 trace 时间轴：按 trace_id 可查的脱敏请求快照 + 阶段耗时。

用途（多渠道 P2 / 02-ledger-tracing §7）：
- 排查「三天前那张图为什么失败」时能看到 prompt/尺寸/模型/渠道
- 管理员可提取 replay_params 做对照重放
- stages 供前端画瀑布时间轴

绝不落库 token / cookie / Authorization / 原始图片字节。
"""

import threading
import time
from pathlib import Path
from typing import Any

from services.config import DATA_DIR
from services.json_file import read_json_file, write_json_file
from utils.diagnostics import redact_auth_diagnostic
from utils.log import logger

# 允许进入快照的标量字段（白名单，避免误带密钥/图片）
_PAYLOAD_SCALAR_KEYS = frozenset({
    "n",
    "size",
    "quality",
    "response_format",
    "stream",
    "partial_images",
    "aspect_ratio",
    "resolution",
    "size_tier",
    "width",
    "height",
    "duration",
    "fps",
    "style",
    "negative_prompt",
})

# 重放时需要的最小参数集
_REPLAY_KEYS = (
    "model",
    "prompt",
    "channel",
    "size",
    "quality",
    "n",
    "response_format",
    "aspect_ratio",
    "resolution",
    "size_tier",
    "width",
    "height",
    "duration",
    "fps",
    "style",
    "negative_prompt",
    "endpoint",
)

# 阶段展示顺序（与前端 useLogTimeline 对齐，未知阶段追加在后）
_STAGE_ORDER = (
    "handler_queue_ms",
    "handler_exec_ms",
    "stream_first_queue_ms",
    "stream_first_exec_ms",
    "account_wait_ms",
    "egress_wait_ms",
    "egress_acquire_ms",
    "upload_ms",
    "bootstrap_ms",
    "requirements_ms",
    "prepare_conversation_ms",
    "generation_start_ms",
    "http_dns_ms",
    "http_tcp_ms",
    "http_tls_ms",
    "http_wait_ms",
    "http_ttfb_ms",
    "sse_first_event_ms",
    "sse_max_gap_ms",
    "sse_last_gap_ms",
    "conversation_stream_ms",
    "stream_error_ms",
    "resolve_ms",
    "download_ms",
    "retry_wait_ms",
    "response_ms",
    "stream_ms",
    "total_ms",
)

_MAX_SNAPSHOTS = 10000
_PROMPT_LIMIT = 4000


def build_payload_snapshot(
    *,
    model: str = "",
    endpoint: str = "",
    request_text: str = "",
    request_shape: dict[str, Any] | None = None,
    body: dict[str, Any] | None = None,
    channel: str | None = None,
    trace_metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """从调用上下文构造脱敏载荷快照（纯函数，便于单测）。

    字段：prompt / model / channel / endpoint / 尺寸类标量 / request_shape。
    绝不包含 token / cookie / Authorization / 图片 bytes。
    """
    payload: dict[str, Any] = {}

    model_text = str(model or "").strip()
    if not model_text and isinstance(body, dict):
        model_text = str(body.get("model") or "").strip()
    if model_text:
        payload["model"] = model_text

    endpoint_text = str(endpoint or "").strip()
    if endpoint_text:
        payload["endpoint"] = endpoint_text

    # 渠道：优先显式传入，否则按模型前缀路由
    channel_text = str(channel or "").strip().lower()
    if not channel_text:
        try:
            from services.channels.registry import channel_for_model

            channel_text = channel_for_model(model_text)
        except Exception:
            channel_text = "chatgpt"
    if channel_text:
        payload["channel"] = channel_text

    # prompt：只取纯文本摘要，再过脱敏
    prompt = str(request_text or "").strip()
    if not prompt and isinstance(body, dict):
        for key in ("prompt", "input", "instructions"):
            value = body.get(key)
            if isinstance(value, str) and value.strip():
                prompt = value.strip()
                break
    if prompt:
        payload["prompt"] = redact_auth_diagnostic(prompt, _PROMPT_LIMIT)

    # 白名单标量：body + trace_metadata（LoggedCall 已从 body 抽过 size/quality 等）
    sources: list[dict[str, Any]] = []
    if isinstance(body, dict):
        sources.append(body)
    if isinstance(trace_metadata, dict):
        sources.append(trace_metadata)
    for source in sources:
        for key in _PAYLOAD_SCALAR_KEYS:
            if key in payload:
                continue
            if key not in source:
                continue
            value = source.get(key)
            if value in (None, ""):
                continue
            if isinstance(value, (str, int, float, bool)):
                # 字符串再脱敏一次，防 size 等字段被塞 token
                if isinstance(value, str):
                    payload[key] = redact_auth_diagnostic(value, 200)
                else:
                    payload[key] = value

    # 输入图数量：只记个数，不记内容
    if "input_image_count" not in payload:
        count = None
        if isinstance(trace_metadata, dict) and "input_image_count" in trace_metadata:
            count = trace_metadata.get("input_image_count")
        elif isinstance(body, dict):
            images = body.get("images")
            if isinstance(images, list):
                count = len(images)
        if count is not None:
            try:
                payload["input_image_count"] = int(count)
            except (TypeError, ValueError):
                pass

    if isinstance(request_shape, dict) and request_shape:
        # 只保留 int 计数
        shape: dict[str, int] = {}
        for key, value in request_shape.items():
            try:
                shape[str(key)] = int(value)
            except (TypeError, ValueError):
                continue
        if shape:
            payload["request_shape"] = shape

    return payload


def extract_replay_params(payload: dict[str, Any] | None) -> dict[str, Any]:
    """从脱敏快照提取「重新以此参数生成」所需字段。"""
    if not isinstance(payload, dict):
        return {}
    replay: dict[str, Any] = {}
    for key in _REPLAY_KEYS:
        if key not in payload:
            continue
        value = payload.get(key)
        if value in (None, ""):
            continue
        if isinstance(value, (str, int, float, bool)):
            replay[key] = value
    return replay


def stages_from_perf(perf: dict[str, Any] | None) -> list[dict[str, Any]]:
    """把 LoggedCall.perf_timings / detail.perf 聚合成 [{stage, elapsed_ms}, ...]。"""
    if not isinstance(perf, dict) or not perf:
        return []
    items: list[tuple[str, int]] = []
    for key, raw in perf.items():
        stage = str(key or "").strip()
        if not stage:
            continue
        try:
            elapsed = int(raw)
        except (TypeError, ValueError):
            continue
        if elapsed < 0:
            continue
        items.append((stage, elapsed))

    order = {name: idx for idx, name in enumerate(_STAGE_ORDER)}
    items.sort(key=lambda pair: (order.get(pair[0], 10_000), pair[0]))
    return [{"stage": stage, "elapsed_ms": elapsed} for stage, elapsed in items]


def attempts_from_usage_rows(rows: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    """把 channel_usage 流水行映射为 attempt 序列。"""
    if not rows:
        return []
    attempts: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        # 跳过日聚合冷数据
        note = str(row.get("note") or "").strip()
        if note == "daily_aggregate":
            continue
        seq = row.get("attempt_seq")
        try:
            seq_int = int(seq) if seq is not None and seq != "" else None
        except (TypeError, ValueError):
            seq_int = None
        elapsed = row.get("elapsed_ms")
        try:
            elapsed_int = int(elapsed) if elapsed is not None and elapsed != "" else None
        except (TypeError, ValueError):
            elapsed_int = None
        attempts.append({
            "seq": seq_int if seq_int is not None else (len(attempts) + 1),
            "account_id": str(row.get("account_id") or "").strip() or None,
            "channel": str(row.get("channel") or "").strip() or None,
            "model": str(row.get("model") or "").strip() or None,
            "action": str(row.get("action") or "").strip() or None,
            "result": str(row.get("result") or "").strip() or None,
            "reason": note or None,
            "elapsed_ms": elapsed_int,
            "upstream_id": str(row.get("upstream_id") or "").strip() or None,
            "ts": row.get("ts"),
            "cost": dict(row.get("cost") or {}) if isinstance(row.get("cost"), dict) else {},
        })
    attempts.sort(key=lambda item: (
        int(item.get("seq") or 0),
        float(item.get("ts") or 0),
    ))
    return attempts


class TraceSnapshotService:
    """按 trace_id 持久化脱敏载荷快照 + 阶段耗时。"""

    def __init__(self, path: Path | None = None) -> None:
        self.path = path or (DATA_DIR / "trace_snapshots.json")
        self._lock = threading.RLock()

    def capture_from_call(self, call: Any, body: dict[str, Any] | None = None) -> dict[str, Any] | None:
        """在 LoggedCall.attach_trace_metadata 时写入初始快照。"""
        trace_id = str(getattr(call, "trace_id", "") or "").strip()
        if not trace_id:
            return None
        payload = build_payload_snapshot(
            model=str(getattr(call, "model", "") or ""),
            endpoint=str(getattr(call, "endpoint", "") or ""),
            request_text=str(getattr(call, "request_text", "") or ""),
            request_shape=getattr(call, "request_shape", None),
            body=body if isinstance(body, dict) else None,
            trace_metadata=getattr(call, "trace_metadata", None),
        )
        return self.save_snapshot(
            trace_id=trace_id,
            call_id=str(getattr(call, "call_id", "") or "").strip() or None,
            payload=payload,
            stages=stages_from_perf(getattr(call, "perf_timings", None)),
        )

    def finalize_from_call(self, call: Any, detail: dict[str, Any] | None = None) -> dict[str, Any] | None:
        """在 LoggedCall.log 结束时合并阶段耗时与调用摘要。"""
        trace_id = str(getattr(call, "trace_id", "") or "").strip()
        if not trace_id:
            return None
        detail = detail if isinstance(detail, dict) else {}
        perf = detail.get("perf") if isinstance(detail.get("perf"), dict) else getattr(call, "perf_timings", None)
        stages = stages_from_perf(perf)
        call_summary = {
            "call_id": str(detail.get("call_id") or getattr(call, "call_id", "") or "").strip() or None,
            "endpoint": str(detail.get("endpoint") or getattr(call, "endpoint", "") or "").strip() or None,
            "model": str(detail.get("model") or getattr(call, "model", "") or "").strip() or None,
            "status": str(detail.get("status") or "").strip() or None,
            "duration_ms": detail.get("duration_ms"),
            "started_at": detail.get("started_at"),
            "ended_at": detail.get("ended_at"),
            "account_email": detail.get("account_email"),
            "conversation_id": detail.get("conversation_id"),
            "error": redact_auth_diagnostic(detail.get("error"), 1000) if detail.get("error") else None,
        }
        # 若尚未 capture，用 detail 补一份 payload
        payload = build_payload_snapshot(
            model=str(call_summary.get("model") or ""),
            endpoint=str(call_summary.get("endpoint") or ""),
            request_text=str(detail.get("request_text_full") or detail.get("request_text") or getattr(call, "request_text", "") or ""),
            request_shape=detail.get("request_shape") if isinstance(detail.get("request_shape"), dict) else getattr(call, "request_shape", None),
            body=None,
            channel=None,
            trace_metadata=detail.get("request_meta") if isinstance(detail.get("request_meta"), dict) else getattr(call, "trace_metadata", None),
        )
        return self.save_snapshot(
            trace_id=trace_id,
            call_id=call_summary.get("call_id"),
            payload=payload,
            stages=stages,
            call=call_summary,
            merge=True,
        )

    def save_snapshot(
        self,
        *,
        trace_id: str,
        call_id: str | None = None,
        payload: dict[str, Any] | None = None,
        stages: list[dict[str, Any]] | None = None,
        call: dict[str, Any] | None = None,
        merge: bool = True,
    ) -> dict[str, Any] | None:
        """写入/合并一条 trace 快照。失败只打日志，不抛。"""
        tid = str(trace_id or "").strip()
        if not tid:
            return None
        now = time.time()
        try:
            with self._lock:
                store = self._load()
                existing = store.get(tid) if merge else None
                if not isinstance(existing, dict):
                    existing = {}

                entry: dict[str, Any] = {
                    "trace_id": tid,
                    "ts": float(existing.get("ts") or now),
                    "updated_at": now,
                }
                cid = str(call_id or existing.get("call_id") or "").strip()
                if cid:
                    entry["call_id"] = cid

                # payload 合并：新字段覆盖旧字段，但空值不抹掉已有
                merged_payload = dict(existing.get("payload") or {}) if isinstance(existing.get("payload"), dict) else {}
                if isinstance(payload, dict):
                    for key, value in payload.items():
                        if value in (None, ""):
                            continue
                        merged_payload[key] = value
                if merged_payload:
                    entry["payload"] = merged_payload
                    entry["replay_params"] = extract_replay_params(merged_payload)

                # stages：有新的就覆盖（finalize 时更完整）
                if stages:
                    entry["stages"] = list(stages)
                elif isinstance(existing.get("stages"), list):
                    entry["stages"] = list(existing["stages"])
                else:
                    entry["stages"] = []

                if isinstance(call, dict) and call:
                    merged_call = dict(existing.get("call") or {}) if isinstance(existing.get("call"), dict) else {}
                    for key, value in call.items():
                        if value in (None, ""):
                            continue
                        merged_call[key] = value
                    entry["call"] = merged_call
                elif isinstance(existing.get("call"), dict):
                    entry["call"] = dict(existing["call"])

                store[tid] = entry
                self._trim(store)
                self._persist(store)
                return dict(entry)
        except Exception as exc:
            logger.warning({
                "event": "trace_snapshot_save_failed",
                "trace_id": tid,
                "error": redact_auth_diagnostic(exc, 500),
            })
            return None

    def get(self, trace_id: str) -> dict[str, Any] | None:
        tid = str(trace_id or "").strip()
        if not tid:
            return None
        with self._lock:
            store = self._load()
            entry = store.get(tid)
            return dict(entry) if isinstance(entry, dict) else None

    def get_trace(self, trace_id: str) -> dict[str, Any] | None:
        """聚合快照 + channel_usage attempts，供 API 返回。"""
        tid = str(trace_id or "").strip()
        if not tid:
            return None

        snapshot = self.get(tid)
        attempts: list[dict[str, Any]] = []
        try:
            from services.channel_usage_service import channel_usage_service

            rows = channel_usage_service.query(trace_id=tid, limit=100)
            attempts = attempts_from_usage_rows(rows)
        except Exception as exc:
            logger.warning({
                "event": "trace_snapshot_attempts_failed",
                "trace_id": tid,
                "error": redact_auth_diagnostic(exc, 500),
            })

        if snapshot is None and not attempts:
            return None

        payload = dict(snapshot.get("payload") or {}) if isinstance(snapshot, dict) else {}
        stages = list(snapshot.get("stages") or []) if isinstance(snapshot, dict) else []
        # 若快照无 stages，尝试从 attempt 的 elapsed 兜底（粗粒度）
        if not stages and attempts:
            stages = [
                {
                    "stage": f"attempt_{item.get('seq')}",
                    "elapsed_ms": int(item["elapsed_ms"]),
                }
                for item in attempts
                if item.get("elapsed_ms") is not None
            ]

        # 若仍无 channel，从 attempt 反推
        if not payload.get("channel") and attempts:
            for item in reversed(attempts):
                if item.get("channel"):
                    payload["channel"] = item["channel"]
                    break
        if not payload.get("model") and attempts:
            for item in reversed(attempts):
                if item.get("model"):
                    payload["model"] = item["model"]
                    break

        call = dict(snapshot.get("call") or {}) if isinstance(snapshot, dict) else {}
        return {
            "trace_id": tid,
            "call_id": (snapshot or {}).get("call_id") or call.get("call_id"),
            "payload": payload,
            "replay_params": extract_replay_params(payload) if payload else dict((snapshot or {}).get("replay_params") or {}),
            "stages": stages,
            "attempts": attempts,
            "call": call,
            "ts": (snapshot or {}).get("ts"),
            "updated_at": (snapshot or {}).get("updated_at"),
        }

    def clear(self) -> None:
        """测试用：清空全部快照。"""
        with self._lock:
            self._persist({})

    def _load(self) -> dict[str, Any]:
        data = read_json_file(
            self.path,
            name="trace_snapshots",
            default_factory=dict,
            expected_types=dict,
        )
        if not isinstance(data, dict):
            return {}
        # 只保留 dict 条目
        return {
            str(key): value
            for key, value in data.items()
            if isinstance(value, dict) and str(key).strip()
        }

    def _persist(self, store: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        write_json_file(self.path, store)

    def _trim(self, store: dict[str, Any]) -> None:
        if len(store) <= _MAX_SNAPSHOTS:
            return
        # 按 updated_at 升序，删最旧的
        ordered = sorted(
            store.items(),
            key=lambda pair: float((pair[1] or {}).get("updated_at") or (pair[1] or {}).get("ts") or 0),
        )
        overflow = len(store) - _MAX_SNAPSHOTS
        for key, _ in ordered[:overflow]:
            store.pop(key, None)


trace_snapshot_service = TraceSnapshotService()
