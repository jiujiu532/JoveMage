from __future__ import annotations

from typing import Any

from services.account_service import account_service
from services.config import config
from services.model_catalog_service import get_model_catalog
from services.openai_backend_api import OpenAIBackendAPI
from utils.helper import CODEX_IMAGE_MODEL


def _model_item(model: str, *, owned_by: str = "chatgpt2api") -> dict[str, Any]:
    return {
        "id": model,
        "object": "model",
        "created": 0,
        "owned_by": owned_by,
        "permission": [],
        "root": model,
        "parent": None,
    }


def _append_model(data: list[Any], seen: set[str], model: object, *, owned_by: str = "chatgpt2api") -> None:
    model_id = str(model or "").strip()
    if not model_id or model_id in seen:
        return
    seen.add(model_id)
    data.append(_model_item(model_id, owned_by=owned_by))


def _append_models(data: list[Any], seen: set[str], models: object, *, owned_by: str = "chatgpt2api") -> None:
    if not isinstance(models, list):
        return
    for model in models:
        _append_model(data, seen, model, owned_by=owned_by)


def _append_upstream_models(data: list[Any], seen: set[str]) -> None:
    try:
        with OpenAIBackendAPI() as backend:
            result = backend.list_models()
    except Exception:
        return
    upstream_data = result.get("data")
    if not isinstance(upstream_data, list):
        return
    for item in upstream_data:
        if not isinstance(item, dict):
            continue
        _append_model(data, seen, item.get("id"))


def _dynamic_image_models() -> list[str]:
    models: list[str] = []
    accounts = account_service.list_accounts()
    web_image_accounts = [
        account
        for account in accounts
        if isinstance(account, dict)
           and account_service._is_image_account_available(account)
           and account_service._normalize_source_type(account.get("source_type")) != "firefly"
    ]
    codex_types = {
        normalized
        for account in accounts
        if isinstance(account, dict)
           and account_service._normalize_source_type(account.get("source_type")) == "codex"
           and account_service._is_image_account_available(account)
           and (normalized := account_service._normalize_account_type(account.get("type")))
    }

    if web_image_accounts:
        models.append("gpt-image-2")
    if codex_types & {"Plus", "Team", "Pro"}:
        models.append(CODEX_IMAGE_MODEL)
    for plan_type in ("Plus", "Team", "Pro"):
        if plan_type in codex_types:
            models.append(f"{plan_type.lower()}-{CODEX_IMAGE_MODEL}")

    return models


def _dynamic_firefly_image_models() -> list[str]:
    """Firefly 族级 id；模块未就绪或渠道关闭时返回空。"""
    if not config.firefly_enabled:
        return []
    try:
        from services.backends.firefly_catalog import list_firefly_image_families
    except ImportError:
        return []
    accounts = account_service.list_accounts()
    has_firefly = any(
        isinstance(account, dict)
        and account_service._normalize_source_type(account.get("source_type")) == "firefly"
        and account_service._is_image_account_available(account)
        for account in accounts
    )
    if not has_firefly:
        return []
    try:
        families = list_firefly_image_families()
    except Exception:
        return []
    if not isinstance(families, list):
        return []
    return [str(item).strip() for item in families if str(item or "").strip()]


def list_models() -> dict[str, Any]:
    catalog = get_model_catalog()
    data: list[Any] = []
    seen: set[str] = set()

    _append_models(data, seen, catalog.get("chat_models"))
    _append_upstream_models(data, seen)
    _append_models(data, seen, catalog.get("image_models"))
    _append_models(data, seen, _dynamic_image_models())
    _append_models(data, seen, _dynamic_firefly_image_models(), owned_by="adobe-firefly")

    return {"object": "list", "data": data}
