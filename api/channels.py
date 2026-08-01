"""渠道描述符只读 API。"""

from __future__ import annotations

from fastapi import APIRouter, Header

from api.support import require_identity
from services.channels.descriptors import build_channel_descriptors


def create_router() -> APIRouter:
    router = APIRouter()

    @router.get("/api/channels")
    async def list_channels_api(authorization: str | None = Header(default=None)):
        # 鉴权手写：与现有 api/* 一致，非中间件
        require_identity(authorization)
        return {"channels": build_channel_descriptors()}

    return router
