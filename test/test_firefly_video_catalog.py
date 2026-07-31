from __future__ import annotations

import os
import unittest

os.environ.setdefault("CHATGPT2API_AUTH_KEY", "test-auth")

from services.backends import firefly_video_catalog as catalog  # noqa: E402
from test._firefly_helpers import (  # noqa: E402
    first_callable,
    get_field as _get,
)


def _resolve_fn():
    return first_callable(
        catalog,
        "resolve_firefly_video_model",
        "resolve_video_model",
        "resolveFireflyVideoModel",
    )


def _list_families_fn():
    fn = first_callable(
        catalog,
        "list_firefly_video_families",
        "list_video_families",
        "firefly_video_families",
        required=False,
    )
    if fn is not None:
        return fn
    # 回退常量
    families = getattr(catalog, "FIREFLY_VIDEO_FAMILIES", None)
    if isinstance(families, dict):
        return lambda: list(families.keys())
    if isinstance(families, (list, tuple)):
        return lambda: list(families)
    raise AssertionError("missing list_firefly_video_families")


def _max_input_images_fn():
    return first_callable(
        catalog,
        "max_input_images",
        "firefly_video_max_input_images",
        "video_max_input_images",
        required=False,
    )


def _video_size_fn():
    return first_callable(
        catalog,
        "video_size",
        "firefly_video_size",
        "video_pixels",
        required=False,
    )


def _family_ids(raw) -> set[str]:
    """兼容 list[str] / list[dict] / dict keys。"""
    if isinstance(raw, dict):
        return {str(k) for k in raw.keys()}
    out: set[str] = set()
    for item in raw:
        if isinstance(item, str):
            out.add(item)
        elif isinstance(item, dict):
            fam = item.get("family") or item.get("id") or item.get("name")
            if fam:
                out.add(str(fam))
        else:
            fam = getattr(item, "family", None) or getattr(item, "id", None)
            if fam:
                out.add(str(fam))
    return out


def _max_images_for(conf: object, family_hint: str) -> int:
    """优先 conf 字段，其次 max_input_images(family/conf)。"""
    direct = _get(conf, "max_input_images", "maxInputImages")
    if direct is not None:
        return int(direct)

    fn = _max_input_images_fn()
    if fn is None:
        raise AssertionError("missing max_input_images helper")

    # 先试 family 字符串，再试 conf
    try:
        return int(fn(family_hint))
    except Exception:
        pass
    try:
        return int(fn(conf))
    except Exception as exc:
        raise AssertionError(f"max_input_images failed: {exc}") from exc


class ResolveFireflyVideoModelTests(unittest.TestCase):
    """resolve_firefly_video_model：完整 id / 未知 / 空默认。"""

    def test_sora2_4s_16x9_720p(self) -> None:
        """firefly-sora2-4s-16x9 → engine=sora2, duration=4, 720p, 1280×720。"""
        conf = _resolve_fn()("firefly-sora2-4s-16x9")
        self.assertIsNotNone(conf)

        engine = str(_get(conf, "engine") or "")
        self.assertEqual(engine, "sora2")
        self.assertEqual(int(_get(conf, "duration") or 0), 4)

        resolution = str(
            _get(conf, "resolution", "output_resolution", "outputResolution") or ""
        ).lower()
        self.assertEqual(resolution, "720p")

        ratio = str(
            _get(conf, "aspect_ratio", "aspectRatio", "ratio") or ""
        ).replace("x", ":")
        self.assertEqual(ratio, "16:9")

        width = _get(conf, "width")
        height = _get(conf, "height")
        self.assertEqual(int(width), 1280)
        self.assertEqual(int(height), 720)

        family = str(_get(conf, "family") or "")
        self.assertEqual(family, "sora2")

    def test_veo31_8s_9x16_1080p(self) -> None:
        """firefly-veo31-8s-9x16-1080p → 1080p, 1080×1920。"""
        conf = _resolve_fn()("firefly-veo31-8s-9x16-1080p")
        self.assertIsNotNone(conf)

        resolution = str(
            _get(conf, "resolution", "output_resolution", "outputResolution") or ""
        ).lower()
        self.assertEqual(resolution, "1080p")

        ratio = str(
            _get(conf, "aspect_ratio", "aspectRatio", "ratio") or ""
        ).replace("x", ":")
        self.assertEqual(ratio, "9:16")

        width = _get(conf, "width")
        height = _get(conf, "height")
        self.assertEqual(int(width), 1080)
        self.assertEqual(int(height), 1920)

        family = str(_get(conf, "family") or "")
        self.assertEqual(family, "veo31")
        self.assertEqual(int(_get(conf, "duration") or 0), 8)

    def test_unknown_model_returns_none(self) -> None:
        """未知 model id 应返回 None。"""
        resolve = _resolve_fn()
        self.assertIsNone(resolve("unknown-video-model"))
        self.assertIsNone(resolve("firefly-sora2-3s-16x9"))  # 非法时长
        self.assertIsNone(resolve("firefly-gpt-image-2-2k-1x1"))  # 图像模型

    def test_empty_falls_back_to_default(self) -> None:
        """空字符串应回落默认模型；若实现返回 None，则 DEFAULT 常量本身可解析。"""
        resolve = _resolve_fn()
        conf = resolve("")
        default_id = (
            getattr(catalog, "DEFAULT_VIDEO_MODEL", None)
            or getattr(catalog, "DEFAULT_MODEL", None)
            or "firefly-sora2-4s-16x9"
        )
        if conf is None:
            conf = resolve(str(default_id))
        self.assertIsNotNone(conf, "empty/default video model should resolve")

        family = str(_get(conf, "family") or "")
        # 默认族通常是 sora2
        self.assertIn(family, ("sora2", "sora2-pro", "veo31"))
        resolution = str(
            _get(conf, "resolution", "output_resolution", "outputResolution") or ""
        ).lower()
        self.assertIn(resolution, ("720p", "1080p"))


class ListFireflyVideoFamiliesTests(unittest.TestCase):
    """list_firefly_video_families：7 族。"""

    def test_contains_seven_families(self) -> None:
        """应含 sora2 / sora2-pro / veo31 / veo31-ref / veo31-fast / kling-o3 / kling3。"""
        families = _list_families_fn()()
        family_ids = _family_ids(families)
        expected = {
            "sora2",
            "sora2-pro",
            "veo31",
            "veo31-ref",
            "veo31-fast",
            "kling-o3",
            "kling3",
        }
        self.assertTrue(
            expected.issubset(family_ids),
            f"missing families: {expected - family_ids}; got={family_ids}",
        )
        self.assertGreaterEqual(len(family_ids), 7)


class MaxInputImagesTests(unittest.TestCase):
    """max_input_images：sora=1, veo/kling=2, veo-ref=3。"""

    def test_max_input_images_by_family(self) -> None:
        """按族断言最大输入图数量。"""
        resolve = _resolve_fn()
        cases = (
            ("firefly-sora2-4s-16x9", "sora2", 1),
            ("firefly-veo31-8s-9x16-1080p", "veo31", 2),
            ("firefly-veo31-ref-8s-16x9-1080p", "veo31-ref", 3),
            ("firefly-kling3-10s-16x9", "kling3", 2),
            ("firefly-kling-o3-15s-9x16", "kling-o3", 2),
        )
        for model_id, family, expected in cases:
            with self.subTest(model_id=model_id):
                conf = resolve(model_id)
                self.assertIsNotNone(conf, f"unresolved {model_id}")
                got = _max_images_for(conf, family)
                self.assertEqual(got, expected)


class VideoPixelTableTests(unittest.TestCase):
    """像素表：720p 1280×720、1080p 1080×1920。"""

    def test_pixel_table(self) -> None:
        """720p 16:9 → 1280×720；1080p 9:16 → 1080×1920。"""
        size_fn = _video_size_fn()
        if size_fn is not None:
            p720 = size_fn("720p", "16:9")
            if isinstance(p720, dict):
                self.assertEqual(int(p720.get("width") or 0), 1280)
                self.assertEqual(int(p720.get("height") or 0), 720)
            else:
                self.assertEqual(tuple(int(x) for x in p720), (1280, 720))

            p1080 = size_fn("1080p", "9:16")
            if isinstance(p1080, dict):
                self.assertEqual(int(p1080.get("width") or 0), 1080)
                self.assertEqual(int(p1080.get("height") or 0), 1920)
            else:
                self.assertEqual(tuple(int(x) for x in p1080), (1080, 1920))
            return

        # 无独立 size 函数时，从 resolve 结果断言
        resolve = _resolve_fn()
        conf720 = resolve("firefly-sora2-4s-16x9")
        self.assertIsNotNone(conf720)
        self.assertEqual(int(_get(conf720, "width")), 1280)
        self.assertEqual(int(_get(conf720, "height")), 720)

        conf1080 = resolve("firefly-veo31-8s-9x16-1080p")
        self.assertIsNotNone(conf1080)
        self.assertEqual(int(_get(conf1080, "width")), 1080)
        self.assertEqual(int(_get(conf1080, "height")), 1920)


if __name__ == "__main__":
    unittest.main()
