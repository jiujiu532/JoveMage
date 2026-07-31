"""Firefly 文生图请求体构造（Phase 1，单候选）。

移植自 adobe2api payloads.py / GPT2Image-Pro firefly-direct/payloads.ts。
图生图（referenceBlobs）留 Phase 2，本模块只做 text2image。
"""

from __future__ import annotations

import time
from typing import Any


def gpt_image_detail_level_from_quality(quality: str | None) -> int:
    """quality low→1 / medium→3 / high→5。"""
    level = str(quality or "medium").strip().lower()
    if level == "high":
        return 5
    if level == "medium":
        return 3
    return 1


def _seed_now() -> int:
    return int(time.time()) % 999999


def build_text2image_payload(
    model_info: dict[str, Any],
    prompt: str,
    n: int = 1,
    quality: str = "medium",
    seeds: list[int] | None = None,
) -> dict[str, Any]:
    """根据 resolve_firefly_image_model 结果构造 generate-async 请求体。

    gpt-image 族：modelSpecificPayload.size="WxH" + generationSettings.detailLevel
    nano-banana 族：modelSpecificPayload.aspectRatio + parameters.addWatermark=false
    """
    if not isinstance(model_info, dict):
        raise ValueError("model_info is required")

    model_id = str(model_info.get("modelId") or "").strip()
    model_version = str(model_info.get("modelVersion") or "").strip()
    if not model_id or not model_version:
        raise ValueError("model_info missing modelId/modelVersion")

    prompt_text = str(prompt or "").strip()
    if not prompt_text:
        raise ValueError("prompt is required")

    count = max(1, int(n or 1))
    seed_list = list(seeds) if seeds else [_seed_now()]
    if not seed_list:
        seed_list = [_seed_now()]

    width = int(model_info.get("width") or 0)
    height = int(model_info.get("height") or 0)
    if width <= 0 or height <= 0:
        raise ValueError("model_info missing positive width/height")

    pixel_table = str(model_info.get("pixel_table") or "").strip().lower()
    is_gpt = pixel_table == "gpt" or model_id.lower() == "gpt-image"

    if is_gpt:
        detail = gpt_image_detail_level_from_quality(quality)
        output_resolution = str(
            model_info.get("output_resolution")
            or str(model_info.get("resolution") or "2k").upper()
        ).upper()
        return {
            "modelId": model_id,
            "modelVersion": model_version,
            "n": count,
            "prompt": prompt_text,
            "seeds": seed_list,
            "output": {"storeInputs": True},
            "referenceBlobs": [],
            "generationMetadata": {
                "module": "text2image",
                "submodule": "ff-image-generate",
            },
            "modelSpecificPayload": {
                "size": f"{width}x{height}",
            },
            "outputResolution": output_resolution,
            "generationSettings": {
                "detailLevel": int(detail),
            },
            "size": {"width": width, "height": height},
            "skipCai": False,
            "addWatermark": False,
        }

    # nano-banana 族
    aspect = str(
        model_info.get("aspect_ratio")
        or str(model_info.get("ratio") or "16:9").replace("x", ":")
    ).strip()
    payload: dict[str, Any] = {
        "modelId": model_id,
        "modelVersion": model_version,
        "n": count,
        "prompt": prompt_text,
        "size": {"width": width, "height": height},
        "seeds": seed_list,
        "groundSearch": False,
        "skipCai": False,
        "addWatermark": False,
        "output": {"storeInputs": True},
        "referenceBlobs": [],
        "generationMetadata": {
            "module": "text2image",
            "submodule": "ff-image-generate",
        },
        "modelSpecificPayload": {
            "parameters": {"addWatermark": False},
        },
    }
    if aspect and aspect.lower() != "auto":
        # Adobe 要 "16:9" 形式
        payload["modelSpecificPayload"]["aspectRatio"] = aspect.replace("x", ":")
    return payload
