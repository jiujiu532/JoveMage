from __future__ import annotations

"""Firefly image/video orchestration extracted from conversation.py.

Pure move of Firefly pool/account/upload/generate flows. ChatGPT image paths
and shared SSE helpers remain in conversation.py.
"""

import base64
import hashlib
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Callable, Iterator

from services.account_service import ImageAccountSelectionError, account_service
from services.backends.firefly_catalog import resolve_firefly_image_model
from services.backends.firefly_client import generate_image as firefly_generate
from services.backends.firefly_client import generate_video as firefly_generate_video
from services.backends.firefly_client import upload_image as firefly_upload
from services.backends.firefly_errors import (
    FireflyAuthError,
    FireflyQuotaExhausted,
    FireflyRequestError,
    FireflyUpstreamTemporary,
    is_rotatable_error,
)
from services.backends.firefly_image_utils import fetch_image_bytes as firefly_fetch
from services.backends.firefly_payloads import (
    build_image2image_payload,
    build_text2image_payload,
)
from services.backends.firefly_video_catalog import (
    center_crop_to_resolution,
    max_input_images,
    resolve_firefly_video_model,
)
from services.backends.firefly_video_payloads import build_firefly_video_payload
from services.channel_usage_service import channel_usage_service
from services.config import config
from services.image_failure import ImageFailure, classify_image_exception, image_failure
from services.protocol.conversation import (
    _monitor_image_stage,
    _raise_if_request_cancelled,
    format_image_result,
    image_stream_error_message,
)
from services.protocol.conversation_types import (
    ConversationRequest,
    ImageGenerationError,
    ImageOutput,
)
from services.request_cancel_service import RequestCancelledError
from utils.diagnostics import diagnostic_excerpt
from utils.helper import is_firefly_model, is_firefly_video_model
from utils.log import logger

# 槽位 finalize：success + 可选 failure / quota_consumed
FinalizeImageSlot = Callable[..., None]
# 选号：attempted_tokens → access_token（内部应已占槽）
SelectFireflyToken = Callable[[set[str]], str]
# 单次尝试业务：token + account + finalize(*, attempt) → outputs
ExecuteFireflyAttempt = Callable[..., list[ImageOutput]]


def _default_select_firefly_token(attempted_tokens: set[str]) -> str:
    """默认 Firefly 选号：source_type=firefly，排除已尝试 token。"""
    return account_service.get_available_access_token(
        source_type="firefly",
        excluded_tokens=attempted_tokens,
    )


def _run_firefly_account_attempts(
        request: ConversationRequest,
        *,
        index: int,
        total: int,
        channel: str,
        execute: ExecuteFireflyAttempt,
        max_attempts: int,
        select_token: SelectFireflyToken | None = None,
        allow_rotate: bool = True,
        monitor_extra: dict[str, Any] | None = None,
        log_kind: str = "image",
        subject: str = "firefly",
        selection_failed_label: str = "image generation failed",
        exhausted_message: str = "firefly account pool exhausted after retries",
        failed_message: str = "firefly image generation failed after retries",
) -> list[ImageOutput]:
    """Firefly 三编排公共骨架：选号占槽 → execute → 错误分类/换号/放槽。

    execute(token, account, finalize) 只保留 payload/upload/generate/落盘等差异。
    allow_rotate=False 时（视频实体钉选）rotatable 错误也不换号，直接抛 last_error。
    Auth 失败只本地 update_account(异常)，不带 auth_invalid failure，避免触发 OpenAI verify。
    """
    select = select_token or _default_select_firefly_token
    extra = dict(monitor_extra or {})
    is_video = str(log_kind or "image").strip().lower() == "video"
    # 账本 channel 收敛为 firefly；action 区分 image/edit/video
    ledger_channel = "firefly"
    if is_video:
        ledger_action = "video"
    elif str(extra.get("mode") or "").strip().lower() == "edit":
        ledger_action = "edit"
    else:
        ledger_action = "image"
    if is_video:
        evt_result_update = "firefly_video_account_result_update_failed"
        evt_slot_release = "firefly_video_account_slot_release_failed"
        evt_report_exhausted = "firefly_video_report_exhausted_failed"
        evt_auth_mark = "firefly_video_auth_mark_abnormal_failed"
        evt_quota = "firefly_video_quota_exhausted"
        evt_rotatable = "firefly_video_rotatable_error"
        evt_stream_fail = "firefly_video_stream_fail"
        evt_orphan = "firefly_video_slot_orphan_release_failed"
    else:
        evt_result_update = "firefly_image_account_result_update_failed"
        evt_slot_release = "firefly_image_account_slot_release_failed"
        evt_report_exhausted = "firefly_report_exhausted_failed"
        evt_auth_mark = "firefly_auth_mark_abnormal_failed"
        evt_quota = "firefly_quota_exhausted"
        evt_rotatable = "firefly_rotatable_error"
        evt_stream_fail = "firefly_image_stream_fail"
        evt_orphan = "firefly_image_slot_orphan_release_failed"

    account_email = ""
    attempted_tokens: set[str] = set()
    last_error: Exception | None = None
    attempts = max(1, int(max_attempts or 1))

    def _record_ledger(
        *,
        token: str,
        account: dict[str, Any],
        success: bool,
        failure: ImageFailure | None = None,
        quota_consumed: bool | None = None,
        attempt_seq: int | None = None,
        attempt_started: float | None = None,
    ) -> None:
        """attempt 轨迹 + 用量流水；异常吞掉避免影响主链路。"""
        try:
            elapsed_ms = None
            if attempt_started is not None:
                elapsed_ms = int((time.perf_counter() - attempt_started) * 1000)
            channel_usage_service.record_image_result(
                trace_id=str(request.trace_id or request.call_id or ""),
                channel=ledger_channel,
                account=account if isinstance(account, dict) else {},
                access_token=token,
                action=ledger_action,
                model=str(request.model or ""),
                success=success,
                quota_consumed=quota_consumed,
                failure=failure,
                attempt_seq=attempt_seq,
                elapsed_ms=elapsed_ms,
            )
        except Exception as ledger_exc:
            logger.warning({
                "event": "channel_usage_record_failed",
                "channel": ledger_channel,
                "error": diagnostic_excerpt(ledger_exc, 500),
            })

    for attempt in range(1, attempts + 1):
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
                channel=channel,
                attempt=attempt,
                **extra,
            )
            token = select(attempted_tokens)
        except ImageAccountSelectionError as exc:
            _monitor_image_stage(
                request,
                "image_local_rejected",
                local_reason="account_pool",
                status="failed",
                index=index,
                total=total,
                channel=channel,
                **extra,
            )
            raise ImageGenerationError(
                str(exc) or selection_failed_label,
                status_code=exc.status_code,
                error_type=exc.error_type,
                code=exc.code,
                account_email=account_email,
            ) from exc
        except RuntimeError as exc:
            raise ImageGenerationError(
                str(exc) or selection_failed_label,
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
                    exhausted_message,
                    status_code=503,
                    error_type="server_error",
                    code="no_available_account",
                )
            break
        attempted_tokens.add(token)

        account_wait_ms = int((time.perf_counter() - account_wait_started) * 1000)
        account = account_service.get_account(token) or {}
        account_email = str(account.get("email") or "").strip()
        attempt_access_token = token
        attempt_refresh_token = str(account.get("refresh_token") or "").strip()
        attempt_started = time.perf_counter()

        def finalize_image_slot(
            success: bool,
            *,
            failure: ImageFailure | None = None,
            quota_consumed: bool | None = None,
            _token: str = token,
            _account: dict[str, Any] = account if isinstance(account, dict) else {},
            _attempt: int = attempt,
            _attempt_started: float = attempt_started,
        ) -> None:
            nonlocal image_slot_finalized
            if image_slot_finalized:
                return
            image_slot_finalized = True
            try:
                account_service.mark_image_result(
                    _token,
                    success,
                    failure=failure,
                    quota_consumed=quota_consumed,
                    expected_access_token=attempt_access_token,
                    expected_refresh_token=attempt_refresh_token or None,
                )
            except Exception as mark_exc:
                log_payload = {
                    "event": evt_result_update,
                    "account_email": account_email,
                    "success": success,
                    "failure_code": failure.code if failure is not None else "",
                    "error": diagnostic_excerpt(mark_exc, 500),
                }
                log_payload.update(extra)
                logger.warning(log_payload)
                try:
                    account_service.release_image_slot(_token)
                except Exception as release_exc:
                    release_payload = {
                        "event": evt_slot_release,
                        "account_email": account_email,
                        "error": diagnostic_excerpt(release_exc, 500),
                    }
                    release_payload.update(extra)
                    logger.warning(release_payload)
            # attempt 轨迹 + 用量流水
            _record_ledger(
                token=_token,
                account=_account,
                success=success,
                failure=failure,
                quota_consumed=quota_consumed,
                attempt_seq=_attempt,
                attempt_started=_attempt_started,
            )

        _monitor_image_stage(
            request,
            "image_account_lookup",
            account_wait_ms=account_wait_ms,
            account_email=account_email,
            account_found=bool(account),
            index=index,
            total=total,
            channel=channel,
            attempt=attempt,
            **extra,
        )

        try:
            return execute(
                token,
                account if isinstance(account, dict) else {},
                finalize_image_slot,
                attempt=attempt,
            )
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
                # report_exhausted 不走 finalize，单独补 attempt 流水
                _record_ledger(
                    token=token,
                    account=account if isinstance(account, dict) else {},
                    success=False,
                    failure=image_failure("image_quota_exhausted", raw_detail=str(exc)),
                    quota_consumed=False,
                    attempt_seq=attempt,
                    attempt_started=attempt_started,
                )
            except Exception as report_exc:
                report_payload = {
                    "event": evt_report_exhausted,
                    "account_email": account_email,
                    "error": diagnostic_excerpt(report_exc, 500),
                }
                report_payload.update(extra)
                logger.warning(report_payload)
                finalize_image_slot(
                    False,
                    failure=image_failure("image_quota_exhausted", raw_detail=str(exc)),
                )
            last_error = ImageGenerationError(
                str(exc) or f"{subject} quota exhausted",
                status_code=429,
                error_type="insufficient_quota",
                code="insufficient_quota",
                account_email=account_email,
                raw_error=str(exc),
                upstream_error=str(exc),
            )
            if not allow_rotate:
                raise last_error from exc
            quota_payload = {
                "event": evt_quota,
                "account_email": account_email,
                "index": index,
                "attempt": attempt,
                "error": diagnostic_excerpt(exc, 500),
            }
            quota_payload.update(extra)
            logger.warning(quota_payload)
            continue
        except FireflyAuthError as exc:
            # 本地标异常，不带 auth_invalid failure（verify_account=True 会触发 OpenAI fetch_remote_info）
            try:
                account_service.update_account(token, {"status": "异常"}, quiet=True)
            except Exception as mark_exc:
                auth_payload = {
                    "event": evt_auth_mark,
                    "account_email": account_email,
                    "error": diagnostic_excerpt(mark_exc, 500),
                }
                auth_payload.update(extra)
                logger.warning(auth_payload)
            finalize_image_slot(False)  # 不带 failure，避免 verify_account
            last_error = ImageGenerationError(
                str(exc) or f"{subject} authentication failed",
                status_code=401,
                error_type="authentication_error",
                code="auth_invalid",
                account_email=account_email,
                raw_error=str(exc),
                upstream_error=str(exc),
            )
            if not allow_rotate:
                raise last_error from exc
            rot_payload = {
                "event": evt_rotatable,
                "account_email": account_email,
                "index": index,
                "attempt": attempt,
                "error_type": type(exc).__name__,
                "error": diagnostic_excerpt(exc, 500),
            }
            rot_payload.update(extra)
            logger.warning(rot_payload)
            continue
        except FireflyUpstreamTemporary as exc:
            finalize_image_slot(
                False,
                failure=image_failure("upstream_unavailable", raw_detail=str(exc)),
            )
            last_error = ImageGenerationError(
                str(exc) or f"{subject} upstream temporary failure",
                status_code=503,
                error_type="server_error",
                code="upstream_unavailable",
                account_email=account_email,
                raw_error=str(exc),
                upstream_error=str(exc),
            )
            if not allow_rotate:
                raise last_error from exc
            temp_payload = {
                "event": evt_rotatable,
                "account_email": account_email,
                "index": index,
                "attempt": attempt,
                "error_type": type(exc).__name__,
                "error": diagnostic_excerpt(exc, 500),
            }
            temp_payload.update(extra)
            logger.warning(temp_payload)
            # 上游临时错误：换号重试
            continue
        except FireflyRequestError as exc:
            finalize_image_slot(
                False,
                failure=image_failure("upstream_error", raw_detail=str(exc)),
            )
            raise ImageGenerationError(
                str(exc) or f"{subject} request failed",
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
            fail_payload = {
                "event": evt_stream_fail,
                "account_email": account_email,
                "index": index,
                "attempt": attempt,
                "error": diagnostic_excerpt(exc, 1000),
            }
            fail_payload.update(extra)
            logger.warning(fail_payload)
            if rotatable and attempt < attempts and allow_rotate:
                continue
            raise last_error from exc
        finally:
            # 仅兜底未 finalize 的路径（异常中途/漏释放）
            if token and not image_slot_finalized:
                try:
                    account_service.release_image_slot(token)
                    image_slot_finalized = True
                except Exception as release_exc:
                    orphan_payload = {
                        "event": evt_orphan,
                        "account_email": account_email,
                        "error": diagnostic_excerpt(release_exc, 500),
                    }
                    orphan_payload.update(extra)
                    logger.warning(orphan_payload)

    if last_error is not None:
        raise last_error
    raise ImageGenerationError(
        failed_message,
        status_code=503,
        error_type="server_error",
        code="no_available_account",
        account_email=account_email,
    )


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
    single_started = time.perf_counter()

    def execute(
        token: str,
        account: dict[str, Any],
        finalize_image_slot: FinalizeImageSlot,
        *,
        attempt: int = 1,
    ) -> list[ImageOutput]:
        account_email = str(account.get("email") or "").strip()
        proxy = str(account.get("proxy") or "").strip() or None
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

    return _run_firefly_account_attempts(
        request,
        index=index,
        total=total,
        channel="firefly",
        execute=execute,
        max_attempts=max_attempts,
        subject="firefly",
        selection_failed_label="image generation failed",
        exhausted_message="firefly account pool exhausted after retries",
        failed_message="firefly image generation failed after retries",
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
    single_started = time.perf_counter()
    monitor_extra = {"mode": "edit"}

    def execute(
        token: str,
        account: dict[str, Any],
        finalize_image_slot: FinalizeImageSlot,
        *,
        attempt: int = 1,
    ) -> list[ImageOutput]:
        account_email = str(account.get("email") or "").strip()
        proxy = str(account.get("proxy") or "").strip() or None
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

    return _run_firefly_account_attempts(
        request,
        index=index,
        total=total,
        channel="firefly",
        execute=execute,
        max_attempts=max_attempts,
        monitor_extra=monitor_extra,
        subject="firefly",
        selection_failed_label="image generation failed",
        exhausted_message="firefly account pool exhausted after retries",
        failed_message="firefly image edit failed after retries",
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
    # 实体 helper 可选：缺失时不钉选账号（与搬迁前 ImportError 回退一致）
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
    single_started = time.perf_counter()

    def select_token(attempted_tokens: set[str]) -> str:
        # 实体钉选：从 firefly 池里挑匹配 account_id 的号；无匹配则明确失败。
        # 注意：_image_slot_condition 底层是普通 Lock，持锁期间禁止再调 get_account。
        # 槽满时循环 wait（对齐 _acquire_next_candidate_token），避免长视频占槽误判无号。
        if not pinned_account_id:
            return _default_select_firefly_token(attempted_tokens)
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
            return token

    def execute(
        token: str,
        account: dict[str, Any],
        finalize_image_slot: FinalizeImageSlot,
        *,
        attempt: int = 1,
    ) -> list[ImageOutput]:
        account_email = str(account.get("email") or "").strip()
        proxy = str(account.get("proxy") or "").strip() or None
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

    return _run_firefly_account_attempts(
        request,
        index=index,
        total=total,
        channel="firefly-video",
        execute=execute,
        max_attempts=max_attempts,
        select_token=select_token,
        allow_rotate=not bool(pinned_account_id),
        log_kind="video",
        subject="firefly video",
        selection_failed_label="video generation failed",
        exhausted_message="firefly video account pool exhausted after retries",
        failed_message="firefly video generation failed after retries",
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

