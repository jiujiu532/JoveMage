from __future__ import annotations

import os
import unittest

os.environ.setdefault("CHATGPT2API_AUTH_KEY", "test-auth")

from services.backends import firefly_payloads as payloads  # noqa: E402
from test._firefly_helpers import (  # noqa: E402
    first_callable,
    first_payload_candidate as _first_candidate,
)


def _detail_level_fn():
    return first_callable(
        payloads,
        "gpt_image_detail_level_from_quality",
        "detail_level_from_quality",
        "gpt_image_detail_level",
    )


def _build_candidates(**kwargs):
    fn = first_callable(
        payloads,
        "build_firefly_image_payload_candidates",
        "build_image_payload_candidates",
        "build_firefly_image_payload",
    )
    return fn(**kwargs)


class GptImagePayloadTests(unittest.TestCase):
    """gpt-image 文生图 payload 关键字段。"""

    def test_text2image_module_size_and_detail_level(self) -> None:
        """module=text2image，modelSpecificPayload.size，generationSettings.detailLevel。"""
        result = _build_candidates(
            prompt="a cat",
            aspect_ratio="16:9",
            output_resolution="2K",
            upstream_model_id="gpt-image",
            upstream_model_version="2",
            quality_level="high",
        )
        payload = _first_candidate(result)

        meta = payload.get("generationMetadata") or payload.get("generation_metadata") or {}
        self.assertEqual(meta.get("module"), "text2image")

        msp = (
            payload.get("modelSpecificPayload")
            or payload.get("model_specific_payload")
            or {}
        )
        size_str = msp.get("size")
        self.assertIsInstance(size_str, str)
        self.assertRegex(str(size_str), r"^\d+x\d+$")
        # 2K 16:9 gpt-image 像素表：2560x1440
        self.assertEqual(size_str, "2560x1440")

        settings = (
            payload.get("generationSettings")
            or payload.get("generation_settings")
            or {}
        )
        detail = settings.get("detailLevel", settings.get("detail_level"))
        self.assertEqual(int(detail), 5)

        self.assertEqual(payload.get("modelId") or payload.get("model_id"), "gpt-image")
        self.assertEqual(
            payload.get("modelVersion") or payload.get("model_version"), "2"
        )


class NanoBananaPayloadTests(unittest.TestCase):
    """nano-banana 文生图 payload 关键字段。"""

    def test_text2image_aspect_ratio_and_no_watermark(self) -> None:
        """modelSpecificPayload.aspectRatio + parameters.addWatermark=false。"""
        result = _build_candidates(
            prompt="a dog",
            aspect_ratio="9:16",
            output_resolution="2K",
            upstream_model_id="gemini-flash",
            upstream_model_version="nano-banana-2",
        )
        payload = _first_candidate(result)

        meta = payload.get("generationMetadata") or payload.get("generation_metadata") or {}
        self.assertEqual(meta.get("module"), "text2image")

        msp = (
            payload.get("modelSpecificPayload")
            or payload.get("model_specific_payload")
            or {}
        )
        aspect = msp.get("aspectRatio") or msp.get("aspect_ratio")
        self.assertIn(str(aspect).replace("x", ":"), ("9:16",))

        params = msp.get("parameters") or {}
        watermark = params.get("addWatermark", params.get("add_watermark"))
        self.assertIs(watermark, False)

        size = payload.get("size") or {}
        if isinstance(size, dict):
            # nano-banana 2K 9:16：1536x2752
            self.assertEqual(int(size.get("width") or 0), 1536)
            self.assertEqual(int(size.get("height") or 0), 2752)


class QualityDetailLevelTests(unittest.TestCase):
    """quality → detailLevel 映射：low→1 / medium→3 / high→5。"""

    def test_quality_mapping(self) -> None:
        fn = _detail_level_fn()
        self.assertEqual(int(fn("low")), 1)
        self.assertEqual(int(fn("medium")), 3)
        self.assertEqual(int(fn("high")), 5)


class SeedsPayloadTests(unittest.TestCase):
    """seeds 传入时应写入 payload。"""

    def test_seeds_are_set_when_provided(self) -> None:
        """显式 seeds 应出现在请求体，不被随机值覆盖。"""
        seeds = [424242]
        result = _build_candidates(
            prompt="seeded",
            aspect_ratio="1:1",
            output_resolution="2K",
            upstream_model_id="gpt-image",
            upstream_model_version="2",
            seeds=seeds,
        )
        payload = _first_candidate(result)
        self.assertEqual(payload.get("seeds"), seeds)


if __name__ == "__main__":
    unittest.main()
