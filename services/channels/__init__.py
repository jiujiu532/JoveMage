"""多渠道注册表与描述符。

埋缝期：ChatGPT 内置默认 + Firefly 首个旁路渠道，静态注册。
"""

from __future__ import annotations

from services.channels.registry import (
    DEFAULT_CHANNEL_ID,
    ChannelEntry,
    channel_for_model,
    get_channel,
    list_channel_entries,
    list_channels,
)

__all__ = [
    "DEFAULT_CHANNEL_ID",
    "ChannelEntry",
    "channel_for_model",
    "get_channel",
    "list_channel_entries",
    "list_channels",
]
