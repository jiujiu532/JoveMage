"""Firefly 图生图辅助：从 URL / data URL 取参考图字节。

供 Phase 2 edits 编排层在 upload_image 之前统一取图。
"""

from __future__ import annotations

import base64
import binascii
import ipaddress
import socket
from typing import Any
from urllib.parse import unquote_to_bytes, urlparse

from curl_cffi import requests as curl_requests

from services.backends.firefly_errors import (
    FireflyRequestError,
    FireflyUpstreamTemporary,
)
from utils.diagnostics import redact_auth_diagnostic
from utils.log import logger

ALLOWED_IMAGE_MIMES = frozenset({"image/png", "image/jpeg", "image/webp"})
DEFAULT_MAX_IMAGE_SIZE = 10 * 1024 * 1024  # 10MB，对齐 adobe2api

try:
    import requests as std_requests  # type: ignore
except Exception:  # pragma: no cover
    std_requests = None  # type: ignore


def _proxy_dict(proxy: str | None) -> dict[str, str] | None:
    text = str(proxy or "").strip()
    if not text:
        return None
    return {"http": text, "https": text}


def _is_blocked_ip(addr: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    """内网 / 环回 / 链路本地 / 保留 / 组播 / 未指定 均拒绝。"""
    return bool(
        addr.is_private
        or addr.is_loopback
        or addr.is_link_local
        or addr.is_reserved
        or addr.is_multicast
        or addr.is_unspecified
    )


def _is_private_host(host: str) -> bool:
    """解析 host，判断是否指向内网/环回/链路本地/保留地址。

    DNS 解析失败时按任务约定返回 False（不因解析失败误杀）；
    字面 IP 与已解析地址仍严格屏蔽私网段。
    """
    text = str(host or "").strip().strip("[]")
    if not text:
        return True
    if text.lower() in {"localhost"}:
        return True
    try:
        # 字面 IP 优先
        try:
            return _is_blocked_ip(ipaddress.ip_address(text))
        except ValueError:
            pass
        # 主机名 → IPv4（gethostbyname）；失败则视为非私网
        addr = ipaddress.ip_address(socket.gethostbyname(text))
        return _is_blocked_ip(addr)
    except Exception:
        return False


def _assert_public_http_url(url: str) -> None:
    """仅允许 http(s)，并拒绝内网/元数据等 SSRF 目标。"""
    parsed = urlparse(str(url or "").strip())
    scheme = (parsed.scheme or "").lower()
    if scheme not in {"http", "https"}:
        raise FireflyRequestError("only http(s) or data URL images are supported")
    host = parsed.hostname
    if not host:
        raise FireflyRequestError("image url missing host")
    if _is_private_host(host):
        raise FireflyRequestError("image url host is not allowed")


def normalize_image_mime(mime: str, *, default: str = "image/png") -> str:
    """规范化 mime；image/jpg → image/jpeg；不在白名单则返回 default。"""
    normalized = str(mime or "").strip().lower().split(";")[0].strip()
    if normalized == "image/jpg":
        normalized = "image/jpeg"
    if normalized in ALLOWED_IMAGE_MIMES:
        return normalized
    fallback = str(default or "image/png").strip().lower()
    if fallback == "image/jpg":
        fallback = "image/jpeg"
    if fallback not in ALLOWED_IMAGE_MIMES:
        fallback = "image/png"
    return fallback


def require_allowed_mime(mime: str) -> str:
    """严格校验 mime 白名单，非法则抛错。"""
    normalized = str(mime or "").strip().lower().split(";")[0].strip()
    if normalized == "image/jpg":
        normalized = "image/jpeg"
    if normalized not in ALLOWED_IMAGE_MIMES:
        raise FireflyRequestError(
            f"unsupported image mime: {mime or '(empty)'}; "
            "allowed: image/png, image/jpeg, image/webp"
        )
    return normalized


def _decode_data_url(url_or_data: str) -> tuple[bytes, str]:
    raw = str(url_or_data or "").strip()
    if not raw.startswith("data:"):
        raise FireflyRequestError("not a data url")
    head, sep, body = raw.partition(",")
    if not sep:
        raise FireflyRequestError("invalid data url")

    mime_type = "image/png"
    mime_part = head[5:]
    if ";" in mime_part:
        mime_type = (mime_part.split(";", 1)[0] or "image/png").strip()
    elif mime_part:
        mime_type = mime_part.strip()

    try:
        if ";base64" in head.lower():
            image_bytes = base64.b64decode(body, validate=True)
        else:
            image_bytes = unquote_to_bytes(body)
    except (binascii.Error, ValueError) as exc:
        raise FireflyRequestError("invalid base64 image data") from exc

    if not image_bytes:
        raise FireflyRequestError("image is empty")
    return image_bytes, require_allowed_mime(mime_type)


def _download_http_image(
    url: str,
    *,
    proxy: str | None,
    timeout: float,
) -> tuple[bytes, str]:
    proxies = _proxy_dict(proxy)
    headers = {"accept": "image/*,*/*;q=0.8"}
    resp: Any
    try:
        resp = curl_requests.get(
            url,
            headers=headers,
            timeout=timeout,
            proxies=proxies,
        )
    except Exception as exc:
        if std_requests is None:
            logger.warning(
                "firefly fetch image network error: %s",
                redact_auth_diagnostic(str(exc))[:300],
            )
            raise FireflyUpstreamTemporary(
                f"fetch image network error: {exc}",
                error_type="network",
            ) from exc
        try:
            resp = std_requests.get(
                url,
                headers=headers,
                timeout=timeout,
                proxies=proxies,
            )
        except Exception as exc2:
            logger.warning(
                "firefly fetch image network error: %s",
                redact_auth_diagnostic(str(exc2))[:300],
            )
            raise FireflyUpstreamTemporary(
                f"fetch image network error: {exc2}",
                error_type="network",
            ) from exc2

    if getattr(resp, "status_code", 0) != 200:
        raise FireflyRequestError(
            f"fetch image failed: HTTP {getattr(resp, 'status_code', 0)}",
            status_code=int(getattr(resp, "status_code", 0) or 0) or None,
        )

    content = resp.content or b""
    if not content:
        raise FireflyRequestError("fetch image returned empty body")

    header_mime = ""
    try:
        header_mime = str(resp.headers.get("content-type") or "").split(";")[0].strip()
    except Exception:
        header_mime = ""
    # 严格校验：HTTP Content-Type 若在白名单则用；否则按魔数猜
    mime = _guess_mime_from_bytes(content, header_mime)
    return content, require_allowed_mime(mime)


def _guess_mime_from_bytes(data: bytes, header_mime: str = "") -> str:
    """优先 header，其次文件魔数。"""
    if header_mime:
        candidate = str(header_mime).strip().lower().split(";")[0].strip()
        if candidate == "image/jpg":
            candidate = "image/jpeg"
        if candidate in ALLOWED_IMAGE_MIMES:
            return candidate
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if data[:3] == b"\xff\xd8\xff":
        return "image/jpeg"
    if len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    return header_mime or "image/png"


def fetch_image_bytes(
    url_or_data: str,
    *,
    proxy: str | None = None,
    max_size: int = DEFAULT_MAX_IMAGE_SIZE,
    timeout: float = 30,
) -> tuple[bytes, str]:
    """从 URL / data URL 获取图片字节和 mime。

    - data:image/png;base64,... → 解码
    - http(s)://... → 下载（可经代理）
    - 校验：大小 ≤ max_size，格式 image/png|jpeg|webp
    返回 (bytes, mime)
    """
    raw = str(url_or_data or "").strip()
    if not raw:
        raise FireflyRequestError("image url is empty")

    limit = int(max_size or DEFAULT_MAX_IMAGE_SIZE)
    if limit <= 0:
        limit = DEFAULT_MAX_IMAGE_SIZE

    if raw.startswith("data:"):
        image_bytes, mime = _decode_data_url(raw)
    elif raw.lower().startswith(("http://", "https://")):
        _assert_public_http_url(raw)
        image_bytes, mime = _download_http_image(
            raw, proxy=proxy, timeout=float(timeout)
        )
    else:
        raise FireflyRequestError(
            "only http(s) or data URL images are supported"
        )

    if not image_bytes:
        raise FireflyRequestError("image is empty")
    if len(image_bytes) > limit:
        raise FireflyRequestError(
            f"image too large: {len(image_bytes)} bytes (max {limit})"
        )
    return image_bytes, mime
