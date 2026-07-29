from __future__ import annotations

import asyncio
import json
from typing import Any, Literal

from fastapi import APIRouter, Body, Header, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from api.support import require_admin
from services.config import config
from services.register import domain_blacklist
from services.register.mail_provider import _entries
from services.register_service import register_service


class RegisterConfigRequest(BaseModel):
    mail: dict | None = None
    proxy: str | None = None
    proxy_pool: list[str] | None = None
    max_relogin_retries: int | None = None
    total: int | None = None
    threads: int | None = None
    mode: str | None = None
    target_quota: int | None = None
    target_available: int | None = None
    check_interval: int | None = None


class OutlookPoolResetRequest(BaseModel):
    scope: str | None = None


class GptMailStatusRequest(BaseModel):
    provider: dict | None = None
    force: bool | None = None


class DomainBlacklistBanRequest(BaseModel):
    provider_ref: str
    domain: str
    reason: str | None = None


class DomainBlacklistUnbanRequest(BaseModel):
    provider_ref: str
    domain: str


class DomainBlacklistImportRequest(BaseModel):
    payload: dict | list
    mode: Literal["merge", "replace"] = "merge"
    provider_ref: str | None = None


def _provider_list_for_blacklist() -> list[dict[str, Any]]:
    """构建非 excluded 的 provider 列表，供前端分组展示。"""
    register = register_service.get() or {}
    mail = register.get("mail") if isinstance(register, dict) else None
    mail_config = mail if isinstance(mail, dict) else {}
    providers_raw = mail_config.get("providers")
    if not isinstance(providers_raw, list):
        mail_config = {**mail_config, "providers": []}
    result: list[dict[str, Any]] = []
    for item in _entries(mail_config if isinstance(mail_config.get("providers"), list) else {"providers": []}):
        ptype = str(item.get("type") or "").strip()
        excluded = domain_blacklist.is_excluded_provider(ptype, str(item.get("provider_ref") or ""))
        if excluded:
            continue
        result.append(
            {
                "provider_ref": str(item.get("provider_ref") or ""),
                "id": item.get("id") or item.get("provider_id") or "",
                "type": ptype,
                "label": item.get("label") or "",
                "enable": bool(item.get("enable")),
                "excluded": False,
            }
        )
    return result


def create_router() -> APIRouter:
    router = APIRouter()

    @router.get("/api/register")
    async def get_register_config(authorization: str | None = Header(default=None)):
        require_admin(authorization)
        return {"register": register_service.get()}

    @router.post("/api/register")
    async def update_register_config(body: RegisterConfigRequest, authorization: str | None = Header(default=None)):
        require_admin(authorization)
        return {"register": register_service.update(body.model_dump(exclude_none=True))}

    @router.post("/api/register/start")
    async def start_register(authorization: str | None = Header(default=None)):
        require_admin(authorization)
        return {"register": register_service.start()}

    @router.post("/api/register/stop")
    async def stop_register(authorization: str | None = Header(default=None)):
        require_admin(authorization)
        return {"register": register_service.stop()}

    @router.post("/api/register/reset")
    async def reset_register(authorization: str | None = Header(default=None)):
        require_admin(authorization)
        return {"register": register_service.reset()}

    @router.post("/api/register/outlook-pool/reset")
    async def reset_outlook_pool(body: OutlookPoolResetRequest, authorization: str | None = Header(default=None)):
        require_admin(authorization)
        return {"register": register_service.reset_outlook_pool(body.scope or "all")}

    @router.post("/api/register/gptmail/status")
    async def get_gptmail_status(body: GptMailStatusRequest, authorization: str | None = Header(default=None)):
        require_admin(authorization)
        try:
            return {"status": register_service.gptmail_status(body.provider, force=bool(body.force))}
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.post("/api/register/gptmail/refresh-key")
    async def refresh_gptmail_public_key(body: GptMailStatusRequest, authorization: str | None = Header(default=None)):
        require_admin(authorization)
        try:
            return {"status": register_service.refresh_gptmail_public_key(body.provider, force=body.force is not False)}
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.get("/api/register/domain-blacklist")
    async def get_domain_blacklist(authorization: str | None = Header(default=None)):
        require_admin(authorization)
        try:
            return {
                "entries": domain_blacklist.list_entries(include_inactive=True),
                "providers": _provider_list_for_blacklist(),
                "builtin_rules": domain_blacklist.BUILTIN_BAN_RULES,
                "custom_rules": config.get_domain_ban_rules(),
            }
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.post("/api/register/domain-blacklist")
    async def ban_domain_blacklist(
        body: DomainBlacklistBanRequest,
        authorization: str | None = Header(default=None),
    ):
        require_admin(authorization)
        try:
            entry = domain_blacklist.ban(
                body.provider_ref,
                body.domain,
                reason=str(body.reason or "").strip(),
                source="manual",
            )
            if entry.get("skipped"):
                raise HTTPException(status_code=400, detail=str(entry.get("reason") or "excluded_provider"))
            return {"entry": entry}
        except HTTPException:
            raise
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.delete("/api/register/domain-blacklist")
    async def unban_domain_blacklist(
        body: DomainBlacklistUnbanRequest | None = Body(default=None),
        provider_ref: str = Query(default=""),
        domain: str = Query(default=""),
        authorization: str | None = Header(default=None),
    ):
        require_admin(authorization)
        pref = str((body.provider_ref if body else "") or provider_ref or "").strip()
        dom = str((body.domain if body else "") or domain or "").strip()
        if not pref or not dom:
            raise HTTPException(status_code=400, detail="provider_ref and domain are required")
        try:
            removed = domain_blacklist.unban(pref, dom)
            return {"removed": bool(removed)}
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.get("/api/register/domain-blacklist/export")
    async def export_domain_blacklist(
        provider_ref: str | None = Query(default=None),
        authorization: str | None = Header(default=None),
    ):
        require_admin(authorization)
        try:
            scope = str(provider_ref).strip() if provider_ref else None
            return domain_blacklist.export_payload(scope)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.post("/api/register/domain-blacklist/import")
    async def import_domain_blacklist(
        body: DomainBlacklistImportRequest,
        authorization: str | None = Header(default=None),
    ):
        require_admin(authorization)
        try:
            scope = str(body.provider_ref).strip() if body.provider_ref else None
            stats = domain_blacklist.import_payload(body.payload, mode=body.mode, provider_ref=scope)
            return {"result": stats}
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.get("/api/register/events")
    async def register_events(token: str = ""):
        require_admin(f"Bearer {token}")

        async def stream():
            last = ""
            while True:
                payload = json.dumps(register_service.get(), ensure_ascii=False)
                if payload != last:
                    last = payload
                    yield f"data: {payload}\n\n"
                await asyncio.sleep(0.5)

        return StreamingResponse(stream(), media_type="text/event-stream")

    return router
