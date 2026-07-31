"""Firefly 文生视频 / 图生视频请求体构造。

移植自：
- 参考/adobe2api-master/core/adobe_client.py（_build_video_payload ~1118–1288）
- 参考/GPT2Image-Pro-main/.../firefly-direct/payloads.ts（buildFireflyVideoPayload）
- docs/plan/2026-06-20-adobe-firefly-video-spec.md

三引擎分叉：
- sora（默认）：prompt 为 JSON 字符串；fps/camera/jobMode/referenceFrames
- veo31-standard / fast：modelSpecificPayload.parameters；ref 模式 asset，否则 general
- kling-o3 / kling3：顶层 duration + generationSettings；frame / element blob
"""

from __future__ import annotations

import json
import time
from typing import Any


def _seed_now() -> int:
    return int(time.time()) % 999999


def _as_size(model_info: dict[str, Any]) -> dict[str, int]:
    """从 model_info 取 size；缺省 1280×720。"""
    try:
        width = int(model_info.get("width") or 1280)
        height = int(model_info.get("height") or 720)
    except (TypeError, ValueError):
        width, height = 1280, 720
    return {"width": max(1, width), "height": max(1, height)}


def _aspect_ratio(model_info: dict[str, Any]) -> str:
    """payload 用冒号比例（读 catalog snake_case）。"""
    aspect = str(model_info.get("aspect_ratio") or "").strip()
    if aspect:
        return aspect.replace("x", ":").replace("×", ":")
    ratio = str(model_info.get("ratio") or "16x9").strip()
    return ratio.replace("x", ":").replace("×", ":") or "16:9"


def _duration(model_info: dict[str, Any]) -> int:
    try:
        return max(1, int(model_info.get("duration") or 4))
    except (TypeError, ValueError):
        return 4


def _engine(model_info: dict[str, Any]) -> str:
    return str(model_info.get("engine") or "sora2").strip().lower()


def _generate_audio(model_info: dict[str, Any]) -> bool:
    """读 catalog snake_case generate_audio；缺省时 kling3 开音频。"""
    if "generate_audio" in model_info:
        return bool(model_info.get("generate_audio"))
    # kling3 默认开音频
    return _engine(model_info) == "kling3"


def _reference_mode(model_info: dict[str, Any]) -> str | None:
    """读 catalog snake_case reference_mode。"""
    text = str(model_info.get("reference_mode") or "").strip().lower()
    return text or None


def _clean_image_ids(reference_image_ids: list[str] | None) -> list[str]:
    if not reference_image_ids:
        return []
    out: list[str] = []
    for item in reference_image_ids:
        text = str(item or "").strip()
        if text:
            out.append(text)
    return out


def _build_sora_prompt_json(
    prompt: str,
    duration: int,
    negative_prompt: str = "",
) -> str:
    """Sora 的 prompt 字段是 JSON 字符串（最易写错）。"""
    payload: dict[str, Any] = {
        "id": 1,
        "duration_sec": int(duration),
        "prompt_text": prompt,
    }
    if negative_prompt:
        payload["negative_prompt"] = negative_prompt
    return json.dumps(payload, ensure_ascii=False)


def _normalize_entity_mentions(
    entity_mentions: list[dict[str, Any]] | None,
) -> list[dict[str, str]]:
    """实体 mention 规范化为 {urn, mention_id}。

    接受字段别名：
    - urn / id / creativeCloudFileId
    - mention_id / mentionId / mention.id
    """
    if not entity_mentions:
        return []
    out: list[dict[str, str]] = []
    for ref in entity_mentions:
        if not isinstance(ref, dict):
            continue
        urn = str(
            ref.get("urn")
            or ref.get("creativeCloudFileId")
            or ref.get("id")
            or ""
        ).strip()
        mention = ref.get("mention")
        mention_id = ""
        if isinstance(mention, dict):
            mention_id = str(mention.get("id") or "").strip()
        if not mention_id:
            mention_id = str(
                ref.get("mention_id") or ref.get("mentionId") or ""
            ).strip()
        if urn and mention_id:
            out.append({"urn": urn, "mention_id": mention_id})
    return out


def build_firefly_video_payload(
    model_info: dict[str, Any],
    prompt: str,
    reference_image_ids: list[str] | None = None,
    *,
    entity_mentions: list[dict[str, Any]] | None = None,
    negative_prompt: str = "",
    generate_audio: bool | None = None,
) -> dict[str, Any]:
    """根据 resolve_firefly_video_model 结果构造 generate-async 视频请求体。

    Args:
        model_info: catalog 解析结果（含 engine/duration/width/height/...）
        prompt: 文本提示
        reference_image_ids: 已上传的 storage image id 列表
        entity_mentions: Kling O3 实体绑定（接口预留）
        negative_prompt: 负向提示（主要 sora 使用）
        generate_audio: 覆盖 catalog 默认音频开关；None 则取 model_info

    Returns:
        可直接 POST 的 dict（三引擎字段各异）
    """
    if not isinstance(model_info, dict):
        raise TypeError("model_info must be a dict")

    engine = _engine(model_info)
    duration = _duration(model_info)
    aspect = _aspect_ratio(model_info)
    size = _as_size(model_info)
    seed_val = _seed_now()
    prompt_text = str(prompt or "")
    neg = str(negative_prompt or "")
    ids = _clean_image_ids(reference_image_ids)
    audio = (
        bool(generate_audio)
        if generate_audio is not None
        else _generate_audio(model_info)
    )
    ref_mode = _reference_mode(model_info)
    # catalog 生产键：upstreamModel（Adobe camelCase）
    upstream_model = str(
        model_info.get("upstreamModel") or "openai:firefly:colligo:sora2"
    )

    # ------------------------------------------------------------------
    # Veo 3.1 standard / fast
    # ------------------------------------------------------------------
    if engine in {"veo31-standard", "veo31-fast"}:
        model_version = (
            "3.1-fast-generate" if engine == "veo31-fast" else "3.1-generate"
        )
        # catalog 若已给出 modelVersion 优先
        catalog_ver = str(model_info.get("modelVersion") or "").strip()
        if catalog_ver:
            model_version = catalog_ver

        payload: dict[str, Any] = {
            "n": 1,
            "seeds": [seed_val],
            "modelId": "veo",
            "modelVersion": model_version,
            "output": {"storeInputs": True},
            "prompt": prompt_text,
            "size": size,
            "generateAudio": audio,
            "referenceBlobs": [],
            "generationMetadata": {"module": "text2video"},
            "modelSpecificPayload": {
                "parameters": {
                    "durationSeconds": int(duration),
                    "aspectRatio": aspect,
                    "addWaterMark": False,
                }
            },
        }
        if ids:
            if engine == "veo31-standard" and ref_mode == "image":
                # veo31-ref：usage=asset，最多 3 张
                payload["referenceBlobs"] = [
                    {"id": image_id, "usage": "asset"} for image_id in ids[:3]
                ]
            else:
                # 普通 veo / fast：usage=general + promptReference，最多 2 张
                payload["referenceBlobs"] = [
                    {
                        "id": image_id,
                        "usage": "general",
                        "promptReference": idx,
                    }
                    for idx, image_id in enumerate(ids[:2], start=1)
                ]
        return payload

    # ------------------------------------------------------------------
    # Kling O3 / Kling 3
    # ------------------------------------------------------------------
    if engine in {"kling-o3", "kling3"}:
        model_version = (
            "kling_o3_pro_reference_to_video"
            if engine == "kling-o3"
            else "kling_v3_standard_i2v"
        )
        catalog_ver = str(model_info.get("modelVersion") or "").strip()
        if catalog_ver:
            model_version = catalog_ver

        has_frames = bool(ids)
        payload = {
            "n": 1,
            "seeds": [seed_val],
            "modelId": "kling",
            "modelVersion": model_version,
            "output": {"storeInputs": True},
            "prompt": prompt_text,
            "size": size,
            "generateAudio": audio,
            "generationMetadata": {
                "module": "image2video" if has_frames else "text2video"
            },
            "duration": int(duration),
            "generationSettings": {"aspectRatio": aspect},
            "referenceBlobs": [
                {"id": image_id, "usage": "frame", "order": idx}
                for idx, image_id in enumerate(ids[:2], start=1)
            ],
        }
        # Kling O3 实体：usage=element + creativeCloudFileId + mention.id
        if engine == "kling-o3":
            for ent in _normalize_entity_mentions(entity_mentions):
                payload["referenceBlobs"].append(
                    {
                        "usage": "element",
                        "creativeCloudFileId": ent["urn"],
                        "mention": {"id": ent["mention_id"]},
                    }
                )
        return payload

    # ------------------------------------------------------------------
    # Sora（默认分支，含 sora2 / sora2-pro）
    # ------------------------------------------------------------------
    payload = {
        "n": 1,
        "seeds": [seed_val],
        "modelId": "sora",
        "modelVersion": str(model_info.get("modelVersion") or "sora-2"),
        "size": size,
        "duration": int(duration),
        "fps": 24,
        "prompt": _build_sora_prompt_json(
            prompt=prompt_text,
            duration=duration,
            negative_prompt=neg,
        ),
        "generationMetadata": {"module": "text2video"},
        "model": upstream_model,
        "generateAudio": audio,
        "generateLoop": False,
        "transparentBackground": False,
        "seed": str(seed_val),
        "locale": "en-US",
        "camera": {
            "angle": "none",
            "shotSize": "none",
            "motion": None,
            "promptStyle": None,
        },
        "negativePrompt": neg,
        "jobMode": "standard",
        "debugGenerationEndpoint": "",
        "referenceBlobs": [],
        "referenceFrames": [],
        "referenceVideo": None,
        "cameraMotionReferenceVideo": None,
        "characterReference": None,
        "editReferenceVideo": None,
        "output": {"storeInputs": True},
    }
    if ids:
        first_id = ids[0]
        payload["referenceBlobs"] = [
            {"id": first_id, "usage": "general", "promptReference": 1}
        ]
        payload["referenceFrames"] = [{"localBlobRef": first_id}, None]
    return payload
