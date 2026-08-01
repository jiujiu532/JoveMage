from __future__ import annotations

from typing import Any

from services.account_service import account_service
from services.config import config
from utils.helper import CODEX_IMAGE_MODEL, is_firefly_video_model


FALLBACK_CHAT_MODELS = [
    "auto",
    "gpt-5",
    "gpt-5-1",
    "gpt-5-2",
    "gpt-5-3",
    "gpt-5-3-mini",
    "gpt-5-5",
    "gpt-5-mini",
]

FALLBACK_IMAGE_MODELS = [
    "gpt-image-2",
]

FALLBACK_VIDEO_MODELS = [
    "firefly-sora2",
    "firefly-veo31",
    "firefly-kling3",
]


def _normalize_list(raw: object) -> list[str]:
    if not isinstance(raw, list):
        return []
    values: list[str] = []
    seen: set[str] = set()
    for item in raw:
        value = str(item or "").strip()
        if not value or value in seen:
            continue
        seen.add(value)
        values.append(value)
    return values


def _settings_dict(value: object) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _configured_chat_models(settings: dict[str, Any]) -> list[str]:
    catalog = _settings_dict(settings.get("model_catalog"))
    explicit = _normalize_list(catalog.get("chat_models"))
    if explicit:
        return explicit

    combined: list[str] = []
    for key in ("base_chat_models", "specialized_chat_models", "image_capable_chat_models"):
        for model in _normalize_list(catalog.get(key)):
            if model not in combined:
                combined.append(model)
    return combined


def _configured_image_models(settings: dict[str, Any]) -> list[str]:
    image_generation = _settings_dict(settings.get("image_generation"))
    catalog = _settings_dict(settings.get("model_catalog"))
    for source in (
        image_generation.get("model_options"),
        catalog.get("image_api_models"),
        image_generation.get("supported_models"),
    ):
        models = [item for item in _normalize_list(source) if not is_firefly_video_model(item)]
        if models:
            return models
    return []


def _configured_video_models(settings: dict[str, Any]) -> list[str]:
    catalog = _settings_dict(settings.get("model_catalog"))
    explicit = _normalize_list(catalog.get("video_api_models"))
    if explicit:
        return explicit
    # 兼容：把配置里混进 image 列表的视频模型提出来
    image_generation = _settings_dict(settings.get("image_generation"))
    mixed: list[str] = []
    for source in (
        image_generation.get("model_options"),
        catalog.get("image_api_models"),
        catalog.get("all_models"),
    ):
        for model in _normalize_list(source):
            if is_firefly_video_model(model) and model not in mixed:
                mixed.append(model)
    return mixed


def _image_models_from_accounts(accounts: list[dict[str, Any]]) -> list[str]:
    available_accounts = [
        account
        for account in accounts
        if isinstance(account, dict) and account_service._is_image_account_available(account)
    ]
    if not available_accounts:
        return []

    models: list[str] = ["gpt-image-2"]
    codex_types = {
        normalized
        for account in available_accounts
        if account_service._normalize_source_type(account.get("source_type")) == "codex"
        and (normalized := account_service._normalize_account_type(account.get("type")))
    }

    if codex_types & {"Plus", "Team", "Pro"}:
        models.append(CODEX_IMAGE_MODEL)
    for plan_type in ("Plus", "Team", "Pro"):
        if plan_type in codex_types:
            models.append(f"{plan_type.lower()}-{CODEX_IMAGE_MODEL}")
    return models


def _video_models_from_runtime() -> list[str]:
    """Firefly 视频开启且有可用账号时返回族级 id；否则空。"""
    if not config.firefly_video_enabled:
        return []
    try:
        from services.backends.firefly_video_catalog import list_firefly_video_families
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
        families = list_firefly_video_families()
    except Exception:
        return []
    if not isinstance(families, list):
        return []
    models: list[str] = []
    for item in families:
        family = str(item or "").strip().lower()
        if not family:
            continue
        if family.startswith("firefly-"):
            models.append(family)
        else:
            models.append(f"firefly-{family}")
    return models


def _unique(values: list[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result


def get_model_catalog() -> dict[str, Any]:
    settings = config.get()
    configured_chat_models = _configured_chat_models(settings)
    configured_image_models = _configured_image_models(settings)
    configured_video_models = _configured_video_models(settings)

    chat_source = "config" if configured_chat_models else "fallback"
    chat_models = configured_chat_models or list(FALLBACK_CHAT_MODELS)

    if configured_image_models:
        image_source = "config"
        image_models = configured_image_models
    else:
        account_models = _image_models_from_accounts(account_service.list_accounts())
        image_source = "accounts" if account_models else "fallback"
        image_models = account_models or list(FALLBACK_IMAGE_MODELS)

    runtime_video = _video_models_from_runtime()
    if configured_video_models:
        video_source = "config"
        video_models = configured_video_models
    elif runtime_video:
        video_source = "runtime"
        video_models = runtime_video
    else:
        # 未启用视频渠道时不塞兜底，避免 UI 选到必失败模型
        video_source = "empty"
        video_models = []

    chat_models = _unique(chat_models)
    image_models = _unique([model for model in image_models if not is_firefly_video_model(model)])
    video_models = _unique(video_models)
    all_models = _unique([*chat_models, *image_models, *video_models])

    return {
        "object": "model_catalog",
        "chat_models": chat_models,
        "image_models": image_models,
        "video_models": video_models,
        "all_models": all_models,
        "capabilities": {
            "image_upscale": config.image_upscale_enabled,
        },
        "source": {
            "chat": chat_source,
            "image": image_source,
            "video": video_source,
        },
        "openai_models_endpoint": "/v1/models",
    }
