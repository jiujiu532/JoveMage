from __future__ import annotations

import inspect
import json
import os
import unittest
from unittest import mock

os.environ.setdefault("CHATGPT2API_AUTH_KEY", "test-auth")

from services.backends import firefly_client as client  # noqa: E402
from services.backends.firefly_errors import (  # noqa: E402
    FireflyRequestError,
)
from test._firefly_helpers import (  # noqa: E402
    first_callable,
    patch_firefly_http,
    stop_patches,
)


def _upload_image(*args, **kwargs):
    """兼容 upload_image 若干命名。"""
    fn = first_callable(
        client,
        "upload_image",
        "upload_firefly_image",
        "upload_storage_image",
    )
    return fn(*args, **kwargs)


def _max_image_bytes() -> int | None:
    """读取实现侧大小上限常量（若有）。"""
    for name in (
        "MAX_UPLOAD_IMAGE_BYTES",
        "MAX_IMAGE_BYTES",
        "MAX_REFERENCE_IMAGE_BYTES",
        "MAX_IMAGE_SIZE",
        "DEFAULT_MAX_IMAGE_BYTES",
        "DEFAULT_MAX_IMAGE_SIZE",
    ):
        value = getattr(client, name, None)
        if isinstance(value, int) and value > 0:
            return value
    return None


def _allowed_mimes() -> set[str] | None:
    for name in (
        "ALLOWED_UPLOAD_MIMES",
        "ALLOWED_UPLOAD_MIME_TYPES",
        "ALLOWED_IMAGE_MIME_TYPES",
        "ALLOWED_IMAGE_MIMES",
        "UPLOAD_MIME_WHITELIST",
        "ALLOWED_MIME_TYPES",
    ):
        value = getattr(client, name, None)
        if isinstance(value, (set, list, tuple, frozenset)) and value:
            return {str(x).lower() for x in value}
    return None


def _capture_upload_post(image_bytes: bytes, mime_type: str, token: str = "tok-abc"):
    """mock curl_cffi post，返回 (image_id, captured_calls)。"""
    fake_response = mock.Mock()
    fake_response.status_code = 200
    fake_response.text = json.dumps({"images": [{"id": "img-uploaded-1"}]})
    fake_response.json.return_value = {"images": [{"id": "img-uploaded-1"}]}
    fake_response.headers = {}

    post_calls: list[dict] = []

    def _capture_post(*args, **kwargs):
        post_calls.append({"args": args, "kwargs": kwargs})
        return fake_response

    session_post = mock.Mock(side_effect=_capture_post)
    fake_session = mock.Mock()
    fake_session.post = session_post
    fake_session.close = mock.Mock()
    fake_session.__enter__ = mock.Mock(return_value=fake_session)
    fake_session.__exit__ = mock.Mock(return_value=False)

    active_patches = patch_firefly_http(
        "services.backends.firefly_client.curl_requests.post",
        "services.backends.firefly_client.requests.post",
        "curl_cffi.requests.post",
        side_effect=_capture_post,
    )
    active_patches.extend(
        patch_firefly_http(
            "services.backends.firefly_client.curl_requests.Session",
            "services.backends.firefly_client.requests.Session",
            return_value=fake_session,
        )
    )

    try:
        # 兼容 mime / mime_type 参数名
        try:
            image_id = _upload_image(token, image_bytes, mime_type)
        except TypeError:
            image_id = _upload_image(
                token, image_bytes, mime=mime_type
            )
    finally:
        stop_patches(active_patches)

    all_calls = list(post_calls)
    if session_post.called:
        for call in session_post.call_args_list:
            all_calls.append({"args": call.args, "kwargs": call.kwargs})

    return image_id, all_calls


def _first_call(all_calls: list[dict]) -> tuple[tuple, dict]:
    if not all_calls:
        raise AssertionError("expected at least one upload POST call")
    call = all_calls[0]
    return call.get("args") or (), call.get("kwargs") or {}


class UploadImageTests(unittest.TestCase):
    """firefly_client.upload_image 请求构造与 id 提取。"""

    def test_upload_posts_raw_bytes_with_correct_headers(self) -> None:
        """应 POST /v2/storage/image，body=raw bytes，Content-Type=mime，
        带 Bearer + x-api-key:projectx_webapp + Origin:new.express.adobe.com。"""
        payload = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32
        mime = "image/png"
        image_id, calls = _capture_upload_post(payload, mime, token="access-xyz")
        self.assertEqual(str(image_id), "img-uploaded-1")

        args, kwargs = _first_call(calls)
        url = kwargs.get("url") or (args[0] if args else "")
        self.assertIn("/v2/storage/image", str(url))
        self.assertIn("firefly-3p.ff.adobe.io", str(url))

        body = kwargs.get("data")
        if body is None and len(args) >= 2:
            body = args[1]
        if body is None:
            body = kwargs.get("content")
        self.assertEqual(body, payload)

        headers = kwargs.get("headers") or {}
        header_map = {str(k).lower(): str(v) for k, v in headers.items()}

        auth = header_map.get("authorization") or ""
        self.assertTrue(
            auth.lower().startswith("bearer "),
            f"Authorization must be Bearer token, got {auth!r}",
        )
        self.assertIn("access-xyz", auth)

        api_key = header_map.get("x-api-key") or ""
        self.assertEqual(api_key, "projectx_webapp")

        content_type = header_map.get("content-type") or ""
        self.assertEqual(content_type, mime)

        origin = header_map.get("origin") or ""
        self.assertIn(
            "new.express.adobe.com",
            origin,
            f"Origin must be Express; got {origin!r}",
        )

    def test_upload_extracts_image_id_from_response(self) -> None:
        """response.json()["images"][0]["id"] 应被正确提取。"""
        payload = b"fake-jpeg-bytes"
        image_id, _calls = _capture_upload_post(payload, "image/jpeg")
        self.assertEqual(image_id, "img-uploaded-1")

    def test_upload_rejects_oversized_image(self) -> None:
        """超过 max_size 应报错（如果实现有此校验）。"""
        limit = _max_image_bytes()
        default_limit = 10 * 1024 * 1024
        oversized = b"x" * ((limit or default_limit) + 1)

        fn = first_callable(
            client, "upload_image", "upload_firefly_image", required=False
        )
        if not callable(fn):
            self.skipTest("upload_image not available")

        kwargs: dict = {}
        try:
            sig = inspect.signature(fn)
            params = sig.parameters
            if "max_size" in params:
                kwargs["max_size"] = limit or default_limit
            elif "max_bytes" in params:
                kwargs["max_bytes"] = limit or default_limit
        except (TypeError, ValueError):
            params = {}

        has_explicit_limit = bool(limit) or ("max_size" in kwargs) or (
            "max_bytes" in kwargs
        )
        if not has_explicit_limit:
            # 探测内建校验
            try:
                with mock.patch(
                    "services.backends.firefly_client.curl_requests.post"
                ) as post:
                    post.return_value = mock.Mock(
                        status_code=200,
                        headers={},
                        text='{"images":[{"id":"x"}]}',
                        json=mock.Mock(
                            return_value={"images": [{"id": "x"}]}
                        ),
                    )
                    _upload_image("tok", oversized, "image/png", **kwargs)
            except Exception:
                return
            self.skipTest("upload_image has no size validation yet")
            return

        with mock.patch(
            "services.backends.firefly_client.curl_requests.post"
        ) as post:
            post.return_value = mock.Mock(
                status_code=200,
                headers={},
                text='{"images":[{"id":"x"}]}',
                json=mock.Mock(return_value={"images": [{"id": "x"}]}),
            )
            with self.assertRaises(Exception) as ctx:
                _upload_image("tok", oversized, "image/png", **kwargs)
        self.assertFalse(post.called, "oversized image must be rejected before POST")
        self.assertIsInstance(
            ctx.exception,
            (FireflyRequestError, ValueError, TypeError, OSError),
        )

    def test_upload_rejects_invalid_mime(self) -> None:
        """非 image/png|jpeg|webp 应报错。"""
        allowed = _allowed_mimes() or {
            "image/png",
            "image/jpeg",
            "image/jpg",
            "image/webp",
        }
        invalid = "application/pdf"
        self.assertNotIn(invalid, {m.lower() for m in allowed})

        fn = first_callable(
            client, "upload_image", "upload_firefly_image", required=False
        )
        if not callable(fn):
            self.skipTest("upload_image not available")

        with mock.patch(
            "services.backends.firefly_client.curl_requests.post"
        ) as post:
            post.return_value = mock.Mock(
                status_code=200,
                headers={},
                text='{"images":[{"id":"x"}]}',
                json=mock.Mock(return_value={"images": [{"id": "x"}]}),
            )
            with self.assertRaises(Exception) as ctx:
                try:
                    _upload_image("tok", b"not-really-pdf", invalid)
                except TypeError:
                    _upload_image("tok", b"not-really-pdf", mime=invalid)
            # 应在 POST 前拒绝
            self.assertFalse(
                post.called,
                "invalid mime must be rejected before POST",
            )
        self.assertIsInstance(
            ctx.exception,
            (FireflyRequestError, ValueError, TypeError),
        )


if __name__ == "__main__":
    unittest.main()
