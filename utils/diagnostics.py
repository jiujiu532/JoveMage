from __future__ import annotations

import re
from typing import Any


EXCEPTION_DIAGNOSTIC_ATTRS: tuple[tuple[str, str], ...] = (
    ("code", "error_code"),
    ("raw_error", "raw_error"),
    ("upstream_error", "upstream_error"),
    ("upstream_error_type", "upstream_error_type"),
    ("upstream_request_id", "upstream_request_id"),
    ("can_resume_poll", "can_resume_poll"),
    ("raw_upstream_message", "raw_upstream_message"),
    ("raw_upstream_message_len", "raw_upstream_message_len"),
    ("raw_upstream_message_truncated", "raw_upstream_message_truncated"),
    ("upstream_message_preview", "upstream_message_preview"),
    ("upstream_message_len", "upstream_message_len"),
    ("upstream_message_truncated", "upstream_message_truncated"),
    ("tool_invoked", "tool_invoked"),
    ("terminal_message", "terminal_message"),
    ("blocked", "blocked"),
    ("poll_attempts", "poll_attempts"),
    ("poll_timeout_secs", "poll_timeout_secs"),
    ("stream_timeout_secs", "stream_timeout_secs"),
    ("stream_timeout_followup", "stream_timeout_followup"),
    ("last_task_error", "last_task_error"),
    ("last_conversation_snapshot", "last_conversation_snapshot"),
)

_AUTH_SECRET_PATTERN = re.compile(
    r"(?i)(?P<prefix>(?:[\"']?(?:access_token|refresh_token|id_token|cookie|otp|code|token|oai-sc|password|api_key|apikey|client_secret|secret)[\"']?\s*[:=]\s*))"
    r"(?P<quote>[\"']?)(?P<value>[^\s,;&}\]\"']+)(?P=quote)"
)
_AUTHORIZATION_PATTERN = re.compile(
    r"(?i)(?P<prefix>\bauthorization\s*[:=]\s*)"
    r"(?:(?:basic|bearer|digest|token|negotiate)\s+)?[^\s,;\"'}\]]+"
)
_BEARER_PATTERN = re.compile(r"(?i)\bBearer\s+[^\s,;\"'}\]]+")
# 裸 JWT（eyJ 开头三段，无 key= 前缀也会命中）
_JWT_PATTERN = re.compile(r"\beyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\b")
# OpenAI 风格 API key（sk- 前缀，带长度下限避免误伤普通缩写）
_OPENAI_KEY_PATTERN = re.compile(r"\bsk-[A-Za-z0-9_-]{16,}\b")
_SENSITIVE_QUERY_PATTERN = re.compile(
    r"(?i)(?P<prefix>[?&](?:access_token|refresh_token|id_token|authorization|cookie|otp|code|token|state|nonce|code_verifier|oai-sc|api_key|apikey|client_secret|password)=)"
    r"[^&#\s]*"
)
_REDACTED = "[REDACTED]"


def diagnostic_excerpt(value: object, limit: int = 1000) -> str:
    """Return a bounded diagnostic string for logs and upstream error details."""
    text = str(value or "").strip()
    if len(text) <= limit:
        return text
    return text[: limit - 15].rstrip() + "...[truncated]"


def redact_auth_diagnostic(value: object, limit: int = 1000) -> str:
    """Return a bounded diagnostic string with authentication secrets removed."""
    text = str(value or "").strip()
    text = _AUTHORIZATION_PATTERN.sub(
        lambda match: f"{match.group('prefix')}{_REDACTED}",
        text,
    )
    text = _BEARER_PATTERN.sub(f"Bearer {_REDACTED}", text)
    text = _JWT_PATTERN.sub(_REDACTED, text)
    text = _OPENAI_KEY_PATTERN.sub(_REDACTED, text)
    text = _SENSITIVE_QUERY_PATTERN.sub(
        lambda match: f"{match.group('prefix')}{_REDACTED}",
        text,
    )
    text = _AUTH_SECRET_PATTERN.sub(
        lambda match: f"{match.group('prefix')}{match.group('quote')}{_REDACTED}{match.group('quote')}",
        text,
    )
    return diagnostic_excerpt(text, limit)


def _redact_nested(value: Any, limit: int) -> Any:
    """递归脱敏：str 过 redact_auth_diagnostic；dict/list 逐层处理；其它原样。"""
    if isinstance(value, str):
        return redact_auth_diagnostic(value, limit)
    if isinstance(value, dict):
        return {k: _redact_nested(v, limit) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_redact_nested(v, limit) for v in value]
    return value


def exception_diagnostic_fields(
    exc: Exception,
    *,
    include_status_code: bool = False,
    string_limit: int = 4000,
) -> dict[str, Any]:
    fields: dict[str, Any] = {}
    attrs = EXCEPTION_DIAGNOSTIC_ATTRS
    if include_status_code:
        attrs = (("status_code", "status_code"), *attrs)
    for attr, key in attrs:
        if not hasattr(exc, attr):
            continue
        value = getattr(exc, attr)
        if value in (None, ""):
            continue
        # str 与嵌套结构统一脱敏（防 access_token/Bearer 等落日志/账本）
        fields[key] = _redact_nested(value, string_limit)
    if "raw_upstream_message" not in fields and hasattr(exc, "last_assistant_text"):
        value = getattr(exc, "last_assistant_text")
        if value not in (None, ""):
            fields["raw_upstream_message"] = _redact_nested(value, string_limit)
    followup = fields.get("stream_timeout_followup")
    if isinstance(followup, dict) and "diagnosis" not in fields:
        fields["diagnosis"] = followup
    return fields
