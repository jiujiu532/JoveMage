from __future__ import annotations

import os
import unittest

os.environ.setdefault("CHATGPT2API_AUTH_KEY", "test-auth")

from services.backends import firefly_video_catalog as catalog  # noqa: E402
from test._firefly_helpers import (  # noqa: E402
    first_callable,
    get_field as _get,
)


# /v1/models 放出的 7 个族级 id（firefly- 前缀）
_FAMILY_IDS = (
    "firefly-sora2",
    "firefly-sora2-pro",
    "firefly-veo31",
    "firefly-veo31-ref",
    "firefly-veo31-fast",
    "firefly-kling-o3",
    "firefly-kling3",
)

# 族级 id → 期望默认完整 id（最短 duration + 16x9 + 族默认 resolution）
_FAMILY_DEFAULT_FULL = {
    "firefly-sora2": "firefly-sora2-4s-16x9",
    "firefly-sora2-pro": "firefly-sora2-pro-4s-16x9",
    "firefly-veo31": "firefly-veo31-4s-16x9-720p",
    "firefly-veo31-ref": "firefly-veo31-ref-4s-16x9-720p",
    "firefly-veo31-fast": "firefly-veo31-fast-4s-16x9-720p",
    "firefly-kling-o3": "firefly-kling-o3-5s-16x9",
    "firefly-kling3": "firefly-kling3-5s-16x9",
}


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
    families = getattr(catalog, "FIREFLY_VIDEO_FAMILIES", None)
    if isinstance(families, dict):
        return lambda: list(families.keys())
    if isinstance(families, (list, tuple)):
        return lambda: list(families)
    raise AssertionError("missing list_firefly_video_families")


def _family_ids(raw) -> set[str]:
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


class FamilyResolveTests(unittest.TestCase):
    """resolve_firefly_video_model：族级 id 可解析（B2）。"""

    def test_firefly_sora2_family_resolves(self) -> None:
        """firefly-sora2 族级 id 非 None。"""
        conf = _resolve_fn()("firefly-sora2")
        self.assertIsNotNone(
            conf,
            "resolve_firefly_video_model('firefly-sora2') must not be None "
            "(family-level resolve)",
        )
        engine = str(_get(conf, "engine") or "")
        self.assertEqual(engine, "sora2")
        self.assertEqual(int(_get(conf, "duration") or 0), 4)

    def test_all_seven_family_ids_resolve(self) -> None:
        """7 个族级 id 均能 resolve。"""
        resolve = _resolve_fn()
        for family_id in _FAMILY_IDS:
            with self.subTest(family_id=family_id):
                conf = resolve(family_id)
                self.assertIsNotNone(
                    conf,
                    f"family id {family_id!r} should resolve (got None)",
                )
                family = str(_get(conf, "family") or "")
                # family 字段通常是短名 sora2 / veo31 ...
                short = family_id.removeprefix("firefly-")
                self.assertEqual(family, short)

    def test_full_id_still_resolves(self) -> None:
        """完整 id firefly-sora2-4s-16x9 仍正常。"""
        conf = _resolve_fn()("firefly-sora2-4s-16x9")
        self.assertIsNotNone(conf)
        self.assertEqual(str(_get(conf, "engine") or ""), "sora2")
        self.assertEqual(int(_get(conf, "duration") or 0), 4)
        ratio = str(
            _get(conf, "aspect_ratio", "aspectRatio", "ratio") or ""
        ).replace("x", ":")
        self.assertEqual(ratio, "16:9")
        self.assertEqual(int(_get(conf, "width") or 0), 1280)
        self.assertEqual(int(_get(conf, "height") or 0), 720)

    def test_family_matches_full_engine_duration(self) -> None:
        """族级与对应默认完整 id 的 engine/duration 一致。"""
        resolve = _resolve_fn()
        for family_id, full_id in _FAMILY_DEFAULT_FULL.items():
            with self.subTest(family_id=family_id, full_id=full_id):
                fam_conf = resolve(family_id)
                full_conf = resolve(full_id)
                self.assertIsNotNone(fam_conf, f"family {family_id} unresolved")
                self.assertIsNotNone(full_conf, f"full {full_id} unresolved")

                fam_engine = str(_get(fam_conf, "engine") or "")
                full_engine = str(_get(full_conf, "engine") or "")
                self.assertEqual(
                    fam_engine,
                    full_engine,
                    f"engine mismatch: family={fam_engine} full={full_engine}",
                )

                fam_dur = int(_get(fam_conf, "duration") or 0)
                full_dur = int(_get(full_conf, "duration") or 0)
                self.assertEqual(
                    fam_dur,
                    full_dur,
                    f"duration mismatch: family={fam_dur} full={full_dur}",
                )

                fam_family = str(_get(fam_conf, "family") or "")
                full_family = str(_get(full_conf, "family") or "")
                self.assertEqual(fam_family, full_family)

    def test_list_families_seven(self) -> None:
        """list_firefly_video_families 应含 7 族。"""
        families = _list_families_fn()()
        family_ids = _family_ids(families)
        # 兼容短名 / firefly- 前缀
        normalized = {
            (f.removeprefix("firefly-") if f.startswith("firefly-") else f)
            for f in family_ids
        }
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
            expected.issubset(normalized),
            f"missing families: {expected - normalized}; got={normalized}",
        )


if __name__ == "__main__":
    unittest.main()
