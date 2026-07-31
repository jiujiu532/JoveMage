from __future__ import annotations

import os
import unittest

os.environ.setdefault("CHATGPT2API_AUTH_KEY", "test-auth")

from services.backends import firefly_payloads as payloads  # noqa: E402


def _first_candidate(result: object) -> dict:
    """兼容返回 list[dict] 或单 dict。"""
    if isinstance(result, list):
        if not result:
            raise AssertionError("expected at least one payload candidate")
        first = result[0]
    else:
        first = result
    if not isinstance(first, dict):
        raise AssertionError(f"payload candidate must be dict, got {type(first)!r}")
    return first


def _build_image2image(**kwargs):
    """图生图 payload 构造：多名称 / 多签名兼容。

    优先散参数 candidates（测试友好），再回落 model_info 版 build_image2image_payload。
    """
    image_ids = (
        kwargs.get("reference_image_ids")
        or kwargs.get("source_image_ids")
        or kwargs.get("image_ids")
        or []
    )
    prompt = kwargs.get("prompt") or ""
    aspect_ratio = kwargs.get("aspect_ratio") or "1:1"
    output_resolution = kwargs.get("output_resolution") or "2K"
    upstream_model_id = kwargs.get("upstream_model_id") or ""
    upstream_model_version = kwargs.get("upstream_model_version") or ""
    quality_level = kwargs.get("quality_level") or kwargs.get("quality") or "medium"
    seeds = kwargs.get("seeds")
    n = int(kwargs.get("n") or 1)

    # 1) 散参数 candidates（与 Phase 1 文生图测试入口对称）
    for name in (
        "build_firefly_image2image_payload_candidates",
        "build_image2image_payload_candidates",
    ):
        fn = getattr(payloads, name, None)
        if not callable(fn):
            continue
        for id_key in ("reference_image_ids", "source_image_ids", "image_ids"):
            try:
                return fn(
                    prompt=prompt,
                    aspect_ratio=aspect_ratio,
                    output_resolution=output_resolution,
                    upstream_model_id=upstream_model_id,
                    upstream_model_version=upstream_model_version,
                    quality_level=quality_level,
                    seeds=seeds,
                    n=n,
                    **{id_key: list(image_ids)},
                )
            except TypeError:
                continue

    # 2) 直接 build_image2image_payload(model_info, prompt, reference_image_ids, ...)
    build = getattr(payloads, "build_image2image_payload", None)
    if callable(build):
        model_info_fn = getattr(payloads, "_model_info_from_loose_params", None)
        if callable(model_info_fn):
            model_info = model_info_fn(
                aspect_ratio=aspect_ratio,
                output_resolution=output_resolution,
                upstream_model_id=upstream_model_id,
                upstream_model_version=upstream_model_version,
            )
        else:
            # 最小 model_info（gpt / nano 足以触发 usage 分叉）
            is_gpt = str(upstream_model_id).lower() == "gpt-image"
            model_info = {
                "modelId": upstream_model_id or "gemini-flash",
                "modelVersion": upstream_model_version or "nano-banana-2",
                "width": 2048 if is_gpt else 2752,
                "height": 2048 if is_gpt else 1536,
                "pixel_table": "gpt" if is_gpt else "nano",
                "output_resolution": str(output_resolution).upper(),
                "aspect_ratio": str(aspect_ratio).replace("x", ":"),
            }
        try:
            return build(
                model_info,
                prompt,
                list(image_ids),
                n=n,
                quality=quality_level,
                seeds=seeds,
            )
        except TypeError:
            return build(
                model_info,
                prompt,
                reference_image_ids=list(image_ids),
                n=n,
                quality=quality_level,
                seeds=seeds,
            )

    # 3) 文生图 candidates + source_image_ids 扩展
    for name in (
        "build_firefly_image_payload_candidates",
        "build_image_payload_candidates",
    ):
        fn = getattr(payloads, name, None)
        if not callable(fn):
            continue
        for id_key in ("source_image_ids", "reference_image_ids", "image_ids"):
            try:
                return fn(
                    prompt=prompt,
                    aspect_ratio=aspect_ratio,
                    output_resolution=output_resolution,
                    upstream_model_id=upstream_model_id,
                    upstream_model_version=upstream_model_version,
                    quality_level=quality_level,
                    seeds=seeds,
                    n=n,
                    **{id_key: list(image_ids)},
                )
            except TypeError:
                continue

    raise AssertionError(
        "missing image2image payload builder "
        "(expected build_firefly_image2image_payload_candidates / "
        "build_image2image_payload)"
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
