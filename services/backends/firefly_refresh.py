"""Firefly 后台 cookie 刷新调度（简版）。

对齐 adobe2api refresh_mgr 思路：周期扫 source_type=firefly 账号，
token 到期则用 cookie 刷 IMS access_token；失败退避 60/180/600/1800s，
连续失败标记 invalid。

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

_lock = threading.Lock()
_runner_started = False
_stop_event = threading.Event()
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


def _should_refresh(account: dict[str, Any], *, skew_seconds: int = 300) -> bool:
    """是否需要刷新：无 token / JWT 过期 / token_expires_at 到期。"""
    status = str(account.get("status") or "").strip().lower()
    if status in {"invalid", "disabled", "deleted"}:
        return False

    cookie = str(account.get("cookie") or "").strip()
    if not cookie:
        return False

    token = str(account.get("access_token") or "").strip()
    if not token:
        return True

    # 显式 expires_at 优先
    expires_at = account.get("token_expires_at")
    try:
        exp_ts = float(expires_at) if expires_at not in (None, "") else None
    except (TypeError, ValueError):
        exp_ts = None
    if exp_ts is not None and exp_ts > 0:
        if exp_ts - skew_seconds <= time.time():
            return True
        return False

    return is_token_expired(token, skew_seconds=skew_seconds)


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
        "status": "active",
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
        source = str(account.get("source_type") or "").strip().lower()
        if source and source != "firefly":
            continue

        key = _account_key(account)
        next_at = _next_retry_at.get(key, 0.0)
        if next_at and now < next_at:
            continue

        if not _should_refresh(account):
            # 未到期：按成功间隔再看
            _next_retry_at[key] = now + interval_sec
            continue

        try:
            update = refresh_one_account(account)
            accounts_updater(account, update)
            _consecutive_failures[key] = 0
            _next_retry_at[key] = now + interval_sec
            logger.info(
                "firefly token refreshed account=%s expires_at=%s",
                key[:16],
                update.get("token_expires_at"),
            )
        except Exception as exc:
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
            # 连续失败达上限 → 标 invalid（由 updater 写回）
            if fails >= len(_FAILURE_BACKOFFS):
                try:
                    accounts_updater(
                        account,
                        {
                            "status": "invalid",
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
    global _runner_started
    with _lock:
        if _runner_started:
            return
        _runner_started = True
        _stop_event.clear()

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

    thread = threading.Thread(
        target=_run,
        name="firefly-refresh-daemon",
        daemon=True,
    )
    thread.start()


def stop_refresh_daemon() -> None:
    """停止后台刷新线程（测试/关闭用）。"""
    global _runner_started
    _stop_event.set()
    with _lock:
        _runner_started = False


def reset_refresh_state() -> None:
    """清空退避状态（测试用）。"""
    _next_retry_at.clear()
    _consecutive_failures.clear()
