"""OpenAI 风格 Firefly 视频生成薄封装。

对齐 openai_v1_image_generations.handle 的形态：
校验 body → ConversationRequest → stream_video_outputs_with_pool → collect。
不提供聊天伪流式。
"""

from __future__ import annotations

from typing import Any

from services.config import config
from services.protocol.conversation import (
    ConversationRequest,
    ImageGenerationError,
    collect_image_outputs,
    stream_video_outputs_with_pool,
)
from utils.helper import is_firefly_video_model


def handle(body: dict[str, Any]) -> dict[str, Any]:
    prompt = str(body.get("prompt") or "").strip()
    if not prompt:
        raise ImageGenerationError(
            "prompt is required",
            status_code=400,
            error_type="invalid_request_error",
            code="invalid_prompt",
        )

    model = str(body.get("model") or config.firefly_video_default_model or "firefly-sora2-4s-16x9").strip()
    if not is_firefly_video_model(model):
        raise ImageGenerationError(
            f"unsupported video model: {model}",
            status_code=400,
            error_type="invalid_request_error",
            code="unsupported_model",
        )

    if not config.firefly_video_enabled:
        raise ImageGenerationError(
            "firefly video channel is disabled",
            status_code=503,
            error_type="server_error",
            code="no_available_account",
        )

    try:
        n = max(1, int(body.get("n") or 1))
    except (TypeError, ValueError):
        n = 1

    size = body.get("size")
    response_format = str(body.get("response_format") or "url")
    base_url = str(body.get("base_url") or "") or None
    progress_callback = body.get("progress_callback")
    images = body.get("images")
    if images is not None and not isinstance(images, list):
        images = [images]

    outputs = stream_video_outputs_with_pool(
        ConversationRequest(
            prompt=prompt,
            model=model,
            n=n,
            size=size if size is None else str(size),
            response_format=response_format,
            base_url=base_url,
            images=images,
            message_as_error=True,
            progress_callback=progress_callback,
            call_id=str(body.get("_call_id") or ""),
            trace_image_perf=bool(body.get("_trace_image_perf")),
        )
    )
    result = collect_image_outputs(outputs)
    result["model"] = model
    if not result.get("data"):
        raise ImageGenerationError(
            "no video generated",
            status_code=400,
            error_type="invalid_request_error",
            code="no_image_generated",
        )
    return result
