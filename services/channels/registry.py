"""渠道注册表：把「渠道」从隐式特判变成显式、可查询的一等概念。

埋缝期只做静态注册（ChatGPT + Firefly）与模型→渠道前缀路由。
rate_budget / model_resolver / router_hook 仅占位，本期不实现。
"""

from __future__ import annotations

from collections.abc import Callable
from copy import deepcopy
from dataclasses import dataclass, field, replace
from typing import Any

# 默认主体航道 id；无前缀模型一律归它
DEFAULT_CHANNEL_ID = "chatgpt"


@dataclass(frozen=True, slots=True)
class ChannelEntry:
    """渠道描述符。id 同时等于账号 source_type 与旁路模型前缀。"""

    id: str
    name: str
    icon: str
    color: str | None
    is_default: bool
    credential_type: str  # "token" | "cookie"
    registerable: bool
    capabilities: list[str]
    enabled: bool
    config_ns: str
    meter_kind: str  # "quota" | "credits"
    # —— 埋缝期占位，本期不实现 ——
    rate_budget: dict[str, Any] | None = None
    model_resolver: Callable[..., Any] | None = field(default=None, repr=False, compare=False)
    router_hook: Callable[..., Any] | None = field(default=None, repr=False, compare=False)

    def to_public_dict(self) -> dict[str, Any]:
        """描述符对外字段（不含 callable 占位）。"""
        return {
            "id": self.id,
            "name": self.name,
            "icon": self.icon,
            "color": self.color,
            "is_default": self.is_default,
            "credential_type": self.credential_type,
            "registerable": self.registerable,
            "capabilities": list(self.capabilities),
            "enabled": self.enabled,
            "config_ns": self.config_ns,
            "meter_kind": self.meter_kind,
        }


def _build_static_registry() -> dict[str, ChannelEntry]:
    """代码内静态注册表（加渠道 2 时改这一处）。插入顺序即 list 顺序：主体在前。"""
    chatgpt = ChannelEntry(
        id="chatgpt",
        name="ChatGPT",
        icon="mdi:chat-outline",
        color=None,
        is_default=True,
        credential_type="token",
        registerable=True,
        capabilities=["chat", "image"],
        enabled=True,
        # ChatGPT 配置留在 config 顶层，不是 channels.chatgpt.*
        config_ns="",
        meter_kind="quota",
    )
    firefly = ChannelEntry(
        id="firefly",
        name="Adobe Firefly",
        icon="mdi:fire",
        color="ember",
        is_default=False,
        credential_type="cookie",
        registerable=False,  # 只能手动导 Express Cookie，无自动注册机
        capabilities=["image", "edit", "video"],
        enabled=False,  # 实际值由 config.firefly_enabled 覆盖
        config_ns="channels.firefly",
        meter_kind="credits",
    )
    return {chatgpt.id: chatgpt, firefly.id: firefly}


_REGISTRY: dict[str, ChannelEntry] = _build_static_registry()


def _read_enabled(channel_id: str, fallback: bool) -> bool:
    """从现有 config 键读渠道开关，不发明新配置。"""
    if channel_id == "firefly":
        try:
            from services.config import config

            return bool(config.firefly_enabled)
        except Exception:
            return fallback
    # ChatGPT 主体航道始终可用
    return True


def _with_live_enabled(entry: ChannelEntry) -> ChannelEntry:
    """返回带最新 enabled 的 entry 副本（capabilities 浅拷贝防外泄修改）。"""
    enabled = _read_enabled(entry.id, entry.enabled)
    caps = list(entry.capabilities)
    rate = deepcopy(entry.rate_budget) if entry.rate_budget is not None else None
    return replace(entry, enabled=enabled, capabilities=caps, rate_budget=rate)


def get_channel(channel_id: str) -> ChannelEntry | None:
    """按 id 取渠道；未知 id 返回 None。enabled 每次现读 config。"""
    key = str(channel_id or "").strip().lower()
    entry = _REGISTRY.get(key)
    if entry is None:
        return None
    return _with_live_enabled(entry)


def list_channel_entries() -> list[ChannelEntry]:
    """返回全部已注册渠道 entry（注册顺序），enabled 现读。"""
    return [_with_live_enabled(entry) for entry in _REGISTRY.values()]


def list_channels() -> list[dict[str, Any]]:
    """返回全部渠道的公共描述（无账号统计），enabled 现读。"""
    return [entry.to_public_dict() for entry in list_channel_entries()]


def channel_for_model(model_id: object) -> str:
    """模型 id → 渠道 id。

    约定：旁路渠道模型为 ``{channel_id}-...``；无匹配前缀则归默认 chatgpt。
    权威入口——业务侧「模型属于哪个渠道」应走这里，而不是散落 is_firefly_* 特判。
    """
    text = str(model_id or "").strip().lower()
    if not text:
        return DEFAULT_CHANNEL_ID
    for channel_id, entry in _REGISTRY.items():
        if entry.is_default:
            continue
        if text.startswith(f"{channel_id}-"):
            return channel_id
    return DEFAULT_CHANNEL_ID
