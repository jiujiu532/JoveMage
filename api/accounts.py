from __future__ import annotations

import asyncio
import io
import json
import re
import uuid
import zipfile
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
from services.task_manager import task_manager
from services.register.openai_register import relogin as _openai_relogin
from services.oauth_login_service import OAuthLoginError, oauth_login_service
from services.sub2api_service import (
    list_remote_accounts as sub2api_list_remote_accounts,
    list_remote_groups as sub2api_list_remote_groups,
    sub2api_config,
    sub2api_import_service,
)
from utils.diagnostics import redact_auth_diagnostic



class ReloginRequest(BaseModel):
    access_token: str = ""


class ReloginBatchRequest(BaseModel):
    tokens: list[str] = Field(default_factory=list)


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


class AccountImportCleanupRequest(BaseModel):
    access_tokens: list[str] = Field(default_factory=list)
    remove: bool = False


class AccountRefreshRequest(BaseModel):
    access_tokens: list[str] = Field(default_factory=list)


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
    filtered = [
        item for item in items
        if _account_matches_keyword(item, keyword)
        and _status_matches_filter(item, status)
        and _account_matches_group(item, group_id)
        and _account_matches_source_type(item, source_type)
    ]
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
        require_admin(authorization)
        tokens = [str(token or "").strip() for token in body.tokens if str(token or "").strip()]
        if not tokens:
            raise HTTPException(status_code=400, detail={"error": "tokens is required"})
        return account_service.delete_accounts(tokens, return_items=False)

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
        require_admin(authorization)
        access_tokens = [str(token or "").strip() for token in body.access_tokens if str(token or "").strip()]
        if not access_tokens:
            access_tokens = account_service.list_tokens()
        if not access_tokens:
            raise HTTPException(status_code=400, detail={"error": "access_tokens is required"})

        progress_id = str(uuid.uuid4())

        async def _do_refresh():
            try:
                await run_in_threadpool(account_service.refresh_accounts, access_tokens, progress_id)
            except Exception as e:
                account_service.finish_refresh_progress(progress_id, error=str(e))

        asyncio.create_task(_do_refresh())

        return {"progress_id": progress_id}

    @router.get("/api/accounts/refresh/progress/{progress_id}")
    async def get_refresh_progress(progress_id: str, authorization: str | None = Header(default=None)):
        require_admin(authorization)
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
    #  Tasks: 任务列表 / 任务详情
    # ============================================================

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

    return router
