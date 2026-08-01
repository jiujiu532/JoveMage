"""Adobe Firefly 3P 客户端：图像提交/轮询/下载、图生图上传、视频生成。

移植自 adobe2api adobe_client 与 GPT2Image-Pro firefly-direct/client.ts。
Phase 1 文生图；Phase 2 upload_image；Phase 3 generate_video + epo→bks 轮询改写。
"""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any
from urllib.parse import urlparse

from curl_cffi import requests as curl_requests

from services.backends.firefly_constants import (
    DEFAULT_SEC_CH_UA,
    DEFAULT_USER_AGENT,
    GENERATE_API_KEY,
    IMPERSONATE,
    auth_headers,
    browser_headers,
    proxy_mapping,
)
from services.backends.firefly_errors import (
    FireflyAuthError,
    FireflyError,
    FireflyRequestError,
    FireflyUpstreamTemporary,
)
from services.backends.firefly_http import header_get, raise_for_firefly_http
from utils.diagnostics import redact_auth_diagnostic
from utils.log import logger

GENERATE_URL = "https://firefly-3p.ff.adobe.io/v2/3p-images/generate-async"
VIDEO_GENERATE_URL = "https://firefly-3p.ff.adobe.io/v2/3p-videos/generate-async"
UPLOAD_URL = "https://firefly-3p.ff.adobe.io/v2/storage/image"

# 兼容旧常量名
DEFAULT_API_KEY = GENERATE_API_KEY
_IMPERSONATE = IMPERSONATE

# 上传参考图允许的 Content-Type
ALLOWED_UPLOAD_MIMES = frozenset({"image/png", "image/jpeg", "image/webp"})
# 上传体积上限，与 fetch_image_bytes 默认 10MB 对齐
MAX_UPLOAD_IMAGE_BYTES = 10 * 1024 * 1024

# 451 回落用标准 requests（可选依赖；没有则继续 curl_cffi）
try:
    import requests as std_requests  # type: ignore
except Exception:  # pragma: no cover
    std_requests = None  # type: ignore


def _proxy_dict(proxy: str | None) -> dict[str, str] | None:
    return proxy_mapping(proxy)


def submit_headers(access_token: str) -> dict[str, str]:
    return auth_headers(
        access_token,
        api_key=GENERATE_API_KEY,
        content_type="application/json",
    )


def poll_headers(access_token: str) -> dict[str, str]:
    # 复用 browser_headers 骨架，避免手写子集漂移
    return auth_headers(
        access_token,
        api_key=GENERATE_API_KEY,
        content_type="application/json",
    )


def _header_get(headers: Any, *names: str) -> str:
    return header_get(headers, *names)


def extract_result_link(headers: Any, submit_data: Any) -> str:
    """优先 header x-override-status-link，否则 body links.result。"""
    header_link = header_get(headers, "x-override-status-link")
    if header_link:
        return header_link

    if not isinstance(submit_data, dict):
        return ""
    links = submit_data.get("links")
    if not isinstance(links, dict):
        return ""
    result_link = links.get("result")
    if isinstance(result_link, str):
        return result_link.strip()
    if isinstance(result_link, dict):
        return str(result_link.get("href") or "").strip()
    return ""


def extract_upstream_job_id(
    poll_url: str = "",
    submit_data: Any = None,
) -> str | None:
    """从 submit body / poll URL 抽取上游任务 id（Adobe 对账凭据）。

    优先 body 的 jobId/taskId/id；否则取 poll_url 路径末段。
    """
    if isinstance(submit_data, dict):
        for key in ("jobId", "job_id", "taskId", "task_id", "id"):
            value = str(submit_data.get(key) or "").strip()
            # 排除明显是 URL / 路径的值
            if value and "://" not in value and "/" not in value:
                return value
        for nested_key in ("job", "task", "result"):
            nested = submit_data.get(nested_key)
            if not isinstance(nested, dict):
                continue
            for key in ("id", "jobId", "job_id", "taskId", "task_id"):
                value = str(nested.get(key) or "").strip()
                if value and "://" not in value and "/" not in value:
                    return value

    raw = str(poll_url or "").strip()
    if not raw:
        return None
    try:
        parsed = urlparse(raw)
        parts = [p for p in parsed.path.split("/") if p]
        if not parts:
            return None
        candidate = parts[-1].strip()
        # 过滤无意义路径段
        if not candidate or candidate.lower() in {
            "result",
            "results",
            "jobs",
            "status",
            "v1",
            "v2",
            "v3",
        }:
            return None
        return candidate
    except Exception:
        return None


def normalize_video_poll_url(url: str) -> str:
    """将 firefly-epo 分片轮询链接改写为 bks 任务查询地址。

    输入: https://firefly-epo{shard}-<region>.adobe.io/.../jobs/.../{jobId}
    输出: https://bks-epo{shard}.adobe.io/v2/jobs/result/{jobId}?host=<原host>/

    非 epo 链接、非法分片、解析失败一律原样返回。
    **漏改则 sora/veo 拿不到结果**（视频成功关键）。
    """
    raw_url = str(url or "")
    if not raw_url:
        return raw_url
    try:
        parsed = urlparse(raw_url)
        host = parsed.netloc
        path_parts = [p for p in parsed.path.split("/") if p]
        if not host or not path_parts:
            return raw_url
        if not host.startswith("firefly-epo"):
            return raw_url
        job_id = path_parts[-1]
        if not job_id:
            return raw_url
        # host 形如 firefly-epo1234-prod.adobe.io → suffix "1234-prod" → shard "1234"
        host_suffix = host[len("firefly-epo") :].split(".", 1)[0]
        shard = host_suffix[:4].strip()
        if len(shard) != 4 or not shard.isdigit():
            return raw_url
        return (
            f"https://bks-epo{shard}.adobe.io/v2/jobs/result/{job_id}"
            f"?host={host}/"
        )
    except Exception:
        return raw_url


def _video_ext_from_content_type(content_type: str) -> str:
    """按 contentType / Content-Type 选扩展名：mp4 / webm / ogv。"""
    ct = str(content_type or "").strip().lower()
    if "webm" in ct:
        return "webm"
    if "ogg" in ct or "ogv" in ct:
        return "ogv"
    if "mp4" in ct or "mpeg" in ct or "quicktime" in ct:
        return "mp4"
    return "mp4"


def _raise_for_http(
    status_code: int,
    headers: Any,
    body: str,
    context: str,
) -> None:
    raise_for_firefly_http(status_code, headers, body, context)


def _post_json(
    url: str,
    headers: dict[str, str],
    payload: dict[str, Any],
    *,
    proxy: str | None,
    timeout: float,
):
    """curl_cffi POST；遇 451 回落标准 requests（对齐 adobe2api）。"""
    proxies = proxy_mapping(proxy)
    try:
        resp = curl_requests.post(
            url,
            headers=headers,
            json=payload,
            timeout=timeout,
            impersonate=IMPERSONATE,
            proxies=proxies,
        )
    except Exception as exc:
        logger.warning(
            "firefly submit network error: %s",
            redact_auth_diagnostic(str(exc))[:300],
        )
        raise FireflyUpstreamTemporary(
            f"submit network error: {exc}",
            error_type="network",
        ) from exc

    if resp.status_code == 451 and std_requests is not None:
        try:
            return std_requests.post(
                url,
                headers=headers,
                json=payload,
                timeout=timeout,
                proxies=proxies,
            )
        except Exception as exc:
            raise FireflyUpstreamTemporary(
                f"submit fallback network error: {exc}",
                status_code=451,
                error_type="network",
            ) from exc
    return resp


def _get(
    url: str,
    headers: dict[str, str],
    *,
    proxy: str | None,
    timeout: float,
    impersonate: bool = True,
):
    proxies = proxy_mapping(proxy)
    try:
        kwargs: dict[str, Any] = {
            "headers": headers,
            "timeout": timeout,
            "proxies": proxies,
        }
        if impersonate:
            kwargs["impersonate"] = IMPERSONATE
        return curl_requests.get(url, **kwargs)
    except Exception as exc:
        logger.warning(
            "firefly GET network error: %s",
            redact_auth_diagnostic(str(exc))[:300],
        )
        raise FireflyUpstreamTemporary(
            f"get network error: {exc}",
            error_type="network",
        ) from exc


def _run_generate_async(
    url: str,
    token: str,
    payload: dict[str, Any],
    *,
    media_key: str,
    poll_url_hook: Callable[[str], str] | None = None,
    download_fn: Callable[..., Any] | None = None,
    timeout: float,
    poll_interval: float,
    proxy: str | None,
    context_prefix: str = "",
    timeout_message: str = "generation timed out",
) -> dict[str, Any]:
    """提交 generate-async → 抽 poll url → 轮询 → 解析 outputs → 下载。

    media_key: outputs[0] 下媒体字段名（image / video）。
    poll_url_hook: 视频 epo→bks 归一化。
    download_fn: (presigned_url, media_dict, *, proxy) → 返回值；默认下图片 bytes。

    返回统一 dict：
    - image 默认：{"bytes": bytes, "upstream_id": str|None}
    - video download_fn：{"bytes": bytes, "ext": str, "upstream_id": str|None, "payload": 原返回}
    """
    # 1. 提交
    resp = _post_json(
        url,
        headers=submit_headers(token),
        payload=payload,
        proxy=proxy,
        timeout=min(60.0, float(timeout)),
    )
    body_text = ""
    try:
        body_text = resp.text or ""
    except Exception:
        body_text = ""

    submit_ctx = f"{context_prefix}submit failed"
    if resp.status_code != 200:
        logger.warning(
            "firefly %s status=%s body=%s",
            submit_ctx,
            resp.status_code,
            redact_auth_diagnostic(body_text)[:300],
        )
        raise_for_firefly_http(
            resp.status_code, resp.headers, body_text, submit_ctx
        )

    try:
        submit_data = resp.json()
    except Exception:
        submit_data = {}

    raw_poll_url = extract_result_link(resp.headers, submit_data)
    if not raw_poll_url:
        raise FireflyRequestError(
            f"{context_prefix}submit succeeded but no poll url returned"
        )
    poll_url = (
        poll_url_hook(str(raw_poll_url)) if poll_url_hook else str(raw_poll_url)
    )
    # 尽早抽上游任务 id，失败路径也可挂到异常上
    upstream_id = extract_upstream_job_id(poll_url, submit_data)

    # 2. 轮询
    deadline = time.time() + float(timeout)
    interval = max(0.5, float(poll_interval))
    latest: dict[str, Any] = {}
    poll_ctx = f"{context_prefix}poll failed"

    while True:
        poll_resp = _get(
            poll_url,
            headers=poll_headers(token),
            proxy=proxy,
            timeout=60,
            impersonate=True,
        )
        if poll_resp.status_code != 200:
            poll_body = ""
            try:
                poll_body = poll_resp.text or ""
            except Exception:
                poll_body = ""
            logger.warning(
                "firefly %s status=%s body=%s",
                poll_ctx,
                poll_resp.status_code,
                redact_auth_diagnostic(poll_body)[:300],
            )
            try:
                raise_for_firefly_http(
                    poll_resp.status_code,
                    poll_resp.headers,
                    poll_body,
                    poll_ctx,
                )
            except FireflyError as exc:
                if upstream_id and not getattr(exc, "upstream_id", None):
                    exc.upstream_id = upstream_id
                raise

        try:
            parsed = poll_resp.json()
            latest = parsed if isinstance(parsed, dict) else {}
        except Exception:
            latest = {}

        # poll 响应里可能补充 jobId
        if not upstream_id:
            upstream_id = extract_upstream_job_id(poll_url, latest)

        status_header = header_get(poll_resp.headers, "x-task-status").upper()
        status_val = str(latest.get("status") or "").upper() or status_header

        outputs = latest.get("outputs") or []
        if isinstance(outputs, list) and outputs:
            first = outputs[0] if isinstance(outputs[0], dict) else {}
            media = first.get(media_key) if isinstance(first, dict) else None
            media_url = ""
            media_obj: dict[str, Any] = {}
            if isinstance(media, dict):
                media_obj = media
                media_url = str(media.get("presignedUrl") or "").strip()
            if not media_url:
                # 保持原对外文案：image 为 "job finished without image url"
                # 视频为 "video job finished without video url"
                if media_key == "image":
                    raise FireflyRequestError(
                        "job finished without image url",
                        upstream_id=upstream_id,
                    )
                raise FireflyRequestError(
                    f"{media_key} job finished without {media_key} url",
                    upstream_id=upstream_id,
                )
            if download_fn is not None:
                media_payload = download_fn(media_url, media_obj, proxy=proxy)
            else:
                media_payload = _download_bytes(media_url, proxy=proxy)
            # 统一包一层，便于编排层读 upstream_id；coerce 仍兼容 dict/tuple
            if isinstance(media_payload, tuple) and media_payload:
                data0 = media_payload[0]
                ext = str(media_payload[1] if len(media_payload) > 1 else "mp4") or "mp4"
                return {
                    "bytes": data0,
                    "ext": ext.lstrip(".") or "mp4",
                    "upstream_id": upstream_id,
                    "payload": media_payload,
                }
            return {
                "bytes": media_payload,
                "upstream_id": upstream_id,
            }

        if status_val in {"FAILED", "CANCELLED", "ERROR"}:
            detail = redact_auth_diagnostic(str(latest)[:300])
            # 原: "image job failed" / "video job failed"
            raise FireflyRequestError(
                f"{media_key} job failed: {detail}",
                upstream_id=upstream_id,
            )

        if time.time() >= deadline:
            # 超时视为上游临时问题，允许换号重试
            raise FireflyUpstreamTemporary(
                timeout_message,
                error_type="timeout",
                upstream_id=upstream_id,
            )
        time.sleep(interval)


def generate_image(
    access_token: str,
    payload: dict[str, Any],
    *,
    proxy: str | None = None,
    timeout: float = 180,
    poll_interval: float = 3,
) -> dict[str, Any]:
    """提交 generate-async → 轮询 → 下载 presign。

    返回 {"bytes": bytes, "upstream_id": str|None}；编排层 coerce 仍兼容纯 bytes。

    错误分类：
    - taste_exhausted → FireflyQuotaExhausted
    - 401/403 → FireflyAuthError
    - 429/451/5xx / 网络 / 超时 → FireflyUpstreamTemporary
    - 其它 → FireflyRequestError
    """
    token = str(access_token or "").strip()
    if not token:
        raise FireflyAuthError("empty access token", status_code=401)
    if not isinstance(payload, dict) or not payload:
        raise FireflyRequestError("empty payload")

    return _run_generate_async(
        GENERATE_URL,
        token,
        payload,
        media_key="image",
        timeout=timeout,
        poll_interval=poll_interval,
        proxy=proxy,
        context_prefix="",
        timeout_message="generation timed out",
    )


def _download_bytes(url: str, *, proxy: str | None = None) -> bytes:
    """下载 presign（无需 TLS 伪装）。"""
    content, _ctype = _download_bytes_with_type(url, proxy=proxy)
    return content


def _download_bytes_with_type(
    url: str,
    *,
    proxy: str | None = None,
    timeout: float = 120,
) -> tuple[bytes, str]:
    """下载 presign，返回 (bytes, content-type)。"""
    try:
        # 优先无 impersonate 的 curl_cffi；失败再试标准 requests
        resp = curl_requests.get(
            url,
            headers={"accept": "*/*"},
            timeout=timeout,
            proxies=proxy_mapping(proxy),
        )
    except Exception as exc:
        if std_requests is None:
            raise FireflyUpstreamTemporary(
                f"download network error: {exc}",
                error_type="network",
            ) from exc
        try:
            resp = std_requests.get(
                url,
                headers={"accept": "*/*"},
                timeout=timeout,
                proxies=proxy_mapping(proxy),
            )
        except Exception as exc2:
            raise FireflyUpstreamTemporary(
                f"download network error: {exc2}",
                error_type="network",
            ) from exc2

    if resp.status_code != 200:
        raise FireflyRequestError(
            f"media download failed: HTTP {resp.status_code}",
            status_code=resp.status_code,
        )
    content = resp.content or b""
    if not content:
        raise FireflyRequestError("media download returned empty body")
    content_type = header_get(getattr(resp, "headers", None), "content-type")
    return content, content_type


def generate_video(
    access_token: str,
    payload: dict[str, Any],
    *,
    proxy: str | None = None,
    timeout: float = 600,
    poll_interval: float = 3,
) -> dict[str, Any]:
    """提交视频 generate-async → epo→bks 归一化 → 轮询 → 下载。

    Returns:
        {"bytes": video_bytes, "ext": ext, "upstream_id": str|None}
        ext 按 contentType 选 mp4/webm/ogv；编排层 coerce 仍兼容 (bytes, ext)。

    错误分类同 generate_image：
    - taste_exhausted → FireflyQuotaExhausted
    - 401/403 → FireflyAuthError
    - 429/451/5xx / 网络 / 超时 → FireflyUpstreamTemporary
    - 其它 → FireflyRequestError
    """
    token = str(access_token or "").strip()
    if not token:
        raise FireflyAuthError("empty access token", status_code=401)
    if not isinstance(payload, dict) or not payload:
        raise FireflyRequestError("empty payload")

    download_timeout = min(180.0, max(60.0, float(timeout) / 2))

    def _download_video(
        media_url: str,
        media: dict[str, Any],
        *,
        proxy: str | None,
    ) -> tuple[bytes, str]:
        video_ctype = str(
            media.get("contentType") or media.get("content_type") or ""
        ).strip()
        content, resp_ctype = _download_bytes_with_type(
            media_url,
            proxy=proxy,
            timeout=download_timeout,
        )
        ext = _video_ext_from_content_type(video_ctype or resp_ctype)
        return content, ext

    return _run_generate_async(
        VIDEO_GENERATE_URL,
        token,
        payload,
        media_key="video",
        poll_url_hook=normalize_video_poll_url,
        download_fn=_download_video,
        timeout=timeout,
        poll_interval=poll_interval,
        proxy=proxy,
        context_prefix="video ",
        timeout_message="video generation timed out",
    )


def _normalize_upload_mime(mime: str) -> str:
    """校验并规范化上传 mime；image/jpg → image/jpeg。"""
    normalized = str(mime or "").strip().lower()
    if normalized == "image/jpg":
        normalized = "image/jpeg"
    if normalized not in ALLOWED_UPLOAD_MIMES:
        raise FireflyRequestError(
            f"unsupported image mime: {mime or '(empty)'}; "
            "allowed: image/png, image/jpeg, image/webp"
        )
    return normalized


def upload_image(
    access_token: str,
    image_bytes: bytes,
    mime: str = "image/png",
    *,
    proxy: str | None = None,
    mime_type: str | None = None,
) -> str:
    """上传参考图到 Adobe 存储，返回 image_id。

    POST https://firefly-3p.ff.adobe.io/v2/storage/image
    body: raw bytes；Content-Type 为传入 mime。

    错误分类同 generate_image：
    - taste_exhausted → FireflyQuotaExhausted
    - 401/403 → FireflyAuthError
    - 429/451/5xx → FireflyUpstreamTemporary
    - 其它 → FireflyRequestError

    mime_type 为历史参数名，与 mime 二选一（mime_type 优先若显式传入）。
    """
    token = str(access_token or "").strip()
    if not token:
        raise FireflyAuthError("empty access token", status_code=401)
    if not image_bytes:
        raise FireflyRequestError("image is empty")
    if len(image_bytes) > MAX_UPLOAD_IMAGE_BYTES:
        raise FireflyRequestError(
            f"image too large: {len(image_bytes)} bytes "
            f"(max {MAX_UPLOAD_IMAGE_BYTES})"
        )

    content_type = _normalize_upload_mime(
        mime_type if mime_type is not None else mime
    )

    headers = auth_headers(
        token,
        api_key=GENERATE_API_KEY,
        content_type=content_type,
        extra={"accept": "application/json"},
    )
    proxies = proxy_mapping(proxy)
    try:
        resp = curl_requests.post(
            UPLOAD_URL,
            headers=headers,
            data=image_bytes,
            timeout=60,
            impersonate=IMPERSONATE,
            proxies=proxies,
        )
    except Exception as exc:
        logger.warning(
            "firefly upload network error: %s",
            redact_auth_diagnostic(str(exc))[:300],
        )
        raise FireflyUpstreamTemporary(
            f"upload network error: {exc}",
            error_type="network",
        ) from exc

    if resp.status_code != 200:
        body = ""
        try:
            body = resp.text or ""
        except Exception:
            body = ""
        logger.warning(
            "firefly upload failed status=%s body=%s",
            resp.status_code,
            redact_auth_diagnostic(body)[:300],
        )
        raise_for_firefly_http(
            resp.status_code, resp.headers, body, "upload image failed"
        )

    try:
        data = resp.json()
    except Exception as exc:
        raise FireflyRequestError("upload response invalid json") from exc

    images = (data or {}).get("images") if isinstance(data, dict) else None
    if not isinstance(images, list) or not images:
        raise FireflyRequestError("upload image succeeded but no image id returned")
    image_id = (images[0] or {}).get("id") if isinstance(images[0], dict) else None
    if not image_id:
        raise FireflyRequestError("upload image succeeded but no image id returned")
    return str(image_id)
