from __future__ import annotations

import json
import os
import unittest

os.environ.setdefault("CHATGPT2API_AUTH_KEY", "test-auth")

from services.backends import firefly_video_payloads as payloads  # noqa: E402
from test._firefly_helpers import first_callable  # noqa: E402

try:
    from services.backends import firefly_video_catalog as catalog  # noqa: E402
except Exception:  # pragma: no cover
    catalog = None  # type: ignore


def _build_fn():
    return first_callable(
        payloads,
        "build_firefly_video_payload",
        "build_video_payload",
        "buildFireflyVideoPayload",
    )


def _resolve_model(model_id: str) -> dict:
    """优先用 catalog 解析；不可用时构造最小 model_info。"""
    if catalog is not None:
        fn = first_callable(
            catalog,
            "resolve_firefly_video_model",
            "resolve_video_model",
            required=False,
        )
        if fn is not None:
            conf = fn(model_id)
            if conf is not None:
                return dict(conf) if not isinstance(conf, dict) else conf

    # 最小回落表（仅保测试在 catalog 缺失时仍可表达意图）
    fallback = {
        "firefly-sora2-4s-16x9": {
            "family": "sora2",
            "engine": "sora2",
            "duration": 4,
            "aspect_ratio": "16:9",
            "ratio": "16x9",
            "resolution": "720p",
            "width": 1280,
            "height": 720,
            "modelId": "sora",
            "modelVersion": "sora-2",
            "upstreamModel": "openai:firefly:colligo:sora2",
            "generate_audio": False,
        },
        "firefly-veo31-8s-9x16-1080p": {
            "family": "veo31",
            "engine": "veo31-standard",
            "duration": 8,
            "aspect_ratio": "9:16",
            "ratio": "9x16",
            "resolution": "1080p",
            "width": 1080,
            "height": 1920,
            "modelId": "veo",
            "modelVersion": "3.1-generate",
            "upstreamModel": "google:firefly:colligo:veo31",
            "generate_audio": False,
        },
        "firefly-veo31-ref-8s-16x9-1080p": {
            "family": "veo31-ref",
            "engine": "veo31-standard",
            "duration": 8,
            "aspect_ratio": "16:9",
            "ratio": "16x9",
            "resolution": "1080p",
            "width": 1920,
            "height": 1080,
            "modelId": "veo",
            "modelVersion": "3.1-generate",
            "upstreamModel": "google:firefly:colligo:veo31",
            "reference_mode": "image",
            "referenceMode": "image",
            "generate_audio": False,
        },
        "firefly-kling3-10s-16x9": {
            "family": "kling3",
            "engine": "kling3",
            "duration": 10,
            "aspect_ratio": "16:9",
            "ratio": "16x9",
            "resolution": "720p",
            "width": 1280,
            "height": 720,
            "modelId": "kling",
            "modelVersion": "kling_v3_standard_i2v",
            "upstreamModel": "kling:firefly:colligo:3.0",
            "generate_audio": True,
            "generateAudio": True,
        },
        "firefly-kling-o3-15s-9x16": {
            "family": "kling-o3",
            "engine": "kling-o3",
            "duration": 15,
            "aspect_ratio": "9:16",
            "ratio": "9x16",
            "resolution": "1080p",
            "width": 1080,
            "height": 1920,
            "modelId": "kling",
            "modelVersion": "kling_o3_pro_reference_to_video",
            "upstreamModel": "kling:firefly:colligo:o3",
            "generate_audio": False,
        },
    }
    if model_id not in fallback:
        raise AssertionError(f"no model_info for {model_id}")
    return dict(fallback[model_id])


def _call_build(
    model_info: dict,
    prompt: str,
    *,
    reference_image_ids=None,
    entity_mentions=None,
    negative_prompt: str = "",
    generate_audio=None,
):
    """兼容多种签名：model_info 优先 / 扁平 kwargs。"""
    fn = _build_fn()
    kwargs_variants = [
        {
            "model_info": model_info,
            "prompt": prompt,
            "reference_image_ids": reference_image_ids,
            "entity_mentions": entity_mentions,
            "negative_prompt": negative_prompt,
            "generate_audio": generate_audio,
        },
        {
            "model_info": model_info,
            "prompt": prompt,
            "images": reference_image_ids,
            "entity_mentions": entity_mentions,
            "negative_prompt": negative_prompt,
        },
        {
            "family": model_info.get("family"),
            "prompt": prompt,
            "images": reference_image_ids,
            "opts": {
                **model_info,
                "entity_mentions": entity_mentions,
                "negative_prompt": negative_prompt,
            },
        },
        # TS 风格扁平参数
        {
            "prompt": prompt,
            "upstreamModel": model_info.get("upstreamModel"),
            "upstreamModelId": model_info.get("modelId")
            or model_info.get("upstreamModelId"),
            "upstreamModelVersion": model_info.get("modelVersion")
            or model_info.get("upstreamModelVersion"),
            "engine": model_info.get("engine"),
            "duration": model_info.get("duration"),
            "aspectRatio": model_info.get("aspect_ratio")
            or model_info.get("aspectRatio"),
            "size": {
                "width": model_info.get("width") or 1280,
                "height": model_info.get("height") or 720,
            },
            "generateAudio": (
                generate_audio
                if generate_audio is not None
                else model_info.get("generate_audio")
                or model_info.get("generateAudio")
            ),
            "referenceMode": model_info.get("reference_mode")
            or model_info.get("referenceMode"),
            "negativePrompt": negative_prompt or None,
            "sourceImageIds": reference_image_ids,
            "entityMentions": entity_mentions,
        },
    ]

    last_err: Exception | None = None
    for kwargs in kwargs_variants:
        # 去掉 None 值，减少 TypeError
        clean = {k: v for k, v in kwargs.items() if v is not None}
        try:
            result = fn(**clean)
            if isinstance(result, list):
                if not result:
                    raise AssertionError("empty payload candidates")
                return result[0]
            if isinstance(result, dict):
                return result
        except TypeError as exc:
            last_err = exc
            continue
    # 位置参数回退：build(model_info, prompt, images)
    try:
        result = fn(model_info, prompt, reference_image_ids or [])
        if isinstance(result, dict):
            return result
        if isinstance(result, list) and result:
            return result[0]
    except TypeError as exc:
        last_err = exc
    raise AssertionError(f"unable to call video payload builder: {last_err}")


def _blobs(payload: dict) -> list:
    blobs = (
        payload.get("referenceBlobs")
        or payload.get("reference_blobs")
        or []
    )
    if not isinstance(blobs, list):
        return []
    return [b for b in blobs if isinstance(b, dict)]


class SoraVideoPayloadTests(unittest.TestCase):
    """Sora：prompt 是 JSON 字符串，含 duration_sec / prompt_text；fps:24。"""

    def test_sora_prompt_is_json_string_with_fps(self) -> None:
        """sora prompt 可 json.loads，含 duration_sec、prompt_text；顶层 fps=24。"""
        model = _resolve_model("firefly-sora2-4s-16x9")
        payload = _call_build(model, "a cat surfing", negative_prompt="blurry")

        prompt_raw = payload.get("prompt")
        self.assertIsInstance(prompt_raw, str, "sora prompt 必须是 JSON 字符串")
        parsed = json.loads(prompt_raw)
        self.assertIsInstance(parsed, dict)
        self.assertEqual(int(parsed.get("duration_sec") or 0), 4)
        self.assertEqual(str(parsed.get("prompt_text") or ""), "a cat surfing")
        # 负向提示可选写入
        if "negative_prompt" in parsed:
            self.assertEqual(parsed.get("negative_prompt"), "blurry")

        self.assertEqual(int(payload.get("fps") or 0), 24)
        self.assertEqual(
            str(payload.get("modelId") or payload.get("model_id") or ""), "sora"
        )


class Veo31VideoPayloadTests(unittest.TestCase):
    """Veo31：parameters 字段；ref=asset / 非 ref=general。"""

    def test_veo31_parameters_and_general_blobs(self) -> None:
        """modelSpecificPayload.parameters 含 durationSeconds/aspectRatio/addWaterMark；
        非 ref 模式 blob usage=general。"""
        model = _resolve_model("firefly-veo31-8s-9x16-1080p")
        payload = _call_build(
            model,
            "cinematic walk",
            reference_image_ids=["img-a", "img-b"],
        )

        msp = (
            payload.get("modelSpecificPayload")
            or payload.get("model_specific_payload")
            or {}
        )
        params = msp.get("parameters") or {}
        self.assertEqual(int(params.get("durationSeconds") or 0), 8)
        aspect = str(params.get("aspectRatio") or params.get("aspect_ratio") or "")
        self.assertEqual(aspect.replace("x", ":"), "9:16")
        watermark = params.get("addWaterMark", params.get("add_watermark"))
        self.assertIs(watermark, False)

        blobs = _blobs(payload)
        self.assertGreaterEqual(len(blobs), 1)
        for blob in blobs:
            self.assertEqual(blob.get("usage"), "general")

    def test_veo31_ref_uses_asset_usage(self) -> None:
        """veo31-ref 模式 referenceBlobs usage=asset。"""
        model = _resolve_model("firefly-veo31-ref-8s-16x9-1080p")
        # 确保 ref 标志存在
        model.setdefault("reference_mode", "image")
        model.setdefault("referenceMode", "image")
        payload = _call_build(
            model,
            "ref style video",
            reference_image_ids=["r1", "r2", "r3"],
        )
        blobs = _blobs(payload)
        self.assertEqual(len(blobs), 3)
        for blob in blobs:
            self.assertEqual(blob.get("usage"), "asset")


class KlingVideoPayloadTests(unittest.TestCase):
    """Kling：顶层 duration；有图 module=image2video；frame/element blob。"""

    def test_kling3_frame_and_audio(self) -> None:
        """kling 顶层 duration；有图 module=image2video；blob usage=frame+order；
        kling3 generateAudio=true。"""
        model = _resolve_model("firefly-kling3-10s-16x9")
        payload = _call_build(
            model,
            "a warrior runs",
            reference_image_ids=["k1", "k2"],
        )

        self.assertEqual(int(payload.get("duration") or 0), 10)

        meta = (
            payload.get("generationMetadata")
            or payload.get("generation_metadata")
            or {}
        )
        self.assertEqual(meta.get("module"), "image2video")

        audio = payload.get("generateAudio", payload.get("generate_audio"))
        self.assertIs(audio, True)

        blobs = _blobs(payload)
        self.assertEqual(len(blobs), 2)
        for idx, blob in enumerate(blobs, start=1):
            self.assertEqual(blob.get("usage"), "frame")
            self.assertEqual(int(blob.get("order") or 0), idx)

    def test_kling_o3_entity_element_blob(self) -> None:
        """kling-o3 实体：blob usage=element + creativeCloudFileId + mention.id。"""
        model = _resolve_model("firefly-kling-o3-15s-9x16")
        entity_mentions = [
            {
                "creativeCloudFileId": "urn:aaid:sc:US:entity-1",
                "mention_id": "mentionABC",
            }
        ]
        payload = _call_build(
            model,
            "a cat @entity:Fluffy walking",
            entity_mentions=entity_mentions,
        )
        blobs = _blobs(payload)
        element_blobs = [b for b in blobs if b.get("usage") == "element"]
        self.assertGreaterEqual(len(element_blobs), 1, f"blobs={blobs}")
        blob = element_blobs[0]
        self.assertEqual(
            str(blob.get("creativeCloudFileId") or ""),
            "urn:aaid:sc:US:entity-1",
        )
        mention = blob.get("mention") or {}
        self.assertEqual(str(mention.get("id") or ""), "mentionABC")


if __name__ == "__main__":
    unittest.main()
