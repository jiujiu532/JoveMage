from __future__ import annotations

import os
import unittest

os.environ.setdefault("CHATGPT2API_AUTH_KEY", "test-auth")

from test._firefly_helpers import (  # noqa: E402
    build_image2image_payload_from_loose,
    first_payload_candidate as _first_candidate,
)


def _build_image2image(**kwargs):
    """图生图 payload 构造：走 test helper（生产 candidates 壳已删）。"""
    image_ids = (
        kwargs.get("reference_image_ids")
        or kwargs.get("source_image_ids")
        or kwargs.get("image_ids")
        or []
    )
    return build_image2image_payload_from_loose(
        prompt=kwargs.get("prompt") or "",
        aspect_ratio=kwargs.get("aspect_ratio") or "1:1",
        output_resolution=kwargs.get("output_resolution") or "2K",
        upstream_model_id=kwargs.get("upstream_model_id") or "",
        upstream_model_version=kwargs.get("upstream_model_version") or "",
        reference_image_ids=list(image_ids),
        quality_level=kwargs.get("quality_level") or kwargs.get("quality") or "medium",
        seeds=kwargs.get("seeds"),
        n=int(kwargs.get("n") or 1),
    )


def _reference_blobs(payload: dict) -> list:
    blobs = payload.get("referenceBlobs")
    if blobs is None:
        blobs = payload.get("reference_blobs")
    if blobs is None:
        return []
    if not isinstance(blobs, list):
        raise AssertionError(f"referenceBlobs must be list, got {type(blobs)!r}")
    return blobs


def _module_of(payload: dict) -> str:
    meta = (
        payload.get("generationMetadata")
        or payload.get("generation_metadata")
        or {}
    )
    if not isinstance(meta, dict):
        return ""
    return str(meta.get("module") or "")


def _blob_usage(blob: object) -> str:
    if not isinstance(blob, dict):
        raise AssertionError(f"reference blob must be dict, got {type(blob)!r}")
    return str(blob.get("usage") or "")


def _blob_id(blob: object) -> str:
    if not isinstance(blob, dict):
        raise AssertionError(f"reference blob must be dict, got {type(blob)!r}")
    return str(blob.get("id") or blob.get("image_id") or blob.get("imageId") or "")


class GptImageEditPayloadTests(unittest.TestCase):
    """gpt-image 图生图：usage 必须是 subject。"""

    def test_image2image_module_and_subject_usage(self) -> None:
        """module=image2image，referenceBlobs[].usage=subject。"""
        result = _build_image2image(
            prompt="edit this cat",
            aspect_ratio="1:1",
            output_resolution="2K",
            upstream_model_id="gpt-image",
            upstream_model_version="2",
            quality_level="medium",
            source_image_ids=["img-gpt-1"],
        )
        payload = _first_candidate(result)

        self.assertEqual(_module_of(payload), "image2image")

        blobs = _reference_blobs(payload)
        self.assertGreaterEqual(len(blobs), 1, "expected at least one referenceBlob")
        self.assertEqual(_blob_id(blobs[0]), "img-gpt-1")
        self.assertEqual(_blob_usage(blobs[0]), "subject")

        # Adobe 新 API 拒收 referenceImages
        self.assertNotIn("referenceImages", payload)
        self.assertNotIn("reference_images", payload)


class NanoBananaEditPayloadTests(unittest.TestCase):
    """nano-banana 图生图：usage 必须是 general（与 gpt 相反！）。"""

    def test_image2image_module_and_general_usage(self) -> None:
        """module=image2image，referenceBlobs[].usage=general。"""
        result = _build_image2image(
            prompt="edit this dog",
            aspect_ratio="1:1",
            output_resolution="2K",
            upstream_model_id="gemini-flash",
            upstream_model_version="nano-banana-2",
            source_image_ids=["img-nano-1"],
        )
        payload = _first_candidate(result)

        self.assertEqual(_module_of(payload), "image2image")

        blobs = _reference_blobs(payload)
        self.assertGreaterEqual(len(blobs), 1, "expected at least one referenceBlob")
        self.assertEqual(_blob_id(blobs[0]), "img-nano-1")
        self.assertEqual(
            _blob_usage(blobs[0]),
            "general",
            "nano-banana must use usage=general (not subject)",
        )


class MultiReferenceTests(unittest.TestCase):
    """多参考图应生成多条 referenceBlobs。"""

    def test_multiple_reference_ids(self) -> None:
        """3 个 image_id → referenceBlobs 长度 3，各 usage 一致。"""
        ids = ["img-a", "img-b", "img-c"]
        result = _build_image2image(
            prompt="multi ref edit",
            aspect_ratio="16:9",
            output_resolution="2K",
            upstream_model_id="gemini-flash",
            upstream_model_version="nano-banana-2",
            source_image_ids=ids,
        )
        payload = _first_candidate(result)

        self.assertEqual(_module_of(payload), "image2image")
        blobs = _reference_blobs(payload)
        self.assertEqual(len(blobs), 3, f"expected 3 blobs, got {blobs!r}")

        got_ids = [_blob_id(b) for b in blobs]
        self.assertEqual(got_ids, ids)

        usages = {_blob_usage(b) for b in blobs}
        self.assertEqual(usages, {"general"})

    def test_multiple_reference_ids_gpt_subject(self) -> None:
        """gpt-image 多参考图：每条 usage 均为 subject。"""
        ids = ["g1", "g2", "g3"]
        result = _build_image2image(
            prompt="multi gpt edit",
            aspect_ratio="1:1",
            output_resolution="2K",
            upstream_model_id="gpt-image",
            upstream_model_version="2",
            source_image_ids=ids,
        )
        payload = _first_candidate(result)
        blobs = _reference_blobs(payload)
        self.assertEqual(len(blobs), 3)
        self.assertEqual([_blob_id(b) for b in blobs], ids)
        self.assertEqual({_blob_usage(b) for b in blobs}, {"subject"})


if __name__ == "__main__":
    unittest.main()
