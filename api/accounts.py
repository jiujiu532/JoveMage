from __future__ import annotations

import asyncio
import io
import json
import re
import uuid
import zipfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from typing import Any, Literal

from fastapi import APIRouter, Header, HTTPException, Query
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import Response
from pydantic import BaseModel, Field

from services.auth_service import auth_service

from api.support import (
    require_admin,
    sanitize_cpa_pool,
    sanitize_cpa_pools,
    sanitize_sub2api_server,
    sanitize_sub2api_servers,
)
from services.account_service import account_service
from services.backends.firefly_auth import decode_jwt_account_id, refresh_access_token
from services.channel_usage_service import channel_usage_service
from services.config import config
from services.cpa_service import cpa_config, cpa_import_service, list_remote_files
from services.log_service import LOG_TYPE_ACCOUNT, log_service
from services.task_manager import task_manager
from services.register.openai_register import (
    _reconstruct_mailbox as _openai_reconstruct_mailbox,
    relogin as _openai_relogin,
)
from services.oauth_login_service import OAuthLoginError, oauth_login_service
from services.sub2api_service import (
    list_remote_accounts as sub2api_list_remote_accounts,
    list_remote_groups as sub2api_list_remote_groups,
    sub2api_config,
    sub2api_import_service,
)
from utils.diagnostics import redact_auth_diagnostic
from utils.helper import anonymize_token

# 账号批量任务分批大小：刷新/巡检/删除统一 20
_INSPECT_BATCH_SIZE = 20
_ACCOUNT_BATCH_SIZE = 20
_LIGHT_TIER_MAX = 50


class ReloginRequest(BaseModel):
    access_token: str = ""


class ReloginBatchRequest(BaseModel):
    tokens: list[str] = Field(default_factory=list)
    tier: Literal["light", "heavy"] | None = None


class ReloginPrecheckRequest(BaseModel):
    tokens: list[str] = Field(default_factory=list)


class AccountInspectRequest(BaseModel):
    """一键巡检：scope 决定用哪些筛选字段。"""

    scope: Literal["filter", "channel", "all"] = "filter"
    keyword: str = ""
    status: str = "all"
    group_id: str = "all"
    source_type: str = "all"


class UserKeyCreateRequest(BaseModel):
    name: str = ""


class UserKeyUpdateRequest(BaseModel):
    name: str | None = None
    enabled: bool | None = None
    key: str | None = None


class AccountCreateRequest(BaseModel):
    tokens: list[str] = Field(default_factory=list)
    accounts: list[dict[str, Any]] = Field(default_factory=list)
    refresh: bool = True
    return_items: bool = True


class AccountDeleteRequest(BaseModel):
    tokens: list[str] = Field(default_factory=list)
    # selected=勾选；filter/channel/all=顶栏范围（影响档位判定）
    scope: Literal["selected", "filter", "channel", "all"] | None = None
    tier: Literal["light", "heavy"] | None = None
    # True → 走 account_delete 后台任务；False → 同步删除（兼容旧前端）
    as_task: bool = False


class AccountImportCleanupRequest(BaseModel):
    access_tokens: list[str] = Field(default_factory=list)
    remove: bool = False


class AccountRefreshRequest(BaseModel):
    access_tokens: list[str] = Field(default_factory=list)
    # selected=勾选；filter/channel/all=顶栏范围（影响档位判定）
    scope: Literal["selected", "filter", "channel", "all"] | None = None
    tier: Literal["light", "heavy"] | None = None


class AccountExportRequest(BaseModel):
    access_tokens: list[str] = Field(default_factory=list)
    format: Literal["json", "zip"] = "json"


class AccountUpdateRequest(BaseModel):
    access_token: str = ""
    type: str | None = None
    source_type: str | None = None
    status: str | None = None
    quota: int | None = None
    proxy: str | None = None
    group_id: str | None = None
    cookie: str | None = None


class AccountBatchUpdateRequest(BaseModel):
    access_tokens: list[str] = Field(default_factory=list)
    status: str | None = None
    # enable|disable|reset：任务化时决定 task_type；未传则由 status 推导
    action: Literal["enable", "disable", "reset"] | None = None
    tier: Literal["light", "heavy"] | None = None
    # True → 走 account_enable/disable/reset 后台任务；False → 同步写状态（兼容旧前端）
    as_task: bool = False


class AccountGroupBindRequest(BaseModel):
    access_tokens: list[str] = Field(default_factory=list)
    group_id: str = ""


class AccountGroupRequest(BaseModel):
    id: str = ""
    name: str = ""
    proxy: str = ""
    proxy_group_id: str = ""
    enabled: bool = True
    notes: str = ""
    create_only: bool = False


class CPAPoolCreateRequest(BaseModel):
    name: str = ""
    base_url: str = ""
    secret_key: str = ""


class CPAPoolUpdateRequest(BaseModel):
    name: str | None = None
    base_url: str | None = None
    secret_key: str | None = None


class CPAImportRequest(BaseModel):
    names: list[str] = Field(default_factory=list)


class Sub2APIServerCreateRequest(BaseModel):
    name: str = ""
    base_url: str = ""
    email: str = ""
    password: str = ""
    api_key: str = ""
    group_id: str = ""


class Sub2APIServerUpdateRequest(BaseModel):
    name: str | None = None
    base_url: str | None = None
    email: str | None = None
    password: str | None = None
    api_key: str | None = None
    group_id: str | None = None


class Sub2APIImportGroupBinding(BaseModel):
    remote_group_id: str = ""
    name: str = ""
    account_ids: list[str] = Field(default_factory=list)


class Sub2APIImportRequest(BaseModel):
    account_ids: list[str] = Field(default_factory=list)
    group_bindings: list[Sub2APIImportGroupBinding] = Field(default_factory=list)
    create_account_groups: bool = True


class OAuthLoginStartRequest(BaseModel):
    """起始 OAuth 桥。email_hint 可选，仅用于让 OpenAI 登录页预填邮箱。"""
    email_hint: str = ""


class OAuthLoginFinishRequest(BaseModel):
    """提交 callback。callback 既可以是完整 URL 也可以只填 code。"""
    session_id: str = ""
    callback: str = ""


def _account_payload_token(item: dict[str, Any]) -> str:
    return str(item.get("access_token") or item.get("accessToken") or "").strip()


def _unique_tokens(tokens: list[str]) -> list[str]:
    return list(dict.fromkeys(str(token or "").strip() for token in tokens if str(token or "").strip()))


def _normalize_create_account_payload(item: dict[str, Any]) -> dict[str, Any]:
    """规范化创建账号 payload；Firefly cookie-only 时先走 IMS 刷出 access_token。"""
    payload = dict(item)
    source_type = _clean_text(payload.get("source_type")).lower()
    cookie = _clean_text(payload.get("cookie"))
    access_token = _account_payload_token(payload)

    if source_type != "firefly":
        return payload

    payload["source_type"] = "firefly"
    if not _clean_text(payload.get("type")):
        payload["type"] = "firefly"
    if cookie:
        payload["cookie"] = cookie

    if not access_token:
        if not cookie:
            raise ValueError("Firefly 账号需要 cookie 或 access_token")

        try:
            refreshed = refresh_access_token(
                cookie,
                proxy=_clean_text(payload.get("proxy")) or None,
            )
        except Exception as exc:
            raise RuntimeError(f"Firefly cookie 换取 access_token 失败: {exc}") from exc

        access_token = _clean_text(refreshed.get("access_token") if isinstance(refreshed, dict) else "")
        if not access_token:
            raise RuntimeError("Firefly cookie 换取 access_token 失败: 响应缺少 access_token")

    # cookie 换 token 与 token-only 都 decode Adobe id；实体钉选只比 account_id
    payload["access_token"] = access_token
    account_id = decode_jwt_account_id(access_token)
    if account_id:
        if not _clean_text(payload.get("user_id")):
            payload["user_id"] = account_id
        if not _clean_text(payload.get("account_id")):
            payload["account_id"] = account_id
    return payload


def _account_matches_source_type(account: dict[str, Any], source_type: str) -> bool:
    needle = _clean_text(source_type).lower()
    if not needle or needle == "all":
        return True
    current = _clean_text(account.get("source_type")).lower()
    if needle == "firefly":
        return current == "firefly"
    if needle == "chatgpt":
        return current != "firefly"
    return current == needle


def _download_timestamp() -> str:
    return datetime.now().strftime("%Y%m%d-%H%M%S")


def _safe_export_name(value: str, fallback: str) -> str:
    clean = re.sub(r"[^A-Za-z0-9._-]+", "-", value.strip()).strip("-._")
    return (clean or fallback)[:80]


def _clean_text(value: object) -> str:
    return str(value or "").strip()


def _slug_id(value: object) -> str:
    raw = _clean_text(value).lower()
    chars: list[str] = []
    for char in raw:
        if char.isalnum() or char in {"-", "_"}:
            chars.append(char)
        elif char.isspace():
            chars.append("-")
    return "".join(chars).strip("-_")


def _config_dict_list(key: str) -> list[dict[str, Any]]:
    raw = config.get().get(key)
    if not isinstance(raw, list):
        return []
    return [dict(item) for item in raw if isinstance(item, dict)]


def _account_group_id(value: object) -> str:
    return _slug_id(value)


def _account_group_proxy_reference(proxy: object, proxy_group_id: object = "") -> str:
    raw = _clean_text(proxy)
    if raw.lower() == "global":
        return ""
    if raw:
        return raw
    legacy_group_id = _clean_text(proxy_group_id)
    return f"group:{legacy_group_id}" if legacy_group_id else ""


def _proxy_group_id_from_reference(proxy: object) -> str:
    raw = _clean_text(proxy)
    if raw.lower().startswith("group:"):
        return _clean_text(raw.split(":", 1)[1])
    return ""


def _account_group_payload(groups: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    accounts = account_service.list_accounts()
    counts: dict[str, int] = {}
    for account in accounts:
        group_id = _clean_text(account.get("group_id"))
        if group_id:
            counts[group_id] = counts.get(group_id, 0) + 1
    normalized_groups = []
    for group in groups if groups is not None else _config_dict_list("account_groups"):
        group_id = _account_group_id(group.get("id"))
        if not group_id:
            continue
        proxy = _account_group_proxy_reference(group.get("proxy"), group.get("proxy_group_id"))
        normalized_groups.append(
            {
                "id": group_id,
                "name": _clean_text(group.get("name")) or group_id,
                "proxy": proxy,
                "proxy_group_id": _proxy_group_id_from_reference(proxy),
                "enabled": bool(group.get("enabled", True)),
                "notes": _clean_text(group.get("notes")),
                "account_count": counts.get(group_id, 0),
            }
        )
    return {
        "groups": normalized_groups,
        "proxy_groups": _config_dict_list("proxy_groups"),
    }


def _upsert_account_group(body: AccountGroupRequest) -> dict[str, Any]:
    group_id = _account_group_id(body.id or body.name)
    if not group_id:
        raise ValueError("account group id is required")
    groups = _config_dict_list("account_groups")
    exists = any(_account_group_id(group.get("id")) == group_id for group in groups)
    if body.create_only and exists:
        raise ValueError("account group already exists")
    proxy = _account_group_proxy_reference(body.proxy, body.proxy_group_id)
    item = {
        "id": group_id,
        "name": body.name.strip() or group_id,
        "proxy": proxy,
        "proxy_group_id": _proxy_group_id_from_reference(proxy),
        "enabled": body.enabled,
        "notes": body.notes.strip(),
    }
    next_groups = [group for group in groups if _account_group_id(group.get("id")) != group_id]
    next_groups.append(item)
    config.update({"account_groups": next_groups})
    return {"group": item, **_account_group_payload(_config_dict_list("account_groups"))}


def _status_matches_filter(account: dict[str, Any], status_filter: str) -> bool:
    status_filter = status_filter.strip().lower()
    if not status_filter or status_filter == "all":
        return True
    status = _clean_text(account.get("status"))
    status_map = {
        "normal": "\u6b63\u5e38",
        "limited": "\u9650\u6d41",
        "abnormal": "\u5f02\u5e38",
        "disabled": "\u7981\u7528",
    }
    expected = status_map.get(status_filter)
    return status == expected if expected else status.lower() == status_filter


def _account_matches_keyword(account: dict[str, Any], keyword: str) -> bool:
    needle = keyword.strip().lower()
    if not needle:
        return True
    fields = (
        account.get("access_token"),
        account.get("email"),
        account.get("user_id"),
        account.get("type"),
        account.get("source_type"),
        account.get("status"),
        account.get("proxy"),
        account.get("group_id"),
    )
    return any(needle in _clean_text(value).lower() for value in fields)


def _account_matches_group(account: dict[str, Any], group_id: str) -> bool:
    group_id = group_id.strip()
    if not group_id or group_id == "all":
        return True
    current = _clean_text(account.get("group_id"))
    if group_id == "__ungrouped__":
        return not current
    return current == group_id


def _is_demo_account(account: dict[str, Any]) -> bool:
    return bool(account.get("is_demo"))


def _filter_accounts(
        *,
        keyword: str = "",
        status: str = "all",
        group_id: str = "all",
        source_type: str = "all",
        exclude_demo: bool = False,
        exclude_firefly: bool = False,
        items: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """与 `_accounts_page` 同款筛选；可选排除 demo / Firefly。"""
    source = items if items is not None else account_service.list_accounts()
    filtered: list[dict[str, Any]] = []
    for item in source:
        if exclude_demo and _is_demo_account(item):
            continue
        if exclude_firefly and _account_matches_source_type(item, "firefly"):
            continue
        if not _account_matches_keyword(item, keyword):
            continue
        if not _status_matches_filter(item, status):
            continue
        if not _account_matches_group(item, group_id):
            continue
        if not _account_matches_source_type(item, source_type):
            continue
        filtered.append(item)
    return filtered


def _accounts_page(
        *,
        page: int,
        page_size: int,
        keyword: str,
        status: str,
        group_id: str,
        source_type: str = "all",
) -> dict[str, Any]:
    items = account_service.list_accounts()
    filtered = _filter_accounts(
        keyword=keyword,
        status=status,
        group_id=group_id,
        source_type=source_type,
        items=items,
    )
    safe_page = max(1, page)
    safe_page_size = max(1, min(page_size, 500))
    start = (safe_page - 1) * safe_page_size
    end = start + safe_page_size
    return {
        "items": filtered[start:end],
        "total": len(filtered),
        "all_total": len(items),
        "page": safe_page,
        "page_size": safe_page_size,
    }


def _resolve_inspect_filter_params(
        scope: str,
        *,
        keyword: str = "",
        status: str = "all",
        group_id: str = "all",
        source_type: str = "all",
) -> dict[str, str]:
    """按 scope 收敛筛选参数。

    - filter：全部筛选参数
    - channel：仅 source_type（=all 时等价 all）
    - all：无过滤
    """
    normalized = (scope or "filter").strip().lower()
    if normalized == "all":
        return {"keyword": "", "status": "all", "group_id": "all", "source_type": "all"}
    if normalized == "channel":
        st = _clean_text(source_type) or "all"
        return {"keyword": "", "status": "all", "group_id": "all", "source_type": st}
    return {
        "keyword": keyword or "",
        "status": status or "all",
        "group_id": group_id or "all",
        "source_type": source_type or "all",
    }


def _classify_removed_account(
        before_status: str,
        before_result: str,
) -> str:
    """账号消失后的计数口径（简单可解释）。

    - 执行前 status=="异常" → removed_invalid
    - 执行前 status=="限流" → removed_quota_exhausted
    - 其它消失看 last_remote_check_result：
      invalid → removed_invalid；exhausted → removed_quota_exhausted
    - 无信息 → removed_invalid
    """
    status = (before_status or "").strip()
    if status == "异常":
        return "removed_invalid"
    if status == "限流":
        return "removed_quota_exhausted"
    result = (before_result or "").strip().lower()
    if result == "exhausted":
        return "removed_quota_exhausted"
    if result == "invalid":
        return "removed_invalid"
    return "removed_invalid"


def _empty_inspect_stats() -> dict[str, Any]:
    return {
        "total": 0,
        "processed": 0,
        "ok": 0,
        "removed_invalid": 0,
        "removed_quota_exhausted": 0,
        "marked_invalid": 0,
        "marked_rate_limited": 0,
        "refresh_failed": 0,
        "stopped": False,
        "errors": [],
    }


def _resolve_account_task_tier(
        tokens: list[str],
        *,
        scope: str | None = None,
        tier: str | None = None,
) -> str:
    """档位判定：显式 tier 优先；否则 scope 为 filter/channel/all 或数量 >50 → heavy。"""
    if tier in ("light", "heavy"):
        return tier
    normalized_scope = (scope or "").strip().lower()
    if normalized_scope in ("filter", "channel", "all"):
        return "heavy"
    if len(tokens) > _LIGHT_TIER_MAX:
        return "heavy"
    return "light"


def _bump_task_batch_progress(
        task,
        *,
        progress: int,
        batch_remaining: int,
        current_batch_size: int = 0,
        current_batch_done: int = 0,
        **result_updates: Any,
) -> None:
    """统一进度上报：bump 总进度 + bump_batch_progress 本批进度。

    基建签名：bump_batch_progress(current_batch_size, current_batch_done)；
    batch_remaining 由属性推导，无需写入。
    """
    size = int(current_batch_size or 0)
    done = int(current_batch_done or 0)
    # 若调用方只给了 batch_remaining，反推 done
    if size > 0 and done == 0 and batch_remaining is not None:
        try:
            remaining = max(0, int(batch_remaining))
            if remaining <= size:
                done = size - remaining
        except (TypeError, ValueError):
            pass
    if hasattr(task, "bump_batch_progress"):
        try:
            task.bump_batch_progress(size, done)
        except TypeError:
            # 兼容其它签名
            try:
                task.bump_batch_progress(
                    current_batch_size=size,
                    current_batch_done=done,
                )
            except TypeError:
                pass
    task.bump(progress=progress, **result_updates)


def _submit_account_task(
        task_type: str,
        total: int,
        fn,
        *,
        tier: str = "light",
):
    """提交账号类任务；优先带 tier（backend-infra），否则回落旧签名。"""
    try:
        return task_manager.submit(task_type, total, fn, tier=tier)
    except TypeError:
        task = task_manager.submit(task_type, total, fn)
        if hasattr(task, "tier"):
            try:
                task.tier = tier
            except Exception:
                pass
        return task


def _run_account_refresh(task, tokens: list[str], *, scope: str | None = None) -> None:
    """刷新任务体：按 20 分批调 refresh_accounts，批边界检查 cancel。"""
    tokens = list(dict.fromkeys(t for t in tokens if t))
    total = len(tokens)
    refreshed = 0
    errors: list[Any] = []
    processed = 0
    stopped = False

    log_service.add(
        LOG_TYPE_ACCOUNT,
        "账号刷新任务开始",
        {
            "scope": scope or "selected",
            "total": total,
            "sample_tokens": [anonymize_token(t) for t in tokens[:5]],
        },
    )

    try:
        for batch_start in range(0, total, _ACCOUNT_BATCH_SIZE):
            if task.cancel_requested:
                stopped = True
                break
            batch = tokens[batch_start: batch_start + _ACCOUNT_BATCH_SIZE]
            batch_size = len(batch)
            # 批开始：本批剩余 = 整批
            _bump_task_batch_progress(
                task,
                progress=processed,
                batch_remaining=batch_size,
                current_batch_size=batch_size,
                current_batch_done=0,
                refreshed=refreshed,
                stopped=stopped,
            )
            # 整批交给 refresh_accounts（内部 ThreadPool 并发）
            # 批级进度：整批完成后一次 bump；批内精细进度依赖 refresh 回调，此处按批更新并留 TODO
            # TODO(backend-infra): 若 refresh_accounts 支持 per-token 回调，改为每完成 1 个更新 batch_remaining
            try:
                result = account_service.refresh_accounts(batch, progress_id=None)
            except Exception as exc:
                safe = redact_auth_diagnostic(exc)
                errors.append(safe)
                # 整批失败仍计入 processed，避免卡死
                processed += batch_size
                _bump_task_batch_progress(
                    task,
                    progress=processed,
                    batch_remaining=0,
                    current_batch_size=batch_size,
                    current_batch_done=batch_size,
                    refreshed=refreshed,
                    stopped=stopped,
                    errors=errors[:50],
                )
                continue

            batch_refreshed = int(result.get("refreshed") or 0)
            batch_errors = result.get("errors") or []
            refreshed += batch_refreshed
            if isinstance(batch_errors, list):
                errors.extend(batch_errors)
            processed += batch_size
            _bump_task_batch_progress(
                task,
                progress=processed,
                batch_remaining=0,
                current_batch_size=batch_size,
                current_batch_done=batch_size,
                refreshed=refreshed,
                stopped=stopped,
                errors=errors[:50],
            )
    except Exception as exc:
        safe = redact_auth_diagnostic(exc)
        log_service.add(
            LOG_TYPE_ACCOUNT,
            "账号刷新任务失败",
            {"scope": scope or "selected", "total": total, "error": safe},
        )
        task.fail(safe)
        return

    summary = {
        "total": total,
        "processed": processed,
        "refreshed": refreshed,
        "errors": errors[:50],
        "stopped": stopped,
        "scope": scope or "selected",
    }
    log_service.add(
        LOG_TYPE_ACCOUNT,
        "账号刷新任务已停止" if stopped else "账号刷新任务完成",
        summary,
    )
    if stopped:
        task.result.update(summary)
        task.cancel()
    else:
        task.complete(**summary)


def _run_account_delete(task, tokens: list[str], *, scope: str | None = None) -> None:
    """删除任务体：按 20 分批 delete_accounts，批边界检查 cancel。"""
    tokens = list(dict.fromkeys(t for t in tokens if t))
    total = len(tokens)
    removed = 0
    processed = 0
    stopped = False
    errors: list[str] = []

    log_service.add(
        LOG_TYPE_ACCOUNT,
        "账号删除任务开始",
        {
            "scope": scope or "selected",
            "total": total,
            "sample_tokens": [anonymize_token(t) for t in tokens[:5]],
        },
    )

    try:
        for batch_start in range(0, total, _ACCOUNT_BATCH_SIZE):
            if task.cancel_requested:
                stopped = True
                break
            batch = tokens[batch_start: batch_start + _ACCOUNT_BATCH_SIZE]
            batch_size = len(batch)
            _bump_task_batch_progress(
                task,
                progress=processed,
                batch_remaining=batch_size,
                current_batch_size=batch_size,
                current_batch_done=0,
                removed=removed,
                stopped=stopped,
            )
            try:
                result = account_service.delete_accounts(batch, return_items=False)
                batch_removed = int(result.get("removed") or 0)
                removed += batch_removed
            except Exception as exc:
                safe = redact_auth_diagnostic(exc)
                errors.append(safe)
            processed += batch_size
            # 删除是同步整批，批结束后剩余清零
            _bump_task_batch_progress(
                task,
                progress=processed,
                batch_remaining=0,
                current_batch_size=batch_size,
                current_batch_done=batch_size,
                removed=removed,
                stopped=stopped,
                errors=errors[:50],
            )
    except Exception as exc:
        safe = redact_auth_diagnostic(exc)
        log_service.add(
            LOG_TYPE_ACCOUNT,
            "账号删除任务失败",
            {"scope": scope or "selected", "total": total, "error": safe},
        )
        task.fail(safe)
        return

    summary = {
        "total": total,
        "processed": processed,
        "removed": removed,
        "errors": errors[:50],
        "stopped": stopped,
        "scope": scope or "selected",
    }
    log_service.add(
        LOG_TYPE_ACCOUNT,
        "账号删除任务已停止" if stopped else "账号删除任务完成",
        summary,
    )
    if stopped:
        task.result.update(summary)
        task.cancel()
    else:
        task.complete(**summary)


def _run_account_inspect(
        task,
        tokens: list[str],
        *,
        scope: str,
) -> None:
    """巡检任务体：分批探活，对比前后状态汇总报告。

    删除动作完全交给 fetch_remote_info(remove_invalid=None) → 配置 auto_remove_*，
    不写第二套删除规则。分批并发模式对齐 refresh_accounts，但保留原始 token 便于统计。

    注意：InvalidAccessTokenError 会在 handle_invalid_token 之后 re-raise，
    所以「抛错」不等于网络失败——需结合事后账号状态判定。
    """
    stats = _empty_inspect_stats()
    stats["total"] = len(tokens)
    errors: list[str] = []

    # 记录执行前快照（status / last_remote_check_result）
    before_snapshot: dict[str, dict[str, str]] = {}
    for token in tokens:
        account = account_service.get_account(token)
        if account is None:
            continue
        before_snapshot[token] = {
            "status": _clean_text(account.get("status")),
            "last_remote_check_result": _clean_text(account.get("last_remote_check_result")),
        }

    log_service.add(
        LOG_TYPE_ACCOUNT,
        "一键巡检开始",
        {
            "scope": scope,
            "total": len(tokens),
            "sample_tokens": [anonymize_token(t) for t in tokens[:5]],
        },
    )

    def _tally_one(token: str, *, raised: bool, error_text: str = "") -> None:
        """按事后状态归类单个账号。

        消失口径（优先执行前 status，再辅以本次是否抛错）：
        - 执行前 status==异常 → removed_invalid
        - 执行前 status==限流 → removed_quota_exhausted
        - 其它：抛错后消失 → removed_invalid（handle_invalid_token 删除）
                 未抛错却消失 → removed_quota_exhausted（auto_remove 额度尽）
                 仍看 last_remote_check_result 兜底
        """
        stats["processed"] += 1
        account = account_service.get_account(token)
        before = before_snapshot.get(token) or {}
        if account is None:
            before_status = before.get("status", "")
            if before_status == "异常":
                stats["removed_invalid"] += 1
            elif before_status == "限流":
                stats["removed_quota_exhausted"] += 1
            elif raised:
                # InvalidAccessToken → handle_invalid_token 删除后 re-raise
                stats["removed_invalid"] += 1
            else:
                # 探活成功但账号被 update_account 因额度尽自动移除
                before_result = before.get("last_remote_check_result", "")
                if before_result == "invalid":
                    stats["removed_invalid"] += 1
                else:
                    stats["removed_quota_exhausted"] += 1
            return

        status = _clean_text(account.get("status"))
        if status == "异常":
            stats["marked_invalid"] += 1
            return
        if status == "限流":
            stats["marked_rate_limited"] += 1
            return
        if raised:
            # 状态未变却抛错 → 网络/上游类，不删
            stats["refresh_failed"] += 1
            if error_text:
                errors.append(f"{anonymize_token(token)}: {error_text}")
            return
        # 正常 / 禁用 / 其它：禁用参与探活但不删，计入 ok
        stats["ok"] += 1

    try:
        for batch_start in range(0, len(tokens), _INSPECT_BATCH_SIZE):
            # 真停止：每批边界检查取消标志，置位即收尾（当前批已跑完，不再开下一批）
            if task.cancel_requested:
                stats["stopped"] = True
                break
            batch = tokens[batch_start: batch_start + _INSPECT_BATCH_SIZE]
            # 本批开始：重置 batch 进度，供停止中展示「本批剩余」
            task.bump_batch_progress(len(batch), 0)
            max_workers = min(10, len(batch)) or 1
            executor = ThreadPoolExecutor(max_workers=max_workers)
            outcomes: dict[str, tuple[bool, str]] = {}
            try:
                futures = {
                    executor.submit(
                        account_service.fetch_remote_info,
                        token,
                        "inspect",
                        None,  # remove_invalid=None → 读配置
                    ): token
                    for token in batch
                }
                batch_done = 0
                for future in as_completed(futures):
                    token = futures[future]
                    try:
                        future.result()
                        outcomes[token] = (False, "")
                    except Exception as exc:
                        outcomes[token] = (True, redact_auth_diagnostic(exc))
                    batch_done += 1
                    task.bump_batch_progress(len(batch), batch_done)
            finally:
                executor.shutdown(wait=True, cancel_futures=False)

            for token in batch:
                raised, err_text = outcomes.get(token, (True, "missing outcome"))
                _tally_one(token, raised=raised, error_text=err_text)

            task.bump(
                progress=stats["processed"],
                total=stats["total"],
                ok=stats["ok"],
                removed_invalid=stats["removed_invalid"],
                removed_quota_exhausted=stats["removed_quota_exhausted"],
                marked_invalid=stats["marked_invalid"],
                marked_rate_limited=stats["marked_rate_limited"],
                refresh_failed=stats["refresh_failed"],
                stopped=stats["stopped"],
            )
    except Exception as exc:
        safe = redact_auth_diagnostic(exc)
        errors.append(safe)
        stats["errors"] = errors[:50]
        log_service.add(
            LOG_TYPE_ACCOUNT,
            "一键巡检失败",
            {"scope": scope, "total": stats["total"], "error": safe},
        )
        task.fail(safe)
        return

    stats["errors"] = errors[:50]
    stopped = bool(stats.get("stopped"))
    log_service.add(
        LOG_TYPE_ACCOUNT,
        "一键巡检已停止" if stopped else "一键巡检完成",
        {
            "scope": scope,
            "total": stats["total"],
            "processed": stats["processed"],
            "ok": stats["ok"],
            "removed_invalid": stats["removed_invalid"],
            "removed_quota_exhausted": stats["removed_quota_exhausted"],
            "marked_invalid": stats["marked_invalid"],
            "marked_rate_limited": stats["marked_rate_limited"],
            "refresh_failed": stats["refresh_failed"],
            "stopped": stopped,
        },
    )
    if stopped:
        task.result.update(stats)
        task.cancel()
    else:
        task.complete(**stats)


def _precheck_relogin_tokens(tokens: list[str]) -> dict[str, Any]:
    """批量重登预检：与 `_reconstruct_mailbox` 同源判定。"""
    can_tokens: list[str] = []
    skip_reasons: dict[str, int] = {}
    unique = _unique_tokens(tokens)
    for token in unique:
        account = account_service.get_account(token)
        if account is None:
            reason = "无邮箱"
            skip_reasons[reason] = skip_reasons.get(reason, 0) + 1
            continue
        email = _clean_text(account.get("email"))
        if not email:
            reason = "无邮箱"
            skip_reasons[reason] = skip_reasons.get(reason, 0) + 1
            continue
        source_type = _clean_text(account.get("source_type")).lower()
        if source_type == "firefly" or "firefly" in source_type:
            reason = "Firefly 账号不支持重登"
            skip_reasons[reason] = skip_reasons.get(reason, 0) + 1
            continue
        # 纯函数，只读 config，无网络 IO
        mailbox = _openai_reconstruct_mailbox(email)
        if not mailbox:
            reason = "非 AHEM 邮箱"
            skip_reasons[reason] = skip_reasons.get(reason, 0) + 1
            continue
        can_tokens.append(token)
    skip = len(unique) - len(can_tokens)
    return {
        "can": len(can_tokens),
        "skip": skip,
        "skip_reasons": skip_reasons,
        "can_tokens": can_tokens,
    }


def _import_abnormal_tokens(access_tokens: list[str]) -> list[str]:
    tokens = _unique_tokens(access_tokens)
    result: list[str] = []
    seen: set[str] = set()
    for token in tokens:
        account = account_service.get_account(token)
        if not account or not _status_matches_filter(account, "abnormal"):
            continue
        current_token = _clean_text(account.get("access_token")) or token
        if current_token and current_token not in seen:
            seen.add(current_token)
            result.append(current_token)
    return result


def _account_zip_bytes(items: list[dict[str, str]]) -> bytes:
    buf = io.BytesIO()
    used_names: set[str] = set()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as archive:
        for index, item in enumerate(items, start=1):
            raw_name = item.get("email") or item.get("account_id") or f"account-{index:03d}"
            base_name = _safe_export_name(raw_name, f"account-{index:03d}")
            name = base_name
            suffix = 2
            while name in used_names:
                name = f"{base_name}-{suffix}"
                suffix += 1
            used_names.add(name)
            archive.writestr(
                f"{name}.json",
                json.dumps(item, ensure_ascii=False, indent=2) + "\n",
            )
    return buf.getvalue()


def create_router() -> APIRouter:
    router = APIRouter()

    @router.get("/api/auth/users")
    async def list_user_keys(authorization: str | None = Header(default=None)):
        require_admin(authorization)
        return {"items": auth_service.list_keys(role="user")}

    @router.post("/api/auth/users")
    async def create_user_key(body: UserKeyCreateRequest, authorization: str | None = Header(default=None)):
        require_admin(authorization)
        try:
            item, raw_key = auth_service.create_key(role="user", name=body.name)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail={"error": str(exc)}) from exc
        return {"item": item, "key": raw_key, "items": auth_service.list_keys(role="user")}

    @router.post("/api/auth/users/{key_id}")
    async def update_user_key(
            key_id: str,
            body: UserKeyUpdateRequest,
            authorization: str | None = Header(default=None),
    ):
        require_admin(authorization)
        updates = {
            key: value
            for key, value in {
                "name": body.name,
                "enabled": body.enabled,
                "key": body.key,
            }.items()
            if value is not None
        }
        if not updates:
            raise HTTPException(status_code=400, detail={"error": "还没有检测到改动，请修改后再保存"})
        try:
            item = auth_service.update_key(key_id, updates, role="user")
        except ValueError as exc:
            raise HTTPException(status_code=400, detail={"error": str(exc)}) from exc
        if item is None:
            raise HTTPException(status_code=404, detail={"error": "这条用户密钥不存在，可能已经被删除"})
        return {"item": item, "items": auth_service.list_keys(role="user")}

    @router.delete("/api/auth/users/{key_id}")
    async def delete_user_key(key_id: str, authorization: str | None = Header(default=None)):
        require_admin(authorization)
        if not auth_service.delete_key(key_id, role="user"):
            raise HTTPException(status_code=404, detail={"error": "这条用户密钥不存在，可能已经被删除"})
        return {"items": auth_service.list_keys(role="user")}

    @router.get("/api/accounts")
    async def get_accounts(
            page: int = Query(default=1, ge=1),
            page_size: int = Query(default=500, ge=1, le=500),
            keyword: str = "",
            status: str = "all",
            group_id: str = "all",
            source_type: str | None = Query(default=None),
            authorization: str | None = Header(default=None),
    ):
        require_admin(authorization)
        return _accounts_page(
            page=page,
            page_size=page_size,
            keyword=keyword,
            status=status,
            group_id=group_id,
            source_type=source_type or "all",
        )

    @router.get("/api/accounts/ids")
    async def list_account_ids(
            keyword: str = "",
            status: str = "all",
            group_id: str = "all",
            source_type: str = "all",
            authorization: str | None = Header(default=None),
    ):
        """返回全部匹配筛选条件的 access_token（不分页，排除 demo）。"""
        require_admin(authorization)
        filtered = _filter_accounts(
            keyword=keyword,
            status=status,
            group_id=group_id,
            source_type=source_type or "all",
            exclude_demo=True,
        )
        tokens = [
            token
            for item in filtered
            if (token := _clean_text(item.get("access_token")))
        ]
        return {"tokens": tokens, "total": len(tokens)}

    @router.get("/api/accounts/{account_id}/usage")
    async def get_account_usage_profile(
            account_id: str,
            recent_limit: int = Query(default=20, ge=1, le=200),
            channel: str | None = Query(default=None),
            authorization: str | None = Header(default=None),
    ):
        """账号行为档案：今日调用/成功率/credits + 最近流水 + 失败原因分组。

        account_id 与 channel_usage 账本字段对齐（email / account_id / user_id）。
        admin 全量可见。
        """
        require_admin(authorization)
        key = str(account_id or "").strip()
        if not key:
            raise HTTPException(status_code=400, detail={"error": "account_id is required"})
        profile = channel_usage_service.account_profile(
            key,
            recent_limit=recent_limit,
            channel=str(channel or "").strip() or None,
        )
        return profile

    @router.get("/api/account-groups")
    async def list_account_groups(authorization: str | None = Header(default=None)):
        require_admin(authorization)
        return _account_group_payload()

    @router.post("/api/account-groups")
    async def save_account_group(body: AccountGroupRequest, authorization: str | None = Header(default=None)):
        require_admin(authorization)
        try:
            return _upsert_account_group(body)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail={"error": str(exc)}) from exc

    @router.delete("/api/account-groups/{group_id}")
    async def delete_account_group(group_id: str, authorization: str | None = Header(default=None)):
        require_admin(authorization)
        normalized = _account_group_id(group_id)
        groups = _config_dict_list("account_groups")
        next_groups = [group for group in groups if _account_group_id(group.get("id")) != normalized]
        if len(next_groups) == len(groups):
            raise HTTPException(status_code=404, detail={"error": "account group not found"})
        config.update({"account_groups": next_groups})
        for account in account_service.list_accounts():
            if _clean_text(account.get("group_id")) == normalized:
                account_service.update_account(account.get("access_token", ""), {"group_id": ""}, quiet=True)
        return {
            "deleted": normalized,
            **_account_group_payload(_config_dict_list("account_groups")),
            "items": account_service.list_accounts(),
        }

    @router.post("/api/accounts")
    async def create_accounts(body: AccountCreateRequest, authorization: str | None = Header(default=None)):
        require_admin(authorization)
        account_payloads: list[dict[str, Any]] = []
        # 规范化阶段的逐条错误（如单条 Firefly cookie 换 token 失败）。
        # 仅当全部失败、无可入库账号时才 400；否则记入返回 errors，让其余账号正常入库。
        normalize_errors: list[str] = []
        for item in body.accounts:
            if not isinstance(item, dict):
                continue
            try:
                account_payloads.append(_normalize_create_account_payload(item))
            except ValueError as exc:
                normalize_errors.append(str(exc))
            except RuntimeError as exc:
                normalize_errors.append(redact_auth_diagnostic(str(exc)))
        payload_tokens = [_account_payload_token(item) for item in account_payloads]
        tokens = _unique_tokens([*body.tokens, *payload_tokens])
        if not tokens:
            detail = normalize_errors[0] if normalize_errors else "tokens is required"
            raise HTTPException(status_code=400, detail={"error": detail, "errors": normalize_errors})
        if account_payloads:
            result = account_service.add_account_items(account_payloads, return_items=body.return_items)
            payload_token_set = set(_unique_tokens(payload_tokens))
            extra_tokens = [token for token in tokens if token not in payload_token_set]
            if extra_tokens:
                extra_result = account_service.add_accounts(extra_tokens, return_items=body.return_items)
                result["added"] = int(result.get("added") or 0) + int(extra_result.get("added") or 0)
                result["skipped"] = int(result.get("skipped") or 0) + int(extra_result.get("skipped") or 0)
        else:
            result = account_service.add_accounts(tokens, return_items=body.return_items)

        # Firefly 走 IMS，不能用 ChatGPT OAuth 续期；创建后跳过这些 token 的 refresh
        firefly_tokens = {
            token
            for item, token in zip(account_payloads, payload_tokens)
            if token and _clean_text(item.get("source_type")).lower() == "firefly"
        }
        refresh_tokens = [token for token in tokens if token not in firefly_tokens]
        if not body.refresh or not refresh_tokens:
            return {
                **result,
                "refreshed": 0,
                "errors": normalize_errors,
                "items": result.get("items", []) if body.return_items else [],
            }
        refresh_result = account_service.refresh_accounts(
            refresh_tokens,
            remove_invalid=False,
        )
        return {
            **result,
            "refreshed": refresh_result.get("refreshed", 0),
            "errors": [*normalize_errors, *(refresh_result.get("errors", []) or [])],
            "items": refresh_result.get("items", result.get("items", [])) if body.return_items else [],
        }

    @router.delete("/api/accounts")
    async def delete_accounts(body: AccountDeleteRequest, authorization: str | None = Header(default=None)):
        """批量删除账号。

        - 默认同步删除（兼容旧前端循环 bulkDelete）。
        - body.as_task=true 时走 account_delete 后台任务，返回 task_id。
        """
        require_admin(authorization)
        tokens = _unique_tokens(body.tokens)
        if not tokens:
            raise HTTPException(status_code=400, detail={"error": "tokens is required"})

        if not body.as_task:
            return account_service.delete_accounts(tokens, return_items=False)

        tier = _resolve_account_task_tier(tokens, scope=body.scope, tier=body.tier)
        scope = (body.scope or "selected").strip().lower()

        def _run(task) -> None:
            _run_account_delete(task, tokens, scope=scope)

        try:
            task = _submit_account_task("account_delete", len(tokens), _run, tier=tier)
        except RuntimeError as exc:
            raise HTTPException(status_code=409, detail={"error": redact_auth_diagnostic(exc)}) from exc

        return {
            "task_id": task.task_id,
            "total": len(tokens),
            "tier": tier,
            "task_type": "account_delete",
        }

    @router.post("/api/accounts/import-cleanup")
    async def cleanup_imported_abnormal_accounts(
            body: AccountImportCleanupRequest,
            authorization: str | None = Header(default=None),
    ):
        require_admin(authorization)
        tokens = _unique_tokens(body.access_tokens)
        if not tokens:
            raise HTTPException(status_code=400, detail={"error": "access_tokens is required"})
        abnormal_tokens = _import_abnormal_tokens(tokens)
        removed = 0
        if body.remove and abnormal_tokens:
            removed = int(account_service.delete_accounts(abnormal_tokens, return_items=False).get("removed") or 0)
        return {
            "checked": len(tokens),
            "abnormal": len(abnormal_tokens),
            "removed": removed,
        }

    @router.post("/api/accounts/refresh")
    async def refresh_accounts(body: AccountRefreshRequest, authorization: str | None = Header(default=None)):
        """提交账号刷新任务（account_refresh）。

        兼容：仍接受 access_tokens；空列表时刷新全部 token。
        返回 task_id（新）+ progress_id（兼容旧前端轮询，映射到 task_id）。
        """
        require_admin(authorization)
        access_tokens = _unique_tokens(body.access_tokens)
        scope = (body.scope or "").strip().lower() or None
        if not access_tokens:
            # 空列表 → 全量；等同 scope=all
            access_tokens = account_service.list_tokens()
            if scope is None:
                scope = "all"
        if not access_tokens:
            raise HTTPException(status_code=400, detail={"error": "access_tokens is required"})

        tier = _resolve_account_task_tier(access_tokens, scope=scope, tier=body.tier)
        resolved_scope = scope or "selected"

        def _run(task) -> None:
            _run_account_refresh(task, access_tokens, scope=resolved_scope)

        try:
            task = _submit_account_task("account_refresh", len(access_tokens), _run, tier=tier)
        except RuntimeError as exc:
            raise HTTPException(status_code=409, detail={"error": redact_auth_diagnostic(exc)}) from exc

        # progress_id 兼容旧前端：与 task_id 相同，旧轮询接口会转发到 TaskManager
        return {
            "task_id": task.task_id,
            "progress_id": task.task_id,
            "total": len(access_tokens),
            "tier": tier,
            "task_type": "account_refresh",
        }

    @router.post("/api/accounts/inspect")
    async def inspect_accounts(body: AccountInspectRequest, authorization: str | None = Header(default=None)):
        """一键巡检：按 scope 取号 → TaskManager 分批探活 → 结构化报告。

        P0 仅 ChatGPT：目标范围排除 firefly。
        """
        require_admin(authorization)
        scope = (body.scope or "filter").strip().lower()
        if scope not in ("filter", "channel", "all"):
            raise HTTPException(status_code=400, detail={"error": "scope must be filter|channel|all"})

        params = _resolve_inspect_filter_params(
            scope,
            keyword=body.keyword,
            status=body.status,
            group_id=body.group_id,
            source_type=body.source_type,
        )
        # P0 仅 ChatGPT：过滤时排除 firefly
        filtered = _filter_accounts(
            keyword=params["keyword"],
            status=params["status"],
            group_id=params["group_id"],
            source_type=params["source_type"],
            exclude_demo=True,
            exclude_firefly=True,
        )
        tokens = [
            token
            for item in filtered
            if (token := _clean_text(item.get("access_token")))
        ]

        def _run(task) -> None:
            _run_account_inspect(task, tokens, scope=scope)

        try:
            # 巡检属扫库语义，固定 heavy 档位
            task = task_manager.submit("account_inspect", len(tokens), _run, tier="heavy")
        except RuntimeError as exc:
            raise HTTPException(status_code=409, detail={"error": redact_auth_diagnostic(exc)}) from exc

        return {"task_id": task.task_id, "total": len(tokens), "tier": task.tier}

    @router.get("/api/accounts/refresh/progress/{progress_id}")
    async def get_refresh_progress(progress_id: str, authorization: str | None = Header(default=None)):
        """兼容旧前端 progress 轮询：优先 TaskManager（task_id=progress_id），再回落旧 progress 表。"""
        require_admin(authorization)
        task = task_manager.get(progress_id)
        if task is not None:
            status = task.status
            done = status in ("completed", "failed", "cancelled", "stopped")
            result = dict(task.result or {})
            payload = {
                "total": task.total,
                "processed": task.progress,
                "done": done,
                "error": task.error or None,
                "status": status,
                "task_id": task.task_id,
                "task_type": task.task_type,
                "cancel_requested": bool(getattr(task, "cancel_requested", False)),
                "batch_remaining": getattr(task, "batch_remaining", result.get("batch_remaining", 0)),
                "result": result if done else None,
                "status_counts": result.get("status_counts"),
                "total_quota": result.get("total_quota", 0),
            }
            return payload
        progress = account_service.get_refresh_progress(progress_id)
        if progress is None:
            raise HTTPException(status_code=404, detail={"error": "progress not found"})
        return progress

    @router.post("/api/accounts/export")
    async def export_accounts(body: AccountExportRequest, authorization: str | None = Header(default=None)):
        require_admin(authorization)
        access_tokens = _unique_tokens(body.access_tokens)
        items = account_service.build_export_items(access_tokens)
        if not items:
            raise HTTPException(
                status_code=400,
                detail={"error": "没有可导出的完整账号，需要同时有 access_token、refresh_token 和 id_token"},
            )

        timestamp = _download_timestamp()
        if body.format == "zip":
            content = _account_zip_bytes(items)
            return Response(
                content,
                media_type="application/zip",
                headers={"Content-Disposition": f'attachment; filename="codex-accounts-{timestamp}.zip"'},
            )

        payload: dict[str, str] | list[dict[str, str]] = items[0] if len(items) == 1 else items
        return Response(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            media_type="application/json",
            headers={"Content-Disposition": f'attachment; filename="codex-accounts-{timestamp}.json"'},
        )

    @router.post("/api/accounts/update")
    async def update_account(body: AccountUpdateRequest, authorization: str | None = Header(default=None)):
        require_admin(authorization)
        access_token = str(body.access_token or "").strip()
        if not access_token:
            raise HTTPException(status_code=400, detail={"error": "access_token is required"})
        updates = {
            key: value
            for key, value in {
                "type": body.type,
                "source_type": body.source_type,
                "status": body.status,
                "quota": body.quota,
                "proxy": body.proxy,
                "group_id": body.group_id,
                "cookie": body.cookie,
            }.items()
            if value is not None
        }
        if not updates:
            raise HTTPException(status_code=400, detail={"error": "还没有检测到改动，请修改后再保存"})
        account = account_service.update_account(access_token, updates)
        if account is None:
            raise HTTPException(status_code=404, detail={"error": "account not found"})
        return {"item": account, "items": account_service.list_accounts()}

    @router.post("/api/accounts/batch-update")
    async def batch_update_accounts(body: AccountBatchUpdateRequest, authorization: str | None = Header(default=None)):
        require_admin(authorization)
        access_tokens = _unique_tokens(body.access_tokens)
        if not access_tokens:
            raise HTTPException(status_code=400, detail={"error": "access_tokens is required"})
        updates = {key: value for key, value in {"status": body.status}.items() if value is not None}
        if not updates:
            raise HTTPException(status_code=400, detail={"error": "no updates provided"})
        updated = 0
        errors: list[str] = []
        for token in access_tokens:
            account = account_service.update_account(token, updates, quiet=True)
            if account is None:
                errors.append(f"{token[:6]}... not found")
            else:
                updated += 1
        return {"updated": updated, "errors": errors, "items": account_service.list_accounts()}

    @router.post("/api/accounts/group")
    async def bind_accounts_group(body: AccountGroupBindRequest, authorization: str | None = Header(default=None)):
        require_admin(authorization)
        access_tokens = _unique_tokens(body.access_tokens)
        if not access_tokens:
            raise HTTPException(status_code=400, detail={"error": "access_tokens is required"})
        group_id = "" if body.group_id.strip() == "__ungrouped__" else _account_group_id(body.group_id)
        if group_id and not any(group.get("id") == group_id for group in _account_group_payload()["groups"]):
            raise HTTPException(status_code=404, detail={"error": "account group not found"})
        updated = 0
        errors: list[str] = []
        for token in access_tokens:
            account = account_service.update_account(token, {"group_id": group_id}, quiet=True)
            if account is None:
                errors.append(f"{token[:6]}... not found")
            else:
                updated += 1
        return {
            "updated": updated,
            "errors": errors,
            "group_id": group_id,
            **_account_group_payload(),
            "items": account_service.list_accounts(),
        }

    @router.post("/api/accounts/oauth/start")
    async def start_oauth_login(
            body: OAuthLoginStartRequest,
            authorization: str | None = Header(default=None),
    ):
        """登记一次 PKCE 会话，返回可让用户浏览器打开的 authorize URL。"""
        require_admin(authorization)
        try:
            return await run_in_threadpool(oauth_login_service.start, body.email_hint)
        except OAuthLoginError as exc:
            raise HTTPException(
                status_code=400,
                detail={"error": redact_auth_diagnostic(exc)},
            ) from exc

    @router.post("/api/accounts/oauth/finish")
    async def finish_oauth_login(
            body: OAuthLoginFinishRequest,
            authorization: str | None = Header(default=None),
    ):
        """收用户从浏览器抓回的 callback URL / code，换出 token 三件套并落盘。"""
        require_admin(authorization)
        try:
            tokens = await run_in_threadpool(oauth_login_service.finish, body.session_id, body.callback)
        except OAuthLoginError as exc:
            raise HTTPException(status_code=400, detail={"error": redact_auth_diagnostic(exc)}) from exc

        payload = {
            "access_token": tokens["access_token"],
            "refresh_token": tokens["refresh_token"],
            "id_token": tokens["id_token"],
            "source_type": "oauth_login",
        }
        add_result = await run_in_threadpool(account_service.add_account_items, [payload])
        refresh_result = await run_in_threadpool(
            account_service.refresh_accounts, [tokens["access_token"]]
        )
        return {
            **add_result,
            "refreshed": refresh_result.get("refreshed", 0),
            "errors": refresh_result.get("errors", []),
            "items": refresh_result.get("items", add_result.get("items", [])),
        }

    @router.get("/api/cpa/pools")
    async def list_cpa_pools(authorization: str | None = Header(default=None)):
        require_admin(authorization)
        return {"pools": sanitize_cpa_pools(cpa_config.list_pools())}

    @router.post("/api/cpa/pools")
    async def create_cpa_pool(body: CPAPoolCreateRequest, authorization: str | None = Header(default=None)):
        require_admin(authorization)
        if not body.base_url.strip():
            raise HTTPException(status_code=400, detail={"error": "base_url is required"})
        if not body.secret_key.strip():
            raise HTTPException(status_code=400, detail={"error": "secret_key is required"})
        pool = cpa_config.add_pool(name=body.name, base_url=body.base_url, secret_key=body.secret_key)
        return {"pool": sanitize_cpa_pool(pool), "pools": sanitize_cpa_pools(cpa_config.list_pools())}

    @router.post("/api/cpa/pools/{pool_id}")
    async def update_cpa_pool(pool_id: str, body: CPAPoolUpdateRequest, authorization: str | None = Header(default=None)):
        require_admin(authorization)
        pool = cpa_config.update_pool(pool_id, body.model_dump(exclude_none=True))
        if pool is None:
            raise HTTPException(status_code=404, detail={"error": "pool not found"})
        return {"pool": sanitize_cpa_pool(pool), "pools": sanitize_cpa_pools(cpa_config.list_pools())}

    @router.delete("/api/cpa/pools/{pool_id}")
    async def delete_cpa_pool(pool_id: str, authorization: str | None = Header(default=None)):
        require_admin(authorization)
        if not cpa_config.delete_pool(pool_id):
            raise HTTPException(status_code=404, detail={"error": "pool not found"})
        return {"pools": sanitize_cpa_pools(cpa_config.list_pools())}

    @router.get("/api/cpa/pools/{pool_id}/files")
    async def cpa_pool_files(pool_id: str, authorization: str | None = Header(default=None)):
        require_admin(authorization)
        pool = cpa_config.get_pool(pool_id)
        if pool is None:
            raise HTTPException(status_code=404, detail={"error": "pool not found"})
        return {"pool_id": pool_id, "files": await run_in_threadpool(list_remote_files, pool)}

    @router.post("/api/cpa/pools/{pool_id}/import")
    async def cpa_pool_import(pool_id: str, body: CPAImportRequest, authorization: str | None = Header(default=None)):
        require_admin(authorization)
        pool = cpa_config.get_pool(pool_id)
        if pool is None:
            raise HTTPException(status_code=404, detail={"error": "pool not found"})
        try:
            job = cpa_import_service.start_import(pool, body.names)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail={"error": str(exc)}) from exc
        return {"import_job": job}

    @router.get("/api/cpa/pools/{pool_id}/import")
    async def cpa_pool_import_progress(pool_id: str, authorization: str | None = Header(default=None)):
        require_admin(authorization)
        pool = cpa_config.get_pool(pool_id)
        if pool is None:
            raise HTTPException(status_code=404, detail={"error": "pool not found"})
        return {"import_job": pool.get("import_job")}

    @router.get("/api/sub2api/servers")
    async def list_sub2api_servers(authorization: str | None = Header(default=None)):
        require_admin(authorization)
        return {"servers": sanitize_sub2api_servers(sub2api_config.list_servers())}

    @router.post("/api/sub2api/servers")
    async def create_sub2api_server(body: Sub2APIServerCreateRequest, authorization: str | None = Header(default=None)):
        require_admin(authorization)
        if not body.base_url.strip():
            raise HTTPException(status_code=400, detail={"error": "base_url is required"})
        has_login = body.email.strip() and body.password.strip()
        has_api_key = bool(body.api_key.strip())
        if not has_login and not has_api_key:
            raise HTTPException(status_code=400, detail={"error": "email+password or api_key is required"})
        server = sub2api_config.add_server(
            name=body.name,
            base_url=body.base_url,
            email=body.email,
            password=body.password,
            api_key=body.api_key,
            group_id=body.group_id,
        )
        return {"server": sanitize_sub2api_server(server), "servers": sanitize_sub2api_servers(sub2api_config.list_servers())}

    @router.post("/api/sub2api/servers/{server_id}")
    async def update_sub2api_server(server_id: str, body: Sub2APIServerUpdateRequest, authorization: str | None = Header(default=None)):
        require_admin(authorization)
        server = sub2api_config.update_server(server_id, body.model_dump(exclude_none=True))
        if server is None:
            raise HTTPException(status_code=404, detail={"error": "server not found"})
        return {"server": sanitize_sub2api_server(server), "servers": sanitize_sub2api_servers(sub2api_config.list_servers())}

    @router.delete("/api/sub2api/servers/{server_id}")
    async def delete_sub2api_server(server_id: str, authorization: str | None = Header(default=None)):
        require_admin(authorization)
        if not sub2api_config.delete_server(server_id):
            raise HTTPException(status_code=404, detail={"error": "server not found"})
        return {"servers": sanitize_sub2api_servers(sub2api_config.list_servers())}

    @router.get("/api/sub2api/servers/{server_id}/groups")
    async def sub2api_server_groups(server_id: str, authorization: str | None = Header(default=None)):
        require_admin(authorization)
        server = sub2api_config.get_server(server_id)
        if server is None:
            raise HTTPException(status_code=404, detail={"error": "server not found"})
        try:
            groups = await run_in_threadpool(sub2api_list_remote_groups, server)
        except Exception as exc:
            raise HTTPException(status_code=502, detail={"error": str(exc)}) from exc
        return {"server_id": server_id, "groups": groups}

    @router.get("/api/sub2api/servers/{server_id}/accounts")
    async def sub2api_server_accounts(
        server_id: str,
        group_id: str | None = Query(default=None),
        authorization: str | None = Header(default=None),
    ):
        require_admin(authorization)
        server = sub2api_config.get_server(server_id)
        if server is None:
            raise HTTPException(status_code=404, detail={"error": "server not found"})
        if group_id is not None:
            server = {**server, "group_id": group_id}
        try:
            accounts = await run_in_threadpool(sub2api_list_remote_accounts, server)
        except Exception as exc:
            raise HTTPException(status_code=502, detail={"error": str(exc)}) from exc
        return {"server_id": server_id, "accounts": accounts}

    @router.post("/api/sub2api/servers/{server_id}/import")
    async def sub2api_server_import(server_id: str, body: Sub2APIImportRequest, authorization: str | None = Header(default=None)):
        require_admin(authorization)
        server = sub2api_config.get_server(server_id)
        if server is None:
            raise HTTPException(status_code=404, detail={"error": "server not found"})
        try:
            job = sub2api_import_service.start_import(
                server,
                body.account_ids,
                group_bindings=[binding.model_dump() for binding in body.group_bindings],
                create_account_groups=body.create_account_groups,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail={"error": str(exc)}) from exc
        return {"import_job": job}

    @router.get("/api/sub2api/servers/{server_id}/import")
    async def sub2api_server_import_progress(server_id: str, authorization: str | None = Header(default=None)):
        require_admin(authorization)
        server = sub2api_config.get_server(server_id)
        if server is None:
            raise HTTPException(status_code=404, detail={"error": "server not found"})
        return {"import_job": server.get("import_job")}


    # ============================================================
    #  Relogin: 单号 / 批量  重新登录失效账号
    #  依赖一代移植的 openai_register.relogin() 与 TaskManager
    # ============================================================

    @router.post("/api/accounts/relogin/precheck")
    async def relogin_precheck(body: ReloginPrecheckRequest, authorization: str | None = Header(default=None)):
        """批量重登预检：可重登 N / 跳过 M + 原因汇总。"""
        require_admin(authorization)
        tokens = [t for t in (body.tokens or []) if str(t or "").strip()]
        if not tokens:
            raise HTTPException(status_code=400, detail={"error": "tokens list is empty"})
        # _reconstruct_mailbox 只读 config，无网络 IO
        return _precheck_relogin_tokens(tokens)

    @router.post("/api/accounts/relogin")
    async def relogin_account(body: ReloginRequest, authorization: str | None = Header(default=None)):
        require_admin(authorization)
        token = (body.access_token or "").strip()
        if not token:
            raise HTTPException(status_code=400, detail={"error": "access_token is required"})

        account = account_service.get_account(token)
        if account is None:
            raise HTTPException(status_code=404, detail={"error": "account not found"})

        email = str(account.get("email") or "")
        password = str(account.get("password") or "")
        if not email:
            raise HTTPException(
                status_code=400,
                detail={"error": "account missing email, cannot relogin"},
            )

        proxy = str(account.get("proxy") or "")
        fp = None
        if isinstance(account.get("fingerprint"), dict):
            fp = dict(account["fingerprint"])
        elif isinstance(account.get("fp"), dict):
            fp = dict(account["fp"])

        try:
            tokens = await run_in_threadpool(_openai_relogin, email, password, proxy, fp)
        except Exception as exc:
            return {"ok": False, "error": redact_auth_diagnostic(exc)}

        new_token = str(tokens.get("access_token") or "")
        if not new_token:
            return {"ok": False, "error": "relogin returned empty access_token"}

        new_token = await run_in_threadpool(account_service.apply_relogin_tokens, token, tokens)
        return {
            "ok": True,
            "access_token": new_token,
            "refresh_token": tokens.get("refresh_token", ""),
            "token_expires_at": tokens.get("token_expires_at", ""),
        }

    @router.post("/api/accounts/relogin-batch")
    async def relogin_accounts_batch(body: ReloginBatchRequest, authorization: str | None = Header(default=None)):
        require_admin(authorization)
        tokens = [t for t in (body.tokens or []) if str(t or "").strip()]
        if not tokens:
            raise HTTPException(status_code=400, detail={"error": "tokens list is empty"})

        def _run_relogin_batch(task) -> None:
            success = 0
            failed = 0
            errors: list[dict[str, str]] = []
            for i, old_token in enumerate(tokens, 1):
                try:
                    account = account_service.get_account(old_token)
                    if account is None:
                        failed += 1
                        errors.append({"token": old_token[:16], "error": "account not found"})
                        task.bump(progress=i, success=success, failed=failed)
                        continue

                    email = str(account.get("email") or "")
                    password = str(account.get("password") or "")
                    if not email:
                        failed += 1
                        errors.append({"token": old_token[:16], "error": "missing email"})
                        task.bump(progress=i, success=success, failed=failed)
                        continue

                    proxy = str(account.get("proxy") or "")
                    fp = None
                    if isinstance(account.get("fingerprint"), dict):
                        fp = dict(account["fingerprint"])
                    elif isinstance(account.get("fp"), dict):
                        fp = dict(account["fp"])

                    new_tokens = _openai_relogin(email, password, proxy, fp)
                    new_token = str(new_tokens.get("access_token") or "")
                    if new_token:
                        account_service.apply_relogin_tokens(old_token, new_tokens)
                        success += 1
                    else:
                        failed += 1
                        errors.append({"token": old_token[:16], "error": "empty access_token"})
                except Exception as exc:
                    failed += 1
                    errors.append({"token": old_token[:16], "error": redact_auth_diagnostic(exc, 200)})
                task.bump(progress=i, success=success, failed=failed)

            task.complete(success=success, failed=failed, errors=errors[:50])

        try:
            task = task_manager.submit("relogin_batch", len(tokens), _run_relogin_batch)
        except RuntimeError as exc:
            raise HTTPException(status_code=409, detail={"error": redact_auth_diagnostic(exc)}) from exc

        return {"task_id": task.task_id, "total": len(tokens)}

    # ============================================================
    #  Tasks: 任务列表 / 任务详情 / 按档位进行中
    # ============================================================

    @router.get("/api/account-tasks/active")
    async def list_active_account_tasks(authorization: str | None = Header(default=None)):
        """按档位返回进行中账号任务（heavy/light 各至多一条，含 stopping）。"""
        require_admin(authorization)
        active = task_manager.list_active_by_tier()
        return {
            "heavy": active["heavy"].to_active_dict() if active["heavy"] else None,
            "light": active["light"].to_active_dict() if active["light"] else None,
        }

    @router.get("/api/tasks")
    async def list_tasks(authorization: str | None = Header(default=None)):
        require_admin(authorization)
        return {"tasks": [t.to_dict() for t in task_manager.list_running()]}

    @router.get("/api/tasks/{task_id}")
    async def get_task(task_id: str, authorization: str | None = Header(default=None)):
        require_admin(authorization)
        task = task_manager.get(task_id)
        if task is None:
            raise HTTPException(status_code=404, detail={"error": "task not found"})
        return task.to_dict()

    @router.post("/api/tasks/{task_id}/cancel")
    async def cancel_task(task_id: str, authorization: str | None = Header(default=None)):
        """请求取消后台任务（仅置 cancel_requested，不直接改 status；任务体批边界收尾）。"""
        require_admin(authorization)
        task = task_manager.request_cancel(task_id)
        if task is None:
            raise HTTPException(status_code=404, detail={"error": "task not found or already finished"})
        # 不改 status；返回快照供前端显示「停止中 + 本批剩余」
        return {
            "ok": True,
            "task_id": task.task_id,
            "status": task.status,
            "cancel_requested": task.cancel_requested,
            "batch_remaining": task.batch_remaining,
            "tier": task.tier,
        }

    return router
