"""Adobe Firefly 3P 视频模型目录（纯数据 + 解析）。

数据移植自：
- 参考/GPT2Image-Pro-main/.../firefly-direct/video-catalog.ts
- 参考/adobe2api-master/core/adobe_client.py（_video_size / 图生视频源图裁切）
- .trellis/tasks/07-31-adobe-firefly-integration/design-phase3-video.md

model-id 形态：firefly-<family>-<dur>s-<ratio>[-<res>]
- sora / kling：分辨率固定，不拼进 id
- veo31 系列：分辨率拼进 id（720p/1080p）
"""

from __future__ import annotations

import io
from typing import Any

try:
    from PIL import Image
except Exception:  # pragma: no cover
    Image = None  # type: ignore

from services.backends.firefly_ratio import ratio_to_colon, ratio_to_suffix

# ---------------------------------------------------------------------------
# 比例：payload 用 "16:9"，完整 model id 后缀用 "16x9"（实现见 firefly_ratio）
# ---------------------------------------------------------------------------

_VIDEO_RATIOS = ("16x9", "9x16")
_VIDEO_RESOLUTIONS = ("720p", "1080p")

DEFAULT_VIDEO_MODEL = "firefly-sora2-4s-16x9"

# 像素表：720p / 1080p × 16:9 / 9:16
VIDEO_SIZE_MAP: dict[str, dict[str, tuple[int, int]]] = {
    "720p": {
        "16:9": (1280, 720),
        "9:16": (720, 1280),
        "16x9": (1280, 720),
        "9x16": (720, 1280),
    },
    "1080p": {
        "16:9": (1920, 1080),
        "9:16": (1080, 1920),
        "16x9": (1920, 1080),
        "9x16": (1080, 1920),
    },
}


# ---------------------------------------------------------------------------
# 族级规格
# ---------------------------------------------------------------------------

# family → 配置模板（不含具体 duration/ratio/resolution 组合）
_VIDEO_FAMILY_SPECS: list[dict[str, Any]] = [
    {
        "family": "sora2",
        "prefix": "firefly-sora2",
        "upstreamModel": "openai:firefly:colligo:sora2",
        "modelId": "sora",
        "modelVersion": "sora-2",
        "engine": "sora2",
        "durations": (4, 8, 12),
        "ratios": _VIDEO_RATIOS,
        "resolutions": ("720p",),
        "resolution_in_id": False,
        "generate_audio": False,
        "label": "Sora 2",
    },
    {
        "family": "sora2-pro",
        "prefix": "firefly-sora2-pro",
        "upstreamModel": "openai:firefly:colligo:sora2-pro",
        "modelId": "sora",
        "modelVersion": "sora-2",
        "engine": "sora2",
        "durations": (4, 8, 12),
        "ratios": _VIDEO_RATIOS,
        "resolutions": ("720p",),
        "resolution_in_id": False,
        "generate_audio": False,
        "label": "Sora 2 Pro",
    },
    {
        "family": "veo31",
        "prefix": "firefly-veo31",
        "upstreamModel": "google:firefly:colligo:veo31",
        "modelId": "veo",
        "modelVersion": "3.1-generate",
        "engine": "veo31-standard",
        "durations": (4, 6, 8),
        "ratios": _VIDEO_RATIOS,
        "resolutions": ("720p", "1080p"),
        "resolution_in_id": True,
        "generate_audio": False,
        "label": "Veo 3.1",
    },
    {
        "family": "veo31-ref",
        "prefix": "firefly-veo31-ref",
        "upstreamModel": "google:firefly:colligo:veo31",
        "modelId": "veo",
        "modelVersion": "3.1-generate",
        "engine": "veo31-standard",
        "durations": (4, 6, 8),
        "ratios": _VIDEO_RATIOS,
        "resolutions": ("720p", "1080p"),
        "resolution_in_id": True,
        "generate_audio": False,
        "reference_mode": "image",
        "label": "Veo 3.1 Reference",
    },
    {
        "family": "veo31-fast",
        "prefix": "firefly-veo31-fast",
        "upstreamModel": "google:firefly:colligo:veo31-fast",
        "modelId": "veo",
        "modelVersion": "3.1-fast-generate",
        "engine": "veo31-fast",
        "durations": (4, 6, 8),
        "ratios": _VIDEO_RATIOS,
        "resolutions": ("720p", "1080p"),
        "resolution_in_id": True,
        "generate_audio": False,
        "label": "Veo 3.1 Fast",
    },
    {
        "family": "kling-o3",
        "prefix": "firefly-kling-o3",
        "upstreamModel": "kling:firefly:colligo:o3",
        "modelId": "kling",
        "modelVersion": "kling_o3_pro_reference_to_video",
        "engine": "kling-o3",
        "durations": (5, 15),
        "ratios": _VIDEO_RATIOS,
        "resolutions": ("1080p",),
        "resolution_in_id": False,
        "generate_audio": False,
        "label": "Kling O3",
    },
    {
        "family": "kling3",
        "prefix": "firefly-kling3",
        "upstreamModel": "kling:firefly:colligo:3.0",
        "modelId": "kling",
        "modelVersion": "kling_v3_standard_i2v",
        "engine": "kling3",
        "durations": (5, 10, 15),
        "ratios": _VIDEO_RATIOS,
        "resolutions": ("720p",),
        "resolution_in_id": False,
        "generate_audio": True,
        "label": "Kling 3.0",
    },
]

# family 短名 → 规格
FIREFLY_VIDEO_FAMILIES: dict[str, dict[str, Any]] = {
    spec["family"]: spec for spec in _VIDEO_FAMILY_SPECS
}

# 完整 model id → 解析结果缓存（启动时注册）
FIREFLY_VIDEO_MODEL_CATALOG: dict[str, dict[str, Any]] = {}


def _default_full_id_for_spec(spec: dict[str, Any]) -> str:
    """族规格 → 默认完整 id：最短 duration + 16x9 + 族默认 resolution。"""
    duration = int(spec["durations"][0])
    ratios = list(spec["ratios"])
    ratio_sfx = "16x9" if "16x9" in ratios else ratios[0]
    resolution = str(spec["resolutions"][0])
    if spec.get("resolution_in_id"):
        return f"{spec['prefix']}-{duration}s-{ratio_sfx}-{resolution}"
    return f"{spec['prefix']}-{duration}s-{ratio_sfx}"


# 族级 id（firefly-sora2 / sora2）→ 默认完整 id
# 对齐图像 resolve 的族级语义，供 /v1/models 放出的族级 id 选型
FAMILY_DEFAULT_FULL_ID: dict[str, str] = {}
for _spec in _VIDEO_FAMILY_SPECS:
    _default_id = _default_full_id_for_spec(_spec)
    FAMILY_DEFAULT_FULL_ID[str(_spec["prefix"]).lower()] = _default_id
    FAMILY_DEFAULT_FULL_ID[str(_spec["family"]).lower()] = _default_id


def _register_video_catalog() -> None:
    """按族规格展开全部合法 model id。"""
    for spec in _VIDEO_FAMILY_SPECS:
        for duration in spec["durations"]:
            for ratio_sfx in spec["ratios"]:
                aspect = ratio_to_colon(ratio_sfx)
                for resolution in spec["resolutions"]:
                    if spec["resolution_in_id"]:
                        model_id = (
                            f"{spec['prefix']}-{int(duration)}s-"
                            f"{ratio_sfx}-{resolution}"
                        )
                    else:
                        model_id = f"{spec['prefix']}-{int(duration)}s-{ratio_sfx}"
                    pixels = video_size(resolution, aspect)
                    if pixels is None:
                        continue
                    width, height = pixels
                    entry: dict[str, Any] = {
                        "family": spec["family"],
                        "engine": spec["engine"],
                        "duration": int(duration),
                        "ratio": ratio_sfx,
                        "aspect_ratio": aspect,
                        "resolution": resolution,
                        "width": int(width),
                        "height": int(height),
                        # Adobe 字段名：video payloads 直接读 modelVersion/upstreamModel
                        "modelId": spec["modelId"],
                        "modelVersion": spec["modelVersion"],
                        "upstreamModel": spec["upstreamModel"],
                        "generate_audio": bool(spec.get("generate_audio")),
                        "full_id": model_id,
                        "description": (
                            f"{spec['label']} "
                            f"({int(duration)}s {aspect} {resolution})"
                        ),
                        "max_input_images": max_input_images(spec["family"]),
                    }
                    if spec.get("reference_mode"):
                        entry["reference_mode"] = spec["reference_mode"]
                    FIREFLY_VIDEO_MODEL_CATALOG[model_id] = entry


def video_size(
    resolution: str,
    aspect_ratio: str,
) -> tuple[int, int] | None:
    """分辨率 + 比例 → (width, height)；未知返回 None。"""
    res = str(resolution or "720p").strip().lower()
    ratio = str(aspect_ratio or "").strip().lower().replace("×", "x")
    table = VIDEO_SIZE_MAP.get(res)
    if not table:
        return None
    # 同时接受 "16:9" / "16x9"
    if ratio in table:
        return table[ratio]
    colon = ratio_to_colon(ratio)
    if colon in table:
        return table[colon]
    suffix = ratio_to_suffix(ratio)
    if suffix in table:
        return table[suffix]
    return None


def max_input_images(family: str) -> int:
    """各视频模型族最大输入图数量。

    veo-ref=3；veo/kling=2；sora=1。
    """
    fam = str(family or "").strip().lower()
    if fam == "veo31-ref":
        return 3
    if fam in {"veo31", "veo31-fast", "kling-o3", "kling3"}:
        return 2
    # sora2 / sora2-pro / 未知
    return 1


def list_firefly_video_families() -> list[str]:
    """族级 id 列表（按注册顺序）。"""
    return [spec["family"] for spec in _VIDEO_FAMILY_SPECS]


def list_firefly_video_model_ids() -> list[str]:
    """全部完整视频 model id。"""
    return list(FIREFLY_VIDEO_MODEL_CATALOG.keys())


def is_firefly_video_model_id(model_id: str | None) -> bool:
    """是否为已注册的视频 model id。"""
    return resolve_firefly_video_model(model_id) is not None


def resolve_firefly_video_model(
    model_id: str | None,
    size: str | None = None,
) -> dict[str, Any] | None:
    """解析完整或族级视频 model id → 模型信息；未知返回 None。

    返回字段（生产单套，无测试别名）：
      family, engine, duration, ratio, aspect_ratio, resolution,
      width, height, modelId, modelVersion, upstreamModel,
      generate_audio, full_id, description, max_input_images
      （可选 reference_mode）

    说明：modelId/modelVersion/upstreamModel 保留 Adobe camelCase，
    因 video payloads 直接读取；其余语义字段 snake_case。

    族级 id（如 firefly-sora2 / sora2）先映射到该族默认完整 id
    （最短 duration + 16x9 + 族默认 resolution），再走完整 id 逻辑；
    对齐图像 resolve_firefly_image_model 的族级语义。

    size 可选：形如 "1280x720" / "720p"，仅在完整 id 已命中时
    用于覆盖分辨率（veo 系列）；非法则忽略。
    """
    raw = str(model_id or "").strip().lower()
    if not raw:
        return None

    # 族级 id → 默认完整 id（/v1/models 放出的是族级）
    if raw not in FIREFLY_VIDEO_MODEL_CATALOG:
        mapped = FAMILY_DEFAULT_FULL_ID.get(raw)
        if mapped is None:
            return None
        raw = mapped

    entry = FIREFLY_VIDEO_MODEL_CATALOG.get(raw)
    if entry is None:
        return None

    result = dict(entry)

    # size 覆盖：仅 resolution_in_id 族（veo）有意义；固定分辨率族忽略
    fam_spec = FIREFLY_VIDEO_FAMILIES.get(result["family"])
    if size and fam_spec and fam_spec.get("resolution_in_id"):
        res_override = _infer_resolution_from_size(size, result["aspect_ratio"])
        if res_override and res_override in fam_spec["resolutions"]:
            pixels = video_size(res_override, result["aspect_ratio"])
            if pixels is not None:
                result["resolution"] = res_override
                result["width"] = int(pixels[0])
                result["height"] = int(pixels[1])
                # full_id 同步
                result["full_id"] = (
                    f"{fam_spec['prefix']}-{int(result['duration'])}s-"
                    f"{result['ratio']}-{res_override}"
                )

    return result


def _infer_resolution_from_size(
    size: str,
    aspect_ratio: str,
) -> str | None:
    """从 size 参数推断 720p/1080p。"""
    text = str(size or "").strip().lower().replace("×", "x")
    if text in _VIDEO_RESOLUTIONS:
        return text
    if "x" in text:
        try:
            w_s, h_s = text.split("x", 1)
            w_i, h_i = int(w_s), int(h_s)
        except (TypeError, ValueError):
            return None
        for res in _VIDEO_RESOLUTIONS:
            pixels = video_size(res, aspect_ratio)
            if pixels and pixels[0] == w_i and pixels[1] == h_i:
                return res
        # 按长边粗判
        long_edge = max(w_i, h_i)
        if long_edge >= 1600:
            return "1080p"
        if long_edge >= 600:
            return "720p"
    return None


def center_crop_to_resolution(
    image_bytes: bytes,
    target_res: str,
    ratio: str,
) -> bytes:
    """Pillow 等比放大后中心裁切到目标 720p/1080p 像素，输出 RGB PNG。

    对齐 adobe2api `_prepare_video_source_image`：
    先 cover 缩放再居中裁切，统一 PNG。

    Raises:
        ValueError: 空图 / 非法分辨率比例 / Pillow 不可用 / 解码失败
    """
    if not image_bytes:
        raise ValueError("image is empty")
    if Image is None:
        raise ValueError("Pillow is required for video image preprocessing")

    aspect = ratio_to_colon(ratio)
    res = str(target_res or "720p").strip().lower()
    pixels = video_size(res, aspect)
    if pixels is None:
        raise ValueError(f"unsupported video size: {res} {aspect}")
    target_w, target_h = int(pixels[0]), int(pixels[1])

    try:
        with Image.open(io.BytesIO(image_bytes)) as src:
            src = src.convert("RGB")
            src_ratio = src.width / max(1, src.height)
            tgt_ratio = target_w / max(1, target_h)

            if src_ratio > tgt_ratio:
                new_h = target_h
                new_w = int(new_h * src_ratio)
            else:
                new_w = target_w
                new_h = int(new_w / max(src_ratio, 1e-6))

            resized = src.resize((new_w, new_h), Image.Resampling.LANCZOS)
            left = max(0, (new_w - target_w) // 2)
            top = max(0, (new_h - target_h) // 2)
            cropped = resized.crop((left, top, left + target_w, top + target_h))

            out = io.BytesIO()
            cropped.save(out, format="PNG")
            return out.getvalue()
    except ValueError:
        raise
    except Exception as exc:
        raise ValueError(f"invalid image for video: {exc}") from exc


# 模块加载时注册目录
_register_video_catalog()
