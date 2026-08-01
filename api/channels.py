"""渠道描述符 + trace 溯源查询 + Firefly credits 对账 API。"""

from __future__ import annotations

from fastapi import APIRouter, Header, HTTPException, Query
from starlette.concurrency import run_in_threadpool

from api.support import require_admin, require_identity
from services.channel_reconcile_service import (
    DEFAULT_RECONCILE_TOLERANCE,
    reconcile_firefly_credits,
)
from services.channels.descriptors import build_channel_descriptors
from services.trace_snapshot_service import trace_snapshot_service


def create_router() -> APIRouter:
    router = APIRouter()

    @router.get("/api/channels")
    async def list_channels_api(authorization: str | None = Header(default=None)):
        # 鉴权手写：与现有 api/* 一致，非中间件
        require_identity(authorization)
        return {"channels": build_channel_descriptors()}

    @router.get("/api/channels/traces/{trace_id}")
    async def get_channel_trace(
        trace_id: str,
        authorization: str | None = Header(default=None),
    ):
        """按 trace_id 返回脱敏载荷快照 + attempt 序列 + 阶段耗时。

        鉴权：require_admin（载荷含 prompt，仅管理员可见）。
        """
        require_admin(authorization)
        tid = str(trace_id or "").strip()
        if not tid:
            raise HTTPException(status_code=400, detail={"error": "trace_id 不能为空"})
        data = trace_snapshot_service.get_trace(tid)
        if data is None:
            raise HTTPException(status_code=404, detail={"error": "trace 不存在或已过期"})
        return data

    @router.post("/api/channels/firefly/reconcile")
    async def reconcile_firefly_credits_api(
        authorization: str | None = Header(default=None),
        tolerance: float = Query(default=DEFAULT_RECONCILE_TOLERANCE, ge=0),
    ):
        """手动触发 Firefly credits 对账（admin）。

        拉取各 firefly 账号远端余额，与本地 channel_usage 流水累计比对，标出漂移。
        底层 curl_cffi 同步，丢线程池执行。
        """
        require_admin(authorization)
        result = await run_in_threadpool(
            reconcile_firefly_credits,
            tolerance=float(tolerance),
        )
        return result

    return router
