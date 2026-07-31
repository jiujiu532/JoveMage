"""Firefly 视频生成路由：POST /v1/videos/generations。

鉴权手写 require_identity；业务走 LoggedCall.run（线程池 + 统一错误体）。
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Header, Request
from pydantic import BaseModel, ConfigDict, Field

from api.support import require_identity, resolve_image_base_url
from services.log_service import LoggedCall
from services.protocol import openai_v1_video_generations


class VideoGenerationRequest(BaseModel):
    model_config = ConfigDict(extra="allow")

    prompt: str = Field(..., min_length=1)
    model: str = "firefly-sora2-4s-16x9"
    n: int = 1
    size: str | None = None
    response_format: str = "url"
    images: list[Any] | None = None


def create_router() -> APIRouter:
    router = APIRouter()

    @router.post("/v1/videos/generations")
    async def generate_videos(
        body: VideoGenerationRequest,
        request: Request,
        authorization: str | None = Header(default=None),
    ):
        identity = require_identity(authorization)
        payload = body.model_dump(mode="python")
        payload["base_url"] = resolve_image_base_url(request)
        call = LoggedCall(
            identity,
            "/v1/videos/generations",
            body.model,
            "文生视频",
            request_text=body.prompt,
        )
        # 视频同步阻塞；LoggedCall.run 已 run_in_threadpool
        return await call.run(openai_v1_video_generations.handle, payload)

    return router
