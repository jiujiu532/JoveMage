from __future__ import annotations

import os
import unittest

os.environ.setdefault("CHATGPT2API_AUTH_KEY", "test-auth")

from services.backends.firefly_catalog import (  # noqa: E402
    list_firefly_image_families,
    ratio_from_size,
    resolve_firefly_image_model,
)
from test._firefly_helpers import get_field as _get  # noqa: E402


class ResolveFireflyImageModelTests(unittest.TestCase):
    """resolve_firefly_image_model：族级 / 完整 id / 默认 / 未知。"""

    def test_family_id_defaults_to_2k_16x9_with_pixels(self) -> None:
        """族级 id firefly-nano-banana-pro 应落到默认 2K/16:9 并给出像素。"""
        conf = resolve_firefly_image_model("firefly-nano-banana-pro")
        self.assertIsNotNone(conf)

        resolution = str(
            _get(conf, "output_resolution", "outputResolution") or ""
        ).upper()
        ratio = str(_get(conf, "aspect_ratio", "aspectRatio") or "")
        # 接受 16:9 或 16x9 两种写法
        ratio_norm = ratio.replace("x", ":")
        width = _get(conf, "width")
        height = _get(conf, "height")

        self.assertEqual(resolution, "2K")
        self.assertEqual(ratio_norm, "16:9")
        # nano-banana 2K 16:9 像素表：2752x1536
        self.assertEqual(int(width), 2752)
        self.assertEqual(int(height), 1536)
        self.assertEqual(
            str(_get(conf, "upstream_model_id", "upstreamModelId") or ""),
            "gemini-flash",
        )
        self.assertEqual(
            str(_get(conf, "upstream_model_version", "upstreamModelVersion") or ""),
            "nano-banana-2",
        )

    def test_full_id_gpt_image_2_4k_1x1(self) -> None:
        """完整 id firefly-gpt-image-2-4k-1x1 应解析到 gpt-image / 2 / 4K / 1:1。"""
        conf = resolve_firefly_image_model("firefly-gpt-image-2-4k-1x1")
        self.assertIsNotNone(conf)

        self.assertEqual(
            str(_get(conf, "upstream_model_id", "upstreamModelId") or ""),
            "gpt-image",
        )
        self.assertEqual(
            str(_get(conf, "upstream_model_version", "upstreamModelVersion") or ""),
            "2",
        )
        self.assertEqual(
            str(_get(conf, "output_resolution", "outputResolution") or "").upper(),
            "4K",
        )
        ratio = str(_get(conf, "aspect_ratio", "aspectRatio") or "").replace("x", ":")
        self.assertEqual(ratio, "1:1")
        # gpt-image 4K 1:1 像素表：2880x2880
        width = _get(conf, "width")
        height = _get(conf, "height")
        if width is not None and height is not None:
            self.assertEqual(int(width), 2880)
            self.assertEqual(int(height), 2880)

    def test_unknown_model_returns_none(self) -> None:
        """未知 model id 应返回 None，由调用方决定报错或回退。"""
        self.assertIsNone(resolve_firefly_image_model("unknown-model"))
        self.assertIsNone(resolve_firefly_image_model("firefly-unknown-9k-1x1"))

    def test_empty_model_falls_back_to_default(self) -> None:
        """空字符串应回退默认模型 firefly-nano-banana-pro-2k-16x9。"""
        conf = resolve_firefly_image_model("")
        self.assertIsNotNone(conf)

        resolution = str(
            _get(conf, "output_resolution", "outputResolution") or ""
        ).upper()
        ratio = str(_get(conf, "aspect_ratio", "aspectRatio") or "").replace("x", ":")
        self.assertEqual(resolution, "2K")
        self.assertEqual(ratio, "16:9")
        self.assertEqual(
            str(_get(conf, "upstream_model_id", "upstreamModelId") or ""),
            "gemini-flash",
        )
        self.assertEqual(
            str(_get(conf, "upstream_model_version", "upstreamModelVersion") or ""),
            "nano-banana-2",
        )


class RatioFromSizeTests(unittest.TestCase):
    """ratio_from_size：像素宽高 → 比例后缀。"""

    def test_square_1024_maps_to_1x1(self) -> None:
        """1024x1024 应映射为 1x1。"""
        result = ratio_from_size(1024, 1024)
        # 允许 "1x1" 或 "1:1"，任务约定优先 1x1
        self.assertIn(str(result).replace(":", "x"), ("1x1",))


class ListFireflyImageFamiliesTests(unittest.TestCase):
    """list_firefly_image_families：对外暴露的 5 个图像族。"""

    def test_contains_five_families(self) -> None:
        """应包含 gpt-image 两版 + nano-banana 三族，共 5 个。"""
        families = list_firefly_image_families()
        self.assertIsInstance(families, (list, tuple, set, frozenset))
        family_ids = {str(item) for item in families}
        expected = {
            "firefly-gpt-image-2",
            "firefly-gpt-image-1.5",
            "firefly-nano-banana-pro",
            "firefly-nano-banana",
            "firefly-nano-banana2",
        }
        self.assertTrue(
            expected.issubset(family_ids),
            f"missing families: {expected - family_ids}; got={family_ids}",
        )
        self.assertGreaterEqual(len(family_ids), 5)


if __name__ == "__main__":
    unittest.main()
