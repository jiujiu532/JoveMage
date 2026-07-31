from __future__ import annotations

import time
from collections import deque
from concurrent.futures import Future, ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
from pathlib import Path
from threading import Condition, Lock
from typing import Any, TYPE_CHECKING

from services.config import config
from services.image_failure import image_failure
from services.log_service import (
    LOG_TYPE_ACCOUNT,
    log_service,
)
from services.storage.base import StorageBackend
from utils.diagnostics import redact_auth_diagnostic
from utils.helper import anonymize_token

if TYPE_CHECKING:
    from services.image_failure import ImageFailure


class ImageAccountSelectionError(RuntimeError):
    """图片账号调度失败。

    这是“本次请求为什么没拿到账号”的错误，不等同于账号持久状态。
    账号是否限流/异常仍由远程配额确认或鉴权结果决定。
    """

    # 控制流只认两个结果：
    #   quota_exhausted -> 远程确认额度耗尽，告诉客户端别重试（429）
    #   unavailable     -> 其它一切（没号/全忙/预检失败/上游波动），可重试（503）
    DEFAULTS: dict[str, tuple[int, str, str]] = {
        "quota_exhausted": (429, "insufficient_quota", "insufficient_quota"),
        "unavailable": (503, "server_error", "no_available_account"),
    }

    def __init__(self, kind: str, message: str = "") -> None:
        defaults = self.DEFAULTS.get(kind, self.DEFAULTS["unavailable"])
        self.kind = kind if kind in self.DEFAULTS else "unavailable"
        self.status_code, self.error_type, self.code = defaults
        detail = message or self.kind.replace("_", " ")
        super().__init__(f"image_account_selection:{self.kind}; {detail}")


class OAuthRefreshError(RuntimeError):
    """Structured OAuth token refresh failure."""

    def __init__(self, status_code: int, error_code: str = "", description: str = "") -> None:
        self.status_code = int(status_code or 0)
        self.error_code = str(error_code or "").strip()
        self.description = str(description or "").strip()[:300]
        details = [f"oauth_refresh_http_{self.status_code}"]
        if self.error_code:
            details.append(self.error_code)
        if self.description and self.description.casefold() != self.error_code.casefold():
            details.append(self.description)
        super().__init__(": ".join(details))


class TerminalRefreshTokenError(OAuthRefreshError):
    """The refresh credential is revoked, expired, or otherwise unusable."""

    def __init__(self, status_code: int, error_code: str = "", description: str = "") -> None:
        super().__init__(status_code, error_code, description)
        self.failure = image_failure("auth_invalid", raw_detail=str(self))


class RefreshCredentialsChangedError(RuntimeError):
    """Refresh credentials changed while an OAuth request was in flight."""

    def __init__(self) -> None:
        message = "OAuth refresh credentials changed during refresh."
        self.failure = image_failure("upstream_unavailable", raw_detail=message)
        super().__init__(message)


class AccountService:
    """账号池服务，使用 token -> account 的 dict 保存账号。"""

    _ACCESS_TOKEN_REFRESH_SKEW_SECONDS = 24 * 60 * 60
    _REFRESH_TOKEN_KEEPALIVE_SECONDS = 3 * 24 * 60 * 60
    _REFRESH_TOKEN_KEEPALIVE_ERROR_BACKOFF_SECONDS = 6 * 60 * 60
    _REFRESH_TOKEN_KEEPALIVE_BATCH_SIZE = 3
    _POOL_HEALTH_REFRESH_BATCH_SIZE = 10
    _TOKEN_REFRESH_ERROR_BACKOFF_SECONDS = 5 * 60
    _OAUTH_TOKEN_URL = "https://auth.openai.com/oauth/token"
    _OAUTH_CLIENT_ID = "app_2SKx67EdpoN0G6j64rFvigXD"
    _OAUTH_USER_AGENT = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/145.0.0.0 Safari/537.36"
    )
    # OAuth 刷新终态错误码：命中时代表 refresh_token 本身已失效，
    # 无论重试多少次都不会再成功（区别于限流/网络抖动等可重试情形）。
    _TERMINAL_REFRESH_ERROR_CODES = frozenset({
        "invalid_grant",
        "invalid_refresh_token",
        "refresh_token_invalidated",
    })
    _TERMINAL_REFRESH_MESSAGE_FRAGMENTS = ("session has ended",)
    # 图片失败后触发账号核验的去重窗口与并发上限（account scope）。
    # image scope 的并发上限复用 config.image_auth_refresh_concurrency（若存在）。
    _IMAGE_FAILURE_REFRESH_DEDUP_SECONDS = 30
    _IMAGE_FAILURE_REFRESH_MAX_CONCURRENT = 2

    # 刷新进度追踪
    _refresh_progress: dict[str, dict] = {}
    _refresh_progress_lock = Lock()

    def __init__(self, storage_backend: StorageBackend):
        self.storage = storage_backend
        self._lock = Lock()
        self._token_refresh_lock = Lock()
        self._oauth_refresh_flights_lock = Lock()
        self._oauth_refresh_flights: dict[tuple[str, str], Future[str]] = {}
        self._image_slot_condition = Condition(self._lock)
        self._index = 0
        self._accounts = self._load_accounts()
        self._image_inflight: dict[str, int] = {}
        self._token_aliases: dict[str, str] = {}
        self._image_failure_refresh_lock = Lock()
        self._image_failure_refresh_active: set[str] = set()
        self._image_failure_refresh_pending: deque[str] = deque()
        self._image_failure_refresh_pending_set: set[str] = set()
        self._image_failure_refresh_rerun: set[str] = set()
        self._image_failure_refresh_started_at: dict[str, float] = {}
        self._cumulative_total = self._load_cumulative_total()

    def _get_cumulative_file(self) -> Path:
        storage_path = getattr(self.storage, "file_path", None)
        if isinstance(storage_path, Path):
            return storage_path.with_name(".cumulative_total")
        from services.config import DATA_DIR
        return DATA_DIR / ".cumulative_total"

    def _load_cumulative_total(self) -> int:
        try:
            f = self._get_cumulative_file()
            if f.exists():
                return int(f.read_text().strip())
        except Exception:
            pass
        return len(self._accounts)

    def _save_cumulative_total(self) -> None:
        try:
            self._get_cumulative_file().write_text(str(self._cumulative_total))
        except Exception:
            pass

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")

    @staticmethod
    def _decode_jwt_payload(token: str) -> dict:
        try:
            payload = str(token or "").split(".")[1]
            payload += "=" * ((4 - len(payload) % 4) % 4)
            import base64
            import json
            data = json.loads(base64.urlsafe_b64decode(payload.encode("ascii")))
            return data if isinstance(data, dict) else {}
        except Exception:
            return {}

    @staticmethod
    def _parse_time(value: object) -> datetime | None:
        raw = str(value or "").strip()
        if not raw:
            return None
        try:
            parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except Exception:
            try:
                parsed = datetime.strptime(raw, "%Y-%m-%d %H:%M:%S")
            except Exception:
                return None
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)

    @staticmethod
    def _timestamp_to_iso(value: object) -> str:
        if isinstance(value, bool):
            return ""
        try:
            if isinstance(value, (int, float, str)):
                ts = int(value)
            else:
                return ""
        except (TypeError, ValueError):
            return ""
        tz = timezone(timedelta(hours=8))
        return datetime.fromtimestamp(ts, tz=timezone.utc).astimezone(tz).isoformat()

    def _load_accounts(self) -> dict[str, dict]:
        accounts = self.storage.load_accounts()
        return {
            normalized["access_token"]: normalized
            for item in accounts
            if (normalized := self._normalize_account(item)) is not None
        }

    def _save_accounts(self) -> None:
        self.storage.save_accounts(list(self._accounts.values()))

    @staticmethod
    def _is_image_account_available(account: dict) -> bool:
        if not isinstance(account, dict):
            return False
        status = str(account.get("status") or "").strip()
        # 中文号池状态 + Firefly refresh 写的 active/invalid 英文态
        if status in {"禁用", "限流", "异常", "invalid", "disabled", "deleted"}:
            return False
        # Firefly 续期成功写 status="active"；与中文“正常”等价
        if AccountService._normalize_source_type(account.get("source_type")) == "firefly":
            return status in {"正常", "active", ""} or int(account.get("quota") or 0) > 0
        if bool(account.get("image_quota_unknown")):
            return True
        # quota 是展示/预估值，不能作为持久调度开关。
        # 只有远程确认后写入的“限流”状态才代表图片额度耗尽；否则 quota=0 也要允许进入预检，
        # 避免本地扣减或额度重置不同步时把账号锁死在候选池外。
        return status == "正常" or int(account.get("quota") or 0) > 0

    @classmethod
    def _is_unlimited_image_quota_account(cls, account: dict) -> bool:
        if not isinstance(account, dict) or not bool(account.get("image_quota_unknown")):
            return False
        account_type = (cls._normalize_account_type(account.get("type")) or "").lower()
        return account_type in {"pro", "prolite"}

    @classmethod
    def _account_matches_plan_type(cls, account: dict, plan_type: str | None = None) -> bool:
        if not plan_type:
            return True
        normalized_plan = cls._normalize_account_type(plan_type)
        normalized_account = cls._normalize_account_type(account.get("type"))
        if not normalized_plan or not normalized_account:
            return False
        return normalized_plan.lower() == normalized_account.lower()

    @classmethod
    def _account_matches_source_type(cls, account: dict, source_type: str | None = None) -> bool:
        if not source_type:
            # 默认选号排除 firefly，避免混池误伤（OpenAI 预检会打残 Firefly 号）
            return cls._normalize_source_type(account.get("source_type")) != "firefly"
        return cls._normalize_source_type(account.get("source_type")) == cls._normalize_source_type(source_type)

    @classmethod
    def _account_matches_any_plan_type(cls, account: dict, plan_types: set[str] | tuple[str, ...] | None = None) -> bool:
        if not plan_types:
            return True
        normalized_account = cls._normalize_account_type(account.get("type"))
        normalized_plans = {
            normalized
            for plan_type in plan_types
            if (normalized := cls._normalize_account_type(plan_type))
        }
        return bool(normalized_account and normalized_account in normalized_plans)

    @staticmethod
    def _normalize_source_type(value: object) -> str:
        return str(value or "web").strip().lower() or "web"

    @staticmethod
    def _normalize_account_type(value: object) -> str | None:
        raw = str(value or "").strip()
        if not raw:
            return None
        key = raw.lower().replace("-", "_").replace(" ", "_")
        compact = key.replace("_", "")
        aliases = {
            "free": "free",
            "plus": "Plus",
            "pro": "Pro",
            "prolite": "ProLite",
            "team": "Team",
            "business": "Team",
            "enterprise": "Enterprise",
        }
        return aliases.get(compact) or aliases.get(key) or raw

    @staticmethod
    def _has_value(value: object) -> bool:
        return value is not None and str(value).strip() != ""

    @staticmethod
    def _bool_value(value: object, default: bool = False) -> bool:
        if isinstance(value, bool):
            return value
        if isinstance(value, (int, float)):
            return bool(value)
        raw = str(value or "").strip().lower()
        if raw in {"1", "true", "yes", "y", "on"}:
            return True
        if raw in {"0", "false", "no", "n", "off", "none", "null", ""}:
            return False
        return default

    @classmethod
    def _quota_value(cls, value: object, default: int = 0) -> int:
        if not cls._has_value(value):
            return max(0, int(default or 0))
        try:
            return max(0, int(float(str(value).strip())))
        except (TypeError, ValueError):
            return max(0, int(default or 0))

    @classmethod
    def _extract_image_quota_from_limits(cls, limits_progress: object) -> tuple[int | None, str | None, bool | None]:
        if not isinstance(limits_progress, list):
            return None, None, None
        if not limits_progress:
            return None, None, None

        for item in limits_progress:
            if not isinstance(item, dict):
                continue
            feature = str(
                item.get("feature_name")
                or item.get("feature")
                or item.get("name")
                or item.get("type")
                or ""
            ).strip().lower()
            if feature in {"image_gen", "image_generation", "image", "images"}:
                restore_at = str(
                    item.get("reset_after")
                    or item.get("restore_at")
                    or item.get("reset_at")
                    or ""
                ).strip() or None
                return cls._quota_value(item.get("remaining"), 0), restore_at, False

        return None, None, True

    def _search_account_type(self, payload: object) -> str | None:
        if isinstance(payload, dict):
            for key in ("plan_type", "account_plan", "account_type", "subscription_type", "type"):
                plan = self._normalize_account_type(payload.get(key))
                if plan:
                    return plan
            for value in payload.values():
                plan = self._search_account_type(value)
                if plan:
                    return plan
        elif isinstance(payload, list):
            for value in payload:
                plan = self._search_account_type(value)
                if plan:
                    return plan
        return None

    def _normalize_account(self, item: dict) -> dict | None:
        if not isinstance(item, dict):
            return None
        access_token = item.get("access_token") or item.get("accessToken") or ""
        if not access_token:
            return None
        normalized = dict(item)
        normalized.pop("accessToken", None)
        normalized["access_token"] = access_token
        if str(normalized.get("type") or "").strip().lower() == "codex":
            normalized["export_type"] = "codex"
            normalized.pop("type", None)
        limits_progress = normalized.get("limits_progress")
        limits_progress = limits_progress if isinstance(limits_progress, list) else []
        derived_quota, derived_restore_at, derived_unknown = self._extract_image_quota_from_limits(limits_progress)
        has_explicit_quota = self._has_value(normalized.get("quota"))
        normalized["type"] = normalized.get("type") or "free"
        normalized["status"] = normalized.get("status") or "正常"
        normalized["email"] = normalized.get("email") or None
        normalized["user_id"] = normalized.get("user_id") or None
        normalized["proxy"] = str(normalized.get("proxy") or "").strip()
        source_type = normalized.get("source_type")
        if not source_type and str(normalized.get("export_type") or "").strip().lower() == "codex":
            source_type = "codex"
        normalized["source_type"] = self._normalize_source_type(source_type)
        if not has_explicit_quota and derived_quota is not None:
            normalized["quota"] = derived_quota
        normalized["quota"] = self._quota_value(normalized.get("quota"), 0)
        if derived_unknown is not None and not self._has_value(normalized.get("image_quota_unknown")):
            normalized["image_quota_unknown"] = derived_unknown
        normalized["image_quota_unknown"] = self._bool_value(normalized.get("image_quota_unknown"), False)
        if (
            normalized["source_type"] == "codex"
            and normalized["quota"] == 0
            and not limits_progress
            and normalized.get("status") not in {"限流", "异常", "禁用"}
            and not normalized.get("last_token_refresh_at")
            and not normalized.get("last_used_at")
        ):
            normalized["image_quota_unknown"] = True
        normalized["limits_progress"] = limits_progress
        normalized["default_model_slug"] = normalized.get("default_model_slug") or None
        if derived_restore_at and not normalized.get("restore_at"):
            normalized["restore_at"] = derived_restore_at
        normalized["restore_at"] = normalized.get("restore_at") or None
        normalized["success"] = int(normalized.get("success") or 0)
        normalized["fail"] = int(normalized.get("fail") or 0)
        normalized["invalid_count"] = int(normalized.get("invalid_count") or 0)
        normalized["last_used_at"] = normalized.get("last_used_at")
        normalized["last_invalid_at"] = normalized.get("last_invalid_at") or None
        normalized["last_refresh_error"] = normalized.get("last_refresh_error") or None
        normalized["last_refresh_error_at"] = normalized.get("last_refresh_error_at") or None
        normalized["last_token_refresh_at"] = normalized.get("last_token_refresh_at") or None
        normalized["last_token_refresh_error"] = normalized.get("last_token_refresh_error") or None
        normalized["last_token_refresh_error_at"] = normalized.get("last_token_refresh_error_at") or None
        normalized["last_remote_checked_at"] = normalized.get("last_remote_checked_at") or None
        normalized["last_remote_check_attempt_at"] = normalized.get("last_remote_check_attempt_at") or None
        normalized["last_remote_check_error"] = normalized.get("last_remote_check_error") or None
        normalized["last_remote_check_error_at"] = normalized.get("last_remote_check_error_at") or None
        normalized["last_remote_check_event"] = normalized.get("last_remote_check_event") or None
        normalized["last_remote_check_result"] = normalized.get("last_remote_check_result") or None
        normalized["created_at"] = normalized.get("created_at") or AccountService._now()
        return normalized

    @staticmethod
    def _jwt_exp(access_token: str) -> int:
        try:
            return int(AccountService._decode_jwt_payload(access_token).get("exp") or 0)
        except (TypeError, ValueError):
            return 0

    @classmethod
    def _token_expires_in(cls, access_token: str) -> int | None:
        exp = cls._jwt_exp(access_token)
        if exp <= 0:
            return None
        return exp - int(time.time())

    @classmethod
    def _token_needs_refresh(cls, access_token: str, *, force: bool = False) -> bool:
        if force:
            return True
        remaining = cls._token_expires_in(access_token)
        # 非 JWT / 坏 payload 时 remaining 为 None：无法判断剩余寿命，
        # 保守视为需要刷新（调用方已保证有 refresh_token 才会真正发起 OAuth）。
        if remaining is None:
            return True
        return remaining <= cls._ACCESS_TOKEN_REFRESH_SKEW_SECONDS

    @classmethod
    def _token_issued_at(cls, access_token: str) -> datetime | None:
        try:
            iat = int(cls._decode_jwt_payload(access_token).get("iat") or 0)
        except (TypeError, ValueError):
            return None
        if iat <= 0:
            return None
        return datetime.fromtimestamp(iat, tz=timezone.utc)

    @staticmethod
    def _safe_response_text(response: object, limit: int = 300) -> str:
        try:
            return redact_auth_diagnostic(getattr(response, "text", ""), limit)
        except Exception:
            return ""

    def _resolve_access_token_locked(self, access_token: str) -> str:
        token = str(access_token or "").strip()
        seen: set[str] = set()
        while token and token not in self._accounts and token in self._token_aliases and token not in seen:
            seen.add(token)
            token = self._token_aliases.get(token, token)
        return token

    def resolve_access_token(self, access_token: str) -> str:
        if not access_token:
            return ""
        with self._lock:
            return self._resolve_access_token_locked(access_token)

    def _get_account_for_token(self, access_token: str) -> tuple[str, dict | None]:
        with self._lock:
            resolved = self._resolve_access_token_locked(access_token)
            account = self._accounts.get(resolved)
            return resolved, dict(account) if account else None

    def _credential_snapshot(self, access_token: str) -> tuple[str, str, dict | None]:
        resolved, account = self._get_account_for_token(access_token)
        if not account:
            return resolved, "", None
        active_token = str(account.get("access_token") or resolved or access_token).strip()
        refresh_token = str(account.get("refresh_token") or "").strip()
        return active_token, refresh_token, account

    def _record_token_refresh_error(
        self,
        access_token: str,
        event: str,
        error: str,
        *,
        expected_access_token: str | None = None,
        expected_refresh_token: str | None = None,
    ) -> bool:
        now = datetime.now(timezone.utc).isoformat()
        safe_error = redact_auth_diagnostic(error or "refresh token failed")
        with self._lock:
            resolved = self._resolve_access_token_locked(access_token)
            current = self._accounts.get(resolved)
            if current is None:
                return False
            if expected_access_token is not None and resolved != str(expected_access_token or "").strip():
                return False
            if expected_refresh_token is not None and (
                str(current.get("refresh_token") or "").strip()
                != str(expected_refresh_token or "").strip()
            ):
                return False
            next_item = dict(current)
            next_item["last_token_refresh_error"] = safe_error
            next_item["last_token_refresh_error_at"] = now
            account = self._normalize_account(next_item)
            if account is None:
                return False
            self._accounts[resolved] = account
            self._save_accounts()
        log_service.add(
            LOG_TYPE_ACCOUNT,
            "refresh_token 刷新 access_token 失败",
            {"source": event, "token": anonymize_token(resolved), "error": safe_error},
        )
        return True

    def _recent_token_refresh_error(self, account: dict) -> bool:
        last_error_at = self._parse_time(account.get("last_token_refresh_error_at"))
        if last_error_at is None:
            return False
        return (datetime.now(timezone.utc) - last_error_at).total_seconds() < self._TOKEN_REFRESH_ERROR_BACKOFF_SECONDS

    def _recent_refresh_token_keepalive_error(self, account: dict, now: datetime) -> bool:
        last_error_at = self._parse_time(account.get("last_token_refresh_error_at"))
        if last_error_at is None:
            return False
        return (now - last_error_at).total_seconds() < self._REFRESH_TOKEN_KEEPALIVE_ERROR_BACKOFF_SECONDS

    def _refresh_token_keepalive_anchor(self, account: dict) -> datetime | None:
        return (
            self._parse_time(account.get("last_token_refresh_at"))
            or self._token_issued_at(str(account.get("access_token") or ""))
            or self._parse_time(account.get("created_at"))
        )

    def _refresh_token_keepalive_due_at(self, account: dict, now: datetime) -> datetime | None:
        if not str(account.get("refresh_token") or "").strip():
            return None
        if account.get("status") == "禁用":
            return None
        if self._recent_refresh_token_keepalive_error(account, now):
            return None
        anchor = self._refresh_token_keepalive_anchor(account)
        if anchor is None:
            return now
        due_at = anchor + timedelta(seconds=self._REFRESH_TOKEN_KEEPALIVE_SECONDS)
        return due_at if due_at <= now else None

    @staticmethod
    def _oauth_refresh_error_fields(data: object) -> tuple[str, str]:
        if not isinstance(data, dict):
            return "", ""
        error = data.get("error")
        nested = error if isinstance(error, dict) else {}
        code = str(
            nested.get("code")
            or data.get("code")
            or (error if isinstance(error, str) else "")
            or ""
        ).strip()
        description = str(
            data.get("error_description")
            or nested.get("message")
            or data.get("message")
            or nested.get("description")
            or ""
        ).strip()
        return code, description

    @classmethod
    def _is_terminal_refresh_error(cls, status_code: int, error_code: str, description: str) -> bool:
        if status_code in {408, 429} or status_code >= 500:
            return False
        normalized_code = str(error_code or "").strip().casefold()
        normalized_description = str(description or "").strip().casefold()
        if normalized_code in cls._TERMINAL_REFRESH_ERROR_CODES:
            return True
        return 400 <= status_code < 500 and any(
            fragment in normalized_description
            for fragment in cls._TERMINAL_REFRESH_MESSAGE_FRAGMENTS
        )

    def _request_access_token_refresh(self, refresh_token: str, account: dict | None = None) -> dict[str, str]:
        from curl_cffi import requests
        from services.proxy_service import proxy_settings

        profile = proxy_settings.get_profile(account=account)
        session = requests.Session(
            proxy=profile.proxy_url or None,
            impersonate="chrome110",
            verify=not profile.skip_ssl_verify,
        )
        try:
            response = session.post(
                self._OAUTH_TOKEN_URL,
                headers={
                    "Accept": "application/json",
                    "Content-Type": "application/x-www-form-urlencoded",
                    "User-Agent": self._OAUTH_USER_AGENT,
                },
                data={
                    "grant_type": "refresh_token",
                    "refresh_token": refresh_token,
                    "client_id": self._OAUTH_CLIENT_ID,
                },
                timeout=60,
            )
            raw_text = self._safe_response_text(response)
            try:
                data = response.json() if raw_text else {}
            except Exception:
                data = {}
            status_code = int(getattr(response, "status_code", 0) or 0)
            if status_code != 200 or not isinstance(data, dict) or not data.get("access_token"):
                error_code, description = self._oauth_refresh_error_fields(data)
                description = redact_auth_diagnostic(description or raw_text, 300)
                error_type = (
                    TerminalRefreshTokenError
                    if self._is_terminal_refresh_error(status_code, error_code, description)
                    else OAuthRefreshError
                )
                raise error_type(status_code, error_code, description)
            return {
                "access_token": str(data.get("access_token") or "").strip(),
                "refresh_token": str(data.get("refresh_token") or refresh_token).strip(),
                "id_token": str(data.get("id_token") or "").strip(),
            }
        finally:
            session.close()

    def _apply_refreshed_tokens(
        self,
        old_access_token: str,
        token_data: dict,
        event: str,
        *,
        expected_access_token: str | None = None,
        expected_refresh_token: str | None = None,
    ) -> str:
        now = datetime.now(timezone.utc).isoformat()
        with self._image_slot_condition:
            old_token = self._resolve_access_token_locked(old_access_token)
            current = self._accounts.get(old_token)
            if current is None:
                if expected_access_token is not None or expected_refresh_token is not None:
                    raise RefreshCredentialsChangedError()
                return old_token
            if expected_access_token is not None and old_token != str(expected_access_token or "").strip():
                raise RefreshCredentialsChangedError()
            if expected_refresh_token is not None and (
                str(current.get("refresh_token") or "").strip()
                != str(expected_refresh_token or "").strip()
            ):
                raise RefreshCredentialsChangedError()
            new_token = str(token_data.get("access_token") or old_token).strip()
            if not new_token:
                return old_token
            if new_token != old_token and new_token in self._accounts:
                raise RefreshCredentialsChangedError()

            next_item = dict(current)
            next_item["access_token"] = new_token
            if "refresh_token" in token_data:
                next_item["refresh_token"] = str(token_data.get("refresh_token") or "").strip()
            if "id_token" in token_data:
                next_item["id_token"] = str(token_data.get("id_token") or "").strip()
            if "token_expires_at" in token_data:
                next_item["token_expires_at"] = str(token_data.get("token_expires_at") or "").strip()
            if token_data.get("status"):
                next_item["status"] = str(token_data.get("status") or "").strip()
            next_item["last_token_refresh_at"] = now
            next_item["last_token_refresh_error"] = None
            next_item["last_token_refresh_error_at"] = None
            next_item["invalid_count"] = 0
            next_item["last_invalid_at"] = None
            next_item["last_refresh_error"] = None
            next_item["last_refresh_error_at"] = None

            account = self._normalize_account(next_item)
            if account is None:
                return old_token

            rotated = new_token != old_token
            if rotated:
                self._accounts.pop(old_token, None)
                self._token_aliases[old_token] = new_token
                old_inflight = int(self._image_inflight.pop(old_token, 0))
                if old_inflight:
                    self._image_inflight[new_token] = int(self._image_inflight.get(new_token, 0)) + old_inflight
                # token 旋转时，把失败刷新队列里的旧 token 改写成新 token，避免丢单。
                with self._image_failure_refresh_lock:
                    def _rewrite_token(token: str) -> str:
                        return new_token if token == old_token else token

                    if old_token in self._image_failure_refresh_pending_set or any(
                        token == old_token for token in self._image_failure_refresh_pending
                    ):
                        pending = (
                            _rewrite_token(token)
                            for token in self._image_failure_refresh_pending
                        )
                        self._image_failure_refresh_pending = deque(dict.fromkeys(pending))
                        self._image_failure_refresh_pending_set = set(self._image_failure_refresh_pending)
                    if old_token in self._image_failure_refresh_active:
                        self._image_failure_refresh_active.discard(old_token)
                        self._image_failure_refresh_active.add(new_token)
                    if old_token in self._image_failure_refresh_rerun:
                        self._image_failure_refresh_rerun.discard(old_token)
                        self._image_failure_refresh_rerun.add(new_token)
                    started_at = self._image_failure_refresh_started_at.pop(old_token, None)
                    if started_at is not None:
                        self._image_failure_refresh_started_at[new_token] = started_at
            self._accounts[new_token] = account
            self._save_accounts()
            self._image_slot_condition.notify_all()

        log_service.add(
            LOG_TYPE_ACCOUNT,
            "refresh_token 已刷新 access_token",
            {"source": event, "token": anonymize_token(new_token), "rotated": rotated},
        )
        return new_token

    def apply_relogin_tokens(self, old_access_token: str, token_data: dict, event: str = "relogin") -> str:
        # relogin 不走 CAS：凭据本身就是要被替换的。
        relogin_data = {**token_data, "status": "正常"}
        return self._apply_refreshed_tokens(old_access_token, relogin_data, event)

    def _refresh_access_token_owner(
        self,
        active_token: str,
        refresh_token: str,
        account: dict,
        *,
        event: str,
    ) -> str:
        try:
            token_data = self._request_access_token_refresh(refresh_token, account)
        except TerminalRefreshTokenError as exc:
            error_str = str(exc)
            self._record_token_refresh_error(
                active_token,
                event,
                error_str,
                expected_access_token=active_token,
                expected_refresh_token=refresh_token,
            )
            self.handle_invalid_token(active_token, event, error=error_str)
            raise
        except Exception as exc:
            error_str = str(exc or "")
            self._record_token_refresh_error(
                active_token,
                event,
                error_str,
                expected_access_token=active_token,
                expected_refresh_token=refresh_token,
            )
            raise
        return self._apply_refreshed_tokens(
            active_token,
            token_data,
            event,
            expected_access_token=active_token,
            expected_refresh_token=refresh_token,
        )

    def refresh_access_token(self, access_token: str, *, force: bool = False, event: str = "refresh_access_token") -> str:
        if not access_token:
            return ""
        for credential_attempt in range(2):
            resolved_token, account = self._get_account_for_token(access_token)
            if not account:
                return access_token
            active_token = str(account.get("access_token") or resolved_token or access_token)
            needs_refresh = self._token_needs_refresh(active_token, force=force)
            refresh_backoff = not force and self._recent_token_refresh_error(account)
            refresh_token = str(account.get("refresh_token") or "").strip()
            if not refresh_token:
                return active_token
            if not needs_refresh or refresh_backoff:
                return active_token

            key = (active_token, refresh_token)
            with self._oauth_refresh_flights_lock:
                future = self._oauth_refresh_flights.get(key)
                owner = future is None
                if future is None:
                    future = Future()
                    self._oauth_refresh_flights[key] = future
            if owner:
                try:
                    # 外层仍用 token 级锁，避免同一进程内并发打爆 OAuth。
                    with self._token_refresh_lock:
                        result = self._refresh_access_token_owner(
                            active_token,
                            refresh_token,
                            account,
                            event=event,
                        )
                except BaseException as exc:
                    future.set_exception(exc)
                else:
                    future.set_result(result)
            try:
                return future.result()
            except TerminalRefreshTokenError:
                # 终态：owner 路径已 handle_invalid_token；返回旧 token 让调用方走
                # refreshed != token 分支（例如 conversation 再兜底标记）。
                return active_token
            except RefreshCredentialsChangedError:
                if credential_attempt == 0:
                    continue
                current_token, current = self._get_account_for_token(access_token)
                return str((current or {}).get("access_token") or current_token or access_token)
            except Exception:
                # 瞬时失败（429/5xx/网络等）：不要静默返回旧 token，
                # 避免上层把“未刷成功”当成“刷完仍是原 token / 可继续用旧 AT”。
                # 错误已在 _refresh_access_token_owner 记入 last_token_refresh_error。
                raise
            finally:
                if owner:
                    with self._oauth_refresh_flights_lock:
                        if self._oauth_refresh_flights.get(key) is future:
                            self._oauth_refresh_flights.pop(key, None)
        return access_token

    def list_expiring_access_tokens(self) -> list[str]:
        with self._lock:
            return [
                token
                for account in self._accounts.values()
                if str(account.get("refresh_token") or "").strip()
                and (token := str(account.get("access_token") or "").strip())
                and self._token_needs_refresh(token)
            ]

    def list_refresh_token_keepalive_tokens(self) -> list[str]:
        now = datetime.now(timezone.utc)
        due_items: list[tuple[datetime, str]] = []
        with self._lock:
            for account in self._accounts.values():
                due_at = self._refresh_token_keepalive_due_at(account, now)
                token = str(account.get("access_token") or "").strip()
                if due_at is not None and token:
                    due_items.append((due_at, token))
        due_items.sort(key=lambda item: item[0])
        return [token for _, token in due_items[: self._REFRESH_TOKEN_KEEPALIVE_BATCH_SIZE]]

    def keepalive_refresh_tokens(self, access_tokens: list[str]) -> dict[str, Any]:
        access_tokens = list(dict.fromkeys(token for token in access_tokens if token))
        if not access_tokens:
            return {"refreshed": 0, "errors": [], "items": self.list_accounts()}

        refreshed = 0
        errors = []
        for access_token in access_tokens:
            before = self.resolve_access_token(access_token)
            try:
                after = self.refresh_access_token(before, force=True, event="refresh_token_keepalive")
            except Exception as exc:
                # 瞬时失败会 re-raise；错误细节多半已写入账号字段。
                account = self.get_account(before)
                error_text = ""
                if account:
                    error_text = str(account.get("last_token_refresh_error") or "").strip()
                errors.append({
                    "token": anonymize_token(before),
                    "error": error_text or redact_auth_diagnostic(str(exc) or "refresh token failed"),
                })
                continue
            account = self.get_account(after)
            if account and str(account.get("last_token_refresh_error") or "").strip():
                errors.append({
                    "token": anonymize_token(before),
                    "error": str(account.get("last_token_refresh_error") or "refresh token failed"),
                })
                continue
            if account:
                refreshed += 1

        return {
            "refreshed": refreshed,
            "errors": errors,
            "items": self.list_accounts(),
        }

    def list_tokens(self) -> list[str]:
        with self._lock:
            return list(self._accounts)

    def _list_ready_candidate_tokens(
            self,
            excluded_tokens: set[str] | None = None,
            plan_type: str | None = None,
            source_type: str | None = None,
            plan_types: set[str] | tuple[str, ...] | None = None,
    ) -> list[str]:
        excluded = set(excluded_tokens or set())
        return [
            token
            for item in self._accounts.values()
            if self._is_image_account_available(item)
               and self._account_matches_plan_type(item, plan_type)
               and self._account_matches_any_plan_type(item, plan_types)
               and self._account_matches_source_type(item, source_type)
               and (token := item.get("access_token") or "")
               and token not in excluded
        ]

    def _list_available_candidate_tokens(
            self,
            excluded_tokens: set[str] | None = None,
            plan_type: str | None = None,
            source_type: str | None = None,
            plan_types: set[str] | tuple[str, ...] | None = None,
    ) -> list[str]:
        max_concurrency = max(1, int(config.image_account_concurrency or 1))
        return [
            token
            for token in self._list_ready_candidate_tokens(excluded_tokens, plan_type, source_type, plan_types)
            if int(self._image_inflight.get(token, 0)) < max_concurrency
        ]

    def _acquire_next_candidate_token(
            self,
            excluded_tokens: set[str] | None = None,
            plan_type: str | None = None,
            source_type: str | None = None,
            plan_types: set[str] | tuple[str, ...] | None = None,
    ) -> str:
        with self._image_slot_condition:
            while True:
                if not self._list_ready_candidate_tokens(excluded_tokens, plan_type, source_type, plan_types):
                    raise self._no_ready_candidate_error(plan_type, source_type, plan_types, excluded_tokens)
                tokens = self._list_available_candidate_tokens(excluded_tokens, plan_type, source_type, plan_types)
                if tokens:
                    access_token = tokens[self._index % len(tokens)]
                    self._index += 1
                    self._image_inflight[access_token] = int(self._image_inflight.get(access_token, 0)) + 1
                    return access_token
                self._image_slot_condition.wait(timeout=1.0)

    def _no_ready_candidate_error(
            self,
            plan_type: str | None,
            source_type: str | None,
            plan_types: set[str] | tuple[str, ...] | None,
            excluded_tokens: set[str] | None,
    ) -> "ImageAccountSelectionError":
        """没有任何 ready 候选时区分两种成因。

        这是“初筛阶段”的判据：只看本地缓存状态，此时还没走远程预检，
        不存在“预检失败”这一维度。匹配账号全部为“限流”（限流只由远程确认写入）
        -> 额度耗尽（429）；否则一律归为可重试的 unavailable（503）。

        注意：get_available_access_token 里的 429 判据更严
        （额外要求 not saw_unavailable_failure），因为那是“预检阶段”，
        会有上游波动等可重试失败混入，不能仅凭限流就下终结性结论。
        """
        excluded = set(excluded_tokens or set())
        matched = 0
        limited = 0
        for item in self._accounts.values():
            token = item.get("access_token") or ""
            if not token or token in excluded:
                continue
            if not (
                self._account_matches_plan_type(item, plan_type)
                and self._account_matches_any_plan_type(item, plan_types)
                and self._account_matches_source_type(item, source_type)
            ):
                continue
            matched += 1
            if str(item.get("status") or "") == "限流":
                limited += 1
        if matched > 0 and limited == matched:
            return ImageAccountSelectionError(
                "quota_exhausted",
                "all matched image accounts are remote-confirmed quota exhausted",
            )
        return ImageAccountSelectionError(
            "unavailable",
            "no image account is ready for current model/status filters",
        )

    def report_exhausted(self, access_token: str, *, reason: str = "taste_exhausted") -> dict | None:
        """Firefly taste_exhausted 等：标限流、quota=0，并释放 inflight 槽位。

        与 ChatGPT 远程 limits 确认后写「限流」同语义，供后续选号走 429 耗尽出口。
        """
        if not access_token:
            return None
        now = datetime.now(timezone.utc)
        with self._image_slot_condition:
            access_token = self._resolve_access_token_locked(access_token)
            self._release_image_slot_locked(access_token)
            current = self._accounts.get(access_token)
            if current is None:
                return None
            next_item = dict(current)
            next_item["status"] = "限流"
            next_item["quota"] = 0
            next_item["image_quota_unknown"] = False
            next_item["last_remote_check_result"] = "exhausted"
            next_item["last_remote_check_event"] = str(reason or "taste_exhausted")
            next_item["last_remote_checked_at"] = now.isoformat()
            next_item["last_remote_check_attempt_at"] = now.isoformat()
            account = self._normalize_account(next_item)
            if account is None:
                return None
            # 对齐 update_account：自动移除额度耗尽账号时清 inflight / alias
            if account.get("status") == "限流" and config.auto_remove_rate_limited_accounts:
                self._accounts.pop(access_token, None)
                self._image_inflight.pop(access_token, None)
                self._token_aliases = {
                    old: new
                    for old, new in self._token_aliases.items()
                    if old != access_token and new != access_token
                }
                if self._accounts:
                    self._index %= len(self._accounts)
                else:
                    self._index = 0
                self._save_accounts()
                self._image_slot_condition.notify_all()
                log_service.add(LOG_TYPE_ACCOUNT, "自动移除额度耗尽账号", {"token": anonymize_token(access_token)})
                return None
            self._accounts[access_token] = account
            self._save_accounts()
            self._image_slot_condition.notify_all()
            return dict(account)

    def get_available_access_token(
            self,
            plan_type: str | None = None,
            source_type: str | None = None,
            plan_types: set[str] | tuple[str, ...] | None = None,
            excluded_tokens: set[str] | None = None,
    ) -> str:
        """从候选池中获取一个可用的图片生图 token。

        基于本地缓存做初筛，然后通过 fetch_remote_info 做远程验证（token 有效性、配额等）。
        限制最大尝试次数防止 token rotation 导致无限循环。

        source_type=\"firefly\" 时跳过 OpenAI 远程预检，纯本地 RR + status 过滤。
        """
        # Firefly 无 ChatGPT limits_progress；额度靠 taste_exhausted → report_exhausted
        if self._normalize_source_type(source_type) == "firefly":
            return self._acquire_next_candidate_token(
                excluded_tokens=excluded_tokens,
                plan_type=plan_type,
                source_type=source_type,
                plan_types=plan_types,
            )

        max_attempts = 20  # 防止无限循环
        attempted_tokens: set[str] = set(excluded_tokens or set())
        # 控制流只保留两个出口，但最终是否能说“额度耗尽”必须谨慎：
        # 只要出现过非额度类失败，就说明不能断言全部账号都耗尽，应返回可重试的 unavailable。
        saw_remote_quota_exhausted = False
        saw_unavailable_failure = False
        for _attempt in range(max_attempts):
            try:
                access_token = self._acquire_next_candidate_token(
                    excluded_tokens=attempted_tokens,
                    plan_type=plan_type,
                    source_type=source_type,
                    plan_types=plan_types,
                )
            except ImageAccountSelectionError:
                if attempted_tokens:
                    break
                raise
            attempted_tokens.add(access_token)
            try:
                account = self.fetch_remote_info(access_token, "get_available_access_token")
            except Exception:
                # 预检失败（上游波动/网络/401 等）：这个号这次不可用，换下一个。
                # 401 已在 fetch_remote_info 内部走异常处理，这里不再二次分类。
                saw_unavailable_failure = True
                self.release_image_slot(access_token)
                continue
            # fetch_remote_info 内部可能因 token rotation 导致 access_token 变化，
            # 把新 token 也加入排除列表，防止重复尝试
            resolved = str((account or {}).get("access_token") or "")
            if resolved and resolved != access_token:
                attempted_tokens.add(resolved)
            if (
                    self._is_image_account_available(account or {})
                    and self._account_matches_plan_type(account or {}, plan_type)
                    and self._account_matches_any_plan_type(account or {}, plan_types)
                    and self._account_matches_source_type(account or {}, source_type)
            ):
                return str((account or {}).get("access_token") or access_token)
            if str((account or {}).get("status") or "") == "限流":
                saw_remote_quota_exhausted = True
            else:
                saw_unavailable_failure = True
            self.release_image_slot(access_token)
        if saw_remote_quota_exhausted and not saw_unavailable_failure:
            raise ImageAccountSelectionError(
                "quota_exhausted",
                f"all usable image accounts remote-confirmed quota exhausted after {len(attempted_tokens)} attempts",
            )
        raise ImageAccountSelectionError(
            "unavailable",
            f"no image account available after {len(attempted_tokens)} attempts",
        )

    def get_text_access_token(self, excluded_tokens: set[str] | None = None) -> str:
        excluded = set(excluded_tokens or set())
        with self._lock:
            candidates = [
                token
                for account in self._accounts.values()
                if account.get("status") not in {"禁用", "异常", "invalid", "disabled", "deleted"}
                   and self._normalize_source_type(account.get("source_type")) != "firefly"
                   and (token := account.get("access_token") or "")
                   and token not in excluded
            ]
            if not candidates:
                return ""
            access_token = candidates[self._index % len(candidates)]
            self._index += 1
        try:
            return self.refresh_access_token(access_token, event="get_text_access_token") or access_token
        except Exception:
            # 机会性续期瞬时失败时仍返回现有 AT，由上游 401 再走 force refresh。
            return access_token

    def mark_text_used(self, access_token: str) -> None:
        if not access_token:
            return
        with self._lock:
            access_token = self._resolve_access_token_locked(access_token)
            current = self._accounts.get(access_token)
            if current is None:
                return
            next_item = dict(current)
            next_item["last_used_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            account = self._normalize_account(next_item)
            if account is None:
                return
            self._accounts[access_token] = account
            self._save_accounts()

    def remove_invalid_token(
        self,
        access_token: str,
        event: str,
        quiet: bool = False,
        remove: bool | None = None,
        error: str | None = None,
    ) -> bool:
        return self.handle_invalid_token(
            access_token,
            event,
            error=error,
            quiet=quiet,
            remove=remove,
        )

    def handle_invalid_token(
        self,
        access_token: str,
        event: str,
        error: str | None = None,
        quiet: bool = False,
        remove: bool | None = None,
    ) -> bool:
        """统一处理鉴权异常账号。

        口径固定为：先记录异常，再按“自动移除异常账号”配置删除或保留异常状态。
        """
        self._record_invalid_token_seen(access_token, event, str(error or "invalid access token"))
        should_remove = config.auto_remove_invalid_accounts if remove is None else remove
        if not should_remove:
            return False
        removed = bool(self.delete_accounts([access_token], return_items=False)["removed"])
        if removed:
            safe_error = redact_auth_diagnostic(error or "")
            log_service.add(LOG_TYPE_ACCOUNT, "自动移除异常账号",
                            {"source": event, "token": anonymize_token(access_token), "error": safe_error})
        elif access_token:
            self.update_account(access_token, {"status": "异常", "quota": 0}, quiet=quiet)
        return removed

    def get_account(self, access_token: str) -> dict | None:
        if not access_token:
            return None
        with self._lock:
            access_token = self._resolve_access_token_locked(access_token)
            account = self._accounts.get(access_token)
            return dict(account) if account else None

    def list_accounts(self) -> list[dict]:
        """返回所有账号的副本，并为每个账号附加当前图片在途数 image_inflight。

        image_inflight 为内存态并发计数(账号正在生成、尚未结束的图片数)。号池空闲时
        若某账号该值持续 > 0，说明其并发槽位泄漏、已被静默排除出调度，可借此在 UI 上诊断。
        """
        with self._lock:
            result = []
            for item in self._accounts.values():
                account = dict(item)
                token = account.get("access_token") or ""
                account["image_inflight"] = int(self._image_inflight.get(token, 0))
                result.append(account)
            return result

    def list_limited_tokens(self) -> list[str]:
        with self._lock:
            return [
                token
                for item in self._accounts.values()
                if item.get("status") == "限流"
                   and (token := item.get("access_token") or "")
            ]

    def list_normal_tokens(self) -> list[str]:
        with self._lock:
            return [
                token
                for item in self._accounts.values()
                if item.get("status") == "正常"
                   and (token := item.get("access_token") or "")
            ]

    @staticmethod
    def _pool_health_freshness_seconds(value: object = None) -> int:
        fallback = max(60, int(config.refresh_account_interval_minute or 0) * 60)
        if not AccountService._has_value(value):
            return fallback
        if isinstance(value, bool) or not isinstance(value, (int, float, str)):
            return fallback
        try:
            return max(60, int(float(value)))
        except (OverflowError, TypeError, ValueError):
            return fallback

    @classmethod
    def _remote_check_is_fresh(
        cls,
        account: dict,
        *,
        now: datetime,
        freshness_seconds: int,
    ) -> bool:
        checked_at = cls._parse_time(account.get("last_remote_checked_at"))
        if checked_at is None:
            return False
        age_seconds = (now - checked_at).total_seconds()
        return 0 <= age_seconds <= freshness_seconds

    @classmethod
    def _remote_check_attempt_is_recent(
        cls,
        account: dict,
        *,
        now: datetime,
        freshness_seconds: int,
    ) -> bool:
        attempted_at = cls._parse_time(account.get("last_remote_check_attempt_at"))
        if attempted_at is None:
            return False
        age_seconds = (now - attempted_at).total_seconds()
        return 0 <= age_seconds <= freshness_seconds

    @classmethod
    def _pool_health_metrics_from_accounts(
        cls,
        accounts: list[dict],
        *,
        now: datetime,
        freshness_seconds: int,
    ) -> dict[str, Any]:
        current_quota = 0
        current_available = 0
        estimated_quota = 0
        estimated_available = 0
        unconfirmed_available = 0
        unknown_quota_count = 0
        latest_checked_at: datetime | None = None

        for account in accounts:
            checked_at = cls._parse_time(account.get("last_remote_checked_at"))
            if checked_at is not None and (latest_checked_at is None or checked_at > latest_checked_at):
                latest_checked_at = checked_at
            if account.get("status") != "正常":
                continue

            is_fresh = cls._remote_check_is_fresh(
                account,
                now=now,
                freshness_seconds=freshness_seconds,
            )
            quota_unknown = cls._bool_value(account.get("image_quota_unknown"), False)
            quota = cls._quota_value(account.get("quota"), 0)
            estimated_available += 1
            if not quota_unknown:
                estimated_quota += quota

            if is_fresh:
                current_available += 1
                if quota_unknown:
                    unknown_quota_count += 1
                else:
                    current_quota += quota
            else:
                unconfirmed_available += 1

        return {
            "current_quota": current_quota,
            "current_available": current_available,
            "estimated_quota": estimated_quota,
            "estimated_available": estimated_available,
            "unconfirmed_available": unconfirmed_available,
            "unknown_quota_count": unknown_quota_count,
            "pool_freshness_seconds": freshness_seconds,
            "pool_last_checked_at": latest_checked_at.isoformat() if latest_checked_at is not None else None,
        }

    @classmethod
    def _pool_health_stale_tokens(
        cls,
        accounts: list[dict],
        *,
        now: datetime,
        freshness_seconds: int,
    ) -> list[str]:
        stale: list[tuple[datetime, str]] = []
        missing_checked_at = datetime.min.replace(tzinfo=timezone.utc)
        for account in accounts:
            token = str(account.get("access_token") or "").strip()
            if (
                account.get("status") != "正常"
                or not token
                or cls._remote_check_is_fresh(
                    account,
                    now=now,
                    freshness_seconds=freshness_seconds,
                )
                or cls._remote_check_attempt_is_recent(
                    account,
                    now=now,
                    freshness_seconds=freshness_seconds,
                )
            ):
                continue
            checked_at = cls._parse_time(account.get("last_remote_checked_at"))
            stale.append((checked_at or missing_checked_at, token))
        stale.sort(key=lambda item: item[0])
        return [token for _, token in stale]

    @staticmethod
    def _pool_health_target_reached(
        metrics: dict[str, Any],
        *,
        target_quota: int | None,
        target_available: int | None,
    ) -> bool:
        return (
            target_quota is not None
            and int(metrics.get("current_quota") or 0) >= max(1, int(target_quota))
        ) or (
            target_available is not None
            and int(metrics.get("current_available") or 0) >= max(1, int(target_available))
        )

    def evaluate_account_pool(
        self,
        *,
        refresh_stale: bool = False,
        freshness_seconds: object = None,
        target_quota: int | None = None,
        target_available: int | None = None,
    ) -> dict[str, Any]:
        freshness = self._pool_health_freshness_seconds(freshness_seconds)
        refreshed = 0
        refresh_errors: list[Any] = []

        while True:
            accounts = self.list_accounts()
            now = datetime.now(timezone.utc)
            metrics = self._pool_health_metrics_from_accounts(
                accounts,
                now=now,
                freshness_seconds=freshness,
            )
            stale_tokens = self._pool_health_stale_tokens(
                accounts,
                now=now,
                freshness_seconds=freshness,
            )
            if (
                not refresh_stale
                or self._pool_health_target_reached(
                    metrics,
                    target_quota=target_quota,
                    target_available=target_available,
                )
                or not stale_tokens
            ):
                return {
                    "current_quota": metrics["current_quota"],
                    "current_available": metrics["current_available"],
                    "estimated_quota": metrics["estimated_quota"],
                    "estimated_available": metrics["estimated_available"],
                    "unconfirmed_available": metrics["unconfirmed_available"],
                    "unknown_quota_count": metrics["unknown_quota_count"],
                    "pool_freshness_seconds": metrics["pool_freshness_seconds"],
                    "pool_last_checked_at": metrics["pool_last_checked_at"],
                    "pool_refreshed": refreshed,
                    "pool_refresh_errors": refresh_errors,
                }

            result = self.refresh_accounts(
                stale_tokens[: self._POOL_HEALTH_REFRESH_BATCH_SIZE],
                remove_invalid=False,
            )
            refreshed += int(result.get("refreshed") or 0)
            refresh_errors.extend(result.get("errors") or [])

    @staticmethod
    def _account_payload_token(item: dict) -> str:
        return str(item.get("access_token") or item.get("accessToken") or "").strip()

    @staticmethod
    def _prepare_account_payload(item: dict) -> dict | None:
        if not isinstance(item, dict):
            return None
        access_token = AccountService._account_payload_token(item)
        if not access_token:
            return None
        payload = dict(item)
        payload.pop("accessToken", None)
        payload["access_token"] = access_token
        # CPA/Codex 导出文件里的 `type=codex` 是导出格式，不是号池套餐类型。
        if str(payload.get("type") or "").strip().lower() == "codex":
            payload["export_type"] = "codex"
            payload["source_type"] = "codex"
            payload.pop("type", None)
        if str(payload.get("export_type") or "").strip().lower() == "codex":
            payload["source_type"] = "codex"
        if payload.get("plan_type") and not payload.get("type"):
            payload["type"] = str(payload.get("plan_type") or "").strip()
        return payload

    def add_account_items(self, items: list[dict], return_items: bool = True) -> dict:
        payloads = [
            payload
            for item in items
            if (payload := self._prepare_account_payload(item)) is not None
        ]
        return self._add_account_payloads(payloads, return_items=return_items)

    def add_accounts(self, tokens: list[str], source_type: str = "web", return_items: bool = True) -> dict:
        tokens = list(dict.fromkeys(token for token in tokens if token))
        if not tokens:
            return {"added": 0, "skipped": 0, "items": self.list_accounts() if return_items else []}
        return self._add_account_payloads([
            {"access_token": token, "source_type": self._normalize_source_type(source_type)}
            for token in tokens
        ], return_items=return_items)

    def _add_account_payloads(self, payloads: list[dict], return_items: bool = True) -> dict:
        deduped: dict[str, dict] = {}
        for payload in payloads:
            if not isinstance(payload, dict):
                continue
            access_token = self._account_payload_token(payload)
            if not access_token:
                continue
            current = deduped.get(access_token, {})
            deduped[access_token] = {**current, **payload, "access_token": access_token}

        if not deduped:
            return {"added": 0, "skipped": 0, "items": self.list_accounts() if return_items else []}

        with self._lock:
            added = 0
            skipped = 0
            for access_token, payload in deduped.items():
                current = self._accounts.get(access_token)
                if current is None:
                    added += 1
                    self._cumulative_total += 1
                    self._save_cumulative_total()
                    current = {"created_at": self._now()}
                else:
                    skipped += 1
                incoming = dict(payload)
                if not incoming.get("created_at"):
                    incoming.pop("created_at", None)
                account = self._normalize_account(
                    {
                        **current,
                        **incoming,
                        "access_token": access_token,
                        "type": str(incoming.get("type") or current.get("type") or "free"),
                    }
                )
                if account is not None:
                    self._accounts[access_token] = account
            self._save_accounts()
            items = [dict(item) for item in self._accounts.values()] if return_items else []
            log_service.add(LOG_TYPE_ACCOUNT, f"新增 {added} 个账号，跳过 {skipped} 个",
                            {"added": added, "skipped": skipped})
        return {"added": added, "skipped": skipped, "items": items}

    def delete_accounts(self, tokens: list[str], return_items: bool = True) -> dict:
        target_set = set(token for token in tokens if token)
        if not target_set:
            return {"removed": 0, "items": self.list_accounts() if return_items else []}
        with self._lock:
            target_set = {self._resolve_access_token_locked(token) for token in target_set if token}
            removed = sum(self._accounts.pop(token, None) is not None for token in target_set)
            for token in target_set:
                self._image_inflight.pop(token, None)
            self._token_aliases = {
                old: new
                for old, new in self._token_aliases.items()
                if old not in target_set and new not in target_set
            }
            if removed:
                if self._accounts:
                    self._index %= len(self._accounts)
                else:
                    self._index = 0
                self._save_accounts()
                log_service.add(LOG_TYPE_ACCOUNT, f"删除 {removed} 个账号", {"removed": removed})
            items = [dict(item) for item in self._accounts.values()] if return_items else []
        return {"removed": removed, "items": items}

    def update_account(self, access_token: str, updates: dict, quiet: bool = False) -> dict | None:
        if not access_token:
            return None
        with self._lock:
            access_token = self._resolve_access_token_locked(access_token)
            current = self._accounts.get(access_token)
            if current is None:
                return None
            account = self._normalize_account({**current, **updates, "access_token": access_token})
            if account is None:
                return None
            if account.get("status") == "限流" and config.auto_remove_rate_limited_accounts:
                # 对齐 delete_accounts：清理 inflight / alias，并唤醒等槽位的线程。
                self._accounts.pop(access_token, None)
                self._image_inflight.pop(access_token, None)
                self._token_aliases = {
                    old: new
                    for old, new in self._token_aliases.items()
                    if old != access_token and new != access_token
                }
                if self._accounts:
                    self._index %= len(self._accounts)
                else:
                    self._index = 0
                self._save_accounts()
                self._image_slot_condition.notify_all()
                log_service.add(LOG_TYPE_ACCOUNT, "自动移除额度耗尽账号", {"token": anonymize_token(access_token)})
                return None
            self._accounts[access_token] = account
            self._save_accounts()
            if not quiet:
                log_service.add(LOG_TYPE_ACCOUNT, "更新账号",
                                {"token": anonymize_token(access_token), "status": account.get("status")})
            return dict(account)
        return None

    def _record_refresh_success(self, access_token: str, event: str) -> None:
        now = datetime.now(timezone.utc).isoformat()
        with self._lock:
            access_token = self._resolve_access_token_locked(access_token)
            current = self._accounts.get(access_token)
            if current is None:
                return
            next_item = dict(current)
            next_item["invalid_count"] = 0
            next_item["last_invalid_at"] = None
            next_item["last_refresh_error"] = None
            next_item["last_refresh_error_at"] = None
            next_item["last_remote_checked_at"] = now
            next_item["last_remote_check_attempt_at"] = now
            next_item["last_remote_check_error"] = None
            next_item["last_remote_check_error_at"] = None
            next_item["last_remote_check_event"] = event
            next_item["last_remote_check_result"] = "ok"
            account = self._normalize_account(next_item)
            if account is not None:
                self._accounts[access_token] = account
                # 与 _record_remote_check_error 一致：成功路径也必须落盘，否则重启丢新鲜度。
                self._save_accounts()

    def _record_remote_check_error(
        self,
        access_token: str,
        event: str,
        error: str,
    ) -> None:
        now = datetime.now(timezone.utc).isoformat()
        safe_error = redact_auth_diagnostic(error or "remote check failed")
        with self._lock:
            access_token = self._resolve_access_token_locked(access_token)
            current = self._accounts.get(access_token)
            if current is None:
                return
            next_item = dict(current)
            next_item["last_remote_check_attempt_at"] = now
            next_item["last_remote_check_error"] = safe_error
            next_item["last_remote_check_error_at"] = now
            next_item["last_remote_check_event"] = event
            next_item["last_remote_check_result"] = "error"
            account = self._normalize_account(next_item)
            if account is not None:
                self._accounts[access_token] = account
                self._save_accounts()

    def _record_invalid_token_seen(
        self,
        access_token: str,
        event: str,
        error: str,
    ) -> bool:
        now = datetime.now(timezone.utc)
        safe_error = redact_auth_diagnostic(error or "invalid access token")
        with self._lock:
            access_token = self._resolve_access_token_locked(access_token)
            current = self._accounts.get(access_token)
            if current is None:
                return True
            next_item = dict(current)
            next_item["status"] = "异常"
            next_item["quota"] = 0
            next_item["invalid_count"] = int(next_item.get("invalid_count") or 0) + 1
            next_item["last_invalid_at"] = now.isoformat()
            next_item["last_refresh_error"] = safe_error
            next_item["last_refresh_error_at"] = now.isoformat()
            next_item["last_remote_checked_at"] = now.isoformat()
            next_item["last_remote_check_attempt_at"] = now.isoformat()
            next_item["last_remote_check_error"] = safe_error
            next_item["last_remote_check_error_at"] = now.isoformat()
            next_item["last_remote_check_event"] = event
            next_item["last_remote_check_result"] = "invalid"
            account = self._normalize_account(next_item)
            if account is not None:
                self._accounts[access_token] = account
                self._save_accounts()
            log_service.add(
                LOG_TYPE_ACCOUNT,
                "标记异常账号",
                {"source": event, "token": anonymize_token(access_token), "error": safe_error},
            )
        return True

    def mark_image_result(
        self,
        access_token: str,
        success: bool,
        *,
        failure: "ImageFailure | None" = None,
        quota_consumed: bool | None = None,
        expected_access_token: str | None = None,
        expected_refresh_token: str | None = None,
    ) -> dict | None:
        if not access_token:
            return None
        now = datetime.now(timezone.utc)
        should_verify_after_failure = False
        consumed_quota = success if quota_consumed is None else bool(quota_consumed)
        with self._image_slot_condition:
            access_token = self._resolve_access_token_locked(access_token)
            self._release_image_slot_locked(access_token)
            current = self._accounts.get(access_token)
            if current is None:
                return None
            # expected AT 也走 alias 链，避免 access_token 旋转后 CAS 误拒绝导致静默丢账。
            if expected_access_token is not None:
                expected_resolved = self._resolve_access_token_locked(expected_access_token)
                if access_token != expected_resolved:
                    return dict(current)
            # RT 旋转（keepalive / force refresh）是正常现象，不能据此丢扣额。
            # 只要 access_token（经 alias）指向同一账号即可记账；RT 不匹配只记诊断。
            if expected_refresh_token is not None and (
                str(current.get("refresh_token") or "").strip()
                != str(expected_refresh_token or "").strip()
            ):
                log_service.add(
                    LOG_TYPE_ACCOUNT,
                    "生图结果记账时 refresh_token 已旋转，仍按 access_token 记账",
                    {
                        "token": anonymize_token(access_token),
                        "expected_rt": anonymize_token(str(expected_refresh_token or "")),
                        "current_rt": anonymize_token(str(current.get("refresh_token") or "")),
                    },
                )
            next_item = dict(current)
            next_item["last_used_at"] = now.astimezone().strftime("%Y-%m-%d %H:%M:%S")
            image_quota_unknown = bool(next_item.get("image_quota_unknown"))
            if success:
                next_item["success"] = int(next_item.get("success") or 0) + 1
            if consumed_quota:
                if not image_quota_unknown:
                    current_quota = max(0, int(next_item.get("quota") or 0))
                    next_item["quota"] = max(0, current_quota - 1)
                    if current_quota <= 1:
                        # 本地扣减到 0 只能说明“展示值需要远程刷新”，不能直接证明账号已限流。
                        next_item["image_quota_unknown"] = True
                        next_item["last_quota_estimated_empty_at"] = now.isoformat()
                if next_item.get("status") == "限流":
                    # 如果极端竞态下限流账号仍然成功出图，说明远程额度已恢复。
                    next_item["status"] = "正常"
                    next_item["image_quota_unknown"] = True
            # 仅账号侧可核验失败涨 fail；取消/文本类 failure=None 或 verify=False 不污染号池。
            if not success and failure is not None and failure.verify_account:
                next_item["fail"] = int(next_item.get("fail") or 0) + 1
                next_item["last_remote_check_result"] = "pending"
                next_item["last_remote_check_event"] = "image_failure"
                next_item["last_remote_check_attempt_at"] = now.isoformat()
                should_verify_after_failure = True
            account = self._normalize_account(next_item)
            if account is None:
                return None
            self._accounts[access_token] = account
            self._save_accounts()
            result = dict(account)
            self._image_slot_condition.notify_all()
        if should_verify_after_failure:
            self._schedule_account_refresh_after_image_failure(access_token, force=True)
        return result

    def _release_image_slot_locked(self, access_token: str) -> None:
        token = self._resolve_access_token_locked(access_token)
        current = int(self._image_inflight.get(token, 0))
        if current <= 1:
            self._image_inflight.pop(token, None)
        else:
            self._image_inflight[token] = current - 1

    def release_image_slot(self, access_token: str) -> None:
        if not access_token:
            return
        with self._image_slot_condition:
            self._release_image_slot_locked(access_token)
            self._image_slot_condition.notify_all()

    def _refresh_account_after_image_failure(self, access_token: str) -> None:
        try:
            self.fetch_remote_info(access_token, event="image_failure", remove_invalid=False)
        except Exception as exc:
            log_service.add(
                LOG_TYPE_ACCOUNT,
                "图片失败后核验账号失败",
                {"token": anonymize_token(access_token), "error": str(exc)},
            )

    def _schedule_account_refresh_after_image_failure(self, access_token: str, *, force: bool = False) -> bool:
        if not access_token:
            return False
        now = time.monotonic()
        with self._lock:
            access_token = self._resolve_access_token_locked(access_token)
            with self._image_failure_refresh_lock:
                cutoff = now - self._IMAGE_FAILURE_REFRESH_DEDUP_SECONDS
                self._image_failure_refresh_started_at = {
                    token: started_at
                    for token, started_at in self._image_failure_refresh_started_at.items()
                    if token in self._image_failure_refresh_active or started_at >= cutoff
                }
                active_refresh_token = next(
                    (
                        token for token in self._image_failure_refresh_active
                        if self._resolve_access_token_locked(token) == access_token
                    ),
                    None,
                )
                if access_token in self._image_failure_refresh_pending_set or active_refresh_token is not None:
                    if force and active_refresh_token is not None:
                        self._image_failure_refresh_rerun.add(active_refresh_token)
                    return True
                last_started_at = max(
                    (
                        started_at
                        for token, started_at in self._image_failure_refresh_started_at.items()
                        if self._resolve_access_token_locked(token) == access_token
                    ),
                    default=0.0,
                )
                if not force and now - last_started_at < self._IMAGE_FAILURE_REFRESH_DEDUP_SECONDS:
                    return False
                self._image_failure_refresh_pending.append(access_token)
                self._image_failure_refresh_pending_set.add(access_token)
        self._start_pending_image_failure_refreshes()
        return True

    def _start_pending_image_failure_refreshes(self) -> None:
        while True:
            with self._image_failure_refresh_lock:
                if not self._image_failure_refresh_pending:
                    return
                if len(self._image_failure_refresh_active) >= self._IMAGE_FAILURE_REFRESH_MAX_CONCURRENT:
                    return
                access_token = self._image_failure_refresh_pending.popleft()
                self._image_failure_refresh_pending_set.discard(access_token)
                self._image_failure_refresh_active.add(access_token)
                self._image_failure_refresh_started_at[access_token] = time.monotonic()

            def refresh(token: str = access_token) -> None:
                try:
                    self._refresh_account_after_image_failure(token)
                finally:
                    with self._lock:
                        resolved_token = self._resolve_access_token_locked(token)
                        with self._image_failure_refresh_lock:
                            self._image_failure_refresh_active.discard(token)
                            rerun_requested = token in self._image_failure_refresh_rerun
                            self._image_failure_refresh_rerun.discard(token)
                            if (
                                rerun_requested
                                and resolved_token
                                and resolved_token not in self._image_failure_refresh_pending_set
                            ):
                                self._image_failure_refresh_pending.append(resolved_token)
                                self._image_failure_refresh_pending_set.add(resolved_token)
                    self._start_pending_image_failure_refreshes()

            try:
                executor = ThreadPoolExecutor(max_workers=1)
                executor.submit(refresh)
                executor.shutdown(wait=False)
            except Exception as exc:
                with self._image_failure_refresh_lock:
                    self._image_failure_refresh_active.discard(access_token)
                log_service.add(
                    LOG_TYPE_ACCOUNT,
                    "图片失败后调度核验失败",
                    {"token": anonymize_token(access_token), "error": str(exc)},
                )

    def fetch_remote_info(
        self,
        access_token: str,
        event: str = "fetch_remote_info",
        remove_invalid: bool | None = None,
    ) -> dict[str, Any] | None:
        if not access_token:
            raise ValueError("access_token is required")

        from services.openai_backend_api import InvalidAccessTokenError, OpenAIBackendAPI

        # preflight 仅做「JWT 可解析且临近过期」的机会性续期。
        # remaining=None（非 JWT / 坏 payload）交给 401 后 force 路径或后台 list_expiring，
        # 避免在远程探活前无谓旋转 token、打乱 401→force-refresh 语义。
        active_token = access_token
        try:
            remaining = self._token_expires_in(access_token)
            if remaining is not None and remaining <= self._ACCESS_TOKEN_REFRESH_SKEW_SECONDS:
                active_token = (
                    self.refresh_access_token(access_token, event=f"{event}:preflight") or access_token
                )
        except Exception:
            active_token = access_token
        try:
            with OpenAIBackendAPI(active_token) as backend:
                result = backend.get_user_info()
        except InvalidAccessTokenError as exc:
            try:
                refreshed_token = self.refresh_access_token(
                    active_token, force=True, event=f"{event}:invalid_access_token"
                )
            except Exception:
                # 瞬时失败等同“未刷到新 token”，走下方 invalid 分支。
                refreshed_token = ""
            if refreshed_token and refreshed_token != active_token:
                try:
                    with OpenAIBackendAPI(refreshed_token) as backend:
                        result = backend.get_user_info()
                except InvalidAccessTokenError as retry_exc:
                    self.handle_invalid_token(
                        refreshed_token,
                        event,
                        error=str(retry_exc),
                        remove=remove_invalid,
                    )
                    raise
                except Exception as retry_exc:
                    self._record_remote_check_error(refreshed_token, event, str(retry_exc))
                    raise
                active_token = refreshed_token
            else:
                self.handle_invalid_token(
                    active_token,
                    event,
                    error=str(exc),
                    remove=remove_invalid,
                )
                raise
        except Exception as exc:
            self._record_remote_check_error(active_token, event, str(exc))
            raise
        self._record_refresh_success(active_token, event)
        updated = self.update_account(active_token, result)
        if updated is not None:
            return updated
        # update_account 可能因为“自动移除额度耗尽账号”删除了远程确认限流的账号。
        # 调用方仍需要知道本次预检的真实结果，不能把它混成普通预检失败。
        return {**result, "access_token": active_token, "_removed_after_refresh": True}

    # ---- 刷新进度追踪 ----

    def init_refresh_progress(self, progress_id: str, total: int) -> None:
        """初始化刷新进度记录。"""
        with self._refresh_progress_lock:
            self._refresh_progress[progress_id] = {
                "total": total,
                "processed": 0,
                "done": False,
                "error": None,
                "status_counts": {"正常": 0, "限流": 0, "异常": 0, "禁用": 0},
                "total_quota": 0,
            }

    def update_refresh_progress(self, progress_id: str, token: str) -> None:
        """刷新单个账号后，更新进度计数。"""
        account = self.get_account(token)
        status = str(account.get("status") or "正常").strip() if account else "异常"
        quota = max(0, int(account.get("quota") or 0)) if account else 0

        with self._refresh_progress_lock:
            progress = self._refresh_progress.get(progress_id)
            if progress is None:
                return
            progress["processed"] += 1
            progress["status_counts"][status] = progress["status_counts"].get(status, 0) + 1
            progress["total_quota"] += quota

    def finish_refresh_progress(self, progress_id: str, result: dict | None = None, error: str | None = None) -> None:
        """标记刷新完成。"""
        with self._refresh_progress_lock:
            progress = self._refresh_progress.get(progress_id)
            if progress is None:
                return
            progress["done"] = True
            progress["result"] = result
            if error:
                progress["error"] = redact_auth_diagnostic(error)

    def get_refresh_progress(self, progress_id: str) -> dict | None:
        """查询刷新进度。"""
        with self._refresh_progress_lock:
            progress = self._refresh_progress.get(progress_id)
            return dict(progress) if progress else None

    def clean_refresh_progress(self, progress_id: str) -> None:
        """清理过期进度记录。"""
        with self._refresh_progress_lock:
            self._refresh_progress.pop(progress_id, None)
    def refresh_accounts(
        self,
        access_tokens: list[str],
        progress_id: str | None = None,
        remove_invalid: bool | None = None,
    ) -> dict[str, Any]:
        access_tokens = list(dict.fromkeys(token for token in access_tokens if token))
        if not access_tokens:
            items = self.list_accounts()
            result = {"refreshed": 0, "errors": [], "items": items}
            if progress_id:
                self.finish_refresh_progress(progress_id, result)
            return result

        refreshed = 0
        errors = []
        max_workers = min(10, len(access_tokens))

        if progress_id:
            self.init_refresh_progress(progress_id, len(access_tokens))

        executor = ThreadPoolExecutor(max_workers=max_workers)
        try:
            futures = {
                executor.submit(self.fetch_remote_info, token, "refresh_accounts", remove_invalid): token
                for token in access_tokens
            }
            for future in as_completed(futures):
                token = futures[future]
                try:
                    account = future.result()
                except (KeyboardInterrupt, SystemExit):
                    executor.shutdown(wait=False, cancel_futures=True)
                    raise
                except Exception as exc:
                    error_str = redact_auth_diagnostic(exc)
                    # TLS/代理连接错误是网络问题，不计入账号失败
                    from services.protocol.conversation import is_tls_connection_error
                    if not is_tls_connection_error(error_str):
                        errors.append({"token": anonymize_token(token), "error": error_str})
                else:
                    if account is not None:
                        refreshed += 1

                if progress_id:
                    self.update_refresh_progress(progress_id, token)
        except (KeyboardInterrupt, SystemExit):
            if progress_id:
                self.finish_refresh_progress(progress_id, error="cancelled")
            executor.shutdown(wait=False, cancel_futures=True)
            raise
        else:
            executor.shutdown(wait=True, cancel_futures=True)

        result = {
            "refreshed": refreshed,
            "errors": errors,
            "items": self.list_accounts(),
        }

        if progress_id:
            self.finish_refresh_progress(progress_id, result)

        return result

    def build_export_items(self, access_tokens: list[str] | None = None) -> list[dict[str, str]]:
        target_tokens = set(token for token in (access_tokens or []) if token)
        with self._lock:
            accounts = [
                dict(item)
                for item in self._accounts.values()
                if not target_tokens or str(item.get("access_token") or "") in target_tokens
            ]

        items: list[dict[str, str]] = []
        for account in accounts:
            access_token = str(account.get("access_token") or "").strip()
            refresh_token = str(account.get("refresh_token") or "").strip()
            id_token = str(account.get("id_token") or "").strip()
            if not access_token or not refresh_token or not id_token:
                continue

            access_payload = self._decode_jwt_payload(access_token)
            id_payload = self._decode_jwt_payload(id_token)
            auth_claim = access_payload.get("https://api.openai.com/auth")
            auth_claim = auth_claim if isinstance(auth_claim, dict) else {}
            profile_claim = access_payload.get("https://api.openai.com/profile")
            profile_claim = profile_claim if isinstance(profile_claim, dict) else {}

            email = (
                str(account.get("email") or "").strip()
                or str(profile_claim.get("email") or "").strip()
                or str(id_payload.get("email") or "").strip()
            )
            account_id = (
                str(account.get("account_id") or "").strip()
                or str(auth_claim.get("chatgpt_account_id") or "").strip()
                or str(account.get("user_id") or "").strip()
            )
            item = {
                "type": str(account.get("export_type") or "codex"),
                "email": email,
                "account_id": account_id,
                "access_token": access_token,
                "refresh_token": refresh_token,
                "id_token": id_token,
                "expired": self._timestamp_to_iso(access_payload.get("exp")),
                "last_refresh": self._timestamp_to_iso(access_payload.get("iat")),
            }
            password = str(account.get("password") or "").strip()
            if password:
                item["password"] = password
            items.append(item)
        return items

    def get_stats(self) -> dict:
        with self._lock:
            items = list(self._accounts.values())
        total = len(items)
        active = sum(1 for a in items if a.get("status") == "正常")
        limited = sum(1 for a in items if a.get("status") == "限流")
        abnormal = sum(1 for a in items if a.get("status") == "异常")
        disabled = sum(1 for a in items if a.get("status") == "禁用")
        normal_items = [a for a in items if a.get("status") == "正常"]
        total_quota = sum(max(0, int(a.get("quota") or 0)) for a in normal_items)
        unlimited = sum(1 for a in normal_items if self._is_unlimited_image_quota_account(a))
        unknown_quota = sum(
            1
            for a in normal_items
            if (
                bool(a.get("image_quota_unknown"))
                or (not bool(a.get("image_quota_unknown")) and max(0, int(a.get("quota") or 0)) <= 0)
            )
            and not self._is_unlimited_image_quota_account(a)
        )
        total_success = sum(int(a.get("success") or 0) for a in items)
        total_fail = sum(int(a.get("fail") or 0) for a in items)
        by_type = {}
        for a in items:
            t = a.get("type", "unknown")
            by_type[t] = by_type.get(t, 0) + 1
        return {
            "total": total,
            "cumulative_total": self._cumulative_total,
            "active": active,
            "limited": limited,
            "abnormal": abnormal,
            "disabled": disabled,
            "total_quota": total_quota,
            "unlimited_quota_count": unlimited,
            "unknown_quota_count": unknown_quota,
            "total_success": total_success,
            "total_fail": total_fail,
            "by_type": by_type,
        }

    def account_health(self) -> dict:
        stats = self.get_stats()
        return {
            "healthy": stats["active"] > 0 or stats["unlimited_quota_count"] > 0,
            "status": "ok" if stats["active"] > 0 else "degraded",
            **stats,
        }


account_service = AccountService(config.get_storage_backend())
