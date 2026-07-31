"""Firefly 文生图 / 图生图请求体构造（单候选）。

移植自 adobe2api payloads.py / GPT2Image-Pro firefly-direct/payloads.ts。
Phase 2：image2image + referenceBlobs（gpt=subject / nano=general）。
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


def _is_gpt_family(model_info: dict[str, Any]) -> bool:
    pixel_table = str(model_info.get("pixel_table") or "").strip().lower()
    model_id = str(model_info.get("modelId") or "").strip().lower()
    return pixel_table == "gpt" or model_id == "gpt-image"


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

    model_info 生产键：modelId / modelVersion / width / height /
    pixel_table / output_resolution / aspect_ratio / ratio / resolution。
    输出给 Adobe 的字段保持 camelCase。
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

    is_gpt = _is_gpt_family(model_info)

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


def build_image2image_payload(
    model_info: dict[str, Any],
    prompt: str,
    reference_image_ids: list[str],
    n: int = 1,
    quality: str = "medium",
    seeds: list[int] | None = None,
) -> dict[str, Any]:
    """图生图请求体。关键区别：module=image2image + referenceBlobs。

    **usage 两族相反（最易错）：**
    - gpt-image 族：usage="subject"
    - nano-banana 族：usage="general"
    """
    if not isinstance(reference_image_ids, (list, tuple)):
        raise ValueError("reference_image_ids is required")
    image_ids = [str(x).strip() for x in reference_image_ids if str(x or "").strip()]
    if not image_ids:
        raise ValueError("reference_image_ids is required")

    payload = build_text2image_payload(
        model_info,
        prompt,
        n=n,
        quality=quality,
        seeds=seeds,
    )

    # gpt → subject；nano → general（Adobe 两族不可共用）
    usage = "subject" if _is_gpt_family(model_info) else "general"
    payload["generationMetadata"] = {
        "module": "image2image",
        "submodule": "ff-image-generate",
    }
    payload["referenceBlobs"] = [
        {"id": image_id, "usage": usage} for image_id in image_ids
    ]
    return payload
