"""Firefly 后台 cookie 刷新调度（简版）。

对齐 adobe2api refresh_mgr 思路：周期扫 source_type=firefly 账号，
token 到期则用 cookie 刷 IMS access_token；失败退避 60/180/600/1800s，
连续失败标记「异常」。

集成层通过 accounts_getter / accounts_updater 注入账号读写，本模块不直接
依赖 account_service，便于单测与解耦。
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from typing import Any

from services.backends.firefly_auth import (
    decode_jwt_account_id,
    decode_jwt_exp,
    is_token_expired,
    refresh_access_token,
)
from utils.diagnostics import redact_auth_diagnostic
from utils.log import logger

# 失败退避阶梯（秒）
_FAILURE_BACKOFFS = (60, 180, 600, 1800)
_DAEMON_TICK_SECONDS = 5.0
_DEFAULT_INTERVAL_HOURS = 15
_DEFAULT_SKEW_SECONDS = 300
# 距过期不足该时间也强制刷新，避免 interval 推后留下真空
_FORCE_REFRESH_WITHIN_SECONDS = 3600

_lock = threading.Lock()
_runner_started = False
_stop_event = threading.Event()
_thread: threading.Thread | None = None
# account_key → next_retry_at (epoch seconds)
_next_retry_at: dict[str, float] = {}
_consecutive_failures: dict[str, int] = {}


def _account_key(account: dict[str, Any]) -> str:
    """稳定账号键：优先 id / email / account_id。"""
    for field in ("id", "account_id", "email", "access_token"):
        value = str(account.get(field) or "").strip()
        if value:
            return value[:64]
    return str(id(account))


def _token_exp_ts(account: dict[str, Any]) -> float | None:
    """解析 token 过期时间：优先 token_expires_at，否则 JWT exp。"""
    expires_at = account.get("token_expires_at")
    try:
        exp_ts = float(expires_at) if expires_at not in (None, "") else None
    except (TypeError, ValueError):
        exp_ts = None
    if exp_ts is not None and exp_ts > 0:
        return exp_ts

    token = str(account.get("access_token") or "").strip()
    if not token:
        return None
    jwt_exp = decode_jwt_exp(token)
    if jwt_exp is None:
        return None
    try:
        exp_ts = float(jwt_exp)
    except (TypeError, ValueError):
        return None
    return exp_ts if exp_ts > 0 else None


def _should_refresh(
    account: dict[str, Any],
    *,
    skew_seconds: int = _DEFAULT_SKEW_SECONDS,
) -> bool:
    """是否需要刷新：无 token / JWT 过期 / token_expires_at 到期 / 距过期不足 1h。"""
    status = str(account.get("status") or "").strip().lower()
    # invalid 兼容旧值；异常 为号池中文状态
    if status in {"invalid", "disabled", "deleted", "异常"}:
        return False

    cookie = str(account.get("cookie") or "").strip()
    if not cookie:
        return False

    token = str(account.get("access_token") or "").strip()
    if not token:
        return True

    exp_ts = _token_exp_ts(account)
    if exp_ts is not None:
        now = time.time()
        if exp_ts - skew_seconds <= now:
            return True
        # 距过期不足 1h 也刷新，避免 interval 推后留下真空
        if exp_ts - now <= _FORCE_REFRESH_WITHIN_SECONDS:
            return True
        return False

    return is_token_expired(token, skew_seconds=skew_seconds)


def _schedule_next_check(
    key: str,
    *,
    now: float,
    interval_sec: float,
    exp_ts: float | None,
    skew_seconds: int = _DEFAULT_SKEW_SECONDS,
) -> float:
    """计算下次检查时间：min(now+interval, exp-skew)，避免 24h token 真空。"""
    next_at = now + interval_sec
    if exp_ts is not None and exp_ts > 0:
        refresh_before = exp_ts - float(skew_seconds)
        next_at = min(next_at, refresh_before)
    # 不把 next 推到过去（否则忙等）；至少推到下一 tick
    if next_at <= now:
        next_at = now + _DAEMON_TICK_SECONDS
    with _lock:
        _next_retry_at[key] = next_at
    return next_at


def refresh_one_account(
    account: dict[str, Any],
    *,
    proxy: str | None = None,
) -> dict[str, Any]:
    """刷新单个账号；成功返回待合并字段，失败抛异常。"""
    cookie = str(account.get("cookie") or "").strip()
    if not cookie:
        raise ValueError("account missing cookie")

    account_proxy = str(account.get("proxy") or proxy or "").strip() or None
    result = refresh_access_token(cookie, proxy=account_proxy)
    access_token = str(result.get("access_token") or "").strip()
    if not access_token:
        raise RuntimeError("refresh returned empty access_token")

    expires_in = result.get("expires_in")
    try:
        expires_in_i = int(expires_in) if expires_in is not None else None
    except (TypeError, ValueError):
        expires_in_i = None

    # token_expires_at：优先 JWT exp，否则 now+expires_in
    exp_ts = decode_jwt_exp(access_token)
    if exp_ts is None and expires_in_i and expires_in_i > 0:
        exp_ts = int(time.time()) + expires_in_i

    account_id = decode_jwt_account_id(access_token) or str(
        account.get("account_id") or ""
    ).strip()

    update: dict[str, Any] = {
        "access_token": access_token,
        # 与号池中文状态对齐
        "status": "正常",
    }
    if exp_ts:
        update["token_expires_at"] = int(exp_ts)
    if account_id:
        update["account_id"] = account_id
    if expires_in_i is not None:
        update["expires_in"] = expires_in_i
    return update


def _process_accounts(
    accounts_getter: Callable[[], list[dict[str, Any]]],
    accounts_updater: Callable[[dict[str, Any], dict[str, Any]], None],
    *,
    interval_hours: float,
) -> None:
    try:
        accounts = accounts_getter() or []
    except Exception as exc:
        logger.warning(
            "firefly refresh getter failed: %s",
            redact_auth_diagnostic(str(exc))[:200],
        )
        return

    now = time.time()
    interval_sec = max(3600.0, float(interval_hours) * 3600.0)

    for account in accounts:
        if not isinstance(account, dict):
            continue
        # 仅处理显式 firefly 账号；空 source_type 不再误收
        source = str(account.get("source_type") or "").strip().lower()
        if source != "firefly":
            continue

        key = _account_key(account)
        with _lock:
            next_at = float(_next_retry_at.get(key, 0.0) or 0.0)
        if next_at and now < next_at:
            continue

        if not _should_refresh(account):
            # 未到期：按 min(interval, exp-skew) 再看，避免 6h 真空
            _schedule_next_check(
                key,
                now=now,
                interval_sec=interval_sec,
                exp_ts=_token_exp_ts(account),
            )
            continue

        try:
            update = refresh_one_account(account)
            accounts_updater(account, update)
            with _lock:
                _consecutive_failures[key] = 0
            new_exp: float | None
            try:
                exp_raw = update.get("token_expires_at")
                new_exp = float(exp_raw) if exp_raw not in (None, "") else None
            except (TypeError, ValueError):
                new_exp = None
            _schedule_next_check(
                key,
                now=now,
                interval_sec=interval_sec,
                exp_ts=new_exp,
            )
            logger.info(
                "firefly token refreshed account=%s expires_at=%s",
                key[:16],
                update.get("token_expires_at"),
            )
        except Exception as exc:
            with _lock:
                fails = int(_consecutive_failures.get(key, 0)) + 1
                _consecutive_failures[key] = fails
                delay = _FAILURE_BACKOFFS[min(fails - 1, len(_FAILURE_BACKOFFS) - 1)]
                _next_retry_at[key] = now + delay
            logger.warning(
                "firefly refresh failed account=%s fails=%s delay=%ss err=%s",
                key[:16],
                fails,
                delay,
                redact_auth_diagnostic(str(exc))[:200],
            )
            # 连续失败达上限 → 标「异常」（由 updater 写回）
            if fails >= len(_FAILURE_BACKOFFS):
                try:
                    accounts_updater(
                        account,
                        {
                            "status": "异常",
                            "last_error": redact_auth_diagnostic(str(exc))[:300],
                        },
                    )
                except Exception as upd_exc:
                    logger.warning(
                        "firefly mark invalid failed: %s",
                        redact_auth_diagnostic(str(upd_exc))[:200],
                    )


def start_refresh_daemon(
    accounts_getter: Callable[[], list[dict[str, Any]]],
    accounts_updater: Callable[[dict[str, Any], dict[str, Any]], None],
    *,
    interval_hours: float = _DEFAULT_INTERVAL_HOURS,
) -> None:
    """启动后台线程，周期检查 firefly 账号 token 并刷新。

    accounts_getter() → list[account_dict]
    accounts_updater(account, fields) → 把 fields 合并写回该账号（调用方负责持久化）
    """
    global _runner_started, _thread

    # 先在锁外等待旧线程退出，避免 clear() 把旧线程从 wait 中唤醒后继续跑
    with _lock:
        if _runner_started and _thread is not None and _thread.is_alive():
            return
        old = _thread

    if old is not None and old.is_alive():
        _stop_event.set()
        old.join(timeout=10)

    with _lock:
        # 二次确认：期间可能被并发 start
        if _runner_started and _thread is not None and _thread.is_alive():
            return
        # 旧线程仍未退出则放弃本次 start，避免双线程
        if _thread is not None and _thread.is_alive():
            logger.warning("firefly refresh daemon old thread still alive; skip start")
            return

        _stop_event.clear()
        _runner_started = True

        def _run() -> None:
            logger.info(
                "firefly refresh daemon started interval_hours=%s",
                interval_hours,
            )
            while not _stop_event.is_set():
                try:
                    _process_accounts(
                        accounts_getter,
                        accounts_updater,
                        interval_hours=interval_hours,
                    )
                except Exception as exc:
                    logger.warning(
                        "firefly refresh loop error: %s",
                        redact_auth_diagnostic(str(exc))[:200],
                    )
                _stop_event.wait(_DAEMON_TICK_SECONDS)
            logger.info("firefly refresh daemon stopped")

        _thread = threading.Thread(
            target=_run,
            name="firefly-refresh-daemon",
            daemon=True,
        )
        _thread.start()


def stop_refresh_daemon() -> None:
    """停止后台刷新线程（测试/关闭用）。"""
    global _runner_started, _thread
    _stop_event.set()
    with _lock:
        t = _thread
        _runner_started = False
    if t is not None and t.is_alive():
        t.join(timeout=10)
    with _lock:
        # 仅在仍指向同一线程时清空，避免 race 清掉新线程引用
        if _thread is t and (t is None or not t.is_alive()):
            _thread = None


def reset_refresh_state() -> None:
    """清空退避状态（测试用）。"""
    with _lock:
        _next_retry_at.clear()
        _consecutive_failures.clear()
