from __future__ import annotations

import base64
import os
import unittest
from unittest import mock

os.environ.setdefault("CHATGPT2API_AUTH_KEY", "test-auth")

from services.backends import firefly_client as client  # noqa: E402
from services.backends.firefly_errors import (  # noqa: E402
    FireflyRequestError,
)

try:
    from services.backends import firefly_image_utils as image_utils  # noqa: E402
except ImportError:  # pragma: no cover
    image_utils = None  # type: ignore


def _modules():
    mods = [client]
    if image_utils is not None:
        mods.append(image_utils)
    return mods


def _resolve_fetch_fn():
    from test._firefly_helpers import first_callable

    names = (
        "fetch_image_bytes",
        "load_image_bytes",
        "download_or_decode_image",
        "resolve_image_bytes",
        "get_image_bytes",
    )
    for mod in _modules():
        fn = first_callable(mod, *names, required=False)
        if fn is not None:
            return getattr(fn, "__name__", names[0]), fn, mod
    return None, None, None


def _fetch_image_bytes(*args, **kwargs):
    """兼容 fetch_image_bytes 若干命名 / 模块位置。"""
    name, fn, _mod = _resolve_fetch_fn()
    if fn is None:
        raise unittest.SkipTest(
            "missing fetch_image_bytes "
            "(expected firefly_client / firefly_image_utils.fetch_image_bytes)"
        )
    return fn(*args, **kwargs)


def _unpack_result(result: object) -> tuple[bytes, str]:
    """兼容 (bytes, mime) / dict / 具名对象。"""
    if isinstance(result, tuple) and len(result) >= 2:
        data, mime = result[0], result[1]
        return bytes(data), str(mime or "")
    if isinstance(result, dict):
        data = result.get("bytes") or result.get("data") or result.get("content")
        mime = (
            result.get("mime")
            or result.get("mime_type")
            or result.get("content_type")
            or result.get("contentType")
            or ""
        )
        if data is None:
            raise AssertionError(f"result dict missing bytes: {result!r}")
        return bytes(data), str(mime)
    data = getattr(result, "bytes", None) or getattr(result, "data", None)
    mime = (
        getattr(result, "mime", None)
        or getattr(result, "mime_type", None)
        or getattr(result, "content_type", None)
        or ""
    )
    if data is None:
        raise AssertionError(f"unsupported fetch result type: {type(result)!r}")
    return bytes(data), str(mime)


def _data_url(mime: str, raw: bytes) -> str:
    b64 = base64.b64encode(raw).decode("ascii")
    return f"data:{mime};base64,{b64}"


def _max_size_default() -> int:
    for mod in _modules():
        for name in (
            "DEFAULT_MAX_IMAGE_SIZE",
            "MAX_UPLOAD_IMAGE_BYTES",
            "MAX_IMAGE_BYTES",
            "MAX_REFERENCE_IMAGE_BYTES",
            "MAX_IMAGE_SIZE",
            "DEFAULT_MAX_IMAGE_BYTES",
        ):
            value = getattr(mod, name, None)
            if isinstance(value, int) and value > 0:
                return value
    return 10 * 1024 * 1024


def _patch_http_get(fake_response):
    """patch 可能的 HTTP GET 入口，返回 active patches 列表。"""
    from test._firefly_helpers import patch_firefly_http

    targets = [
        "services.backends.firefly_image_utils.curl_requests.get",
        "services.backends.firefly_client.curl_requests.get",
        "services.backends.firefly_image_utils.requests.get",
        "services.backends.firefly_client.requests.get",
        "curl_cffi.requests.get",
    ]
    for mod_name, mod in (
        ("services.backends.firefly_image_utils", image_utils),
        ("services.backends.firefly_client", client),
    ):
        if mod is None:
            continue
        if getattr(mod, "std_requests", None) is not None:
            targets.append(f"{mod_name}.std_requests.get")

    return patch_firefly_http(*targets, return_value=fake_response)


class FetchImageBytesTests(unittest.TestCase):
    """fetch_image_bytes：URL / data URL → (bytes, mime)。"""

    def test_data_url_png_decoded(self) -> None:
        """data:image/png;base64,... 应解码为 bytes + image/png。"""
        raw = b"\x89PNG\r\n\x1a\n" + b"png-body"
        src = _data_url("image/png", raw)
        data, mime = _unpack_result(_fetch_image_bytes(src))
        self.assertEqual(data, raw)
        self.assertIn("png", mime.lower())

    def test_data_url_jpeg_decoded(self) -> None:
        """data:image/jpeg;base64,... 应解码。"""
        raw = b"\xff\xd8\xff" + b"jpeg-body"
        src = _data_url("image/jpeg", raw)
        data, mime = _unpack_result(_fetch_image_bytes(src))
        self.assertEqual(data, raw)
        self.assertTrue(
            "jpeg" in mime.lower() or "jpg" in mime.lower(),
            f"expected jpeg mime, got {mime!r}",
        )

    def test_http_url_downloaded(self) -> None:
        """http(s) URL 应下载（mock HTTP）。"""
        if _resolve_fetch_fn()[1] is None:
            self.skipTest("missing fetch_image_bytes")

        # 用真实 webp 魔数，避免 mime 嗅探失败
        raw = b"RIFF" + (100).to_bytes(4, "little") + b"WEBP" + b"\x00" * 32
        url = "https://cdn.example.com/ref/photo.webp"

        fake_response = mock.Mock()
        fake_response.status_code = 200
        fake_response.content = raw
        fake_response.headers = {"Content-Type": "image/webp"}
        fake_response.text = ""

        name, _fn, mod = _resolve_fetch_fn()
        active = _patch_http_get(fake_response)

        # 也 patch 内部 helper（若直接下载）
        helper_patches = []
        if mod is not None:
            for helper in (
                "_download_http_image",
                "_fetch_http_image",
                "_get_http_image_bytes",
                "_download_bytes",
            ):
                if not callable(getattr(mod, helper, None)):
                    continue
                # _download_http_image 返回 (bytes, mime)
                if helper in ("_download_http_image", "_fetch_http_image"):
                    p = mock.patch.object(
                        mod, helper, return_value=(raw, "image/webp")
                    )
                else:
                    p = mock.patch.object(mod, helper, return_value=raw)
                p.start()
                helper_patches.append(p)

        try:
            data, mime = _unpack_result(_fetch_image_bytes(url))
        finally:
            for p in active:
                p.stop()
            for p in helper_patches:
                p.stop()

        self.assertEqual(data, raw)
        if mime:
            self.assertTrue(
                "webp" in mime.lower() or "image/" in mime.lower(),
                f"unexpected mime {mime!r}",
            )

    def test_oversized_raises(self) -> None:
        """超过 max_size 应报错。"""
        if _resolve_fetch_fn()[1] is None:
            self.skipTest("missing fetch_image_bytes")

        limit = _max_size_default()
        huge = b"z" * (limit + 8)
        src = _data_url("image/png", huge)

        raised = False
        err: Exception | None = None
        try:
            _fetch_image_bytes(src, max_size=limit)
        except TypeError:
            try:
                _fetch_image_bytes(src)
            except Exception as exc:
                raised = True
                err = exc
        except Exception as exc:
            raised = True
            err = exc

        if not raised:
            self.fail(
                f"expected oversized image to raise "
                f"(limit={limit}, size={len(huge)})"
            )
        self.assertIsInstance(
            err,
            (FireflyRequestError, ValueError, OSError, RuntimeError),
        )


if __name__ == "__main__":
    unittest.main()
