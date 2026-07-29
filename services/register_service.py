from __future__ import annotations

import json
import re
import threading
import time
import uuid
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from datetime import datetime, time as dt_time, timedelta, timezone
from pathlib import Path

from services.account_service import account_service
from services.config import DATA_DIR
from services.json_file import read_json_object, write_json_file
from services.register import mail_provider, openai_register
from utils.timezone import BEIJING_TZ, beijing_now


REGISTER_FILE = DATA_DIR / "register.json"


def _serialize_outlook_pool(credentials: list[dict]) -> str:
    return "\n".join(
        f'{c["email"]}----{c.get("password", "")}----{c["client_id"]}----{c["refresh_token"]}' for c in credentials
    )


def _merge_outlook_pool(old_text: str, new_text: str) -> str:
    """合并已存邮箱池与新导入文本，按邮箱去重，新导入的同名邮箱覆盖旧凭据。"""
    merged: dict[str, dict] = {}
    for credential in mail_provider.parse_outlook_credentials(old_text or ""):
        merged[credential["email"].strip().lower()] = credential
    for credential in mail_provider.parse_outlook_credentials(new_text or ""):
        merged[credential["email"].strip().lower()] = credential
    return _serialize_outlook_pool(list(merged.values()))


def _outlook_credential_changed(old: dict | None, new: dict) -> bool:
    if not old:
        return False
    for key in ("password", "client_id", "refresh_token"):
        if str(old.get(key) or "") != str(new.get(key) or ""):
            return True
    return False


def _safe_bool(value: object, fallback: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    if text in {"1", "true", "yes", "on"}:
        return True
    if text in {"0", "false", "no", "off"}:
        return False
    return fallback


def _clamp_int(value: object, *, fallback: int, lower: int, upper: int) -> int:
    try:
        parsed = int(str(value)) if value not in (None, "") else fallback
    except (TypeError, ValueError):
        parsed = fallback
    return min(max(parsed, lower), upper)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _provider_id(provider: dict) -> str:
    return str(provider.get("id") or provider.get("provider_id") or "").strip()


def _ensure_provider_id(provider: dict) -> str:
    provider_id = _provider_id(provider)
    if provider_id:
        provider["id"] = provider_id
        provider.pop("provider_id", None)
        return provider_id
    provider_id = f"provider-{uuid.uuid4().hex[:12]}"
    provider["id"] = provider_id
    return provider_id


# ---------------------------------------------------------------------------
# 定时抢注：时段解析与判定（跨天 = start > end，start == end 非法）
# ---------------------------------------------------------------------------

_HHMM_RE = re.compile(r"^([01]?\d|2[0-3]):([0-5]\d)$")

SCHEDULE_DEFAULTS = {
    "enabled": False,
    "windows": [],
    "threads": 10,
    "max_relogin_retries": 3,
    "preempt_minutes": 5,
    "drain_timeout_minutes": 15,
}


def _parse_hhmm(value: object) -> dt_time | None:
    match = _HHMM_RE.match(str(value or "").strip())
    if not match:
        return None
    return dt_time(hour=int(match.group(1)), minute=int(match.group(2)))


def _normalize_window(raw: dict) -> dict | None:
    """规范化单个时段；start==end 视为非法返回 None。start>end 表示跨天。"""
    if not isinstance(raw, dict):
        return None
    start = _parse_hhmm(raw.get("start"))
    end = _parse_hhmm(raw.get("end"))
    if start is None or end is None or start == end:
        return None
    return {"start": f"{start.hour:02d}:{start.minute:02d}", "end": f"{end.hour:02d}:{end.minute:02d}"}


def _normalize_schedule(raw: object) -> dict:
    source = raw if isinstance(raw, dict) else {}
    windows: list[dict] = []
    if isinstance(source.get("windows"), list):
        for item in source["windows"]:
            window = _normalize_window(item)
            if window:
                windows.append(window)
    return {
        "enabled": _safe_bool(source.get("enabled"), False),
        "windows": windows,
        "threads": _clamp_int(source.get("threads"), fallback=SCHEDULE_DEFAULTS["threads"], lower=1, upper=200),
        "max_relogin_retries": _clamp_int(source.get("max_relogin_retries"), fallback=SCHEDULE_DEFAULTS["max_relogin_retries"], lower=0, upper=10),
        "preempt_minutes": _clamp_int(source.get("preempt_minutes"), fallback=SCHEDULE_DEFAULTS["preempt_minutes"], lower=0, upper=60),
        "drain_timeout_minutes": _clamp_int(source.get("drain_timeout_minutes"), fallback=SCHEDULE_DEFAULTS["drain_timeout_minutes"], lower=0, upper=360),
    }


def _window_bounds(day, start: dt_time, end: dt_time, tz=BEIJING_TZ) -> tuple[datetime, datetime]:
    """返回某天在某 tz 下的时段起止（跨天 end 落在次日）。"""
    start_dt = datetime.combine(day, start, tzinfo=tz)
    end_dt = datetime.combine(day, end, tzinfo=tz)
    if end_dt <= start_dt:
        end_dt += timedelta(days=1)
    return start_dt, end_dt


def _active_schedule_window(now: datetime, windows: list[dict]) -> dict | None:
    """now 是否落在任一时段内（含跨天：同时检查「今天开始」与「昨天开始跨到今天」）。

    返回 {"start", "end", "start_dt", "end_dt"}，未命中返回 None。
    """
    now = now.astimezone(BEIJING_TZ)
    today = now.date()
    for window in windows:
        start = _parse_hhmm(window.get("start"))
        end = _parse_hhmm(window.get("end"))
        if start is None or end is None or start == end:
            continue
        # 今天开始的时段（start<end 当天；start>end 跨到明天）
        s_today, e_today = _window_bounds(today, start, end)
        if s_today <= now < e_today:
            return {"start": window["start"], "end": window["end"], "start_dt": s_today, "end_dt": e_today}
        # 昨天开始跨到今天的时段（仅当 start>end）
        s_yesterday = s_today - timedelta(days=1)
        e_yesterday = e_today - timedelta(days=1)
        if start > end and s_yesterday <= now < e_yesterday:
            return {"start": window["start"], "end": window["end"], "start_dt": s_yesterday, "end_dt": e_yesterday}
    return None


def _next_schedule_window(now: datetime, windows: list[dict]) -> dict | None:
    """最近的下一时段（未来 8 天内），含正在进行的时段。"""
    now = now.astimezone(BEIJING_TZ)
    best: dict | None = None
    for offset in range(-1, 9):
        day = now.date() + timedelta(days=offset)
        for window in windows:
            start = _parse_hhmm(window.get("start"))
            end = _parse_hhmm(window.get("end"))
            if start is None or end is None or start == end:
                continue
            start_dt, end_dt = _window_bounds(day, start, end)
            if end_dt <= now:
                continue
            if start_dt <= now:
                return {"start": window["start"], "end": window["end"], "start_dt": start_dt, "end_dt": end_dt}
            if best is None or start_dt < best["start_dt"]:
                best = {"start": window["start"], "end": window["end"], "start_dt": start_dt, "end_dt": end_dt}
    return best


def _format_schedule_hint(info: dict | None) -> dict | None:
    if not info:
        return None
    return {
        "start": info["start"],
        "end": info["end"],
        "start_dt": info["start_dt"].isoformat(),
        "end_dt": info["end_dt"].isoformat(),
    }


def _default_config() -> dict:
    return {**openai_register.config, "mode": "total", "target_quota": 100, "target_available": 10, "check_interval": 5, "enabled": False, "stats": {"success": 0, "fail": 0, "done": 0, "running": 0, "threads": openai_register.config["threads"], "elapsed_seconds": 0, "avg_seconds": 0, "success_rate": 0, "current_quota": 0, "current_available": 0}}


def _normalize(raw: dict) -> dict:
    cfg = _default_config()
    cfg.update({k: v for k, v in raw.items() if k not in {"stats", "logs"}})
    cfg["total"] = max(1, int(cfg.get("total") or 1))
    cfg["threads"] = max(1, int(cfg.get("threads") or 1))
    cfg["mode"] = str(cfg.get("mode") or "total").strip() if str(cfg.get("mode") or "total").strip() in {"total", "quota", "available"} else "total"
    cfg["target_quota"] = max(1, int(cfg.get("target_quota") or 1))
    cfg["target_available"] = max(1, int(cfg.get("target_available") or 1))
    cfg["check_interval"] = max(1, int(cfg.get("check_interval") or 5))
    cfg["max_relogin_retries"] = _clamp_int(cfg.get("max_relogin_retries"), fallback=3, lower=0, upper=10)
    cfg["proxy"] = str(cfg.get("proxy") or "").strip()
    raw_proxy_pool = cfg.get("proxy_pool")
    if isinstance(raw_proxy_pool, list):
        cfg["proxy_pool"] = [str(item).strip() for item in raw_proxy_pool if str(item or "").strip()]
    else:
        cfg["proxy_pool"] = []
    if cfg["proxy"] and not cfg["proxy_pool"]:
        cfg["proxy_pool"] = [cfg["proxy"]]
    default_config = _default_config()
    default_mail = default_config["mail"] if isinstance(default_config.get("mail"), dict) else {}
    merged_mail = dict(default_mail)
    mail = cfg.get("mail")
    if isinstance(mail, dict):
        merged_mail.update(mail)
    cfg["mail"] = merged_mail
    cfg["mail"]["api_use_register_proxy"] = _safe_bool(cfg["mail"].get("api_use_register_proxy"), True)
    cfg["mail"].pop("proxy", None)
    cfg["enabled"] = bool(cfg.get("enabled"))
    cfg["schedule"] = _normalize_schedule(raw.get("schedule"))
    default_stats = default_config["stats"] if isinstance(default_config.get("stats"), dict) else {}
    stats = dict(default_stats)
    raw_stats = raw.get("stats")
    if isinstance(raw_stats, dict):
        stats.update(raw_stats)
    stats["threads"] = cfg["threads"]
    cfg["stats"] = stats
    return cfg


class RegisterService:
    def __init__(self, store_file: Path):
        self._store_file = store_file
        self._lock = threading.RLock()
        self._runner: threading.Thread | None = None
        self._scheduler: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._wake_event = threading.Event()
        self._user_stop = threading.Event()
        self._schedule_active = threading.Event()
        self._drain_event = threading.Event()
        self._resubmit_event = threading.Event()
        self._phase = "idle"  # idle|daily_running|preempt_drain|schedule_running|post_drain
        self._current_kind: str | None = None  # "daily" | "schedule"
        self._restore_daily_after = False
        self._logs: list[dict] = []
        openai_register.register_log_sink = self._append_log
        self._config = self._load()
        self._ensure_scheduler()
        if self._config["enabled"]:
            self.start()

    def _load(self) -> dict:
        return _normalize(read_json_object(self._store_file, name="register.json"))

    def _save(self) -> None:
        write_json_file(self._store_file, self._config)

    def get(self) -> dict:
        with self._lock:
            schedule = dict(self._config.get("schedule") or {})
            windows = schedule.get("windows") if isinstance(schedule.get("windows"), list) else []
            if windows:
                schedule["next_window"] = _format_schedule_hint(_next_schedule_window(beijing_now(), windows))
            else:
                schedule["next_window"] = None
            snapshot = json.loads(json.dumps({
                **self._config,
                "schedule": schedule,
                "phase": self._phase,
                "run_kind": self._current_kind,
                "logs": self._logs[-300:],
            }, ensure_ascii=False))
        self._redact_outlook_pools(snapshot)
        return snapshot

    @staticmethod
    def _mask_email(email: str) -> str:
        local, sep, domain = str(email or "").partition("@")
        if not sep:
            return "***"
        masked = (local[:2] + "***" + local[-1:]) if len(local) > 2 else (local[:1] + "***")
        return f"{masked}@{domain}"

    def _redact_outlook_pools(self, snapshot: dict) -> None:
        """把 outlook_token 邮箱池里的密码/refresh_token 从对外输出中抹掉，仅保留脱敏预览与统计。

        mailboxes 改为只写导入框（输出为空），避免把密码与 refresh_token 通过 GET/SSE 反复广播。
        """
        mail = snapshot.get("mail")
        if not isinstance(mail, dict):
            return
        providers = mail.get("providers")
        if not isinstance(providers, list):
            return
        for index, provider in enumerate(providers):
            if not isinstance(provider, dict) or provider.get("type") != "outlook_token":
                continue
            pool_text = str(provider.get("mailboxes") or "")
            base_credentials = mail_provider.parse_outlook_credentials(pool_text)
            credentials = mail_provider.expand_outlook_aliases(base_credentials, provider)
            provider["mailboxes"] = ""
            provider["mailboxes_count"] = len(credentials)
            provider["mailboxes_base_count"] = len(base_credentials)
            provider["mailboxes_alias_count"] = max(0, len(credentials) - len(base_credentials))
            provider["mailboxes_preview"] = [self._mask_email(c["email"]) for c in credentials]
            provider["mailboxes_stats"] = mail_provider.outlook_token_pool_stats(credentials)
            provider["mailboxes_parse_stats"] = mail_provider.inspect_outlook_credentials(pool_text)

    def _drop_mail_proxy(self) -> None:
        if isinstance(self._config.get("mail"), dict):
            self._config["mail"].pop("proxy", None)

    def _merge_outlook_pools(self, updates: dict) -> None:
        """对 outlook_token provider：把前端新导入的 mailboxes 与已存池按邮箱合并去重。

        前端 mailboxes 是只写导入框，留空表示不改动；填入的新行追加/覆盖已存凭据。
        按数组下标与已存的同类型 provider 对齐。
        """
        mail = updates.get("mail")
        if not isinstance(mail, dict) or not isinstance(mail.get("providers"), list):
            return
        current_mail = self._config.get("mail")
        old_mail = current_mail if isinstance(current_mail, dict) else {}
        current_providers = old_mail.get("providers")
        old_providers = current_providers if isinstance(current_providers, list) else []
        old_outlook_by_id = {
            _provider_id(provider): provider
            for provider in old_providers
            if isinstance(provider, dict) and provider.get("type") == "outlook_token" and _provider_id(provider)
        }
        old_outlook_by_order = [
            provider
            for provider in old_providers
            if isinstance(provider, dict) and provider.get("type") == "outlook_token"
        ]
        outlook_index = 0
        providers = mail["providers"]
        for index, provider in enumerate(providers):
            if not isinstance(provider, dict):
                continue
            _ensure_provider_id(provider)
            if provider.get("type") != "outlook_token":
                continue
            provider_id = _provider_id(provider)
            old = old_outlook_by_id.get(provider_id) or {}
            if not old and index < len(old_providers) and isinstance(old_providers[index], dict) and old_providers[index].get("type") == "outlook_token":
                old = old_providers[index]
            if not old and outlook_index < len(old_outlook_by_order):
                old = old_outlook_by_order[outlook_index]
            outlook_index += 1
            old_text = str(old.get("mailboxes") or "") if old.get("type") == "outlook_token" else ""
            new_text = str(provider.get("mailboxes") or "")
            old_credentials = {
                credential["email"].strip().lower(): credential
                for credential in mail_provider.parse_outlook_credentials(old_text or "")
            }
            new_credentials = mail_provider.parse_outlook_credentials(new_text or "")
            if new_text.strip():
                provider["mailboxes"] = _merge_outlook_pool(old_text, new_text)
                refreshed_credentials = [
                    credential
                    for credential in new_credentials
                    if _outlook_credential_changed(old_credentials.get(credential["email"].strip().lower()), credential)
                ]
                if refreshed_credentials:
                    refreshed_addresses = [
                        item["email"]
                        for credential in refreshed_credentials
                        for item in mail_provider.expand_outlook_aliases([credential], provider)
                    ]
                    mail_provider.clear_outlook_token_states(
                        refreshed_addresses,
                        states=mail_provider.OUTLOOK_REFRESHED_CREDENTIAL_RESET_STATES,
                    )
            elif old_text:
                provider["mailboxes"] = _merge_outlook_pool(old_text, "")
            else:
                provider["mailboxes"] = ""
            for key in ("mailboxes_count", "mailboxes_base_count", "mailboxes_alias_count", "mailboxes_preview", "mailboxes_stats", "mailboxes_parse_stats"):
                provider.pop(key, None)

    def _prune_unused_outlook_pools(self) -> int:
        mail = self._config.get("mail")
        if not isinstance(mail, dict):
            return 0
        providers = mail.get("providers")
        if not isinstance(providers, list):
            return 0
        total_removed = 0
        for provider in providers:
            if not isinstance(provider, dict) or provider.get("type") != "outlook_token":
                continue
            credentials = mail_provider.parse_outlook_credentials(str(provider.get("mailboxes") or ""))
            kept, removed = mail_provider.prune_outlook_unused_credentials(credentials, provider)
            if removed:
                provider["mailboxes"] = _serialize_outlook_pool(kept)
                total_removed += removed
            for key in ("mailboxes_count", "mailboxes_base_count", "mailboxes_alias_count", "mailboxes_preview", "mailboxes_stats", "mailboxes_parse_stats"):
                provider.pop(key, None)
        return total_removed

    def update(self, updates: dict) -> dict:
        with self._lock:
            self._merge_outlook_pools(updates)
            self._config = _normalize({**self._config, **updates})
            self._drop_mail_proxy()
            openai_register.config.update({k: self._config[k] for k in ("mail", "proxy", "proxy_pool", "total", "threads", "max_relogin_retries")})
            self._save()
            self._ensure_scheduler()
            self._wake_event.set()
            return self.get()

    # ---- 运行参数同步 ----

    def _sync_run_params(self, kind: str) -> None:
        """把当前相位的线程数/重登/选源 purpose 同步进 openai_register.config。"""
        if kind == "schedule":
            schedule = self._config.get("schedule") or {}
            threads = _clamp_int(schedule.get("threads"), fallback=10, lower=1, upper=200)
            retries = _clamp_int(schedule.get("max_relogin_retries"), fallback=3, lower=0, upper=10)
        else:
            threads = _clamp_int(self._config.get("threads"), fallback=3, lower=1, upper=200)
            retries = _clamp_int(self._config.get("max_relogin_retries"), fallback=3, lower=0, upper=10)
        openai_register.config.update({
            "mail": self._config.get("mail"),
            "proxy": self._config.get("proxy"),
            "proxy_pool": self._config.get("proxy_pool"),
            "total": self._config.get("total"),
            "threads": threads,
            "max_relogin_retries": retries,
            "mail_purpose": "schedule" if kind == "schedule" else "daily",
        })

    def _reset_run_state(self, threads: int) -> None:
        self._logs = []
        metrics = self._pool_metrics()
        self._config["stats"] = {
            "job_id": uuid.uuid4().hex, "success": 0, "fail": 0, "done": 0, "running": 0,
            "threads": threads, **metrics, "started_at": _now(), "updated_at": _now(),
        }
        with openai_register.stats_lock:
            openai_register.stats.update({"done": 0, "success": 0, "fail": 0, "start_time": time.time()})

    def _set_phase(self, phase: str, kind: str | None = None) -> None:
        with self._lock:
            self._phase = phase
            if kind is not None:
                self._current_kind = kind
            elif phase == "idle":
                self._current_kind = None
            self._config["stats"]["updated_at"] = _now()
            self._save()

    # ---- 启动 / 停止 ----

    def start(self) -> dict:
        with self._lock:
            self._user_stop.clear()
            self._config["enabled"] = True
            self._drop_mail_proxy()
            if self._runner and self._runner.is_alive():
                self._save()
                self._wake_event.set()
                return self.get()
            self._save()
            self._runner = threading.Thread(target=self._orchestrate, daemon=True, name="openai-register")
            self._runner.start()
            self._append_log("注册任务已启动", "yellow")
            return self.get()

    def stop(self) -> dict:
        """上帝键：停止一切相位，不做自动恢复；调度配置保留待后续自动触发。"""
        with self._lock:
            self._user_stop.set()
            self._config["enabled"] = False
            self._restore_daily_after = False
            self._config["stats"]["updated_at"] = _now()
            self._save()
            self._append_log("已请求停止注册任务，正在等待当前运行任务结束", "yellow")
            return self.get()

    def reset(self) -> dict:
        with self._lock:
            self._logs = []
            self._config["stats"] = {"success": 0, "fail": 0, "done": 0, "running": 0, "threads": self._config["threads"], "elapsed_seconds": 0, "avg_seconds": 0, "success_rate": 0, **self._pool_metrics(), "updated_at": _now()}
            with openai_register.stats_lock:
                openai_register.stats.update({"done": 0, "success": 0, "fail": 0, "start_time": 0.0})
            self._save()
            return self.get()

    def reset_outlook_pool(self, scope: str = "all") -> dict:
        scope = str(scope or "all").strip().lower()
        if scope == "unused":
            with self._lock:
                removed = self._prune_unused_outlook_pools()
                openai_register.config.update({k: self._config[k] for k in ("mail", "proxy", "proxy_pool", "total", "threads", "max_relogin_retries")})
                self._save()
                self._append_log(f"已清空 Outlook 邮箱池未使用邮箱，移除 {removed} 个", "yellow")
            return self.get()
        scope_aliases = {"failed": "retryable", "retryable": "retryable", "invalid": "invalid", "all": "all"}
        scope = scope_aliases.get(scope, "all")
        cleared = mail_provider.reset_outlook_token_pool_state(scope)
        scope_label = {"retryable": "占用/临时失败", "invalid": "异常", "all": "全部"}[scope]
        with self._lock:
            self._append_log(
                f"已重置 Outlook 邮箱池状态（范围={scope_label}），清除 {cleared} 条记录",
                "yellow",
            )
        return self.get()

    def _mail_config_with_proxy(self) -> dict:
        mail = json.loads(json.dumps(self._config.get("mail") if isinstance(self._config.get("mail"), dict) else {}, ensure_ascii=False))
        use_register_proxy = _safe_bool(mail.get("api_use_register_proxy"), True)
        mail["api_use_register_proxy"] = use_register_proxy
        mail["proxy"] = str(self._config.get("proxy") or "").strip() if use_register_proxy else ""
        return mail

    def gptmail_status(self, provider: dict | None = None, force: bool = False) -> dict:
        with self._lock:
            mail = self._mail_config_with_proxy()
        return mail_provider.gptmail_status(mail, provider, force=force)

    def refresh_gptmail_public_key(self, provider: dict | None = None, force: bool = True) -> dict:
        with self._lock:
            mail = self._mail_config_with_proxy()
        return mail_provider.refresh_gptmail_public_key(mail, provider, force=force)

    def _append_log(self, text: str, color: str = "") -> None:
        with self._lock:
            self._logs.append({"time": _now(), "text": str(text), "level": str(color or "info")})
            self._logs = self._logs[-300:]

    def _pool_metrics(
        self,
        *,
        refresh_stale: bool = False,
        target_quota: int | None = None,
        target_available: int | None = None,
    ) -> dict:
        return account_service.evaluate_account_pool(
            refresh_stale=refresh_stale,
            target_quota=target_quota,
            target_available=target_available,
        )

    def _target_reached(self, cfg: dict, submitted: int) -> bool:
        mode = str(cfg.get("mode") or "total")
        if mode == "quota":
            target_quota = max(1, int(cfg.get("target_quota") or 1))
            metrics = self._pool_metrics(refresh_stale=True, target_quota=target_quota)
            self._bump(**metrics)
            reached = metrics["current_quota"] >= target_quota
            self._append_log(f"检查号池：当前正常账号={metrics['current_available']}，当前剩余额度={metrics['current_quota']}，目标额度={cfg.get('target_quota')}，{'跳过注册' if reached else '继续注册'}", "yellow")
            return reached
        if mode == "available":
            target_available = max(1, int(cfg.get("target_available") or 1))
            metrics = self._pool_metrics(refresh_stale=True, target_available=target_available)
            self._bump(**metrics)
            reached = metrics["current_available"] >= target_available
            self._append_log(f"检查号池：当前正常账号={metrics['current_available']}，目标账号={cfg.get('target_available')}，当前剩余额度={metrics['current_quota']}，{'跳过注册' if reached else '继续注册'}", "yellow")
            return reached
        return submitted >= int(cfg.get("total") or 1)

    def _bump(self, **updates) -> None:
        with self._lock:
            self._config["stats"].update(updates)
            stats = self._config["stats"]
            started_at = str(stats.get("started_at") or "")
            if started_at:
                try:
                    elapsed = max(0.0, (datetime.now(timezone.utc) - datetime.fromisoformat(started_at)).total_seconds())
                except Exception:
                    elapsed = 0.0
                success = int(stats.get("success") or 0)
                fail = int(stats.get("fail") or 0)
                stats["elapsed_seconds"] = round(elapsed, 1)
                stats["avg_seconds"] = round(elapsed / success, 1) if success else 0
                stats["success_rate"] = round(success * 100 / max(1, success + fail), 1)
            self._config["stats"]["updated_at"] = _now()
            self._save()

    # ---- 单相位运行器：dispatch / drain 受 _schedule_active / _drain_event 控制 ----

    def _run_batch(self, kind: str) -> dict:
        """跑一个相位（daily 或 schedule），返回 {success, fail, done}。

        - 派发受 `_schedule_active`（schedule 相位）/ enabled（daily 相位）控制；
        - `_drain_event` 置位后立即停止派发，仅等待在途任务归零；
        - 每次进入都重建 ThreadPoolExecutor，线程数取该相位配置。
        """
        self._sync_run_params(kind)
        threads = int(openai_register.config.get("threads") or 1)
        self._reset_run_state(threads)
        submitted, done, success, fail = 0, 0, 0, 0
        with ThreadPoolExecutor(max_workers=threads) as executor:
            futures = set()
            while True:
                cfg = self.get()
                # 该相位是否还允许派发
                if kind == "schedule":
                    allow_dispatch = (
                        self._schedule_active.is_set()
                        and not self._user_stop.is_set()
                        and not self._drain_event.is_set()
                    )
                else:
                    allow_dispatch = (
                        cfg["enabled"]
                        and not self._user_stop.is_set()
                        and not self._drain_event.is_set()
                        and not self._schedule_active.is_set()  # 被定时抢占时停发
                    )
                while allow_dispatch and not self._target_reached(cfg, submitted) and len(futures) < threads:
                    submitted += 1
                    futures.add(executor.submit(openai_register.worker, submitted))
                self._bump(running=len(futures), done=done, success=success, fail=fail, phase=self._phase, run_kind=kind)
                if not futures:
                    # 无在途任务：drain 完成 / 被停 / 目标达成 都退出
                    if self._drain_event.is_set() or self._user_stop.is_set():
                        break
                    if kind == "schedule" and not self._schedule_active.is_set():
                        break
                    if kind == "daily" and (not cfg["enabled"] or str(cfg.get("mode") or "total") == "total"):
                        break
                    if kind == "daily" and self._schedule_active.is_set():
                        break
                    time.sleep(max(1, int(cfg.get("check_interval") or 5)))
                    continue
                finished, futures = wait(futures, timeout=1.0, return_when=FIRST_COMPLETED)
                for future in finished:
                    done += 1
                    try:
                        result = future.result()
                        success += 1 if result.get("ok") else 0
                        fail += 0 if result.get("ok") else 1
                    except Exception:
                        fail += 1
        self._bump(running=0, done=done, success=success, fail=fail, finished_at=_now(), phase=self._phase, run_kind=kind)
        return {"success": success, "fail": fail, "done": done}

    # ---- 相位编排器 ----

    def _orchestrate(self) -> None:
        """主运行循环：决定跑 daily 还是 schedule，处理抢占与恢复。"""
        while not self._user_stop.is_set():
            schedule_cfg = self._config.get("schedule") or {}
            windows = schedule_cfg.get("windows") if isinstance(schedule_cfg.get("windows"), list) else []
            now = beijing_now()
            active = _active_schedule_window(now, windows) if (schedule_cfg.get("enabled") and windows) else None

            if active:
                # 定时抢注时段内（含重启落在窗口内 → 继续抢注直到结束）
                self._schedule_active.set()
                self._drain_event.clear()
                self._set_phase("schedule_running", "schedule")
                self._append_log(
                    f"进入定时抢注时段 {active['start']}-{active['end']}（Asia/Shanghai），线程={schedule_cfg.get('threads')}",
                    "yellow",
                )
                result = self._run_batch("schedule")
                self._schedule_active.clear()
                self._append_log(f"定时抢注结束，成功{result['success']}，失败{result['fail']}", "yellow")

                if self._user_stop.is_set():
                    break
                # 时段结束后 drain 在途任务（等零或超时强制归零）
                self._post_drain(schedule_cfg)
                if self._user_stop.is_set():
                    break
                # 恢复日常：仅当之前是日常在跑且用户未按上帝键
                if self._restore_daily_after and self._config.get("enabled"):
                    self._append_log("恢复日常注册", "yellow")
                    continue
                break

            # 非时段：日常模式
            self._schedule_active.clear()
            self._drain_event.clear()
            if not self._config.get("enabled"):
                break
            self._set_phase("daily_running", "daily")
            self._append_log(f"日常注册运行中，模式={self._config['mode']}，线程数={self._config['threads']}", "yellow")
            was_daily = True
            result = self._run_batch("daily")
            # daily 退出原因判断
            if self._user_stop.is_set():
                break
            if self._schedule_active.is_set():
                # 被定时抢占：drain 在途 → 标记恢复 → 回到循环进入 schedule
                self._restore_daily_after = was_daily and self._config.get("enabled")
                self._preempt_drain(schedule_cfg)
                continue
            # 正常跑完（total 达成 / 用户停用 enabled）→ 结束
            self._append_log(f"日常注册结束，成功{result['success']}，失败{result['fail']}", "yellow")
            break

        with self._lock:
            self._schedule_active.clear()
            self._drain_event.clear()
            if not self._restore_daily_after or self._user_stop.is_set():
                self._config["enabled"] = False
            self._set_phase("idle", None)
            self._save()

    def _preempt_drain(self, schedule_cfg: dict) -> None:
        """定时开始前抢占 drain：停止派发，等待在途归零。"""
        self._set_phase("preempt_drain")
        self._drain_event.set()
        timeout = _clamp_int(schedule_cfg.get("drain_timeout_minutes"), fallback=15, lower=0, upper=360) * 60
        deadline = time.monotonic() + timeout
        self._append_log(f"定时抢注即将开始，停止派发日常任务，等待在途归零（最长{timeout // 60}分钟）", "yellow")
        while not self._user_stop.is_set():
            running = int(self._config["stats"].get("running") or 0)
            if running <= 0 or time.monotonic() >= deadline:
                break
            time.sleep(0.5)
        self._drain_event.clear()

    def _post_drain(self, schedule_cfg: dict) -> None:
        """定时结束后 drain：等待在途归零或超时强制归零。"""
        self._set_phase("post_drain", "schedule")
        self._drain_event.set()
        timeout = _clamp_int(schedule_cfg.get("drain_timeout_minutes"), fallback=15, lower=0, upper=360) * 60
        deadline = time.monotonic() + timeout
        self._append_log(f"定时抢注时段结束，等待在途任务归零（最长{timeout // 60}分钟）", "yellow")
        while not self._user_stop.is_set():
            running = int(self._config["stats"].get("running") or 0)
            if running <= 0 or time.monotonic() >= deadline:
                break
            time.sleep(0.5)
        self._drain_event.clear()

    # ---- 常驻调度器：定时到点抢占 / 提前收束 ----

    def _ensure_scheduler(self) -> None:
        schedule_cfg = self._config.get("schedule") or {}
        if schedule_cfg.get("enabled") and schedule_cfg.get("windows"):
            if not (self._scheduler and self._scheduler.is_alive()):
                self._stop_event.clear()
                self._scheduler = threading.Thread(target=self._scheduler_loop, daemon=True, name="register-scheduler")
                self._scheduler.start()

    def _scheduler_loop(self) -> None:
        while not self._stop_event.is_set():
            schedule_cfg = self._config.get("schedule") or {}
            windows = schedule_cfg.get("windows") if isinstance(schedule_cfg.get("windows"), list) else []
            if not (schedule_cfg.get("enabled") and windows):
                time.sleep(1.0)
                continue
            now = beijing_now()
            active = _active_schedule_window(now, windows)
            if active:
                # 窗口内：若当前没在跑 schedule，唤醒 orchestrator 接管
                if self._phase != "schedule_running" and not self._user_stop.is_set():
                    self._schedule_active.set()
                    self._wake_event.set()
                    if not (self._runner and self._runner.is_alive()) and self._config.get("enabled"):
                        self._runner = threading.Thread(target=self._orchestrate, daemon=True, name="openai-register")
                        self._runner.start()
                time.sleep(1.0)
                continue
            # 窗口外：检查是否临近下一时段（提前 preempt_minutes 收束日常）
            nxt = _next_schedule_window(now, windows)
            if nxt and self._phase == "daily_running":
                preempt = _clamp_int(schedule_cfg.get("preempt_minutes"), fallback=5, lower=0, upper=60)
                seconds_to_start = (nxt["start_dt"] - now).total_seconds()
                if 0 < seconds_to_start <= preempt * 60:
                    self._append_log(f"距离定时抢注 {nxt['start']} 还有 {int(seconds_to_start)} 秒，提前收束日常派发", "yellow")
                    self._schedule_active.set()  # 触发 daily 停发 + preempt_drain
            self._wake_event.wait(timeout=1.0)
            self._wake_event.clear()


register_service = RegisterService(REGISTER_FILE)
