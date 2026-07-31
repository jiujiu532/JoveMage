from __future__ import annotations

import base64
import hashlib
import json
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterable, Iterator

import tiktoken

from services.account_service import ImageAccountSelectionError, account_service
from services.backends.firefly_image_utils import fetch_image_bytes as firefly_fetch
from services.config import config
from services.image_failure import FAILURE_CODE_ALIASES as _IMAGE_FAILURE_CODE_ALIASES
from services.image_failure import ImageFailure, classify_image_exception, image_failure
from services.image_storage_service import image_storage_service
from services.image_upscale_service import upscale_image_if_needed
from services.openai_backend_api import ImageContentPolicyError, ImagePollTimeoutError, ImageTextReplyError, OpenAIBackendAPI
from services.proxy_service import proxy_settings
from services.realtime_monitor_service import realtime_monitor_service
from services.request_cancel_service import RequestCancelledError, request_cancel_service
from utils.helper import (
    IMAGE_MODELS,
    extract_image_from_message_content,
    is_codex_image_model,
    is_firefly_model,
    is_firefly_video_model,
    is_supported_image_model,
    split_image_model,
)
from utils.image_tokens import count_image_content_tokens
from utils.log import logger
from utils.diagnostics import diagnostic_excerpt


class ImageGenerationError(Exception):
    def __init__(
        self,
        message: str,
        status_code: int = 502,
        error_type: str = "server_error",
        code: str | None = "upstream_error",
        param: str | None = None,
        account_email: str = "",
        conversation_id: str = "",
        raw_error: str = "",
        upstream_error: str = "",
        raw_upstream_message: str = "",
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.error_type = error_type
        self.code = code
        self.param = param
        self.account_email = account_email
        self.conversation_id = conversation_id
        self.raw_error = raw_error
        self.upstream_error = upstream_error
        self.raw_upstream_message = raw_upstream_message

    def to_openai_error(self) -> dict[str, Any]:
        error_dict = {
            "error": {
                "message": public_image_error_message(str(self), code=self.code),
                "type": self.error_type,
                "param": self.param,
                "code": self.code,
            }
        }
        if self.account_email:
            error_dict["error"]["account_email"] = self.account_email
        return error_dict


# 轨道 B 步骤5：结构化错误分类优先，字符串启发式作为兜底（见
# .trellis/tasks/07-26-sync-upstream-271/design.md）。
#
# 本仓库自定义的 18 处调用点与下面这套字符串启发式判断函数（_is_image_quota_error 等）
# 全部原样保留，只是在它们之前新增一层「结构化 code 判定」：
# 调用方（services/protocol/conversation.py 自身 _generate_single_image 等处、
# services/account_service.py 的 ImageAccountSelectionError）现在大多已经显式传入
# 与 services/image_failure.py 的 FAILURE_POLICIES / FAILURE_CODE_ALIASES 一致的
# 结构化失败码（如 "insufficient_quota"、"image_poll_timeout"、
# "content_policy_violation" 等），因此优先按 code 归类比逐条 in lower 扫描原始文本更可靠。
# 若 code 为空或不在已知映射表内（例如历史调用只传了裸消息），则完全退回原有的
# 字符串启发式链路，保证行为不回归。
_IMAGE_TEXT_REVIEW_FAILURE_CODES = frozenset({
    "content_policy_violation",
    "invalid_image_input",
    "upstream_text_reply",
    "no_image_generated",
})

_IMAGE_FRIENDLY_KEY_BY_FAILURE_CODE: dict[str, str] = {
    "image_quota_exhausted": "quota",
    "insufficient_quota": "quota",
    "no_available_account": "no_account",
    "unsupported_model": "unsupported_model",
    "image_poll_timeout": "poll_timeout",
    "image_stream_interrupted": "stream_interrupted",
    "image_stream_timeout": "stream_interrupted",
    "upstream_connection_failed": "connection_failed",
    "upstream_connection_timeout": "connection_timeout",
    "auth_invalid": "token_invalid",
}


def _normalized_image_failure_code(code: str | None) -> str:
    normalized = str(code or "").strip().lower()
    return _IMAGE_FAILURE_CODE_ALIASES.get(normalized, normalized)


def public_image_error_message(message: str, code: str | None = None) -> str:
    text = str(message or "").strip()
    lower = text.lower()
    if not config.image_error_friendly_enabled:
        return _legacy_public_image_error_message(text)
    normalized_code = _normalized_image_failure_code(code)
    if normalized_code in _IMAGE_TEXT_REVIEW_FAILURE_CODES:
        return _public_text_reply_message(text)
    friendly_key = _IMAGE_FRIENDLY_KEY_BY_FAILURE_CODE.get(normalized_code)
    if friendly_key:
        return _friendly_image_error_message(friendly_key)
    if not text:
        return _friendly_image_error_message("fallback")
    selection_key = _image_account_selection_error_key(lower)
    if selection_key:
        return _friendly_image_error_message(selection_key)
    if _is_image_quota_error(lower):
        return _friendly_image_error_message("quota")
    if _is_local_image_busy_error(lower):
        return _friendly_image_error_message("local_busy")
    if "unsupported image model" in lower:
        return _friendly_image_error_message("unsupported_model")
    if _is_image_poll_timeout_error(lower):
        return _friendly_image_error_message("poll_timeout")
    if is_stream_transport_error(text):
        return _friendly_image_error_message("stream_interrupted")
    if is_connection_timeout_error(text):
        return _friendly_image_error_message("connection_timeout")
    if is_tls_connection_error(text):
        return _friendly_image_error_message("connection_failed")
    if _is_upstream_text_reply_error(text):
        return _public_text_reply_message(text)
    if any(item in lower for item in ("backend-api/", "status=", "body=", "chatgpt.com", "upstreamhttperror")):
        return _friendly_image_error_message("fallback")
    return text or _friendly_image_error_message("fallback")


def _legacy_public_image_error_message(message: str) -> str:
    text = str(message or "").strip()
    lower = text.lower()
    fallback = "The image generation request failed. Please try again later."
    if any(item in lower for item in ("backend-api/", "status=", "body=", "chatgpt.com", "upstreamhttperror")):
        return fallback
    return text or fallback


def _friendly_image_error_message(key: str, text: str = "") -> str:
    messages = config.get_image_error_messages()
    template = str(messages.get(key) or messages.get("fallback") or "图片生成请求失败，请稍后重试。").strip()
    if text:
        if "{text}" in template:
            return template.replace("{text}", text)
        return f"{template}\n文本如下：{text}"
    return template.replace("{text}", "").strip()


def _public_text_excerpt(message: str, limit: int = 260) -> str:
    text = str(message or "").strip()
    text = re.sub(r"(?i)^status(?:_code)?\s*=\s*\d+\s*[,，:：]?\s*", "", text)
    text = re.sub(r"(?i)^error\s*[:：]\s*", "", text)
    text = " ".join(text.split())
    lower = text.lower()
    if any(item in lower for item in ("backend-api/", "authorization", "access_token", "refresh_token", "cookie", "bearer ")):
        return ""
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "..."


def _public_text_reply_message(message: str) -> str:
    excerpt = _public_text_excerpt(message)
    return _friendly_image_error_message("text_reply", excerpt) if excerpt else _friendly_image_error_message("text_reply")


def _is_image_quota_error(lower: str) -> bool:
    return (
        "image_account_selection:quota_exhausted" in lower
        or "insufficient_quota" in lower
    )


def _image_account_selection_error_key(lower: str) -> str:
    if "image_account_selection:quota_exhausted" in lower:
        return "quota"
    if "image_account_selection:unavailable" in lower:
        return "no_account"
    return ""


def _is_local_image_busy_error(lower: str) -> bool:
    return (
        "no account in the pool" in lower
        or "no available image quota" in lower
        or "account concurrency" in lower
        or "server busy" in lower
        or "local busy" in lower
        or "rate-limit status" in lower
    )


def _is_image_poll_timeout_error(lower: str) -> bool:
    return (
        "生图超时" in lower
        or "imagepolltimeouterror" in lower
        or "image_poll_timeout" in lower
        or "poll timeout" in lower
        or "image_poll_timeout_secs" in lower
    )


def _is_upstream_text_reply_error(message: str) -> bool:
    lower = str(message or "").lower()
    return (
        is_model_text_reply_instead_of_image(message)
        or "upstream completed without generating images" in lower
        or "no image result found" in lower
        or "returned a text description" in lower
        or "content_policy_violation" in lower
        or "防护限制" in message
        or "违反" in message
        or "裸露" in message
        or "色情" in message
        or "情色" in message
    )


def _is_content_policy_image_message(message: str) -> bool:
    text = str(message or "")
    lower = text.lower()
    return (
        "content policy" in lower
        or "policy violation" in lower
        or "content_policy_violation" in lower
        or "safety" in lower and "policy" in lower
        or "防护限制" in text
        or "可能违反" in text
        or "违反" in text
        or "裸露" in text
        or "色情" in text
        or "情色" in text
    )


def _image_message_error_metadata(message: str) -> tuple[int, str, str]:
    if _is_content_policy_image_message(message):
        return 400, "invalid_request_error", "content_policy_violation"
    if is_model_text_reply_instead_of_image(message):
        return 400, "invalid_request_error", "upstream_text_reply"
    return 400, "invalid_request_error", "no_image_generated"


def _monitor_image_stage(request: "ConversationRequest", event: str, **data: Any) -> None:
    if request.trace_image_perf and request.call_id:
        realtime_monitor_service.stage(request.call_id, event, model=request.model, **data)


def _raise_if_request_cancelled(request: "ConversationRequest") -> None:
    if request.call_id:
        request_cancel_service.raise_if_cancelled(request.call_id)


def _elapsed_ms(started: float) -> int:
    return int((time.perf_counter() - started) * 1000)


def _proxy_hash(proxy_url: object) -> str:
    value = str(proxy_url or "").strip()
    if not value:
        return "direct"
    return hashlib.sha1(value.encode("utf-8")).hexdigest()[:8]


def _backend_egress_data(backend: OpenAIBackendAPI) -> dict[str, Any]:
    profile = getattr(backend, "proxy_profile", None)
    proxy_url = getattr(profile, "proxy_url", "") if profile else ""
    return {
        "proxy_source": str(getattr(profile, "proxy_source", "") or "direct"),
        "proxy_hash": _proxy_hash(proxy_url),
        "egress_key": str(getattr(profile, "egress_key", "") or "direct"),
        "egress_label": str(getattr(profile, "egress_label", "") or ""),
        "proxy_group_id": str(getattr(profile, "proxy_group_id", "") or ""),
        "proxy_node_id": str(getattr(profile, "proxy_node_id", "") or ""),
        "proxy_node_name": str(getattr(profile, "proxy_node_name", "") or ""),
        "image_egress_limit": int(getattr(profile, "image_concurrency_limit", 0) or 0),
        "has_proxy": bool(proxy_url),
        "egress_mode": str(getattr(profile, "egress_mode", "") or "direct"),
    }


def _backend_http_timing_data(backend: OpenAIBackendAPI | None, name: str = "image_generation_stream") -> dict[str, Any]:
    if backend is None or not hasattr(backend, "pop_http_timing"):
        return {}
    try:
        return backend.pop_http_timing(name)
    except Exception:
        return {}


_IMAGE_PROGRESS_STAGE_EVENTS = {
    "uploading": "image_uploading",
    "bootstrapping": "image_bootstrapping",
    "getting_token": "image_getting_token",
    "preparing_conversation": "image_preparing_conversation",
    "starting_generation": "image_starting_generation",
    "generating": "image_generating",
}

_IMAGE_PROGRESS_DURATION_KEYS = {
    "uploading": "upload_ms",
    "bootstrapping": "bootstrap_ms",
    "getting_token": "requirements_ms",
    "preparing_conversation": "prepare_conversation_ms",
    "starting_generation": "generation_start_ms",
}


def _image_progress_callback_with_monitor(
        request: "ConversationRequest",
        index: int,
        total: int,
        account_email_getter: Callable[[], str],
) -> Callable[[str], None]:
    original_callback = request.progress_callback
    last_step = ""
    last_step_started = time.perf_counter()

    def report(step: str) -> None:
        nonlocal last_step, last_step_started
        now = time.perf_counter()
        step_name = str(step or "").strip()
        data: dict[str, Any] = {
            "index": index,
            "total": total,
        }
        account_email = account_email_getter()
        if account_email:
            data["account_email"] = account_email
        duration_key = _IMAGE_PROGRESS_DURATION_KEYS.get(last_step)
        if duration_key:
            data[duration_key] = int((now - last_step_started) * 1000)
        stage_event = _IMAGE_PROGRESS_STAGE_EVENTS.get(step_name)
        if stage_event:
            _monitor_image_stage(request, stage_event, **data)
        last_step = step_name
        last_step_started = now
        if original_callback:
            original_callback(step_name)

    return report


def _resolve_image_urls_with_monitor(
        backend: OpenAIBackendAPI,
        request: "ConversationRequest",
        conversation_id: str,
        file_ids: list[str],
        sediment_ids: list[str],
        index: int,
        total: int,
        path: str = "",
        **kwargs: Any,
) -> list[str]:
    resolve_started = time.perf_counter()
    try:
        image_urls = backend.resolve_conversation_image_urls(
            conversation_id,
            file_ids,
            sediment_ids,
            **kwargs,
        )
    except Exception as exc:
        text_reply = isinstance(exc, ImageTextReplyError)
        if request.trace_image_perf:
            resolve_ms = _elapsed_ms(resolve_started)
            _monitor_image_stage(
                request,
                "image_text_reply" if text_reply else "image_resolve_failed",
                conversation_id=conversation_id,
                resolve_ms=resolve_ms,
                index=index,
                total=total,
                status="failed",
                upstream_error=diagnostic_excerpt(repr(exc), 1000),
            )
            log_payload: dict[str, Any] = {
                "event": "image_text_reply" if text_reply else "image_resolve_failed",
                "call_id": request.call_id,
                "conversation_id": conversation_id,
                "resolve_ms": resolve_ms,
                "error": repr(exc)[:300],
            }
            if path:
                log_payload["path"] = path
            if text_reply:
                logger.info(log_payload)
            else:
                logger.warning(log_payload)
        raise
    if request.trace_image_perf:
        resolve_ms = _elapsed_ms(resolve_started)
        _monitor_image_stage(
            request,
            "image_resolve_done",
            conversation_id=conversation_id,
            resolve_ms=resolve_ms,
            url_count=len(image_urls),
            index=index,
            total=total,
        )
        log_payload = {
            "event": "image_resolve_done",
            "call_id": request.call_id,
            "conversation_id": conversation_id,
            "resolve_ms": resolve_ms,
            "url_count": len(image_urls),
        }
        if path:
            log_payload["path"] = path
        logger.info(log_payload)
    return image_urls


def _download_image_bytes_with_monitor(
        backend: OpenAIBackendAPI,
        request: "ConversationRequest",
        conversation_id: str,
        image_urls: list[str],
        index: int,
        total: int,
        path: str = "",
) -> list[bytes]:
    download_started = time.perf_counter()
    try:
        downloaded_images = backend.download_image_bytes(image_urls)
    except Exception as exc:
        if request.trace_image_perf:
            download_ms = _elapsed_ms(download_started)
            _monitor_image_stage(
                request,
                "image_download_failed",
                conversation_id=conversation_id,
                download_ms=download_ms,
                url_count=len(image_urls),
                index=index,
                total=total,
                status="failed",
                upstream_error=diagnostic_excerpt(repr(exc), 1000),
            )
            log_payload: dict[str, Any] = {
                "event": "image_download_failed",
                "call_id": request.call_id,
                "conversation_id": conversation_id,
                "download_ms": download_ms,
                "url_count": len(image_urls),
                "error": repr(exc)[:300],
            }
            if path:
                log_payload["path"] = path
            logger.warning(log_payload)
        raise
    if request.trace_image_perf:
        download_ms = _elapsed_ms(download_started)
        download_bytes = sum(len(image) for image in downloaded_images)
        download_kbps = int((download_bytes / 1024) / (download_ms / 1000)) if download_ms > 0 else 0
        _monitor_image_stage(
            request,
            "image_download_done",
            conversation_id=conversation_id,
            download_ms=download_ms,
            download_bytes=download_bytes,
            download_kbps=download_kbps,
            url_count=len(image_urls),
            image_count=len(downloaded_images),
            index=index,
            total=total,
        )
        log_payload = {
            "event": "image_download_done",
            "call_id": request.call_id,
            "conversation_id": conversation_id,
            "download_ms": download_ms,
            "download_bytes": download_bytes,
            "download_kbps": download_kbps,
            "url_count": len(image_urls),
            "image_count": len(downloaded_images),
        }
        if path:
            log_payload["path"] = path
        logger.info(log_payload)
    return downloaded_images


def _retry_sleep_with_monitor(
        request: "ConversationRequest",
        seconds: float,
        *,
        conversation_id: str = "",
        account_email: str = "",
        index: int = 1,
        total: int = 1,
) -> None:
    wait_secs = max(0.0, float(seconds or 0))
    _monitor_image_stage(
        request,
        "image_retry_wait",
        conversation_id=conversation_id,
        account_email=account_email,
        retry_wait_ms=int(wait_secs * 1000),
        index=index,
        total=total,
        status="waiting",
    )
    if wait_secs > 0:
        time.sleep(wait_secs)


def is_token_invalid_error(message: str) -> bool:
    text = str(message or "").lower()
    return (
        "token_invalidated" in text
        or "token_revoked" in text
        or "authentication token has been invalidated" in text
        or "invalidated oauth token" in text
    )


def is_tls_connection_error(message: str) -> bool:
    """检测 TLS/SSL 连接错误，这类错误通常可以通过重试解决。"""
    text = str(message or "").lower()
    return (
        "curl: (35)" in text
        or "tls connect error" in text
        or "openssl_internal" in text
        or "ssl: wrong_version_number" in text
        or "ssl: certificate_verify_failed" in text
        or "connection aborted" in text
        or "remote disconnected" in text
        or "connection reset by peer" in text
        or "upstream image connection failed" in text
    )


def is_connection_timeout_error(message: str) -> bool:
    """检测连接超时错误（如 curl 28），这类错误可通过同账号短等待重试解决。"""
    text = str(message or "").lower()
    return (
        "curl: (28)" in text
        or "operation timed out" in text
        or "connection timed out" in text
        or "read timed out" in text
        or "connect timeout" in text
        or "upstream connection timed out" in text
    )


def is_stream_transport_error(message: str) -> bool:
    """检测上游流式响应传输错误，这类错误通常来自 HTTP/2/SSE/代理长连接。"""
    text = str(message or "").lower()
    return (
        "curl: (92)" in text
        or "http/2 stream" in text
        or "internal_error" in text
        or "stream was not closed cleanly" in text
        or "stream reset" in text
        or "response ended prematurely" in text
        or "sse stream exceeded" in text
        or "upstream image stream interrupted" in text
    )


def image_stream_error_message(message: str) -> str:
    text = str(message or "")
    if not config.image_error_friendly_enabled:
        return _legacy_image_stream_error_message(text)
    if is_token_invalid_error(text):
        return _friendly_image_error_message("token_invalid")
    if is_stream_transport_error(text):
        return _friendly_image_error_message("stream_interrupted")
    if is_tls_connection_error(text):
        return _friendly_image_error_message("connection_failed")
    if is_connection_timeout_error(text):
        return _friendly_image_error_message("connection_timeout")
    return text or _friendly_image_error_message("fallback")


def _legacy_image_stream_error_message(message: str) -> str:
    text = str(message or "")
    if is_token_invalid_error(text):
        return "image generation failed"
    if is_stream_transport_error(text):
        return "upstream image stream interrupted, please retry later"
    if is_tls_connection_error(text):
        return "upstream image connection failed, please retry later"
    if is_connection_timeout_error(text):
        return "upstream connection timed out, please retry later"
    return text or "image generation failed"


REFERENCED_IMAGE_IDS_RE = re.compile(r'"referenced_image_ids"\s*:\s*\[([^\]]+)\]')
# 检测模型返回的部分工具调用 JSON（如 {"size":"1920x1088","n":1}）
# 这些 JSON 包含图片生成工具的参数，但没有实际生成图片
TOOL_PARAMS_JSON_RE = re.compile(
    r'\{\s*"size"\s*:\s*"\d+x\d+"\s*,\s*"n"\s*:\s*\d+\s*\}'
)


def is_model_text_reply_instead_of_image(message: str) -> bool:
    """检测模型是否返回了文本回复（包含工具调用 JSON）而非实际生成图片。

    当上游 ChatGPT 未能触发图片生成工具时，会返回一段描述性文本，
    其中可能包含 JSON 参数（如 prompt、referenced_image_ids、size/n 等）。
    这种情况应被视为「上游未生成图片」而非「内容策略违规」。

    检测两种模式：
    1. 完整的工具调用 JSON（含 referenced_image_ids）
    2. 部分的工具参数 JSON（如 {"size":"1920x1088","n":1}）
    """
    if not message:
        return False
    if REFERENCED_IMAGE_IDS_RE.search(message):
        return True
    # 检测部分工具参数 JSON（模型返回了工具参数但未触发工具）
    if TOOL_PARAMS_JSON_RE.search(message):
        return True
    return False


def encode_images(images: Iterable[tuple[bytes, str, str]]) -> list[str]:
    return [base64.b64encode(data).decode("ascii") for data, _, _ in images if data]


def save_image_bytes(image_data: bytes, base_url: str | None = None) -> str:
    return image_storage_service.save(image_data, base_url).url


def message_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict) and str(item.get("type") or "") in {"text", "input_text", "output_text"}:
                parts.append(str(item.get("text") or ""))
        return "".join(parts)
    return ""


def normalize_messages(messages: object, system: Any = None) -> list[dict[str, Any]]:
    normalized = []
    if config.global_system_prompt:
        normalized.append({"role": "system", "content": config.global_system_prompt})
    system_text = message_text(system)
    if system_text:
        normalized.append({"role": "system", "content": system_text})
    if isinstance(messages, list):
        for message in messages:
            if not isinstance(message, dict):
                continue
            role = message.get("role", "user")
            content = message.get("content", "")
            text = message_text(content)
            images: list[tuple[bytes, str]] = []
            if role == "user":
                images.extend(extract_image_from_message_content(content))
                if isinstance(content, list):
                    for part in content:
                        if not isinstance(part, dict) or part.get("type") != "image":
                            continue
                        data = part.get("data")
                        if isinstance(data, (bytes, bytearray)) and all(existing[0] != bytes(data) for existing in images):
                            images.append((bytes(data), str(part.get("mime") or "image/png")))
            if images:
                parts: list[Any] = []
                if text:
                    parts.append({"type": "text", "text": text})
                for data, mime in images:
                    parts.append({"type": "image", "data": data, "mime": mime})
                normalized.append({"role": role, "content": parts})
            else:
                normalized.append({"role": role, "content": text})
    return normalized


def prompt_with_global_system(prompt: str) -> str:
    return f"{config.global_system_prompt}\n\n{prompt}" if config.global_system_prompt else prompt


def assistant_history_text(messages: list[dict[str, Any]]) -> str:
    return "".join(str(item.get("content") or "") for item in messages if item.get("role") == "assistant")


def assistant_history_messages(messages: list[dict[str, Any]]) -> list[str]:
    return [str(item.get("content") or "") for item in messages if item.get("role") == "assistant" and item.get("content")]


def build_image_prompt(prompt: str, size: str | None, quality: str = "auto") -> str:
    hints = []
    if size:
        hints.append(f"输出图片尺寸为 {size}。")
    if quality:
        hints.append(f"输出图片质量为 {quality}。")
    return f"{prompt.strip()}\n\n{''.join(hints)}" if hints else prompt


def encoding_for_model(model: str):
    try:
        return tiktoken.encoding_for_model(model)
    except KeyError:
        try:
            return tiktoken.get_encoding("o200k_base")
        except KeyError:
            return tiktoken.get_encoding("cl100k_base")


def count_message_image_tokens(messages: list[dict[str, Any]], model: str) -> int:
    return sum(count_image_content_tokens(message.get("content"), model) for message in messages)


def count_message_text_tokens(messages: list[dict[str, Any]], model: str) -> int:
    encoding = encoding_for_model(model)
    total = 0
    for message in messages:
        total += 3
        for key, value in message.items():
            if key == "content" and isinstance(value, list):
                total += len(encoding.encode(message_text(value)))
            elif isinstance(value, str):
                total += len(encoding.encode(value))
            else:
                continue
            if key == "name":
                total += 1
    return total + 3


def count_message_tokens(messages: list[dict[str, Any]], model: str) -> int:
    return count_message_text_tokens(messages, model) + count_message_image_tokens(messages, model)


def count_text_tokens(text: str, model: str) -> int:
    return len(encoding_for_model(model).encode(text))


def format_image_result(
    items: list[dict[str, Any]],
    prompt: str,
    response_format: str,
    base_url: str | None = None,
    created: int | None = None,
    message: str = "",
    requested_size: str | None = None,
) -> dict[str, Any]:
    data: list[dict[str, Any]] = []
    for item in items:
        b64_json = str(item.get("b64_json") or "").strip()
        if not b64_json:
            continue
        revised_prompt = str(item.get("revised_prompt") or prompt).strip() or prompt
        image_bytes = upscale_image_if_needed(base64.b64decode(b64_json), requested_size)
        stored_url = save_image_bytes(image_bytes, base_url)
        if response_format == "b64_json":
            data.append({
                "b64_json": base64.b64encode(image_bytes).decode("ascii"),
                "url": stored_url,
                "revised_prompt": revised_prompt,
            })
        else:
            data.append({
                "url": stored_url,
                "revised_prompt": revised_prompt,
            })
    result: dict[str, Any] = {"created": created or int(time.time()), "data": data}
    if message and not data:
        result["message"] = message
    return result


@dataclass
class ConversationRequest:
    model: str = "auto"
    prompt: str = ""
    messages: list[dict[str, Any]] | None = None
    thinking_effort: str = ""
    images: list[str] | None = None
    n: int = 1
    size: str | None = None
    quality: str = "auto"
    response_format: str = "b64_json"
    base_url: str | None = None
    message_as_error: bool = False
    progress_callback: Any = None  # Callable[[str], None] | None
    call_id: str = ""
    trace_image_perf: bool = False


@dataclass
class ConversationState:
    text: str = ""
    raw_text: str = ""
    conversation_id: str = ""
    file_ids: list[str] = field(default_factory=list)
    sediment_ids: list[str] = field(default_factory=list)
    blocked: bool = False
    tool_invoked: bool | None = None
    turn_use_case: str = ""


@dataclass
class ImageOutput:
    kind: str
    model: str
    index: int
    total: int
    created: int = field(default_factory=lambda: int(time.time()))
    text: str = ""
    upstream_event_type: str = ""
    data: list[dict[str, Any]] = field(default_factory=list)
    account_email: str = ""
    conversation_id: str = ""

    def to_chunk(self) -> dict[str, Any]:
        chunk: dict[str, Any] = {
            "object": "image.generation.chunk",
            "created": self.created,
            "model": self.model,
            "index": self.index,
            "total": self.total,
            "progress_text": self.text,
            "upstream_event_type": self.upstream_event_type,
            "data": [],
        }
        if self.account_email:
            chunk["_account_email"] = self.account_email
        if self.conversation_id:
            chunk["_conversation_id"] = self.conversation_id
        if self.kind == "message":
            chunk.update({
                "object": "image.generation.message",
                "message": self.text,
            })
            chunk.pop("progress_text", None)
            chunk.pop("upstream_event_type", None)
        elif self.kind == "result":
            chunk.update({
                "object": "image.generation.result",
                "data": self.data,
            })
            chunk.pop("progress_text", None)
            chunk.pop("upstream_event_type", None)
        return chunk


def assistant_message_text(message: dict[str, Any]) -> str:
    content = message.get("content") or {}
    parts = content.get("parts") or []
    if isinstance(parts, list) and parts:
        text = "".join(part for part in parts if isinstance(part, str))
        if text:
            return text
    # Fallback: content_type "code" stores text in the "text" field instead of "parts"
    text_field = str(content.get("text") or "")
    if text_field:
        return text_field
    return ""


def strip_history(text: str, history_text: str = "") -> str:
    text = str(text or "")
    history_text = str(history_text or "")
    while history_text and text.startswith(history_text):
        text = text[len(history_text):]
    return text


def sanitize_output_text(text: str) -> str:
    text = str(text or "")

    def is_internal_annotation_part(part: str) -> bool:
        value = part.strip()
        if not value:
            return True
        lower = value.lower()
        return bool(
            re.fullmatch(r"turn\d+[a-z]*\d*", lower)
            or re.fullmatch(r"turn\d+\w*", lower)
            or lower.startswith(("turn", "source", "sources"))
        )

    def readable_annotation_part(parts: list[str]) -> str:
        for part in parts:
            value = part.strip()
            if value and not is_internal_annotation_part(value):
                return value
        return ""

    def replace_annotation(match: re.Match[str]) -> str:
        payload = match.group(1)
        parts = [part.strip() for part in payload.split("\ue202")]
        kind = (parts[0] if parts else "").lower()
        data = parts[1:]
        if kind == "url":
            label = data[0] if data else ""
            url = data[1] if len(data) > 1 else ""
            if label and url.startswith(("http://", "https://")):
                return f"{label} ({url})"
            return label or url
        if kind == "cite":
            return readable_annotation_part(data)
        return readable_annotation_part(data)

    # ChatGPT web sometimes returns rich annotation markers using private-use
    # characters. API clients cannot render those. Preserve readable labels
    # from entity/link annotations, while removing internal citation pointers.
    text = re.sub(r"\ue200([^\ue201]*)\ue201", replace_annotation, text)
    text = re.sub(r"\ue200[^\ue201]*$", "", text)
    text = re.sub(r"\s+([.,;:!?])", r"\1", text)
    return text


def assistant_raw_text(event: dict[str, Any], current_text: str = "", history_text: str = "") -> str:
    for candidate in (event, event.get("v")):
        if not isinstance(candidate, dict):
            continue
        message = candidate.get("message")
        if not isinstance(message, dict):
            continue
        role = str((message.get("author") or {}).get("role") or "").strip().lower()
        if role != "assistant":
            continue
        text = assistant_message_text(message)
        if text:
            return strip_history(text, history_text)
    return apply_text_patch(event, current_text, history_text)


def assistant_text(event: dict[str, Any], current_text: str = "", history_text: str = "") -> str:
    return sanitize_output_text(assistant_raw_text(event, current_text, history_text))


def event_assistant_text(event: dict[str, Any], history_text: str = "") -> str:
    for candidate in (event, event.get("v")):
        if not isinstance(candidate, dict):
            continue
        message = candidate.get("message")
        if isinstance(message, dict) and (message.get("author") or {}).get("role") == "assistant":
            return strip_history(assistant_message_text(message), history_text)
    return ""


def apply_text_patch(event: dict[str, Any], current_text: str = "", history_text: str = "") -> str:
    if event.get("p") == "/message/content/parts/0":
        return apply_patch_op(event, current_text, history_text)

    operations = event.get("v")
    if isinstance(operations, str) and current_text and not event.get("p") and not event.get("o"):
        return current_text + operations

    if event.get("o") == "patch" and isinstance(operations, list):
        text = current_text
        for item in operations:
            if isinstance(item, dict):
                text = apply_text_patch(item, text, history_text)
        return text

    if not isinstance(operations, list):
        return current_text

    text = current_text
    for item in operations:
        if isinstance(item, dict):
            text = apply_text_patch(item, text, history_text)
    return text


def apply_patch_op(operation: dict[str, Any], current_text: str, history_text: str = "") -> str:
    op = operation.get("o")
    value = str(operation.get("v") or "")
    if op == "append":
        return current_text + value
    if op == "replace":
        return strip_history(value, history_text)
    return current_text


def add_unique(values: list[str], candidates: list[str]) -> None:
    for candidate in candidates:
        if candidate and candidate not in values:
            values.append(candidate)


FILE_SERVICE_ID_RE = re.compile(r"file-service://([A-Za-z0-9_-]+)")
FILE_ID_RE = re.compile(r"\b(file[-_](?!service\b)[A-Za-z0-9_-]+)\b")
# 真正的图片文件 ID 格式：file_00000000 + 24位十六进制字符（共32字符）
# 用于过滤非图片文件 ID（如 file_upload_business_upsell）
REAL_IMAGE_FILE_ID_RE = re.compile(r"\bfile_00000000[a-f0-9]{24}\b")
SEDIMENT_ID_RE = re.compile(r"sediment://([A-Za-z0-9_-]+)")


def extract_conversation_ids(payload: str) -> tuple[str, list[str], list[str]]:
    conversation_match = re.search(r'"conversation_id"\s*:\s*"([^"]+)"', payload)
    conversation_id = conversation_match.group(1) if conversation_match else ""
    file_ids: list[str] = []
    # Negative lookahead excludes "file-service" (URI prefix, not a real id).
    add_unique(file_ids, FILE_SERVICE_ID_RE.findall(payload))
    # 只提取真正的图片文件 ID（file_00000000... 格式），过滤非图片文件 ID（如 file_upload_business_upsell）
    add_unique(file_ids, REAL_IMAGE_FILE_ID_RE.findall(payload))
    sediment_ids = SEDIMENT_ID_RE.findall(payload)
    return conversation_id, file_ids, sediment_ids


def is_image_tool_event(event: dict[str, Any]) -> bool:
    value = event.get("v")
    message = event.get("message") or (value.get("message") if isinstance(value, dict) else None)
    if not isinstance(message, dict):
        return False
    metadata = message.get("metadata") or {}
    author = message.get("author") or {}
    content = message.get("content") or {}
    if author.get("role") != "tool":
        return False
    if metadata.get("async_task_type") == "image_gen":
        return True
    if content.get("content_type") != "multimodal_text":
        return False
    return any(
        isinstance(part, dict) and (
                part.get("content_type") == "image_asset_pointer"
                or str(part.get("asset_pointer") or "").startswith(("file-service://", "sediment://"))
        )
        for part in content.get("parts") or []
    )


def _is_user_message_event(event: dict[str, Any]) -> bool:
    """检查事件是否来自 user 角色消息。"""
    value = event.get("v")
    message = event.get("message") or (value.get("message") if isinstance(value, dict) else None)
    if isinstance(message, dict):
        author = message.get("author") or {}
        if str(author.get("role") or "").strip().lower() == "user":
            return True
    return False


def update_conversation_state(state: ConversationState, payload: str, event: dict[str, Any] | None = None) -> None:
    conversation_id, file_ids, sediment_ids = extract_conversation_ids(payload)
    if conversation_id and not state.conversation_id:
        state.conversation_id = conversation_id
    # Accept file_id / sediment_id when any of:
    #   1) event is a complete image_gen tool message
    #   2) prior server_ste_metadata already flipped tool_invoked True (in an image_gen turn),
    #      BUT only for non-user messages — user messages contain the uploaded input image
    #      which must NOT be treated as a generated output.
    #   3) patch event whose payload references asset_pointer / file-service://,
    #      BUT only when the event is not a user message.
    is_patch_event = isinstance(event, dict) and event.get("o") == "patch"
    is_user_msg = isinstance(event, dict) and _is_user_message_event(event)
    image_context = (
        (isinstance(event, dict) and is_image_tool_event(event))
        or (state.tool_invoked is True and not is_user_msg)
        or (is_patch_event and not is_user_msg and ("asset_pointer" in payload or "file-service://" in payload))
    )
    if image_context:
        add_unique(state.file_ids, file_ids)
        add_unique(state.sediment_ids, sediment_ids)
    if not isinstance(event, dict):
        return
    state.conversation_id = str(event.get("conversation_id") or state.conversation_id)
    value = event.get("v")
    if isinstance(value, dict):
        state.conversation_id = str(value.get("conversation_id") or state.conversation_id)
    if event.get("type") == "moderation":
        moderation = event.get("moderation_response")
        if isinstance(moderation, dict) and moderation.get("blocked") is True:
            state.blocked = True
    if event.get("type") == "server_ste_metadata":
        metadata = event.get("metadata")
        if isinstance(metadata, dict):
            if isinstance(metadata.get("tool_invoked"), bool):
                state.tool_invoked = metadata["tool_invoked"]
            state.turn_use_case = str(metadata.get("turn_use_case") or state.turn_use_case)


def conversation_base_event(event_type: str, state: ConversationState, **extra: Any) -> dict[str, Any]:
    return {
        "type": event_type,
        "text": state.text,
        "conversation_id": state.conversation_id,
        "file_ids": list(state.file_ids),
        "sediment_ids": list(state.sediment_ids),
        "blocked": state.blocked,
        "tool_invoked": state.tool_invoked,
        "turn_use_case": state.turn_use_case,
        **extra,
    }


def iter_conversation_payloads(payloads: Iterator[str], history_text: str = "",
                               history_messages: list[str] | None = None) -> Iterator[dict[str, Any]]:
    state = ConversationState()
    history_messages = history_messages or []
    history_index = 0
    # 最后一条 history 被 skip 时暂存；若整轮无新 delta，视为模型复述而非回放
    last_skipped_history_text = ""
    for payload in payloads:
        # print(f"[upstream_sse] {payload}", flush=True)
        if not payload:
            continue
        if payload == "[DONE]":
            # 仅 history 回放被 skip、全程无新增文本：把最后一次匹配当作真实回答吐出
            if not state.text and last_skipped_history_text:
                state.raw_text = last_skipped_history_text
                state.text = sanitize_output_text(last_skipped_history_text)
                yield conversation_base_event(
                    "conversation.delta",
                    state,
                    delta=state.text,
                )
            yield conversation_base_event("conversation.done", state, done=True)
            break
        try:
            event = json.loads(payload)
        except json.JSONDecodeError:
            update_conversation_state(state, payload)
            yield conversation_base_event("conversation.raw", state, payload=payload)
            continue
        if not isinstance(event, dict):
            yield conversation_base_event("conversation.event", state, raw=event)
            continue
        update_conversation_state(state, payload, event)
        # 历史回放：完整 assistant 消息精确等于下一条 history，且当前尚无新文本时才 skip。
        # 用未 strip 的全文匹配，避免 history_text 拼接干扰。
        full_assistant = event_assistant_text(event, "")
        if (
            history_index < len(history_messages)
            and full_assistant
            and full_assistant == history_messages[history_index]
            and not state.text
            and not state.raw_text
        ):
            history_index += 1
            if history_index >= len(history_messages):
                last_skipped_history_text = full_assistant
            else:
                last_skipped_history_text = ""
            state.raw_text = ""
            state.text = ""
            continue
        next_raw_text = assistant_raw_text(event, state.raw_text, history_text)
        next_text = sanitize_output_text(next_raw_text)
        state.raw_text = next_raw_text
        if next_text != state.text:
            # 已有真实增量，清空「最后 history 可能是复述」标记
            last_skipped_history_text = ""
            delta = next_text[len(state.text):] if next_text.startswith(state.text) else next_text
            state.text = next_text
            yield conversation_base_event("conversation.delta", state, raw=event, delta=delta)
            continue
        yield conversation_base_event("conversation.event", state, raw=event)


def conversation_events(
    backend: OpenAIBackendAPI,
    messages: list[dict[str, Any]] | None = None,
    model: str = "auto",
    prompt: str = "",
    images: list[str] | None = None,
    size: str | None = None,
    quality: str = "auto",
    thinking_effort: str = "",
) -> Iterator[dict[str, Any]]:
    normalized = normalize_messages(messages or ([{"role": "user", "content": prompt}] if prompt else []))
    image_model = is_supported_image_model(model)
    history_text = "" if image_model else assistant_history_text(normalized)
    history_messages = [] if image_model else assistant_history_messages(normalized)
    final_prompt = prompt_with_global_system(build_image_prompt(prompt, size, quality)) if image_model else prompt
    payloads = backend.stream_conversation(
        messages=normalized,
        model=model,
        prompt=final_prompt,
        images=images if image_model else None,
        system_hints=["picture_v2"] if image_model else None,
        thinking_effort=thinking_effort if not image_model else "",
    )
    yield from iter_conversation_payloads(payloads, history_text, history_messages)


def _text_account_email(access_token: str) -> str:
    account = account_service.get_account(access_token)
    if not account:
        return ""
    return str(account.get("email") or "").strip()


def _remember_text_account(backend: OpenAIBackendAPI, access_token: str) -> str:
    email = _text_account_email(access_token)
    setattr(backend, "account_email", email)
    return email


def text_backend() -> OpenAIBackendAPI:
    access_token = account_service.get_text_access_token()
    backend = OpenAIBackendAPI(access_token=access_token)
    _remember_text_account(backend, access_token)
    return backend


def stream_text_deltas(backend: OpenAIBackendAPI, request: ConversationRequest) -> Iterator[str]:
    attempted_tokens: set[str] = set()
    token = getattr(backend, "access_token", "")
    emitted = False
    try:
        while True:
            if token and token in attempted_tokens:
                raise RuntimeError("no available text account")
            if token:
                attempted_tokens.add(token)
            active_backend: OpenAIBackendAPI | None = None
            try:
                _remember_text_account(backend, token)
                active_backend = OpenAIBackendAPI(access_token=token)
                _remember_text_account(active_backend, token)
                for event in conversation_events(
                    active_backend,
                    messages=request.messages,
                    model=request.model,
                    prompt=request.prompt,
                    thinking_effort=request.thinking_effort,
                ):
                    if event.get("type") != "conversation.delta":
                        continue
                    delta = str(event.get("delta") or "")
                    if delta:
                        emitted = True
                        yield delta
                account_service.mark_text_used(token)
                return
            except Exception as exc:
                error_message = str(exc)
                if token and not emitted and is_token_invalid_error(error_message):
                    # force refresh 瞬时失败会 re-raise：此时 token 未必真失效，
                    # 不标 handle_invalid，直接换号重试，由下一次 401 再定夺。
                    try:
                        refreshed_token = account_service.refresh_access_token(token, force=True, event="text_stream")
                    except Exception:
                        token = account_service.get_text_access_token(attempted_tokens)
                        if token:
                            continue
                        raise
                    if refreshed_token and refreshed_token != token and refreshed_token not in attempted_tokens:
                        token = refreshed_token
                    else:
                        account_service.handle_invalid_token(token, "text_stream", error=error_message)
                        token = account_service.get_text_access_token(attempted_tokens)
                    if token:
                        continue
                if token and not getattr(exc, "account_email", ""):
                    setattr(exc, "account_email", _text_account_email(token))
                raise
            finally:
                if active_backend is not None:
                    active_backend.close()
    finally:
        # text_backend() 创建的 session 只用于持有 token/email，真正请求走 active_backend；
        # 这里统一关闭，避免调用方忘记 close 导致连接泄漏。
        close = getattr(backend, "close", None)
        if callable(close):
            close()


def collect_text(backend: OpenAIBackendAPI, request: ConversationRequest) -> str:
    return "".join(stream_text_deltas(backend, request))


def _get_detailed_error_from_tasks(
    backend: OpenAIBackendAPI,
    conversation_id: str,
    timeout_secs: float = 10.0,
    wait_secs: float = 2.0,
) -> str:
    """从 /backend-api/tasks/ 接口获取结构化错误信息。

    当 SSE 流检测到 moderation 拦截时，轮询 tasks 接口获取详细错误文本。
    使用结构化字段（metadata.is_error, author.role, content.content_type）判断，
    而非依赖易变的文本匹配。

    参数：
    - `backend`：OpenAIBackendAPI 实例。
    - `conversation_id`：会话 ID。
    - `timeout_secs`：请求超时秒数。
    - `wait_secs`：等待任务创建的秒数。设为 0 可跳过等待。

    返回：
    - 详细错误信息文本，如果未找到则返回空字符串。
    """
    import time as _time
    try:
        if wait_secs > 0:
            _time.sleep(wait_secs)
        tasks = backend._query_backend_tasks(conversation_id=conversation_id, timeout_secs=timeout_secs)
        if not tasks:
            return ""

        for task in tasks:
            is_error, error_msg, metadata = backend.check_task_error(task)
            if is_error and error_msg:
                logger.info({
                    "event": "image_task_structured_error",
                    "conversation_id": conversation_id,
                    "error_msg": error_msg,
                    "metadata": metadata,
                })
                return error_msg
        return ""
    except Exception as exc:
        logger.warning({
            "event": "image_task_error_query_failed",
            "conversation_id": conversation_id,
            "error": diagnostic_excerpt(exc, 300),
        })
        return ""


def _recover_image_conversation_id(
        backend: OpenAIBackendAPI,
        request: ConversationRequest,
        *,
        reason: str,
        message: str = "",
        started_at: float | None = None,
) -> str:
    """从最近对话中补救 conversation_id；只做一次，失败不影响主流程。"""
    if not request.prompt:
        return ""
    try:
        recovered_id = backend.find_conversation_by_prompt(
            request.prompt,
            started_at or time.time(),
            timeout_secs=5.0,
        )
        if recovered_id:
            logger.info({
                "event": "image_conversation_id_recovered",
                "reason": reason,
                "conversation_id": recovered_id,
                "message_preview": message[:200],
            })
            return recovered_id
    except Exception as exc:
        logger.warning({
            "event": "image_conversation_id_recovery_failed",
            "reason": reason,
            "error": repr(exc)[:300],
        })
    return ""


def _image_stream_timeout_task_diagnostics(
        backend: OpenAIBackendAPI,
        conversation_id: str,
) -> tuple[str, list[dict[str, Any]], str]:
    """Collect a small task summary after an upstream SSE timeout."""
    try:
        tasks = backend._query_backend_tasks(conversation_id=conversation_id, timeout_secs=5.0)
    except Exception as exc:
        return "", [], diagnostic_excerpt(repr(exc), 1000)

    summaries: list[dict[str, Any]] = []
    first_error = ""
    for task in tasks[:5]:
        if not isinstance(task, dict):
            continue
        is_error, error_msg, metadata = backend.check_task_error(task)
        metadata = metadata if isinstance(metadata, dict) else {}
        if error_msg and not first_error:
            first_error = error_msg
        summary: dict[str, Any] = {
            "id": str(task.get("id") or task.get("task_id") or "")[:80],
            "status": str(task.get("status") or metadata.get("status") or "")[:80],
            "type": str(task.get("type") or metadata.get("async_task_type") or "")[:80],
            "is_error": bool(is_error or metadata.get("is_error")),
        }
        for key in ("conversation_id", "original_conversation_id"):
            value = task.get(key)
            if value not in (None, ""):
                summary[key] = str(value)[:80]
        if error_msg:
            summary["error_preview"] = diagnostic_excerpt(error_msg, 500)
        summaries.append({key: value for key, value in summary.items() if value not in (None, "")})
    return first_error, summaries, ""


def _image_stream_timeout_error(
        raw_error: str,
        conversation_id: str,
        upstream_error: str,
        raw_upstream_message: str,
        followup: dict[str, Any],
        conversation_snapshot: dict[str, Any] | None = None,
) -> ImageGenerationError:
    exc = ImageGenerationError(
        image_stream_error_message(raw_error),
        status_code=502,
        error_type="server_error",
        code="image_stream_timeout",
        conversation_id=conversation_id,
        raw_error=raw_error,
        upstream_error=diagnostic_excerpt(upstream_error or raw_error, 4000),
        raw_upstream_message=diagnostic_excerpt(raw_upstream_message, 4000),
    )
    setattr(exc, "stream_timeout_secs", config.image_stream_timeout_secs)
    setattr(exc, "stream_timeout_followup", followup)
    if followup.get("task_error"):
        setattr(exc, "last_task_error", followup["task_error"])
    if conversation_snapshot:
        setattr(exc, "last_conversation_snapshot", conversation_snapshot)
    if raw_upstream_message:
        setattr(exc, "upstream_message_preview", diagnostic_excerpt(raw_upstream_message, 1000))
    return exc


def _recover_after_image_stream_timeout(
        backend: OpenAIBackendAPI,
        request: ConversationRequest,
        last: dict[str, Any],
        timeout_error: Exception,
        index: int,
        total: int,
        stream_started_at: float,
) -> ImageOutput:
    raw_error = str(timeout_error) or f"SSE stream exceeded {config.image_stream_timeout_secs}s"
    conversation_id = str(last.get("conversation_id") or "")
    file_ids = [str(item) for item in last.get("file_ids") or []]
    sediment_ids = [str(item) for item in last.get("sediment_ids") or []]
    message = str(last.get("text") or "").strip()

    if not conversation_id:
        conversation_id = _recover_image_conversation_id(
            backend,
            request,
            reason="stream_timeout",
            message=message or raw_error,
            started_at=stream_started_at,
        )

    followup: dict[str, Any] = {
        "reason": "sse_timeout",
        "timeout_secs": config.image_stream_timeout_secs,
        "conversation_id": conversation_id,
        "stream_error": raw_error,
        "last_stream_state": {
            "conversation_id": str(last.get("conversation_id") or ""),
            "file_ids": file_ids,
            "sediment_ids": sediment_ids,
            "blocked": bool(last.get("blocked")),
            "tool_invoked": last.get("tool_invoked"),
            "turn_use_case": str(last.get("turn_use_case") or ""),
            "text_preview": diagnostic_excerpt(message, 1000),
        },
    }
    task_error = ""
    task_summaries: list[dict[str, Any]] = []
    task_probe_error = ""
    conversation_snapshot: dict[str, Any] = {}
    latest_assistant_text = ""
    policy_message = ""
    conversation_probe_error = ""

    if conversation_id:
        task_error, task_summaries, task_probe_error = _image_stream_timeout_task_diagnostics(backend, conversation_id)
        try:
            conversation = backend._get_conversation(conversation_id, timeout_secs=10)
            conversation_snapshot, latest_assistant_text = backend._conversation_poll_snapshot(conversation)
            for record in backend._extract_image_tool_records(conversation):
                add_unique(file_ids, [str(item) for item in record.get("file_ids") or []])
                add_unique(sediment_ids, [str(item) for item in record.get("sediment_ids") or []])
            policy_message = backend._find_content_policy_error_in_conversation(conversation)
        except Exception as exc:
            conversation_probe_error = diagnostic_excerpt(repr(exc), 1000)

    followup.update({
        "task_error": diagnostic_excerpt(task_error, 2000),
        "task_count": len(task_summaries),
        "tasks": task_summaries,
        "task_probe_error": task_probe_error,
        "conversation_probe_error": conversation_probe_error,
        "conversation_message_count": len(conversation_snapshot.get("messages") or []) if conversation_snapshot else 0,
        "latest_assistant_text": diagnostic_excerpt(latest_assistant_text, 2000),
        "policy_message": diagnostic_excerpt(policy_message, 2000),
        "recovered_file_ids": file_ids,
        "recovered_sediment_ids": sediment_ids,
    })

    policy_error = policy_message or (task_error if task_error and _is_content_policy_image_message(task_error) else "")
    if policy_error:
        policy_exc = ImageGenerationError(
            policy_error,
            status_code=400,
            error_type="invalid_request_error",
            code="content_policy_violation",
            conversation_id=conversation_id,
            raw_error=raw_error,
            upstream_error=policy_error,
            raw_upstream_message=policy_error,
        )
        setattr(policy_exc, "stream_timeout_secs", config.image_stream_timeout_secs)
        setattr(policy_exc, "stream_timeout_followup", followup)
        if conversation_snapshot:
            setattr(policy_exc, "last_conversation_snapshot", conversation_snapshot)
        raise policy_exc

    if file_ids or sediment_ids:
        try:
            image_urls = _resolve_image_urls_with_monitor(
                backend,
                request,
                conversation_id,
                file_ids,
                sediment_ids,
                index=index,
                total=total,
                path="stream_timeout_followup",
                poll=False,
            )
            result_output = _image_result_output_from_urls(
                backend,
                request,
                conversation_id,
                image_urls,
                index,
                total,
                path="stream_timeout_followup",
            )
            if result_output:
                logger.info({
                    "event": "image_stream_timeout_recovered_result",
                    "call_id": request.call_id,
                    "conversation_id": conversation_id,
                    "file_ids": file_ids,
                    "sediment_ids": sediment_ids,
                    "url_count": len(image_urls),
                })
                return result_output
        except Exception as exc:
            followup["result_recovery_error"] = diagnostic_excerpt(repr(exc), 1000)

    upstream_error = task_error or policy_message
    if not upstream_error:
        upstream_error = json.dumps(
            {
                key: value
                for key, value in followup.items()
                if key not in {"conversation_snapshot"}
            },
            ensure_ascii=False,
            default=str,
        )
    logger.warning({
        "event": "image_stream_timeout_followup",
        "call_id": request.call_id,
        "conversation_id": conversation_id,
        "task_error": diagnostic_excerpt(task_error, 500),
        "task_count": len(task_summaries),
        "file_ids": file_ids,
        "sediment_ids": sediment_ids,
        "conversation_probe_error": conversation_probe_error,
        "task_probe_error": task_probe_error,
    })
    raise _image_stream_timeout_error(
        raw_error,
        conversation_id,
        upstream_error,
        latest_assistant_text or message,
        followup,
        conversation_snapshot,
    )


def _cleanup_image_conversations_after_success(backend: OpenAIBackendAPI, outputs: Iterable[ImageOutput]) -> None:
    if not config.image_remove_conversation_after_result:
        return
    conversation_ids: list[str] = []
    seen: set[str] = set()
    for output in outputs:
        conversation_id = str(getattr(output, "conversation_id", "") or "").strip()
        if output.kind != "result" or not conversation_id or conversation_id in seen:
            continue
        seen.add(conversation_id)
        conversation_ids.append(conversation_id)
    for conversation_id in conversation_ids:
        try:
            backend.delete_conversation(conversation_id)
            logger.info({"event": "image_conversation_removed", "conversation_id": conversation_id})
        except Exception as exc:
            logger.warning({
                "event": "image_conversation_remove_failed",
                "conversation_id": conversation_id,
                "error": diagnostic_excerpt(exc, 500),
            })


def _image_result_output_from_urls(
        backend: OpenAIBackendAPI,
        request: ConversationRequest,
        conversation_id: str,
        image_urls: list[str],
        index: int,
        total: int,
        *,
        path: str = "",
) -> ImageOutput | None:
    if not image_urls:
        return None
    if request.progress_callback:
        request.progress_callback("receiving_image")
    downloaded_images = _download_image_bytes_with_monitor(
        backend,
        request,
        conversation_id,
        image_urls,
        index,
        total,
        path=path,
    )
    image_items = [
        {"b64_json": base64.b64encode(image_data).decode("ascii")}
        for image_data in downloaded_images
    ]
    data = format_image_result(
        image_items,
        request.prompt,
        request.response_format,
        request.base_url,
        int(time.time()),
        requested_size=request.size,
    )["data"]
    if not data:
        return None
    return ImageOutput(
        kind="result",
        model=request.model,
        index=index,
        total=total,
        data=data,
        conversation_id=conversation_id,
    )


def stream_image_outputs(
        backend: OpenAIBackendAPI,
        request: ConversationRequest,
        index: int = 1,
        total: int = 1,
) -> Iterator[ImageOutput]:
    """执行一张 ChatGPT 图片任务。

    统一原则：上游 SSE 只负责启动/生成阶段；SSE 结束后只进入一次结果解析/轮询。
    不再在文本回复、空结果、轮询超时后叠加多轮长重试，避免一个配置的 300 秒被隐式放大到十几分钟。
    """
    last: dict[str, Any] = {}
    conversation_stream_started = time.perf_counter()
    conversation_wall_started = time.time()
    try:
        for event in conversation_events(
                backend,
                prompt=request.prompt,
                model=request.model,
                images=request.images or [],
                size=request.size,
                quality=request.quality,
        ):
            last = event
            if event.get("type") == "conversation.delta":
                yield ImageOutput(
                    kind="progress",
                    model=request.model,
                    index=index,
                    total=total,
                    text=str(event.get("delta") or ""),
                    upstream_event_type="conversation.delta",
                )
                continue
            if event.get("type") == "conversation.event":
                raw = event.get("raw")
                raw_type = str(raw.get("type") or "") if isinstance(raw, dict) else ""
                yield ImageOutput(
                    kind="progress",
                    model=request.model,
                    index=index,
                    total=total,
                    upstream_event_type=raw_type,
                )
    except TimeoutError as exc:
        yield _recover_after_image_stream_timeout(
            backend,
            request,
            last,
            exc,
            index,
            total,
            conversation_wall_started,
        )
        return

    conversation_id = str(last.get("conversation_id") or "")
    file_ids = [str(item) for item in last.get("file_ids") or []]
    sediment_ids = [str(item) for item in last.get("sediment_ids") or []]
    message = str(last.get("text") or "").strip()
    should_poll_for_image = bool(request.images) or last.get("turn_use_case") == "image gen"
    # Image-generation SSE can finish with a human-readable queue/status
    # placeholder while the actual file IDs are still committed via the
    # conversation document.  When the turn structurally says an image should be
    # polled, do not treat stream text as terminal; let the poll path decide
    # from conversation/tool structure.
    is_text_reply = bool(
        message
        and not should_poll_for_image
        and backend._is_human_facing_image_text_reply_payload(message, last)
    )
    conversation_stream_ms = int((time.perf_counter() - conversation_stream_started) * 1000)
    http_timing = _backend_http_timing_data(backend)
    _monitor_image_stage(
        request,
        "image_stream_resolve_start",
        conversation_id=conversation_id,
        conversation_stream_ms=conversation_stream_ms,
        index=index,
        total=total,
        **http_timing,
    )
    logger.info({
        "event": "image_stream_resolve_start",
        "call_id": request.call_id,
        "conversation_id": conversation_id,
        "file_ids": file_ids,
        "sediment_ids": sediment_ids,
        "tool_invoked": last.get("tool_invoked"),
        "turn_use_case": last.get("turn_use_case"),
        "is_text_reply": is_text_reply,
        "should_poll_for_image": should_poll_for_image,
        "conversation_stream_ms": conversation_stream_ms,
        **http_timing,
    })
    if request.progress_callback:
        request.progress_callback("image_stream_resolve_start")

    if is_text_reply:
        logger.info({
            "event": "image_stream_text_reply_detected",
            "conversation_id": conversation_id,
            "message_preview": message[:200],
        })

    if not conversation_id and (should_poll_for_image or is_text_reply):
        conversation_id = _recover_image_conversation_id(
            backend,
            request,
            reason="stream_result",
            message=message,
        )

    if message and not file_ids and not sediment_ids and last.get("blocked"):
        detailed_error = _get_detailed_error_from_tasks(backend, conversation_id)
        error_text = detailed_error or message or "Image generation was rejected by upstream policy."
        yield ImageOutput(kind="message", model=request.model, index=index, total=total, text=error_text, conversation_id=conversation_id)
        return

    if is_text_reply and message and not file_ids and not sediment_ids:
        text_exc = ImageTextReplyError(message)
        setattr(text_exc, "conversation_id", conversation_id or "")
        setattr(text_exc, "upstream_error", message)
        setattr(text_exc, "raw_upstream_message", message)
        setattr(text_exc, "last_assistant_text", message)
        raise text_exc

    detailed_error = ""
    if not file_ids and not sediment_ids and conversation_id:
        detailed_error = _get_detailed_error_from_tasks(backend, conversation_id, timeout_secs=5.0, wait_secs=1.0)
        if detailed_error and not should_poll_for_image and not is_text_reply:
            logger.info({
                "event": "image_task_error_before_poll",
                "conversation_id": conversation_id,
                "error": detailed_error,
            })
            yield ImageOutput(kind="message", model=request.model, index=index, total=total, text=detailed_error, conversation_id=conversation_id)
            return
        if detailed_error and _is_content_policy_image_message(detailed_error):
            logger.info({
                "event": "image_task_policy_error_before_poll",
                "conversation_id": conversation_id,
                "error": detailed_error,
            })
            yield ImageOutput(kind="message", model=request.model, index=index, total=total, text=detailed_error, conversation_id=conversation_id)
            return
        if detailed_error:
            logger.info({
                "event": "image_task_error_observed_before_poll",
                "conversation_id": conversation_id,
                "error": detailed_error,
            })

    if message and not file_ids and not sediment_ids and not should_poll_for_image and not is_text_reply:
        yield ImageOutput(kind="message", model=request.model, index=index, total=total, text=message, conversation_id=conversation_id)
        return

    image_urls = _resolve_image_urls_with_monitor(
        backend,
        request,
        conversation_id,
        file_ids,
        sediment_ids,
        poll_timeout_secs=config.image_poll_timeout_secs,
        index=index,
        total=total,
    )
    result_output = _image_result_output_from_urls(
        backend,
        request,
        conversation_id,
        image_urls,
        index,
        total,
    )
    if result_output:
        yield result_output
        return

    if message and not should_poll_for_image:
        yield ImageOutput(kind="message", model=request.model, index=index, total=total, text=message, conversation_id=conversation_id)
        return

    if detailed_error:
        yield ImageOutput(kind="message", model=request.model, index=index, total=total, text=detailed_error, conversation_id=conversation_id)
        return

    if conversation_id:
        yield ImageOutput(
            kind="message",
            model=request.model,
            index=index,
            total=total,
            text="Image generation completed upstream but the result could not be retrieved. Please try again in a moment.",
            conversation_id=conversation_id,
        )
        return

    yield ImageOutput(
        kind="message",
        model=request.model,
        index=index,
        total=total,
        text="Image generation started upstream but the response was incomplete. Please try again.",
        conversation_id=conversation_id,
    )

def _codex_response_images(value: Any) -> list[str]:
    if isinstance(value, dict):
        if value.get("type") == "image_generation_call" and isinstance(value.get("result"), str):
            result = value["result"].strip()
            if result:
                return [result.split(",", 1)[1] if result.startswith("data:image/") else result]
        images: list[str] = []
        for item in value.values():
            images.extend(_codex_response_images(item))
        return images
    if isinstance(value, list):
        images: list[str] = []
        for item in value:
            images.extend(_codex_response_images(item))
        return images
    return []


def stream_codex_image_outputs(
        backend: OpenAIBackendAPI,
        request: ConversationRequest,
        index: int = 1,
        total: int = 1,
) -> Iterator[ImageOutput]:
    codex_started = time.perf_counter()
    images = _codex_response_images(list(backend.iter_codex_image_response_events(
        prompt=request.prompt,
        images=request.images or [],
        size=request.size,
        quality=request.quality,
    )))
    if request.trace_image_perf:
        _monitor_image_stage(
            request,
            "image_codex_response_done",
            response_ms=int((time.perf_counter() - codex_started) * 1000),
            image_count=len(images),
            index=index,
            total=total,
        )
        logger.info({
            "event": "image_codex_response_done",
            "call_id": request.call_id,
            "model": request.model,
            "index": index,
            "total": total,
            "response_ms": int((time.perf_counter() - codex_started) * 1000),
            "image_count": len(images),
        })
    if not images:
        raise ImageGenerationError("No image result found in response")
    data = format_image_result(
        [{"b64_json": item, "revised_prompt": request.prompt} for item in images],
        request.prompt,
        request.response_format,
        request.base_url,
        int(time.time()),
        requested_size=request.size,
    )["data"]
    if data:
        yield ImageOutput(kind="result", model=request.model, index=index, total=total, data=data)
        return
    raise ImageGenerationError("No image result found in response")


def _generate_single_image(
        request: ConversationRequest,
        index: int,
        total: int,
) -> list[ImageOutput]:
    """为单张图片执行生成逻辑（含重试），返回结果列表。

    该函数在独立线程中运行，每个线程使用不同的账号，
    实现并行生图，避免串行超时阻塞。
    """
    account_email = ""
    retry_token = ""
    fallback_retry_pending = False
    fallback_retry_used = False
    fallback_from_egress: dict[str, Any] = {}
    single_started = time.perf_counter()

    while True:
        account_wait_started = time.perf_counter()
        stream_started = 0.0
        try:
            _raise_if_request_cancelled(request)
            if retry_token:
                token = retry_token
                retry_token = ""
            else:
                if request.progress_callback:
                    request.progress_callback("getting_account")
                _monitor_image_stage(request, "image_getting_account", index=index, total=total)
                plan_type, _ = split_image_model(request.model)
                codex_model = is_codex_image_model(request.model)
                token = account_service.get_available_access_token(
                    plan_type=plan_type,
                    source_type="codex" if codex_model else None,
                    plan_types=("plus", "team", "pro") if codex_model and not plan_type else None,
                )
        except ImageAccountSelectionError as exc:
            _monitor_image_stage(
                request,
                "image_local_rejected",
                local_reason="account_pool",
                status="failed",
                index=index,
                total=total,
            )
            raise ImageGenerationError(
                str(exc) or "image generation failed",
                status_code=exc.status_code,
                error_type=exc.error_type,
                code=exc.code,
                account_email=account_email,
            ) from exc
        except RuntimeError as exc:
            _monitor_image_stage(
                request,
                "image_local_rejected",
                local_reason="account_pool",
                status="failed",
                index=index,
                total=total,
            )
            raise ImageGenerationError(str(exc) or "image generation failed", account_email=account_email) from exc

        emitted_for_token = False
        returned_message = False
        returned_result = False
        image_slot_finalized = False
        account_wait_ms = int((time.perf_counter() - account_wait_started) * 1000)
        account = account_service.get_account(token) or {}
        account_email = str(account.get("email") or "").strip()
        attempt_access_token = token
        attempt_refresh_token = str(account.get("refresh_token") or "").strip()

        def finalize_image_slot(
            success: bool,
            *,
            failure: ImageFailure | None = None,
            quota_consumed: bool | None = None,
        ) -> None:
            """收口 mark_image_result：幂等、带 CAS 与结构化 failure，失败时释放槽位。"""
            nonlocal image_slot_finalized
            if image_slot_finalized:
                return
            image_slot_finalized = True
            try:
                account_service.mark_image_result(
                    token,
                    success,
                    failure=failure,
                    quota_consumed=quota_consumed,
                    expected_access_token=attempt_access_token,
                    expected_refresh_token=attempt_refresh_token,
                )
            except Exception as mark_exc:
                logger.warning({
                    "event": "image_account_result_update_failed",
                    "account_email": account_email,
                    "success": success,
                    "failure_code": failure.code if failure is not None else "",
                    "error": diagnostic_excerpt(mark_exc, 500),
                })
                try:
                    account_service.release_image_slot(token)
                except Exception as release_exc:
                    logger.warning({
                        "event": "image_account_slot_release_failed",
                        "account_email": account_email,
                        "error": diagnostic_excerpt(release_exc, 500),
                    })

        _monitor_image_stage(
            request,
            "image_account_lookup",
            account_wait_ms=account_wait_ms,
            account_email=account_email,
            account_found=bool(account),
            index=index,
            total=total,
        )
        if account_wait_ms >= 5000:
            logger.warning({
                "event": "image_account_wait_slow",
                "call_id": request.call_id,
                "account_wait_ms": account_wait_ms,
                "account_email": account_email,
                "index": index,
            })
        logger.debug({
            "event": "image_account_lookup",
            "call_id": request.call_id,
            "token_prefix": token[:12] + "..." if len(token) > 12 else token,
            "account_email": account_email,
            "account_found": bool(account),
            "account_wait_ms": account_wait_ms,
            "index": index,
        })
        backend: OpenAIBackendAPI | None = None
        egress_acquired = False
        try:
            egress_started = time.perf_counter()
            fallback_profile = None
            using_fallback_profile = fallback_retry_pending
            fallback_retry_pending = False
            if using_fallback_profile:
                fallback_profile = proxy_settings.get_fallback_profile(
                    upstream=True,
                    reserve_image_egress=True,
                )
                if fallback_profile is None:
                    raise ImageGenerationError(
                        "fallback proxy is not configured",
                        status_code=502,
                        error_type="server_error",
                        code="connection_failed",
                        account_email=account_email,
                    )
            backend = OpenAIBackendAPI(
                access_token=token,
                proxy_profile=fallback_profile,
                reserve_image_egress=fallback_profile is None,
            )
            backend.cancel_checker = lambda: _raise_if_request_cancelled(request)
            if request.trace_image_perf:
                egress_data = _backend_egress_data(backend)
                if using_fallback_profile:
                    egress_data.update({
                        "fallback_retry": True,
                        "fallback_from_egress_key": fallback_from_egress.get("egress_key", ""),
                        "fallback_from_egress_label": fallback_from_egress.get("egress_label", ""),
                    })
                _monitor_image_stage(
                    request,
                    "image_egress_waiting",
                    account_email=account_email,
                    index=index,
                    total=total,
                    **egress_data,
                )
            egress_acquire_ms = proxy_settings.acquire_image_egress(backend.proxy_profile)
            egress_acquired = int(getattr(backend.proxy_profile, "image_concurrency_limit", 0) or 0) > 0
            egress_wait_ms = int((time.perf_counter() - egress_started) * 1000)
            if request.trace_image_perf:
                egress_data = _backend_egress_data(backend)
                if using_fallback_profile:
                    egress_data.update({
                        "fallback_retry": True,
                        "fallback_from_egress_key": fallback_from_egress.get("egress_key", ""),
                        "fallback_from_egress_label": fallback_from_egress.get("egress_label", ""),
                    })
                _monitor_image_stage(
                    request,
                    "image_egress_ready",
                    egress_wait_ms=egress_wait_ms,
                    egress_acquire_ms=egress_acquire_ms,
                    account_email=account_email,
                    index=index,
                    total=total,
                    **egress_data,
                )
                logger.debug({
                    "event": "image_egress_ready",
                    "call_id": request.call_id,
                    "model": request.model,
                    "index": index,
                    "total": total,
                    "account_email": account_email,
                    "egress_wait_ms": egress_wait_ms,
                    "egress_acquire_ms": egress_acquire_ms,
                    **egress_data,
                })
            if request.progress_callback or request.trace_image_perf:
                backend.progress_callback = _image_progress_callback_with_monitor(
                    request,
                    index,
                    total,
                    lambda: account_email,
                )
            stream_fn = stream_codex_image_outputs if is_codex_image_model(request.model) else stream_image_outputs
            outputs: list[ImageOutput] = []
            stream_started = time.perf_counter()
            for output in stream_fn(backend, request, index, total):
                _raise_if_request_cancelled(request)
                if account_email and not output.account_email:
                    output.account_email = account_email
                if output.kind == "message" and request.message_as_error:
                    status_code, error_type, code = _image_message_error_metadata(output.text)
                    raise ImageGenerationError(
                        output.text or "Image generation was rejected by upstream policy.",
                        status_code=status_code,
                        error_type=error_type,
                        code=code,
                        account_email=account_email,
                        conversation_id=output.conversation_id,
                        upstream_error=output.text or "",
                        raw_upstream_message=output.text or "",
                    )
                emitted_for_token = True
                returned_message = output.kind == "message"
                returned_result = returned_result or output.kind == "result"
                outputs.append(output)
            stream_ms = int((time.perf_counter() - stream_started) * 1000)
            if request.trace_image_perf:
                _monitor_image_stage(
                    request,
                    "image_single_stream_done",
                    stream_ms=stream_ms,
                    returned_message=returned_message,
                    returned_result=returned_result,
                    account_email=account_email,
                    index=index,
                    total=total,
                )
                logger.info({
                    "event": "image_single_stream_done",
                    "call_id": request.call_id,
                    "model": request.model,
                    "index": index,
                    "total": total,
                    "stream_ms": stream_ms,
                    "returned_message": returned_message,
                    "returned_result": returned_result,
                    "account_email": account_email,
                })
            if returned_message:
                message_text = next(
                    (str(getattr(item, "text", "") or "") for item in outputs if item.kind == "message"),
                    "",
                )
                _, _, message_code = _image_message_error_metadata(message_text)
                finalize_image_slot(
                    False,
                    failure=image_failure(message_code, raw_detail=message_text),
                )
                if request.trace_image_perf:
                    _monitor_image_stage(
                        request,
                        "image_single_done",
                        total_ms=int((time.perf_counter() - single_started) * 1000),
                        status="message",
                        account_email=account_email,
                        index=index,
                        total=total,
                    )
                    logger.info({
                        "event": "image_single_done",
                        "call_id": request.call_id,
                        "model": request.model,
                        "index": index,
                        "total": total,
                        "total_ms": int((time.perf_counter() - single_started) * 1000),
                        "status": "message",
                        "account_email": account_email,
                    })
                return outputs
            if not returned_result:
                finalize_image_slot(
                    False,
                    failure=image_failure("no_image_generated", raw_detail="upstream completed without generating images"),
                )
                if emitted_for_token:
                    conv_id = outputs[-1].conversation_id if outputs else ""
                    raise ImageGenerationError(
                        "upstream completed without generating images",
                        status_code=400,
                        error_type="invalid_request_error",
                        code="no_image_generated",
                        account_email=account_email,
                        conversation_id=conv_id,
                    )
                return outputs
            _cleanup_image_conversations_after_success(backend, outputs)
            finalize_image_slot(True)
            if request.trace_image_perf:
                _monitor_image_stage(
                    request,
                    "image_single_done",
                    total_ms=int((time.perf_counter() - single_started) * 1000),
                    status="success",
                    account_email=account_email,
                    index=index,
                    total=total,
                )
                logger.info({
                    "event": "image_single_done",
                    "call_id": request.call_id,
                    "model": request.model,
                    "index": index,
                    "total": total,
                    "total_ms": int((time.perf_counter() - single_started) * 1000),
                    "status": "success",
                    "account_email": account_email,
                })
            return outputs
        except ImagePollTimeoutError as exc:
            finalize_image_slot(
                False,
                failure=classify_image_exception(exc, code="image_poll_timeout"),
            )
            if account_email:
                setattr(exc, "account_email", account_email)
            raw_error = str(exc)
            upstream_error = getattr(exc, "upstream_error", "") or getattr(exc, "last_task_error", "") or raw_error
            logger.warning({
                "event": "image_poll_timeout",
                "request_token": token,
                "account_email": account_email,
                "index": index,
                "error": str(exc)[:200],
                "upstream_error": str(upstream_error)[:1000] if upstream_error else "",
                "last_conversation_snapshot": getattr(exc, "last_conversation_snapshot", None),
            })
            image_error = ImageGenerationError(
                raw_error,
                status_code=502,
                error_type="server_error",
                code="image_poll_timeout",
                account_email=account_email,
                conversation_id=getattr(exc, "conversation_id", ""),
                raw_error=raw_error,
                upstream_error=str(upstream_error or ""),
                raw_upstream_message=str(getattr(exc, "last_assistant_text", "") or ""),
            )
            for attr in (
                "poll_attempts",
                "poll_timeout_secs",
                "last_task_error",
                "last_conversation_snapshot",
                "last_assistant_text",
            ):
                if hasattr(exc, attr):
                    setattr(image_error, attr, getattr(exc, attr))
            raise image_error from exc
        except RequestCancelledError as exc:
            # 取消不是账号故障：不传 failure，避免触发核验队列
            finalize_image_slot(False)
            if request.trace_image_perf:
                _monitor_image_stage(
                    request,
                    "image_cancelled",
                    status="cancelled",
                    account_email=account_email,
                    index=index,
                    total=total,
                )
            raise ImageGenerationError(
                str(exc) or "request cancelled by administrator",
                status_code=499,
                error_type="server_error",
                code="request_cancelled",
                account_email=account_email,
            ) from exc
        except ImageContentPolicyError as exc:
            finalize_image_slot(
                False,
                failure=classify_image_exception(exc, code="content_policy_violation"),
            )
            if request.trace_image_perf:
                _monitor_image_stage(
                    request,
                    "image_stream_failed",
                    stream_error_ms=int((time.perf_counter() - stream_started) * 1000) if stream_started > 0 else 0,
                    account_email=account_email,
                    index=index,
                    total=total,
                    status="failed",
                    upstream_error=str(exc),
                )
            logger.warning({
                "event": "image_stream_content_policy_error",
                "request_token": token,
                "account_email": account_email,
                "error": diagnostic_excerpt(exc, 1000),
                "index": index,
            })
            raise ImageGenerationError(
                str(exc) or "Image generation was rejected by upstream policy.",
                status_code=400,
                error_type="invalid_request_error",
                code="content_policy_violation",
                account_email=account_email,
                conversation_id=getattr(exc, "conversation_id", ""),
                upstream_error=str(exc),
                raw_upstream_message=str(exc),
            ) from exc
        except ImageTextReplyError as exc:
            finalize_image_slot(
                False,
                failure=classify_image_exception(exc, code="upstream_text_reply"),
            )
            text_reply = str(exc) or "上游返回了文本回复而不是图片。"
            if request.trace_image_perf:
                _monitor_image_stage(
                    request,
                    "image_text_reply",
                    stream_error_ms=int((time.perf_counter() - stream_started) * 1000) if stream_started > 0 else 0,
                    account_email=account_email,
                    index=index,
                    total=total,
                    status="failed",
                    upstream_error=text_reply,
                )
            logger.info({
                "event": "image_stream_text_reply",
                "request_token": token,
                "account_email": account_email,
                "conversation_id": getattr(exc, "conversation_id", ""),
                "message_preview": diagnostic_excerpt(text_reply, 1000),
                "index": index,
            })
            image_error = ImageGenerationError(
                text_reply,
                status_code=400,
                error_type="invalid_request_error",
                code="upstream_text_reply",
                account_email=account_email,
                conversation_id=getattr(exc, "conversation_id", ""),
                raw_error=text_reply,
                upstream_error=str(getattr(exc, "upstream_error", "") or text_reply),
                raw_upstream_message=str(getattr(exc, "raw_upstream_message", "") or text_reply),
            )
            for attr in (
                "upstream_message_preview",
                "last_conversation_snapshot",
                "last_assistant_text",
            ):
                if hasattr(exc, attr):
                    setattr(image_error, attr, getattr(exc, attr))
            raise image_error from exc
        except ImageGenerationError as exc:
            finalize_image_slot(
                False,
                failure=image_failure(
                    getattr(exc, "code", None),
                    raw_detail=str(getattr(exc, "raw_error", "") or exc),
                ),
                quota_consumed=(
                    _normalized_image_failure_code(getattr(exc, "code", None))
                    == "image_download_failed"
                ),
            )
            if account_email and not getattr(exc, "account_email", ""):
                exc.account_email = account_email
            error_text = str(exc)
            if request.trace_image_perf:
                _monitor_image_stage(
                    request,
                    "image_stream_failed",
                    stream_error_ms=int((time.perf_counter() - stream_started) * 1000) if stream_started > 0 else 0,
                    account_email=account_email,
                    index=index,
                    total=total,
                    status="failed",
                    upstream_error=error_text,
                )
            logger.warning({
                "event": "image_stream_generation_error",
                "request_token": token,
                "account_email": account_email,
                "error": diagnostic_excerpt(error_text, 1000),
                "index": index,
            })
            raise
        except Exception as exc:
            last_error = str(exc)
            stream_error_ms = int((time.perf_counter() - stream_started) * 1000) if stream_started > 0 else 0
            http_timing = _backend_http_timing_data(backend)
            if request.trace_image_perf and stream_error_ms > 0:
                _monitor_image_stage(
                    request,
                    "image_stream_failed",
                    stream_error_ms=stream_error_ms,
                    stream_ms=stream_error_ms,
                    account_email=account_email,
                    index=index,
                    total=total,
                    status="failed",
                    upstream_error=last_error,
                    **http_timing,
                )
            logger.warning({
                "event": "image_stream_fail",
                "request_token": token,
                "account_email": account_email,
                "error": diagnostic_excerpt(last_error, 1000),
                "stream_error_ms": stream_error_ms,
                "index": index,
                **http_timing,
            })
            if not emitted_for_token and is_token_invalid_error(last_error):
                # 不传 failure：避免异步核验与下方 force refresh / handle_invalid_token 双开。
                finalize_image_slot(False)
                # 瞬时刷新失败不标失效：清空 token 走下一轮重选新号（同 text_stream 换号语义，不冒泡）。
                try:
                    refreshed_token = account_service.refresh_access_token(token, force=True, event="image_stream")
                except Exception:
                    token = ""
                    continue
                if refreshed_token and refreshed_token != token:
                    token = refreshed_token
                    continue
                account_service.handle_invalid_token(token, "image_stream", error=last_error)
                continue
            quick_timeout_retry_ms = min(30000, max(5000, int(config.image_stream_timeout_secs * 1000 * 0.2)))
            early_connection_failure = (
                not emitted_for_token
                and (stream_error_ms == 0 or stream_error_ms <= quick_timeout_retry_ms)
                and (is_tls_connection_error(last_error) or is_connection_timeout_error(last_error))
            )
            fallback_reference = proxy_settings.get_fallback_proxy_reference()
            if early_connection_failure and fallback_reference and not fallback_retry_used:
                fallback_retry_used = True
                fallback_retry_pending = True
                retry_token = token
                fallback_from_egress = _backend_egress_data(backend) if backend is not None else {}
                logger.warning({
                    "event": "image_stream_fallback_retry",
                    "request_token": token,
                    "account_email": account_email,
                    "index": index,
                    "fallback_proxy_configured": True,
                    "fallback_from_egress_key": fallback_from_egress.get("egress_key", ""),
                    "fallback_from_egress_label": fallback_from_egress.get("egress_label", ""),
                    "stream_error_ms": stream_error_ms,
                    "error": last_error[:200],
                })
                if request.trace_image_perf:
                    _monitor_image_stage(
                        request,
                        "image_egress_fallback_retry",
                        account_email=account_email,
                        index=index,
                        total=total,
                        status="retrying",
                        fallback_from_egress_key=fallback_from_egress.get("egress_key", ""),
                        fallback_from_egress_label=fallback_from_egress.get("egress_label", ""),
                    )
                continue
            failure = classify_image_exception(exc)
            if is_stream_transport_error(last_error) and failure.code == "internal_error":
                failure = image_failure("image_stream_interrupted", raw_detail=last_error)
            elif is_tls_connection_error(last_error) and failure.code == "internal_error":
                failure = image_failure("upstream_connection_failed", raw_detail=last_error)
            elif is_connection_timeout_error(last_error) and failure.code == "internal_error":
                failure = image_failure("upstream_connection_timeout", raw_detail=last_error)
            finalize_image_slot(
                False,
                failure=failure,
                quota_consumed=(failure.code == "image_download_failed"),
            )
            raise ImageGenerationError(
                image_stream_error_message(last_error),
                account_email=account_email,
                conversation_id="",
                raw_error=last_error,
                upstream_error=last_error,
                code=failure.code,
            ) from exc
        finally:
            if egress_acquired and backend is not None:
                proxy_settings.release_image_egress(backend.proxy_profile)
            if backend is not None:
                backend.close()


def _firefly_image_result_output(
        request: ConversationRequest,
        image_bytes: bytes,
        index: int,
        total: int,
) -> ImageOutput:
    """将 Firefly 返回的图片字节整理为与 ChatGPT 路径一致的 ImageOutput。"""
    if not image_bytes:
        raise ImageGenerationError(
            "firefly upstream returned empty image bytes",
            status_code=400,
            error_type="invalid_request_error",
            code="no_image_generated",
        )
    image_items = [{"b64_json": base64.b64encode(image_bytes).decode("ascii")}]
    data = format_image_result(
        image_items,
        request.prompt,
        request.response_format,
        request.base_url,
        int(time.time()),
        requested_size=request.size,
    )["data"]
    if not data:
        raise ImageGenerationError(
            "firefly image format produced empty data",
            status_code=400,
            error_type="invalid_request_error",
            code="no_image_generated",
        )
    return ImageOutput(
        kind="result",
        model=request.model,
        index=index,
        total=total,
        data=data,
    )


# Firefly 图生图最多上传 6 张参考图（与 Adobe 3P 通道上限对齐）
_MAX_FIREFLY_REFERENCE_IMAGES = 6
_BASE64_CHARSET_RE = re.compile(r"^[A-Za-z0-9+/=\s]+$")


def _guess_image_mime(data: bytes) -> str:
    """从魔数猜测图片 MIME，供 Firefly upload 的 content-type。"""
    if not data:
        return "image/jpeg"
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if data[:3] == b"\xff\xd8\xff":
        return "image/jpeg"
    if len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    if data[:6] in (b"GIF87a", b"GIF89a"):
        return "image/gif"
    return "image/jpeg"


def _looks_like_base64(text: str) -> bool:
    """字符集 + 长度校验：避免把 URL/路径误当 base64。"""
    cleaned = "".join(str(text or "").split())
    if len(cleaned) < 16 or len(cleaned) % 4 != 0:
        return False
    return bool(_BASE64_CHARSET_RE.fullmatch(cleaned))


def _decode_firefly_image_entry(
        entry: object,
        *,
        proxy: str | None = None,
) -> tuple[bytes, str] | None:
    """把 request.images 单项解码为 (bytes, mime)；无法解码返回 None。

    分支顺序：dict{"url"} → data: → http(s):（走 fetch）→ 形似 base64 才 decode。
    URL 永不 b64decode。
    """
    if isinstance(entry, (bytes, bytearray)):
        data = bytes(entry)
        return (data, _guess_image_mime(data)) if data else None
    if isinstance(entry, tuple) and entry:
        first = entry[0]
        if isinstance(first, (bytes, bytearray)) and first:
            mime = str(entry[1] if len(entry) > 1 else "") or _guess_image_mime(bytes(first))
            return bytes(first), mime
        if isinstance(first, str):
            entry = first
        else:
            return None
    if isinstance(entry, dict):
        # 支持 {"url": ...} / {"image_url": {"url": ...}} / {"b64_json": ...}
        for key in ("url", "image_url", "b64_json", "data"):
            nested = entry.get(key)
            if nested is None:
                continue
            if isinstance(nested, dict):
                nested_url = nested.get("url")
                if nested_url is not None:
                    return _decode_firefly_image_entry(nested_url, proxy=proxy)
                continue
            return _decode_firefly_image_entry(nested, proxy=proxy)
        return None
    if not isinstance(entry, str):
        return None
    text = entry.strip()
    if not text:
        return None
    # data URL
    if text.startswith("data:") and "," in text:
        header, payload = text.split(",", 1)
        mime = "image/jpeg"
        if header.startswith("data:") and ";base64" in header:
            mime = header[5:].split(";", 1)[0].strip() or mime
        try:
            data = base64.b64decode(payload)
        except Exception:
            return None
        if not data:
            return None
        if mime == "image/jpg":
            mime = "image/jpeg"
        return data, mime or _guess_image_mime(data)
    # 裸 http(s) URL：走 fetch，禁止 b64decode
    if text.lower().startswith(("http://", "https://")):
        try:
            data, mime = firefly_fetch(text, proxy=proxy)
        except Exception:
            return None
        if not data:
            return None
        return bytes(data), str(mime or "") or _guess_image_mime(bytes(data))
    # 纯 base64（encode_images 产物）；须形似 base64
    if not _looks_like_base64(text):
        return None
    try:
        data = base64.b64decode(text, validate=False)
    except Exception:
        return None
    if not data:
        return None
    return data, _guess_image_mime(data)


def _normalize_firefly_image_inputs(
        image_inputs: object | None = None,
        *,
        request: ConversationRequest | None = None,
) -> list[tuple[bytes, str]]:
    """统一参考图输入：最多 6 张 (bytes, mime)。"""
    raw: list[Any]
    if image_inputs is None:
        raw = list((request.images if request is not None else None) or [])
    elif isinstance(image_inputs, list):
        raw = image_inputs
    else:
        raw = [image_inputs]
    result: list[tuple[bytes, str]] = []
    for item in raw:
        decoded = _decode_firefly_image_entry(item)
        if decoded is None:
            continue
        result.append(decoded)
        if len(result) >= _MAX_FIREFLY_REFERENCE_IMAGES:
            break
    return result


def _coerce_firefly_image_bytes(image_bytes: object) -> bytes:
    """兼容 generate_image 返回 bytes / dict / list / base64 str。"""
    if isinstance(image_bytes, dict):
        for key in ("bytes", "image_bytes", "data", "image", "content"):
            if key in image_bytes and image_bytes[key] is not None:
                image_bytes = image_bytes[key]
                break
        else:
            images = image_bytes.get("images")
            if isinstance(images, (list, tuple)) and images:
                image_bytes = images[0]
    if isinstance(image_bytes, (list, tuple)):
        image_bytes = image_bytes[0] if image_bytes else b""
    if isinstance(image_bytes, str):
        text = image_bytes.strip()
        if text.startswith("data:") and "," in text:
            text = text.split(",", 1)[1]
        image_bytes = base64.b64decode(text)
    if not isinstance(image_bytes, (bytes, bytearray)):
        raise ImageGenerationError(
            "firefly generate_image returned non-bytes result",
            status_code=502,
            error_type="server_error",
            code="upstream_error",
        )
    return bytes(image_bytes)


def _build_firefly_image2image_payload(
        resolved: dict[str, Any],
        *,
        prompt: str,
        image_ids: list[str],
        quality: str,
) -> dict[str, Any]:
    """构造图生图 payload；优先用 backends 的 build_image2image_payload，缺失则回退。"""
    try:
        from services.backends.firefly_payloads import build_image2image_payload
    except ImportError:
        build_image2image_payload = None  # type: ignore[assignment]

    if callable(build_image2image_payload):
        try:
            # 正式签名：reference_image_ids=
            return build_image2image_payload(
                resolved,
                prompt,
                reference_image_ids=image_ids,
                n=1,
                quality=quality,
            )
        except TypeError:
            # 兼容 image_ids= 或纯位置参数
            try:
                return build_image2image_payload(
                    resolved,
                    prompt=prompt,
                    image_ids=image_ids,
                    quality=quality,
                    n=1,
                )
            except TypeError:
                return build_image2image_payload(resolved, prompt, image_ids, n=1, quality=quality)

    # 回退：在 text2image 体上改 module + referenceBlobs
    from services.backends.firefly_payloads import build_text2image_payload

    payload = build_text2image_payload(
        resolved,
        prompt=prompt,
        quality=quality,
        n=1,
    )
    is_gpt = (
        str(resolved.get("pixel_table") or "").strip().lower() == "gpt"
        or str(resolved.get("modelId") or "").strip().lower() == "gpt-image"
    )
    # gpt-image 图生图 usage=subject；nano-banana 族 usage=general
    usage = "subject" if is_gpt else "general"
    payload["generationMetadata"] = {
        "module": "image2image",
        "submodule": "ff-image-generate",
    }
    payload["referenceBlobs"] = [{"id": img_id, "usage": usage} for img_id in image_ids]
    return payload


def _generate_single_image_firefly(
        request: ConversationRequest,
        index: int,
        total: int,
) -> list[ImageOutput]:
    """Firefly 渠道单图：选号占槽 → generate_image → finalize/mark。

    generate_image 为同步阻塞轮询，本函数本身在线程池 worker 内运行。
    """
    # 延迟导入：backends 由并行 agent 落地，启动期未就绪时给清晰错误
    try:
        from services.backends.firefly_catalog import resolve_firefly_image_model
        from services.backends.firefly_client import generate_image as firefly_generate
        from services.backends.firefly_errors import (
            FireflyAuthError,
            FireflyQuotaExhausted,
            FireflyRequestError,
            FireflyUpstreamTemporary,
            is_rotatable_error,
        )
        from services.backends.firefly_payloads import build_text2image_payload
    except ImportError as exc:
        raise ImageGenerationError(
            f"firefly backend modules are not available: {exc}",
            status_code=503,
            error_type="server_error",
            code="no_available_account",
        ) from exc

    if not config.firefly_enabled:
        raise ImageGenerationError(
            "firefly channel is disabled",
            status_code=503,
            error_type="server_error",
            code="no_available_account",
        )

    # size 交给 catalog 解析宽高，避免把 size 误传给 payload builder
    resolved = resolve_firefly_image_model(request.model, size=request.size)
    if resolved is None:
        raise ImageGenerationError(
            f"unsupported firefly image model: {request.model}",
            status_code=400,
            error_type="invalid_request_error",
            code="unsupported_model",
        )

    max_attempts = max(1, int(config.firefly_retry_max_attempts or 3))
    account_email = ""
    attempted_tokens: set[str] = set()
    last_error: Exception | None = None
    single_started = time.perf_counter()

    for attempt in range(1, max_attempts + 1):
        _raise_if_request_cancelled(request)
        account_wait_started = time.perf_counter()
        image_slot_finalized = False
        token = ""
        try:
            if request.progress_callback:
                request.progress_callback("getting_account")
            _monitor_image_stage(
                request,
                "image_getting_account",
                index=index,
                total=total,
                channel="firefly",
                attempt=attempt,
            )
            token = account_service.get_available_access_token(
                source_type="firefly",
                excluded_tokens=attempted_tokens,
            )
        except ImageAccountSelectionError as exc:
            _monitor_image_stage(
                request,
                "image_local_rejected",
                local_reason="account_pool",
                status="failed",
                index=index,
                total=total,
                channel="firefly",
            )
            raise ImageGenerationError(
                str(exc) or "image generation failed",
                status_code=exc.status_code,
                error_type=exc.error_type,
                code=exc.code,
                account_email=account_email,
            ) from exc
        except RuntimeError as exc:
            raise ImageGenerationError(
                str(exc) or "image generation failed",
                account_email=account_email,
            ) from exc

        if token in attempted_tokens:
            # 同 token 已试过仍被分到：释放槽位；保留既有 last_error，勿用 503 覆盖真实 401/429
            try:
                account_service.release_image_slot(token)
            except Exception:
                pass
            if last_error is None:
                last_error = ImageGenerationError(
                    "firefly account pool exhausted after retries",
                    status_code=503,
                    error_type="server_error",
                    code="no_available_account",
                )
            break
        attempted_tokens.add(token)

        account_wait_ms = int((time.perf_counter() - account_wait_started) * 1000)
        account = account_service.get_account(token) or {}
        account_email = str(account.get("email") or "").strip()
        proxy = str(account.get("proxy") or "").strip() or None
        attempt_access_token = token
        attempt_refresh_token = str(account.get("refresh_token") or "").strip()

        def finalize_image_slot(
            success: bool,
            *,
            failure: ImageFailure | None = None,
            quota_consumed: bool | None = None,
        ) -> None:
            nonlocal image_slot_finalized
            if image_slot_finalized:
                return
            image_slot_finalized = True
            try:
                account_service.mark_image_result(
                    token,
                    success,
                    failure=failure,
                    quota_consumed=quota_consumed,
                    expected_access_token=attempt_access_token,
                    expected_refresh_token=attempt_refresh_token or None,
                )
            except Exception as mark_exc:
                logger.warning({
                    "event": "firefly_image_account_result_update_failed",
                    "account_email": account_email,
                    "success": success,
                    "failure_code": failure.code if failure is not None else "",
                    "error": diagnostic_excerpt(mark_exc, 500),
                })
                try:
                    account_service.release_image_slot(token)
                except Exception as release_exc:
                    logger.warning({
                        "event": "firefly_image_account_slot_release_failed",
                        "account_email": account_email,
                        "error": diagnostic_excerpt(release_exc, 500),
                    })

        _monitor_image_stage(
            request,
            "image_account_lookup",
            account_wait_ms=account_wait_ms,
            account_email=account_email,
            account_found=bool(account),
            index=index,
            total=total,
            channel="firefly",
            attempt=attempt,
        )

        try:
            if request.progress_callback:
                request.progress_callback("starting_generation")
            _monitor_image_stage(
                request,
                "image_generation_start",
                account_email=account_email,
                index=index,
                total=total,
                channel="firefly",
                attempt=attempt,
            )
            payload = build_text2image_payload(
                resolved,
                prompt=request.prompt,
                quality=request.quality,
                n=1,
            )
            gen_started = time.perf_counter()
            # 已在线程池 worker 内；generate_image 同步阻塞轮询。
            # 签名以 (token, payload) 为准，timeout/poll 作可选 kwargs 兼容。
            try:
                image_bytes = firefly_generate(
                    token,
                    payload,
                    proxy=proxy,
                    timeout=config.firefly_gen_timeout_sec,
                    poll_interval=config.firefly_poll_interval_sec,
                )
            except TypeError:
                image_bytes = firefly_generate(token, payload, proxy=proxy)
            gen_ms = int((time.perf_counter() - gen_started) * 1000)
            try:
                image_bytes = _coerce_firefly_image_bytes(image_bytes)
            except ImageGenerationError as coerce_exc:
                coerce_exc.account_email = account_email
                raise
            output = _firefly_image_result_output(request, image_bytes, index, total)
            output.account_email = account_email
            # Firefly 真实额度靠 taste_exhausted/credits，成功不扣本地 quota
            finalize_image_slot(True, quota_consumed=False)
            if request.trace_image_perf:
                _monitor_image_stage(
                    request,
                    "image_single_done",
                    total_ms=int((time.perf_counter() - single_started) * 1000),
                    gen_ms=gen_ms,
                    status="success",
                    account_email=account_email,
                    index=index,
                    total=total,
                    channel="firefly",
                )
            return [output]
        except RequestCancelledError as exc:
            finalize_image_slot(False)
            raise ImageGenerationError(
                str(exc) or "request cancelled by administrator",
                status_code=499,
                error_type="server_error",
                code="request_cancelled",
                account_email=account_email,
            ) from exc
        except FireflyQuotaExhausted as exc:
            # report_exhausted 内部已 release 槽；标记 finalized 避免 finally 双释放
            try:
                account_service.report_exhausted(token, reason="taste_exhausted")
                image_slot_finalized = True
            except Exception as report_exc:
                logger.warning({
                    "event": "firefly_report_exhausted_failed",
                    "account_email": account_email,
                    "error": diagnostic_excerpt(report_exc, 500),
                })
                finalize_image_slot(
                    False,
                    failure=image_failure("image_quota_exhausted", raw_detail=str(exc)),
                )
            last_error = ImageGenerationError(
                str(exc) or "firefly quota exhausted",
                status_code=429,
                error_type="insufficient_quota",
                code="insufficient_quota",
                account_email=account_email,
                raw_error=str(exc),
                upstream_error=str(exc),
            )
            logger.warning({
                "event": "firefly_quota_exhausted",
                "account_email": account_email,
                "index": index,
                "attempt": attempt,
                "error": diagnostic_excerpt(exc, 500),
            })
            continue
        except FireflyAuthError as exc:
            # 本地标异常，不带 auth_invalid failure（verify_account=True 会触发 OpenAI fetch_remote_info）
            try:
                account_service.update_account(token, {"status": "异常"}, quiet=True)
            except Exception as mark_exc:
                logger.warning({
                    "event": "firefly_auth_mark_abnormal_failed",
                    "account_email": account_email,
                    "error": diagnostic_excerpt(mark_exc, 500),
                })
            finalize_image_slot(False)  # 不带 failure，避免 verify_account
            last_error = ImageGenerationError(
                str(exc) or "firefly authentication failed",
                status_code=401,
                error_type="authentication_error",
                code="auth_invalid",
                account_email=account_email,
                raw_error=str(exc),
                upstream_error=str(exc),
            )
            logger.warning({
                "event": "firefly_rotatable_error",
                "account_email": account_email,
                "index": index,
                "attempt": attempt,
                "error_type": type(exc).__name__,
                "error": diagnostic_excerpt(exc, 500),
            })
            continue
        except FireflyUpstreamTemporary as exc:
            finalize_image_slot(
                False,
                failure=image_failure("upstream_unavailable", raw_detail=str(exc)),
            )
            last_error = ImageGenerationError(
                str(exc) or "firefly upstream temporary failure",
                status_code=503,
                error_type="server_error",
                code="upstream_unavailable",
                account_email=account_email,
                raw_error=str(exc),
                upstream_error=str(exc),
            )
            logger.warning({
                "event": "firefly_rotatable_error",
                "account_email": account_email,
                "index": index,
                "attempt": attempt,
                "error_type": type(exc).__name__,
                "error": diagnostic_excerpt(exc, 500),
            })
            # 上游临时错误：换号重试
            continue
        except FireflyRequestError as exc:
            finalize_image_slot(
                False,
                failure=image_failure("upstream_error", raw_detail=str(exc)),
            )
            raise ImageGenerationError(
                str(exc) or "firefly request failed",
                status_code=int(getattr(exc, "status_code", 0) or 400),
                error_type="invalid_request_error",
                code=str(getattr(exc, "code", "") or "upstream_error"),
                account_email=account_email,
                raw_error=str(exc),
                upstream_error=str(exc),
            ) from exc
        except ImageGenerationError:
            if not image_slot_finalized:
                finalize_image_slot(False, failure=image_failure("upstream_error"))
            raise
        except Exception as exc:
            finalize_image_slot(
                False,
                failure=classify_image_exception(exc),
            )
            rotatable = False
            try:
                rotatable = bool(is_rotatable_error(exc))
            except Exception:
                rotatable = False
            last_error = ImageGenerationError(
                image_stream_error_message(str(exc)),
                account_email=account_email,
                raw_error=str(exc),
                upstream_error=str(exc),
                code="upstream_error",
            )
            logger.warning({
                "event": "firefly_image_stream_fail",
                "account_email": account_email,
                "index": index,
                "attempt": attempt,
                "error": diagnostic_excerpt(exc, 1000),
            })
            if rotatable and attempt < max_attempts:
                continue
            raise last_error from exc
        finally:
            # 仅兜底未 finalize 的路径（异常中途/漏释放）
            if token and not image_slot_finalized:
                try:
                    account_service.release_image_slot(token)
                    image_slot_finalized = True
                except Exception as release_exc:
                    logger.warning({
                        "event": "firefly_image_slot_orphan_release_failed",
                        "account_email": account_email,
                        "error": diagnostic_excerpt(release_exc, 500),
                    })

    if last_error is not None:
        raise last_error
    raise ImageGenerationError(
        "firefly image generation failed after retries",
        status_code=503,
        error_type="server_error",
        code="no_available_account",
        account_email=account_email,
    )


def _generate_single_image_firefly_edit(
        request: ConversationRequest,
        index: int,
        total: int,
        image_inputs: object | None = None,
) -> list[ImageOutput]:
    """Firefly 图生图单张编排：上传参考图 → image2image payload → generate → mark。

    image_inputs: list of (bytes, mime) 或 list of url/data-url/base64 strings；
    缺省时取 request.images。本函数在线程池 worker 内运行（upload/generate 同步阻塞）。
    """
    try:
        from services.backends.firefly_catalog import resolve_firefly_image_model
        from services.backends.firefly_client import generate_image as firefly_generate
        from services.backends.firefly_client import upload_image as firefly_upload
        from services.backends.firefly_errors import (
            FireflyAuthError,
            FireflyQuotaExhausted,
            FireflyRequestError,
            FireflyUpstreamTemporary,
            is_rotatable_error,
        )
    except ImportError as exc:
        raise ImageGenerationError(
            f"firefly backend modules are not available: {exc}",
            status_code=503,
            error_type="server_error",
            code="no_available_account",
        ) from exc

    if not config.firefly_enabled:
        raise ImageGenerationError(
            "firefly channel is disabled",
            status_code=503,
            error_type="server_error",
            code="no_available_account",
        )

    resolved = resolve_firefly_image_model(request.model, size=request.size)
    if resolved is None:
        raise ImageGenerationError(
            f"unsupported firefly image model: {request.model}",
            status_code=400,
            error_type="invalid_request_error",
            code="unsupported_model",
        )

    # 先规范化参考图；URL/dict/base64 均由 _decode_firefly_image_entry 处理
    refs = _normalize_firefly_image_inputs(image_inputs, request=request)
    if not refs:
        raise ImageGenerationError(
            "image is required for firefly image edit",
            status_code=400,
            error_type="invalid_request_error",
            code="invalid_image",
        )

    max_attempts = max(1, int(config.firefly_retry_max_attempts or 3))
    account_email = ""
    attempted_tokens: set[str] = set()
    last_error: Exception | None = None
    single_started = time.perf_counter()

    for attempt in range(1, max_attempts + 1):
        _raise_if_request_cancelled(request)
        account_wait_started = time.perf_counter()
        image_slot_finalized = False
        token = ""
        try:
            if request.progress_callback:
                request.progress_callback("getting_account")
            _monitor_image_stage(
                request,
                "image_getting_account",
                index=index,
                total=total,
                channel="firefly",
                attempt=attempt,
                mode="edit",
            )
            token = account_service.get_available_access_token(
                source_type="firefly",
                excluded_tokens=attempted_tokens,
            )
        except ImageAccountSelectionError as exc:
            _monitor_image_stage(
                request,
                "image_local_rejected",
                local_reason="account_pool",
                status="failed",
                index=index,
                total=total,
                channel="firefly",
                mode="edit",
            )
            raise ImageGenerationError(
                str(exc) or "image generation failed",
                status_code=exc.status_code,
                error_type=exc.error_type,
                code=exc.code,
                account_email=account_email,
            ) from exc
        except RuntimeError as exc:
            raise ImageGenerationError(
                str(exc) or "image generation failed",
                account_email=account_email,
            ) from exc

        if token in attempted_tokens:
            # 同 token 已试过仍被分到：释放槽位；保留既有 last_error，勿用 503 覆盖真实 401/429
            try:
                account_service.release_image_slot(token)
            except Exception:
                pass
            if last_error is None:
                last_error = ImageGenerationError(
                    "firefly account pool exhausted after retries",
                    status_code=503,
                    error_type="server_error",
                    code="no_available_account",
                )
            break
        attempted_tokens.add(token)

        account_wait_ms = int((time.perf_counter() - account_wait_started) * 1000)
        account = account_service.get_account(token) or {}
        account_email = str(account.get("email") or "").strip()
        proxy = str(account.get("proxy") or "").strip() or None
        attempt_access_token = token
        attempt_refresh_token = str(account.get("refresh_token") or "").strip()

        def finalize_image_slot(
            success: bool,
            *,
            failure: ImageFailure | None = None,
            quota_consumed: bool | None = None,
        ) -> None:
            nonlocal image_slot_finalized
            if image_slot_finalized:
                return
            image_slot_finalized = True
            try:
                account_service.mark_image_result(
                    token,
                    success,
                    failure=failure,
                    quota_consumed=quota_consumed,
                    expected_access_token=attempt_access_token,
                    expected_refresh_token=attempt_refresh_token or None,
                )
            except Exception as mark_exc:
                logger.warning({
                    "event": "firefly_image_account_result_update_failed",
                    "account_email": account_email,
                    "success": success,
                    "failure_code": failure.code if failure is not None else "",
                    "error": diagnostic_excerpt(mark_exc, 500),
                    "mode": "edit",
                })
                try:
                    account_service.release_image_slot(token)
                except Exception as release_exc:
                    logger.warning({
                        "event": "firefly_image_account_slot_release_failed",
                        "account_email": account_email,
                        "error": diagnostic_excerpt(release_exc, 500),
                        "mode": "edit",
                    })

        _monitor_image_stage(
            request,
            "image_account_lookup",
            account_wait_ms=account_wait_ms,
            account_email=account_email,
            account_found=bool(account),
            index=index,
            total=total,
            channel="firefly",
            attempt=attempt,
            mode="edit",
        )

        try:
            if request.progress_callback:
                request.progress_callback("starting_generation")
            _monitor_image_stage(
                request,
                "image_generation_start",
                account_email=account_email,
                index=index,
                total=total,
                channel="firefly",
                attempt=attempt,
                mode="edit",
                reference_count=len(refs),
            )

            # 1) 顺序上传参考图，拿到 image id 列表
            image_ids: list[str] = []
            upload_started = time.perf_counter()
            for ref_index, (img_bytes, mime) in enumerate(refs, start=1):
                _raise_if_request_cancelled(request)
                try:
                    image_id = firefly_upload(
                        token,
                        img_bytes,
                        mime_type=mime or "image/jpeg",
                        proxy=proxy,
                    )
                except TypeError:
                    image_id = firefly_upload(token, img_bytes, mime or "image/jpeg", proxy=proxy)
                image_id = str(image_id or "").strip()
                if not image_id:
                    raise ImageGenerationError(
                        f"firefly upload returned empty image id (ref #{ref_index})",
                        status_code=502,
                        error_type="server_error",
                        code="upstream_error",
                        account_email=account_email,
                    )
                image_ids.append(image_id)
            upload_ms = int((time.perf_counter() - upload_started) * 1000)
            _monitor_image_stage(
                request,
                "image_firefly_upload_done",
                account_email=account_email,
                index=index,
                total=total,
                channel="firefly",
                mode="edit",
                upload_ms=upload_ms,
                reference_count=len(image_ids),
            )

            # 2) 构造 image2image payload（mask 不传给 Firefly）
            payload = _build_firefly_image2image_payload(
                resolved,
                prompt=request.prompt,
                image_ids=image_ids,
                quality=request.quality,
            )

            # 3) 同步 generate
            gen_started = time.perf_counter()
            try:
                image_bytes = firefly_generate(
                    token,
                    payload,
                    proxy=proxy,
                    timeout=config.firefly_gen_timeout_sec,
                    poll_interval=config.firefly_poll_interval_sec,
                )
            except TypeError:
                image_bytes = firefly_generate(token, payload, proxy=proxy)
            gen_ms = int((time.perf_counter() - gen_started) * 1000)
            try:
                image_bytes = _coerce_firefly_image_bytes(image_bytes)
            except ImageGenerationError as coerce_exc:
                coerce_exc.account_email = account_email
                raise

            output = _firefly_image_result_output(request, image_bytes, index, total)
            output.account_email = account_email
            # Firefly 真实额度靠 taste_exhausted/credits，成功不扣本地 quota
            finalize_image_slot(True, quota_consumed=False)
            if request.trace_image_perf:
                _monitor_image_stage(
                    request,
                    "image_single_done",
                    total_ms=int((time.perf_counter() - single_started) * 1000),
                    gen_ms=gen_ms,
                    upload_ms=upload_ms,
                    status="success",
                    account_email=account_email,
                    index=index,
                    total=total,
                    channel="firefly",
                    mode="edit",
                )
            return [output]
        except RequestCancelledError as exc:
            finalize_image_slot(False)
            raise ImageGenerationError(
                str(exc) or "request cancelled by administrator",
                status_code=499,
                error_type="server_error",
                code="request_cancelled",
                account_email=account_email,
            ) from exc
        except FireflyQuotaExhausted as exc:
            try:
                account_service.report_exhausted(token, reason="taste_exhausted")
                image_slot_finalized = True
            except Exception as report_exc:
                logger.warning({
                    "event": "firefly_report_exhausted_failed",
                    "account_email": account_email,
                    "error": diagnostic_excerpt(report_exc, 500),
                    "mode": "edit",
                })
                finalize_image_slot(
                    False,
                    failure=image_failure("image_quota_exhausted", raw_detail=str(exc)),
                )
            last_error = ImageGenerationError(
                str(exc) or "firefly quota exhausted",
                status_code=429,
                error_type="insufficient_quota",
                code="insufficient_quota",
                account_email=account_email,
                raw_error=str(exc),
                upstream_error=str(exc),
            )
            logger.warning({
                "event": "firefly_quota_exhausted",
                "account_email": account_email,
                "index": index,
                "attempt": attempt,
                "error": diagnostic_excerpt(exc, 500),
                "mode": "edit",
            })
            continue
        except FireflyAuthError as exc:
            # 本地标异常，不带 auth_invalid failure（verify_account=True 会触发 OpenAI fetch_remote_info）
            try:
                account_service.update_account(token, {"status": "异常"}, quiet=True)
            except Exception as mark_exc:
                logger.warning({
                    "event": "firefly_auth_mark_abnormal_failed",
                    "account_email": account_email,
                    "error": diagnostic_excerpt(mark_exc, 500),
                    "mode": "edit",
                })
            finalize_image_slot(False)  # 不带 failure，避免 verify_account
            last_error = ImageGenerationError(
                str(exc) or "firefly authentication failed",
                status_code=401,
                error_type="authentication_error",
                code="auth_invalid",
                account_email=account_email,
                raw_error=str(exc),
                upstream_error=str(exc),
            )
            logger.warning({
                "event": "firefly_rotatable_error",
                "account_email": account_email,
                "index": index,
                "attempt": attempt,
                "error_type": type(exc).__name__,
                "error": diagnostic_excerpt(exc, 500),
                "mode": "edit",
            })
            continue
        except FireflyUpstreamTemporary as exc:
            finalize_image_slot(
                False,
                failure=image_failure("upstream_unavailable", raw_detail=str(exc)),
            )
            last_error = ImageGenerationError(
                str(exc) or "firefly upstream temporary failure",
                status_code=503,
                error_type="server_error",
                code="upstream_unavailable",
                account_email=account_email,
                raw_error=str(exc),
                upstream_error=str(exc),
            )
            logger.warning({
                "event": "firefly_rotatable_error",
                "account_email": account_email,
                "index": index,
                "attempt": attempt,
                "error_type": type(exc).__name__,
                "error": diagnostic_excerpt(exc, 500),
                "mode": "edit",
            })
            continue
        except FireflyRequestError as exc:
            finalize_image_slot(
                False,
                failure=image_failure("upstream_error", raw_detail=str(exc)),
            )
            raise ImageGenerationError(
                str(exc) or "firefly request failed",
                status_code=int(getattr(exc, "status_code", 0) or 400),
                error_type="invalid_request_error",
                code=str(getattr(exc, "code", "") or "upstream_error"),
                account_email=account_email,
                raw_error=str(exc),
                upstream_error=str(exc),
            ) from exc
        except ImageGenerationError:
            if not image_slot_finalized:
                finalize_image_slot(False, failure=image_failure("upstream_error"))
            raise
        except Exception as exc:
            finalize_image_slot(
                False,
                failure=classify_image_exception(exc),
            )
            rotatable = False
            try:
                rotatable = bool(is_rotatable_error(exc))
            except Exception:
                rotatable = False
            last_error = ImageGenerationError(
                image_stream_error_message(str(exc)),
                account_email=account_email,
                raw_error=str(exc),
                upstream_error=str(exc),
                code="upstream_error",
            )
            logger.warning({
                "event": "firefly_image_stream_fail",
                "account_email": account_email,
                "index": index,
                "attempt": attempt,
                "error": diagnostic_excerpt(exc, 1000),
                "mode": "edit",
            })
            if rotatable and attempt < max_attempts:
                continue
            raise last_error from exc
        finally:
            if token and not image_slot_finalized:
                try:
                    account_service.release_image_slot(token)
                    image_slot_finalized = True
                except Exception as release_exc:
                    logger.warning({
                        "event": "firefly_image_slot_orphan_release_failed",
                        "account_email": account_email,
                        "error": diagnostic_excerpt(release_exc, 500),
                        "mode": "edit",
                    })

    if last_error is not None:
        raise last_error
    raise ImageGenerationError(
        "firefly image edit failed after retries",
        status_code=503,
        error_type="server_error",
        code="no_available_account",
        account_email=account_email,
    )


def _stream_firefly_image_outputs(request: ConversationRequest) -> Iterator[ImageOutput]:
    """Firefly 渠道并行/串行编排，形状对齐 stream_image_outputs_with_pool。

    带参考图（request.images）走图生图，否则走文生图。
    """
    has_refs = bool(request.images)
    generate_fn = (
        _generate_single_image_firefly_edit if has_refs else _generate_single_image_firefly
    )
    mode = "edit" if has_refs else "text2image"

    if request.n <= 1:
        outputs = generate_fn(request, 1, 1)
        for output in outputs:
            yield output
        return

    if not config.image_parallel_generation:
        logger.info({
            "event": "firefly_image_serial_generation_start",
            "n": request.n,
            "model": request.model,
            "mode": mode,
        })
        for index in range(1, request.n + 1):
            outputs = generate_fn(request, index, request.n)
            for output in outputs:
                yield output
        return

    logger.info({
        "event": "firefly_image_parallel_generation_start",
        "n": request.n,
        "model": request.model,
        "mode": mode,
    })
    futures = {}
    results: dict[int, list[ImageOutput]] = {}
    errors: dict[int, Exception] = {}
    with ThreadPoolExecutor(max_workers=request.n) as executor:
        for index in range(1, request.n + 1):
            future = executor.submit(generate_fn, request, index, request.n)
            futures[future] = index

        emitted = False
        last_error = ""
        for future in as_completed(futures):
            index = futures[future]
            try:
                outputs = future.result()
                results[index] = outputs
                for output in outputs:
                    emitted = True
                    yield output
            except Exception as exc:
                errors[index] = exc
                last_error = str(exc)
                logger.warning({
                    "event": "firefly_image_parallel_generation_error",
                    "index": index,
                    "error": last_error[:300],
                    "mode": mode,
                })

    if errors:
        failed_indexes = sorted(errors.keys())
        success_indexes = sorted(results.keys())
        detail = "; ".join(f"index {i}: {errors[i]}" for i in failed_indexes)
        if not emitted:
            if not last_error:
                last_error = "no firefly account could generate images"
            raise ImageGenerationError(
                image_stream_error_message(last_error),
                conversation_id="",
                raw_error=last_error,
                upstream_error=last_error,
            )
        raise ImageGenerationError(
            f"partial image generation failure: {len(success_indexes)}/{request.n} succeeded; "
            f"failed indexes {failed_indexes}: {detail[:400]}",
            conversation_id="",
            raw_error=detail,
            upstream_error=detail,
            code="partial_image_failure",
        )

    if not emitted:
        if not last_error:
            last_error = "no firefly account could generate images"
        raise ImageGenerationError(
            image_stream_error_message(last_error),
            conversation_id="",
            raw_error=last_error,
            upstream_error=last_error,
        )


def _firefly_account_id(account: dict[str, Any] | None) -> str:
    """从账号记录取 Adobe/Firefly account_id（实体钉选匹配用）。"""
    if not isinstance(account, dict):
        return ""
    for key in ("account_id", "adobe_account_id", "user_id", "id"):
        value = str(account.get(key) or "").strip()
        if value:
            return value
    return ""


def _save_firefly_video_bytes(
        video_bytes: bytes,
        *,
        ext: str = "mp4",
        base_url: str | None = None,
) -> str:
    """视频字节落盘到 images_dir，返回本站 /images/... URL。

    不走 image_storage_service（其 index 仅登记图片扩展名），直接原子写本地。
    """
    if not video_bytes:
        raise ImageGenerationError(
            "firefly upstream returned empty video bytes",
            status_code=400,
            error_type="invalid_request_error",
            code="no_image_generated",
        )
    clean_ext = str(ext or "mp4").strip().lower().lstrip(".") or "mp4"
    if clean_ext not in {"mp4", "webm", "ogv", "mov", "m4v"}:
        clean_ext = "mp4"
    file_hash = hashlib.md5(video_bytes).hexdigest()
    now = time.localtime()
    relative_dir = Path(
        time.strftime("%Y", now),
        time.strftime("%m", now),
        time.strftime("%d", now),
    )
    rel = f"{relative_dir.as_posix()}/{int(time.time())}_{file_hash}.{clean_ext}"
    root = config.images_dir.resolve()
    path = (root / rel).resolve()
    try:
        path.relative_to(root)
    except ValueError as exc:
        raise ImageGenerationError(
            "invalid video storage path",
            status_code=500,
            error_type="server_error",
            code="upstream_error",
        ) from exc
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_bytes(video_bytes)
    tmp.replace(path)
    public_base = (base_url or config.base_url or "").rstrip("/")
    return f"{public_base}/images/{rel}" if public_base else f"/images/{rel}"


def _coerce_firefly_video_result(result: object) -> tuple[bytes, str]:
    """兼容 generate_video 返回 (bytes, ext) / bytes / dict。"""
    if isinstance(result, tuple) and result:
        data = result[0]
        ext = str(result[1] if len(result) > 1 else "mp4") or "mp4"
        if isinstance(data, (bytes, bytearray)):
            return bytes(data), ext.lstrip(".")
        raise ImageGenerationError(
            "firefly generate_video returned non-bytes result",
            status_code=502,
            error_type="server_error",
            code="upstream_error",
        )
    if isinstance(result, dict):
        for key in ("bytes", "video_bytes", "data", "content", "video"):
            if key in result and result[key] is not None:
                data = result[key]
                ext = str(result.get("ext") or result.get("extension") or "mp4")
                if isinstance(data, (bytes, bytearray)):
                    return bytes(data), ext.lstrip(".") or "mp4"
        raise ImageGenerationError(
            "firefly generate_video returned dict without video bytes",
            status_code=502,
            error_type="server_error",
            code="upstream_error",
        )
    if isinstance(result, (bytes, bytearray)):
        return bytes(result), "mp4"
    raise ImageGenerationError(
        "firefly generate_video returned non-bytes result",
        status_code=502,
        error_type="server_error",
        code="upstream_error",
    )


def _generate_single_video_firefly(
        request: ConversationRequest,
        index: int,
        total: int,
) -> list[ImageOutput]:
    """Firefly 视频单条编排：选号占槽 →（可选）上传参考图 → generate_video → 落盘。

    generate_video 为同步阻塞轮询，本函数本身在线程池 worker 内运行。
    prompt 含 @entity: 时钉选实体绑定账号（跨账号不可混用）。
    """
    try:
        from services.backends.firefly_video_catalog import (
            center_crop_to_resolution,
            max_input_images,
            resolve_firefly_video_model,
        )
        from services.backends.firefly_client import generate_video as firefly_generate_video
        from services.backends.firefly_client import upload_image as firefly_upload
        from services.backends.firefly_errors import (
            FireflyAuthError,
            FireflyQuotaExhausted,
            FireflyRequestError,
            FireflyUpstreamTemporary,
            is_rotatable_error,
        )
        from services.backends.firefly_video_payloads import build_firefly_video_payload
    except ImportError as exc:
        raise ImageGenerationError(
            f"firefly video backend modules are not available: {exc}",
            status_code=503,
            error_type="server_error",
            code="no_available_account",
        ) from exc

    try:
        from services.backends.firefly_entities import (
            required_account_id_for_prompt,
            resolve_entity_refs_for_prompt,
        )
    except ImportError:
        required_account_id_for_prompt = None  # type: ignore[assignment]
        resolve_entity_refs_for_prompt = None  # type: ignore[assignment]

    if not config.firefly_video_enabled:
        raise ImageGenerationError(
            "firefly video channel is disabled",
            status_code=503,
            error_type="server_error",
            code="no_available_account",
        )

    resolved = resolve_firefly_video_model(request.model, size=request.size)
    if resolved is None:
        raise ImageGenerationError(
            f"unsupported firefly video model: {request.model}",
            status_code=400,
            error_type="invalid_request_error",
            code="unsupported_model",
        )

    # 实体钉选：@entity:Name 绑定同一 Adobe 账号
    pinned_account_id = ""
    entity_mentions: list[dict[str, Any]] = []
    video_prompt = str(request.prompt or "")
    if callable(required_account_id_for_prompt) and "@entity:" in video_prompt:
        try:
            if callable(resolve_entity_refs_for_prompt):
                video_prompt, entity_mentions, pinned = resolve_entity_refs_for_prompt(video_prompt)
                pinned_account_id = str(pinned or "").strip()
            else:
                pinned_account_id = str(required_account_id_for_prompt(video_prompt) or "").strip()
        except ValueError as exc:
            raise ImageGenerationError(
                str(exc),
                status_code=400,
                error_type="invalid_request_error",
                code="invalid_entity",
            ) from exc

    # 规范化参考图（图生视频）；URL/dict/base64 均由 _decode_firefly_image_entry 处理
    refs = _normalize_firefly_image_inputs(request.images, request=request)
    # 请求带了 images 但规范化后 refs 为空 → 禁止静默退化成 t2v
    if request.images and not refs:
        raise ImageGenerationError(
            "failed to decode reference image(s) for firefly video",
            status_code=400,
            error_type="invalid_request_error",
            code="invalid_image",
        )

    max_refs = max_input_images(str(resolved.get("family") or ""))
    if len(refs) > max_refs:
        raise ImageGenerationError(
            f"video model supports at most {max_refs} input image(s)",
            status_code=400,
            error_type="invalid_request_error",
            code="invalid_image",
        )

    max_attempts = max(1, int(config.firefly_retry_max_attempts or 3))
    account_email = ""
    attempted_tokens: set[str] = set()
    last_error: Exception | None = None
    single_started = time.perf_counter()

    for attempt in range(1, max_attempts + 1):
        _raise_if_request_cancelled(request)
        account_wait_started = time.perf_counter()
        image_slot_finalized = False
        token = ""
        try:
            if request.progress_callback:
                request.progress_callback("getting_account")
            _monitor_image_stage(
                request,
                "image_getting_account",
                index=index,
                total=total,
                channel="firefly-video",
                attempt=attempt,
            )
            # 实体钉选：从 firefly 池里挑匹配 account_id 的号；无匹配则明确失败。
            # 注意：_image_slot_condition 底层是普通 Lock，持锁期间禁止再调 get_account。
            # 槽满时循环 wait（对齐 _acquire_next_candidate_token），避免长视频占槽误判无号。
            if pinned_account_id:
                with account_service._image_slot_condition:  # noqa: SLF001 — 与 image inflight 共用
                    def _pinned_available() -> list[str]:
                        return [
                            t
                            for t in account_service._list_available_candidate_tokens(  # noqa: SLF001
                                attempted_tokens,
                                plan_type=None,
                                source_type="firefly",
                                plan_types=None,
                            )
                            if _firefly_account_id(account_service._accounts.get(t)) == pinned_account_id  # noqa: SLF001
                        ]

                    def _pinned_ready() -> list[str]:
                        return [
                            t
                            for t in account_service._list_ready_candidate_tokens(  # noqa: SLF001
                                attempted_tokens, None, "firefly", None
                            )
                            if _firefly_account_id(account_service._accounts.get(t)) == pinned_account_id  # noqa: SLF001
                        ]

                    while True:
                        candidates = _pinned_available()
                        if candidates:
                            break
                        # 有 ready 但槽满 → 循环 wait；完全没有 ready → 直接失败
                        if not _pinned_ready():
                            raise ImageAccountSelectionError(
                                "unavailable",
                                f"no firefly account for entity-bound account_id={pinned_account_id}",
                            )
                        account_service._image_slot_condition.wait(timeout=1.0)  # noqa: SLF001
                    token = candidates[0]
                    account_service._image_inflight[token] = (  # noqa: SLF001
                        int(account_service._image_inflight.get(token, 0)) + 1  # noqa: SLF001
                    )
            else:
                token = account_service.get_available_access_token(
                    source_type="firefly",
                    excluded_tokens=attempted_tokens,
                )
        except ImageAccountSelectionError as exc:
            _monitor_image_stage(
                request,
                "image_local_rejected",
                local_reason="account_pool",
                status="failed",
                index=index,
                total=total,
                channel="firefly-video",
            )
            raise ImageGenerationError(
                str(exc) or "video generation failed",
                status_code=exc.status_code,
                error_type=exc.error_type,
                code=exc.code,
                account_email=account_email,
            ) from exc
        except RuntimeError as exc:
            raise ImageGenerationError(
                str(exc) or "video generation failed",
                account_email=account_email,
            ) from exc

        if token in attempted_tokens:
            try:
                account_service.release_image_slot(token)
            except Exception:
                pass
            if last_error is None:
                last_error = ImageGenerationError(
                    "firefly video account pool exhausted after retries",
                    status_code=503,
                    error_type="server_error",
                    code="no_available_account",
                )
            break
        attempted_tokens.add(token)

        account_wait_ms = int((time.perf_counter() - account_wait_started) * 1000)
        account = account_service.get_account(token) or {}
        account_email = str(account.get("email") or "").strip()
        proxy = str(account.get("proxy") or "").strip() or None
        attempt_access_token = token
        attempt_refresh_token = str(account.get("refresh_token") or "").strip()

        def finalize_image_slot(
            success: bool,
            *,
            failure: ImageFailure | None = None,
            quota_consumed: bool | None = None,
        ) -> None:
            nonlocal image_slot_finalized
            if image_slot_finalized:
                return
            image_slot_finalized = True
            try:
                account_service.mark_image_result(
                    token,
                    success,
                    failure=failure,
                    quota_consumed=quota_consumed,
                    expected_access_token=attempt_access_token,
                    expected_refresh_token=attempt_refresh_token or None,
                )
            except Exception as mark_exc:
                logger.warning({
                    "event": "firefly_video_account_result_update_failed",
                    "account_email": account_email,
                    "success": success,
                    "failure_code": failure.code if failure is not None else "",
                    "error": diagnostic_excerpt(mark_exc, 500),
                })
                try:
                    account_service.release_image_slot(token)
                except Exception as release_exc:
                    logger.warning({
                        "event": "firefly_video_account_slot_release_failed",
                        "account_email": account_email,
                        "error": diagnostic_excerpt(release_exc, 500),
                    })

        _monitor_image_stage(
            request,
            "image_account_lookup",
            account_wait_ms=account_wait_ms,
            account_email=account_email,
            account_found=bool(account),
            index=index,
            total=total,
            channel="firefly-video",
            attempt=attempt,
        )

        try:
            if request.progress_callback:
                request.progress_callback("starting_generation")
            _monitor_image_stage(
                request,
                "image_generation_start",
                account_email=account_email,
                index=index,
                total=total,
                channel="firefly-video",
                attempt=attempt,
            )

            # 图生视频：中心裁切 + 上传（复用 Phase 2 upload_image）
            source_image_ids: list[str] = []
            if refs:
                target_res = str(resolved.get("resolution") or "720p")
                aspect = str(resolved.get("aspect_ratio") or resolved.get("ratio") or "16:9")
                for image_bytes, mime in refs[:max_refs]:
                    try:
                        prepared = center_crop_to_resolution(image_bytes, target_res, aspect)
                        upload_mime = "image/png"
                    except Exception:
                        prepared = image_bytes
                        upload_mime = mime or "image/jpeg"
                    image_id = firefly_upload(token, prepared, upload_mime, proxy=proxy)
                    if image_id:
                        source_image_ids.append(str(image_id))

            payload = build_firefly_video_payload(
                resolved,
                video_prompt,
                reference_image_ids=source_image_ids or None,
                entity_mentions=entity_mentions or None,
            )
            gen_started = time.perf_counter()
            try:
                video_result = firefly_generate_video(
                    token,
                    payload,
                    proxy=proxy,
                    timeout=config.firefly_video_timeout_sec,
                    poll_interval=config.firefly_video_poll_interval_sec,
                )
            except TypeError:
                video_result = firefly_generate_video(token, payload, proxy=proxy)
            gen_ms = int((time.perf_counter() - gen_started) * 1000)
            video_bytes, video_ext = _coerce_firefly_video_result(video_result)
            video_url = _save_firefly_video_bytes(
                video_bytes,
                ext=video_ext,
                base_url=request.base_url,
            )
            data_item: dict[str, Any] = {"url": video_url, "revised_prompt": request.prompt}
            if request.response_format == "b64_json":
                data_item["b64_json"] = base64.b64encode(video_bytes).decode("ascii")
            output = ImageOutput(
                kind="result",
                model=request.model,
                index=index,
                total=total,
                data=[data_item],
                account_email=account_email,
            )
            # Firefly 真实额度靠 taste_exhausted/credits，成功不扣本地 quota
            finalize_image_slot(True, quota_consumed=False)
            if request.trace_image_perf:
                _monitor_image_stage(
                    request,
                    "image_single_done",
                    total_ms=int((time.perf_counter() - single_started) * 1000),
                    gen_ms=gen_ms,
                    status="success",
                    account_email=account_email,
                    index=index,
                    total=total,
                    channel="firefly-video",
                )
            return [output]
        except RequestCancelledError as exc:
            finalize_image_slot(False)
            raise ImageGenerationError(
                str(exc) or "request cancelled by administrator",
                status_code=499,
                error_type="server_error",
                code="request_cancelled",
                account_email=account_email,
            ) from exc
        except FireflyQuotaExhausted as exc:
            try:
                account_service.report_exhausted(token, reason="taste_exhausted")
                image_slot_finalized = True
            except Exception as report_exc:
                logger.warning({
                    "event": "firefly_video_report_exhausted_failed",
                    "account_email": account_email,
                    "error": diagnostic_excerpt(report_exc, 500),
                })
                finalize_image_slot(
                    False,
                    failure=image_failure("image_quota_exhausted", raw_detail=str(exc)),
                )
            last_error = ImageGenerationError(
                str(exc) or "firefly video quota exhausted",
                status_code=429,
                error_type="insufficient_quota",
                code="insufficient_quota",
                account_email=account_email,
                raw_error=str(exc),
                upstream_error=str(exc),
            )
            # 实体钉选不可换号；额度耗尽直接失败
            if pinned_account_id:
                raise last_error from exc
            logger.warning({
                "event": "firefly_video_quota_exhausted",
                "account_email": account_email,
                "index": index,
                "attempt": attempt,
                "error": diagnostic_excerpt(exc, 500),
            })
            continue
        except FireflyAuthError as exc:
            try:
                account_service.update_account(token, {"status": "异常"}, quiet=True)
            except Exception as mark_exc:
                logger.warning({
                    "event": "firefly_video_auth_mark_abnormal_failed",
                    "account_email": account_email,
                    "error": diagnostic_excerpt(mark_exc, 500),
                })
            finalize_image_slot(False)
            last_error = ImageGenerationError(
                str(exc) or "firefly video authentication failed",
                status_code=401,
                error_type="authentication_error",
                code="auth_invalid",
                account_email=account_email,
                raw_error=str(exc),
                upstream_error=str(exc),
            )
            if pinned_account_id:
                raise last_error from exc
            logger.warning({
                "event": "firefly_video_rotatable_error",
                "account_email": account_email,
                "index": index,
                "attempt": attempt,
                "error_type": type(exc).__name__,
                "error": diagnostic_excerpt(exc, 500),
            })
            continue
        except FireflyUpstreamTemporary as exc:
            finalize_image_slot(
                False,
                failure=image_failure("upstream_unavailable", raw_detail=str(exc)),
            )
            last_error = ImageGenerationError(
                str(exc) or "firefly video upstream temporary failure",
                status_code=503,
                error_type="server_error",
                code="upstream_unavailable",
                account_email=account_email,
                raw_error=str(exc),
                upstream_error=str(exc),
            )
            if pinned_account_id:
                raise last_error from exc
            logger.warning({
                "event": "firefly_video_rotatable_error",
                "account_email": account_email,
                "index": index,
                "attempt": attempt,
                "error_type": type(exc).__name__,
                "error": diagnostic_excerpt(exc, 500),
            })
            continue
        except FireflyRequestError as exc:
            finalize_image_slot(
                False,
                failure=image_failure("upstream_error", raw_detail=str(exc)),
            )
            raise ImageGenerationError(
                str(exc) or "firefly video request failed",
                status_code=int(getattr(exc, "status_code", 0) or 400),
                error_type="invalid_request_error",
                code=str(getattr(exc, "code", "") or "upstream_error"),
                account_email=account_email,
                raw_error=str(exc),
                upstream_error=str(exc),
            ) from exc
        except ImageGenerationError:
            if not image_slot_finalized:
                finalize_image_slot(False, failure=image_failure("upstream_error"))
            raise
        except Exception as exc:
            finalize_image_slot(
                False,
                failure=classify_image_exception(exc),
            )
            rotatable = False
            try:
                rotatable = bool(is_rotatable_error(exc))
            except Exception:
                rotatable = False
            last_error = ImageGenerationError(
                image_stream_error_message(str(exc)),
                account_email=account_email,
                raw_error=str(exc),
                upstream_error=str(exc),
                code="upstream_error",
            )
            logger.warning({
                "event": "firefly_video_stream_fail",
                "account_email": account_email,
                "index": index,
                "attempt": attempt,
                "error": diagnostic_excerpt(exc, 1000),
            })
            if rotatable and attempt < max_attempts and not pinned_account_id:
                continue
            raise last_error from exc
        finally:
            if token and not image_slot_finalized:
                try:
                    account_service.release_image_slot(token)
                    image_slot_finalized = True
                except Exception as release_exc:
                    logger.warning({
                        "event": "firefly_video_slot_orphan_release_failed",
                        "account_email": account_email,
                        "error": diagnostic_excerpt(release_exc, 500),
                    })

    if last_error is not None:
        raise last_error
    raise ImageGenerationError(
        "firefly video generation failed after retries",
        status_code=503,
        error_type="server_error",
        code="no_available_account",
        account_email=account_email,
    )


def stream_video_outputs_with_pool(request: ConversationRequest) -> Iterator[ImageOutput]:
    """Firefly 视频编排入口（不做聊天伪流式；n>1 串行，复用 image inflight）。"""
    if not is_firefly_video_model(request.model) and not is_firefly_model(request.model):
        raise ImageGenerationError(
            f"unsupported video model: {request.model}",
            status_code=400,
            error_type="invalid_request_error",
            code="unsupported_model",
        )
    if not is_firefly_video_model(request.model):
        raise ImageGenerationError(
            f"model is not a firefly video model: {request.model}",
            status_code=400,
            error_type="invalid_request_error",
            code="unsupported_model",
        )

    n = max(1, int(request.n or 1))
    if n <= 1:
        outputs = _generate_single_video_firefly(request, 1, 1)
        for output in outputs:
            yield output
        return

    # 视频任务更重：默认串行，避免同时占满账号与线程池
    logger.info({
        "event": "firefly_video_serial_generation_start",
        "n": n,
        "model": request.model,
    })
    for index in range(1, n + 1):
        outputs = _generate_single_video_firefly(request, index, n)
        for output in outputs:
            yield output


def stream_image_outputs_with_pool(request: ConversationRequest) -> Iterator[ImageOutput]:
    """并行生成多张图片，每张图片使用独立线程和账号，互不阻塞。"""
    # 视频模型请走 /v1/videos/generations，避免污染 images 语义
    if is_firefly_video_model(request.model):
        raise ImageGenerationError(
            "firefly video models require POST /v1/videos/generations",
            status_code=400,
            error_type="invalid_request_error",
            code="unsupported_model",
        )
    # 渠道分发：firefly-* 不进 ChatGPT 上游
    if is_firefly_model(request.model):
        yield from _stream_firefly_image_outputs(request)
        return

    if not is_supported_image_model(request.model):
        _monitor_image_stage(
            request,
            "image_local_rejected",
            local_reason="unsupported_model",
            status="failed",
        )
        raise ImageGenerationError("unsupported image model,supported models: " + ", ".join(sorted(IMAGE_MODELS)))

    if request.n <= 1:
        # 单张图片，直接执行（无需线程池开销）
        outputs = _generate_single_image(request, 1, 1)
        for output in outputs:
            yield output
        return

    # 多张图片：根据配置选择并行或串行执行
    if not config.image_parallel_generation:
        logger.info({
            "event": "image_serial_generation_start",
            "n": request.n,
            "model": request.model,
        })
        for index in range(1, request.n + 1):
            outputs = _generate_single_image(request, index, request.n)
            for output in outputs:
                yield output
        return

    logger.info({
        "event": "image_parallel_generation_start",
        "n": request.n,
        "model": request.model,
    })
    # 每张图片一个线程，同时启动
    futures = {}
    results: dict[int, list[ImageOutput]] = {}
    errors: dict[int, Exception] = {}
    with ThreadPoolExecutor(max_workers=request.n) as executor:
        for index in range(1, request.n + 1):
            future = executor.submit(_generate_single_image, request, index, request.n)
            futures[future] = index

        # yield 结果：按完成顺序立即输出，不再等所有图片都结束后才返回成功结果。
        emitted = False
        last_error = ""

        for future in as_completed(futures):
            index = futures[future]
            try:
                outputs = future.result()
                results[index] = outputs
                for output in outputs:
                    emitted = True
                    yield output
            except Exception as exc:
                errors[index] = exc
                last_error = str(exc)
                logger.warning({
                    "event": "image_parallel_generation_error",
                    "index": index,
                    "error": last_error[:300],
                })
                if not emitted:
                    logger.warning({
                        "event": "image_parallel_failure_before_success",
                        "failed_index": index,
                        "error": last_error[:200],
                    })

    # 并行 n>1：部分 index 失败时不能静默当全成功（客户端会收到 HTTP 200 少图）。
    # 方案 a：已有成功输出仍统一 raise partial failure，让上层映射为错误语义。
    if errors:
        failed_indexes = sorted(errors.keys())
        success_indexes = sorted(results.keys())
        detail = "; ".join(f"index {i}: {errors[i]}" for i in failed_indexes)
        for index in failed_indexes:
            logger.warning({
                "event": "image_parallel_partial_failure",
                "failed_index": index,
                "success_count": len(success_indexes),
                "failed_count": len(failed_indexes),
                "error": str(errors[index])[:200],
            })
        if not emitted:
            if not last_error:
                last_error = "no account in the pool could generate images — check account quota and rate-limit status"
            raise ImageGenerationError(
                image_stream_error_message(last_error),
                conversation_id="",
                raw_error=last_error,
                upstream_error=last_error,
            )
        raise ImageGenerationError(
            f"partial image generation failure: {len(success_indexes)}/{request.n} succeeded; "
            f"failed indexes {failed_indexes}: {detail[:400]}",
            conversation_id="",
            raw_error=detail,
            upstream_error=detail,
            code="partial_image_failure",
        )

    if not emitted:
        if not last_error:
            last_error = "no account in the pool could generate images — check account quota and rate-limit status"
        raise ImageGenerationError(
            image_stream_error_message(last_error),
            conversation_id="",
            raw_error=last_error,
            upstream_error=last_error,
        )


def _image_stream_payload(output: ImageOutput, event_type: str, payload: dict[str, Any]) -> dict[str, Any]:
    item = {"type": event_type, **payload}
    if output.account_email:
        item["_account_email"] = output.account_email
    if output.conversation_id:
        item["_conversation_id"] = output.conversation_id
    return item


def _image_stream_partial_count(value: object) -> int:
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError):
        return 0


def stream_image_chunks(
    outputs: Iterable[ImageOutput],
    event_prefix: str = "image_generation",
    usage_builder: Callable[[list[dict[str, Any]]], dict[str, Any]] | None = None,
    partial_images: object = 0,
) -> Iterator[dict[str, Any]]:
    prefix = str(event_prefix or "image_generation").strip() or "image_generation"
    emit_partial = _image_stream_partial_count(partial_images) > 0
    for output in outputs:
        if output.kind == "result":
            for item_index, item in enumerate(output.data):
                if not isinstance(item, dict):
                    continue
                b64_json = str(item.get("b64_json") or "").strip()
                if not b64_json:
                    continue
                if emit_partial:
                    yield _image_stream_payload(
                        output,
                        f"{prefix}.partial_image",
                        {
                            "b64_json": b64_json,
                            "partial_image_index": max(0, item_index),
                        },
                    )
                completed: dict[str, Any] = {"b64_json": b64_json}
                if usage_builder:
                    usage = usage_builder([item])
                    if usage:
                        completed["usage"] = usage
                completed_payload = _image_stream_payload(output, f"{prefix}.completed", completed)
                image_url = str(item.get("url") or "").strip()
                if image_url:
                    completed_payload["_image_urls"] = [image_url]
                yield completed_payload
        elif output.kind == "message" and output.text:
            yield _image_stream_payload(
                output,
                f"{prefix}.failed",
                {"error": {"message": output.text, "type": "image_generation_error"}},
            )


def collect_image_outputs(outputs: Iterable[ImageOutput]) -> dict[str, Any]:
    created = None
    data: list[dict[str, Any]] = []
    message = ""
    progress_parts: list[str] = []
    account_email = ""
    for output in outputs:
        created = created or output.created
        if output.account_email and not account_email:
            account_email = output.account_email
        if output.kind == "progress" and output.text:
            progress_parts.append(output.text)
        elif output.kind == "message":
            message = output.text
        elif output.kind == "result":
            data.extend(output.data)

    result: dict[str, Any] = {"created": created or int(time.time()), "data": data}
    if not data:
        text = message or "".join(progress_parts).strip()
        if text:
            result["message"] = text
    if account_email:
        result["_account_email"] = account_email
    return result
