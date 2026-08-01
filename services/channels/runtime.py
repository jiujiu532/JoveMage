from __future__ import annotations

"""渠道运行时状态：进程内熔断 + 速率预算（占位兑现）。

本期：
- 熔断只服务 Firefly 旁路（ChatGPT 主航道不经此模块）
- 状态纯内存，不持久化；进程重启后熔断/令牌桶清零
- rate_budget 是 01 描述符占位的最小可用实现，后续渠道 2 再泛化

配置键（ConfigStore 双读：channels.firefly.* > 平铺 firefly_*）：
- circuit_failure_threshold（默认 5）
- circuit_cooldown_sec（默认 300）
- rate_budget（默认 {"poll_per_sec": 5}）
"""

import threading
import time
from typing import Any

from utils.diagnostics import redact_auth_diagnostic
from utils.log import logger

# ---- 默认值（与 03 §8 / 任务约定对齐）----
DEFAULT_CIRCUIT_FAILURE_THRESHOLD = 5
DEFAULT_CIRCUIT_COOLDOWN_SEC = 300
DEFAULT_POLL_PER_SEC = 5.0
FIREFLY_CHANNEL_ID = "firefly"

# 模块级锁：熔断状态 + 令牌桶共用一把，状态体量小、调用不频繁
_lock = threading.RLock()

# channel -> 熔断运行时
_circuit_states: dict[str, dict[str, Any]] = {}
# channel -> 令牌桶运行时
_rate_states: dict[str, dict[str, Any]] = {}


def _normalize_channel(channel: str | None) -> str:
    return str(channel or "").strip().lower()


def _safe_positive_int(value: object, default: int, minimum: int = 1) -> int:
    try:
        parsed = int(float(value))  # type: ignore[arg-type]
    except (TypeError, ValueError, OverflowError):
        return default
    return max(minimum, parsed)


def _safe_positive_float(value: object, default: float, minimum: float = 0.1) -> float:
    try:
        parsed = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError, OverflowError):
        return default
    if parsed <= 0:
        return default
    return max(minimum, parsed)


def _read_firefly_nested() -> dict[str, Any]:
    """读 channels.firefly 嵌套 dict；失败返回空。"""
    try:
        from services.config import config

        config.reload_if_changed()
        data = config.data if isinstance(getattr(config, "data", None), dict) else {}
        channels = data.get("channels")
        if not isinstance(channels, dict):
            return {}
        firefly = channels.get("firefly")
        return dict(firefly) if isinstance(firefly, dict) else {}
    except Exception:
        return {}


def _read_firefly_root() -> dict[str, Any]:
    try:
        from services.config import config

        config.reload_if_changed()
        data = getattr(config, "data", None)
        return dict(data) if isinstance(data, dict) else {}
    except Exception:
        return {}


def _dual_read_firefly(key: str, default: object = None) -> object:
    """channels.firefly.<key> > firefly_<key> 平铺 > default。

    不依赖 ConfigStore 是否已声明该属性；新键可直接落 nested。
    """
    nested = _read_firefly_nested()
    if key in nested:
        return nested.get(key)
    root = _read_firefly_root()
    flat_key = f"firefly_{key}"
    if flat_key in root:
        return root.get(flat_key)
    return default


def circuit_failure_threshold() -> int:
    raw = _dual_read_firefly("circuit_failure_threshold", DEFAULT_CIRCUIT_FAILURE_THRESHOLD)
    return _safe_positive_int(raw, DEFAULT_CIRCUIT_FAILURE_THRESHOLD, 1)


def circuit_cooldown_sec() -> int:
    raw = _dual_read_firefly("circuit_cooldown_sec", DEFAULT_CIRCUIT_COOLDOWN_SEC)
    return _safe_positive_int(raw, DEFAULT_CIRCUIT_COOLDOWN_SEC, 1)


def rate_budget_config(channel: str | None = FIREFLY_CHANNEL_ID) -> dict[str, Any]:
    """读取渠道 rate_budget；缺省保守值。

    形状示例：{"poll_per_sec": 5}
    本期仅消费 poll_per_sec；其它键忽略。
    """
    cid = _normalize_channel(channel) or FIREFLY_CHANNEL_ID
    raw: object = None
    if cid == FIREFLY_CHANNEL_ID:
        raw = _dual_read_firefly("rate_budget", None)
    if not isinstance(raw, dict):
        return {"poll_per_sec": DEFAULT_POLL_PER_SEC}
    out = dict(raw)
    if "poll_per_sec" not in out:
        out["poll_per_sec"] = DEFAULT_POLL_PER_SEC
    return out


def _circuit_state(channel: str) -> dict[str, Any]:
    """取或建 channel 熔断状态（调用方须持锁）。"""
    state = _circuit_states.get(channel)
    if state is None:
        state = {
            "fail_count": 0,
            "open_until": 0.0,  # > now 表示 open
            "opened_at": 0.0,
        }
        _circuit_states[channel] = state
    return state


def is_channel_open(channel: str) -> bool:
    """熔断期（circuit open）返回 True。

    半开：冷却到期后自动放行（返回 False）；下一次失败会再次打开。
    """
    cid = _normalize_channel(channel)
    if not cid:
        return False
    now = time.time()
    with _lock:
        state = _circuit_state(cid)
        open_until = float(state.get("open_until") or 0.0)
        if open_until <= 0:
            return False
        if now < open_until:
            return True
        # 到期：半开放行，清 open_until 但保留 fail_count 供观察；
        # 成功会归零，失败会重新累计并可能再次 open。
        state["open_until"] = 0.0
        return False


def record_channel_success(channel: str) -> None:
    """成功：连续失败计数归零并关闭熔断。"""
    cid = _normalize_channel(channel)
    if not cid:
        return
    with _lock:
        state = _circuit_state(cid)
        state["fail_count"] = 0
        state["open_until"] = 0.0
        state["opened_at"] = 0.0


def record_channel_failure(
    channel: str,
    *,
    trace_id: str = "",
    model: str = "",
    account_id: str = "system",
) -> bool:
    """失败：滑动窗口连续失败 +1；达阈值则 open 熔断。

    返回 True 表示本次调用刚触发熔断（open 边沿）。
    熔断触发时写 ledger：action=circuit, result=open。
    """
    cid = _normalize_channel(channel)
    if not cid:
        return False

    threshold = circuit_failure_threshold()
    cooldown = circuit_cooldown_sec()
    opened_now = False
    fail_count = 0
    open_until = 0.0

    with _lock:
        state = _circuit_state(cid)
        # 已在 open 期内再失败：不重复记 open 事件，只维持 open
        now = time.time()
        current_open_until = float(state.get("open_until") or 0.0)
        if current_open_until > now:
            state["fail_count"] = int(state.get("fail_count") or 0) + 1
            return False

        fail_count = int(state.get("fail_count") or 0) + 1
        state["fail_count"] = fail_count
        if fail_count >= threshold:
            open_until = now + float(cooldown)
            state["open_until"] = open_until
            state["opened_at"] = now
            opened_now = True

    if opened_now:
        logger.warning({
            "event": "channel_circuit_open",
            "channel": cid,
            "fail_count": fail_count,
            "threshold": threshold,
            "cooldown_sec": cooldown,
            "open_until": open_until,
        })
        _append_circuit_open_ledger(
            channel=cid,
            fail_count=fail_count,
            trace_id=trace_id,
            model=model,
            account_id=account_id,
            cooldown_sec=cooldown,
        )
    return opened_now


def _append_circuit_open_ledger(
    *,
    channel: str,
    fail_count: int,
    trace_id: str,
    model: str,
    account_id: str,
    cooldown_sec: int,
) -> None:
    """熔断 open 事件进 channel_usage；异常吞掉。"""
    try:
        from services.channel_usage_service import channel_usage_service

        note = f"fail_count={fail_count}; cooldown_sec={cooldown_sec}"
        channel_usage_service.append(
            trace_id=str(trace_id or "circuit").strip() or "circuit",
            channel=channel,
            account_id=str(account_id or "system").strip() or "system",
            action="circuit",
            model=str(model or "").strip(),
            result="open",
            note=redact_auth_diagnostic(note, 500),
        )
    except Exception as exc:
        logger.warning({
            "event": "channel_circuit_ledger_failed",
            "channel": channel,
            "error": redact_auth_diagnostic(exc, 500),
        })


def channel_circuit_status(channel: str | None = None) -> dict[str, Any]:
    """返回熔断状态快照。

    - channel 指定：单渠道 dict {open, until, fail_count, ...}
    - channel 省略：{channel_id: status_dict, ...}
    """
    now = time.time()
    with _lock:
        if channel is not None:
            cid = _normalize_channel(channel)
            if not cid:
                return {
                    "open": False,
                    "until": 0.0,
                    "fail_count": 0,
                    "threshold": circuit_failure_threshold(),
                    "cooldown_sec": circuit_cooldown_sec(),
                }
            state = _circuit_state(cid)
            open_until = float(state.get("open_until") or 0.0)
            return {
                "channel": cid,
                "open": open_until > now,
                "until": open_until if open_until > now else 0.0,
                "fail_count": int(state.get("fail_count") or 0),
                "threshold": circuit_failure_threshold(),
                "cooldown_sec": circuit_cooldown_sec(),
            }
        # 全量：已有状态 + 至少包含 firefly 便于排查
        channels = set(_circuit_states.keys()) | {FIREFLY_CHANNEL_ID}
        out: dict[str, Any] = {}
        for cid in sorted(channels):
            state = _circuit_state(cid)
            open_until = float(state.get("open_until") or 0.0)
            out[cid] = {
                "open": open_until > now,
                "until": open_until if open_until > now else 0.0,
                "fail_count": int(state.get("fail_count") or 0),
            }
        return out


def acquire_channel_rate(
    channel: str,
    *,
    op: str = "poll",
    timeout_sec: float = 30.0,
) -> bool:
    """渠道级速率预算 acquire（进程内令牌桶）。

    占位兑现：01 的 ChannelEntry.rate_budget 此前为空；本期只对 Firefly
    上游入口（submit/poll 聚合）限速，阈值 channels.firefly.rate_budget.poll_per_sec。
    不碰全局线程池。后续渠道 2 到来再按 channel/op 泛化。

    返回 True 表示拿到配额；超时返回 False（调用方可选择降级/报错）。
    """
    cid = _normalize_channel(channel) or FIREFLY_CHANNEL_ID
    budget = rate_budget_config(cid)
    # 当前只实现 poll 预算；其它 op 走同一 poll_per_sec 桶（最小可用）
    rate = _safe_positive_float(
        budget.get("poll_per_sec"),
        DEFAULT_POLL_PER_SEC,
        minimum=0.1,
    )
    # 令牌桶：容量 = max(1, rate)，每秒补 rate 个
    capacity = max(1.0, rate)
    refill_per_sec = rate
    deadline = time.time() + max(0.0, float(timeout_sec or 0.0))

    while True:
        with _lock:
            state = _rate_states.get(cid)
            now = time.time()
            if state is None:
                state = {
                    "tokens": capacity,
                    "updated_at": now,
                    "rate": refill_per_sec,
                    "capacity": capacity,
                }
                _rate_states[cid] = state
            else:
                # 配置热更新：rate 变化时同步桶参数
                if abs(float(state.get("rate") or 0.0) - refill_per_sec) > 1e-9:
                    state["rate"] = refill_per_sec
                    state["capacity"] = capacity
                elapsed = max(0.0, now - float(state.get("updated_at") or now))
                tokens = min(
                    float(state.get("capacity") or capacity),
                    float(state.get("tokens") or 0.0) + elapsed * float(state.get("rate") or refill_per_sec),
                )
                state["tokens"] = tokens
                state["updated_at"] = now

            if float(state["tokens"]) >= 1.0:
                state["tokens"] = float(state["tokens"]) - 1.0
                return True

            # 还需多久补到 1 个 token
            need = 1.0 - float(state["tokens"])
            rate_now = float(state.get("rate") or refill_per_sec) or refill_per_sec
            wait_sec = max(0.01, need / rate_now)

        if time.time() + wait_sec > deadline:
            logger.warning({
                "event": "channel_rate_budget_timeout",
                "channel": cid,
                "op": op,
                "poll_per_sec": rate,
            })
            return False
        time.sleep(min(wait_sec, 0.05))


def reset_channel_runtime_state(channel: str | None = None) -> None:
    """测试/运维：清空熔断与限速状态。channel=None 清空全部。"""
    with _lock:
        if channel is None:
            _circuit_states.clear()
            _rate_states.clear()
            return
        cid = _normalize_channel(channel)
        _circuit_states.pop(cid, None)
        _rate_states.pop(cid, None)
