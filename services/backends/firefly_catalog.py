"""Adobe Firefly 图像模型目录（纯数据 + 解析）。

数据移植自：
- 参考/GPT2Image-Pro-main/.../firefly-direct/catalog.ts
- 参考/GPT2Image-Pro-main/.../firefly-direct/payloads.ts 像素表
- 参考/adobe2api-master/core/models/{catalog,payloads,resolver}.py

对外 /v1/models 只暴露族级 id；分辨率/比例由请求 size 或完整 id 再解析，
避免 5×3×N 组合爆炸。
"""

from __future__ import annotations

from typing import Any

from services.backends.firefly_ratio import ratio_to_colon, ratio_to_suffix

# 通用 / gpt / nano-banana2 支持的比例（id 后缀形式）
_COMMON_RATIOS = ("1x1", "16x9", "9x16", "4x3", "3x4")
_GPT_RATIOS = (
    "1x1",
    "5x4",
    "9x16",
    "21x9",
    "16x9",
    "3x2",
    "4x3",
    "4x5",
    "3x4",
    "2x3",
)
_NANO2_EXTRA = ("1x8", "1x4", "4x1", "8x1")
_NANO2_RATIOS = _COMMON_RATIOS + _NANO2_EXTRA

_RESOLUTIONS = ("1k", "2k", "4k")

DEFAULT_MODEL = "firefly-nano-banana-pro"
DEFAULT_RESOLUTION = "2k"
DEFAULT_RATIO = "16x9"
# 兼容完整默认 id（参考项目 DEFAULT_MODEL_ID）
DEFAULT_FULL_MODEL_ID = f"{DEFAULT_MODEL}-{DEFAULT_RESOLUTION}-{DEFAULT_RATIO}"


# ---------------------------------------------------------------------------
# 族级目录
# ---------------------------------------------------------------------------

FIREFLY_IMAGE_FAMILIES: dict[str, dict[str, Any]] = {
    "firefly-gpt-image-2": {
        "upstreamModel": "openai:firefly:gpt-image",
        "modelId": "gpt-image",
        "modelVersion": "2",
        "resolutions": list(_RESOLUTIONS),
        "ratios": list(_GPT_RATIOS),
        "description": "Firefly GPT Image 2",
        "pixel_table": "gpt",
    },
    "firefly-gpt-image-1.5": {
        "upstreamModel": "openai:firefly:gpt-image",
        "modelId": "gpt-image",
        "modelVersion": "1.5",
        "resolutions": list(_RESOLUTIONS),
        "ratios": list(_GPT_RATIOS),
        "description": "Firefly GPT Image 1.5",
        "pixel_table": "gpt",
    },
    "firefly-nano-banana-pro": {
        "upstreamModel": "google:firefly:colligo:nano-banana-pro",
        "modelId": "gemini-flash",
        "modelVersion": "nano-banana-2",
        "resolutions": list(_RESOLUTIONS),
        "ratios": list(_COMMON_RATIOS),
        "description": "Firefly Nano Banana Pro",
        "pixel_table": "nano",
    },
    "firefly-nano-banana": {
        "upstreamModel": "google:firefly:colligo:nano-banana-pro",
        "modelId": "gemini-flash",
        "modelVersion": "nano-banana-2",
        "resolutions": list(_RESOLUTIONS),
        "ratios": list(_COMMON_RATIOS),
        "description": "Firefly Nano Banana",
        "pixel_table": "nano",
    },
    "firefly-nano-banana2": {
        "upstreamModel": "google:firefly:colligo:nano-banana-pro",
        "modelId": "gemini-flash",
        "modelVersion": "nano-banana-3",
        "resolutions": list(_RESOLUTIONS),
        "ratios": list(_NANO2_RATIOS),
        "description": "Firefly Nano Banana 2",
        "pixel_table": "nano",
    },
}

# 展示顺序即 /v1/models 顺序
_FAMILY_ORDER: tuple[str, ...] = (
    "firefly-gpt-image-2",
    "firefly-gpt-image-1.5",
    "firefly-nano-banana-pro",
    "firefly-nano-banana",
    "firefly-nano-banana2",
)

# ---------------------------------------------------------------------------
# 像素表：(resolution, ratio_suffix) → (width, height)
# 移植自 payloads.ts ratioMap* / gptRatioMap*
# ---------------------------------------------------------------------------

SIZE_TABLE_NANO: dict[tuple[str, str], tuple[int, int]] = {
    # 1K
    ("1k", "1x1"): (1024, 1024),
    ("1k", "1x8"): (384, 3072),
    ("1k", "1x4"): (512, 2048),
    ("1k", "16x9"): (1360, 768),
    ("1k", "9x16"): (768, 1360),
    ("1k", "4x1"): (2048, 512),
    ("1k", "4x3"): (1152, 864),
    ("1k", "3x4"): (864, 1152),
    ("1k", "8x1"): (3072, 384),
    # 2K
    ("2k", "1x1"): (2048, 2048),
    ("2k", "1x8"): (768, 6144),
    ("2k", "1x4"): (1024, 4096),
    ("2k", "16x9"): (2752, 1536),
    ("2k", "9x16"): (1536, 2752),
    ("2k", "4x1"): (4096, 1024),
    ("2k", "4x3"): (2048, 1536),
    ("2k", "3x4"): (1536, 2048),
    ("2k", "8x1"): (6144, 768),
    # 4K
    ("4k", "1x1"): (4096, 4096),
    ("4k", "1x8"): (1536, 12288),
    ("4k", "1x4"): (2048, 8192),
    ("4k", "16x9"): (5504, 3072),
    ("4k", "9x16"): (3072, 5504),
    ("4k", "4x1"): (8192, 2048),
    ("4k", "4x3"): (4096, 3072),
    ("4k", "3x4"): (3072, 4096),
    ("4k", "8x1"): (12288, 1536),
}

SIZE_TABLE_GPT: dict[tuple[str, str], tuple[int, int]] = {
    # 1K
    ("1k", "1x1"): (1024, 1024),
    ("1k", "5x4"): (1120, 896),
    ("1k", "9x16"): (720, 1280),
    ("1k", "21x9"): (1456, 624),
    ("1k", "16x9"): (1280, 720),
    ("1k", "4x3"): (1152, 864),
    ("1k", "3x2"): (1248, 832),
    ("1k", "4x5"): (896, 1120),
    ("1k", "3x4"): (864, 1152),
    ("1k", "2x3"): (832, 1248),
    # 2K
    ("2k", "1x1"): (2048, 2048),
    ("2k", "5x4"): (2240, 1792),
    ("2k", "9x16"): (1440, 2560),
    ("2k", "21x9"): (3024, 1296),
    ("2k", "16x9"): (2560, 1440),
    ("2k", "4x3"): (2304, 1728),
    ("2k", "3x2"): (2496, 1664),
    ("2k", "4x5"): (1792, 2240),
    ("2k", "3x4"): (1728, 2304),
    ("2k", "2x3"): (1664, 2496),
    # 4K（gpt 4K 并非严格 4 倍，沿用 Adobe 像素表）
    ("4k", "1x1"): (2880, 2880),
    ("4k", "5x4"): (3200, 2560),
    ("4k", "9x16"): (2160, 3840),
    ("4k", "21x9"): (3696, 1584),
    ("4k", "16x9"): (3840, 2160),
    ("4k", "4x3"): (3264, 2448),
    ("4k", "3x2"): (3504, 2336),
    ("4k", "4x5"): (2560, 3200),
    ("4k", "3x4"): (2448, 3264),
    ("4k", "2x3"): (2336, 3504),
}


def _lookup_pixels(
    table: dict[tuple[str, str], tuple[int, int]],
    resolution: str,
    ratio_suffix: str,
) -> tuple[int, int] | None:
    key = (resolution.lower(), ratio_to_suffix(ratio_suffix))
    return table.get(key)


def size_from_ratio(ratio: str, output_resolution: str = "2k") -> dict[str, int]:
    """nano 族：ratio + 分辨率 → {width, height}；未知回退 16:9 2k。"""
    res = (output_resolution or "2k").lower()
    if res not in _RESOLUTIONS:
        res = "2k"
    suffix = ratio_to_suffix(ratio)
    pixels = _lookup_pixels(SIZE_TABLE_NANO, res, suffix)
    if pixels is None:
        pixels = SIZE_TABLE_NANO.get((res, "16x9")) or (2752, 1536)
    return {"width": int(pixels[0]), "height": int(pixels[1])}


def gpt_image_pixels_from_ratio(
    ratio: str, output_resolution: str = "2k"
) -> dict[str, int] | None:
    """gpt-image 族像素；不支持的比例返回 None。"""
    res = (output_resolution or "2k").lower()
    if res not in _RESOLUTIONS:
        res = "2k"
    pixels = _lookup_pixels(SIZE_TABLE_GPT, res, ratio_to_suffix(ratio))
    if pixels is None:
        return None
    return {"width": int(pixels[0]), "height": int(pixels[1])}


# WxH → 粗映射比例（以 direct catalog.ratioFromSize 为准）
_SIZE_TO_RATIO: dict[str, str] = {
    "1024x1024": "1x1",
    "1536x1536": "1x1",
    "2048x2048": "1x1",
    "1024x1792": "9x16",
    "1536x2752": "9x16",
    "1792x1024": "16x9",
    "2752x1536": "16x9",
    "2048x1536": "4x3",
    "1536x2048": "3x4",
    # gpt 常见
    "1280x720": "16x9",
    "720x1280": "9x16",
    "2560x1440": "16x9",
    "1440x2560": "9x16",
}


def ratio_from_size(w: int | str | None, h: int | None = None) -> str:
    """宽高粗映射为比例后缀（如 '16x9'）；未知回退 '1x1'。

    支持 ratio_from_size(1024, 1024) 或 ratio_from_size("1024x1024")。
    """
    if h is None and isinstance(w, str):
        key = str(w or "").strip().lower().replace("×", "x")
        if key in _SIZE_TO_RATIO:
            return _SIZE_TO_RATIO[key]
        # 尝试解析 "WxH"
        if "x" in key:
            parts = key.split("x", 1)
            try:
                w_i, h_i = int(parts[0]), int(parts[1])
            except (TypeError, ValueError):
                return "1x1"
        else:
            return "1x1"
    else:
        try:
            w_i, h_i = int(w or 0), int(h or 0)
        except (TypeError, ValueError):
            return "1x1"
        key = f"{w_i}x{h_i}"
        if key in _SIZE_TO_RATIO:
            return _SIZE_TO_RATIO[key]

    if w_i <= 0 or h_i <= 0:
        return "1x1"
    # 最近邻粗判
    aspect = w_i / h_i
    candidates = [
        ("1x1", 1.0),
        ("16x9", 16 / 9),
        ("9x16", 9 / 16),
        ("4x3", 4 / 3),
        ("3x4", 3 / 4),
        ("3x2", 3 / 2),
        ("2x3", 2 / 3),
        ("5x4", 5 / 4),
        ("4x5", 4 / 5),
        ("21x9", 21 / 9),
    ]
    best = min(candidates, key=lambda item: abs(item[1] - aspect))
    return best[0]


def list_firefly_image_families() -> list[str]:
    """族级 id 列表（给 /v1/models）。"""
    return list(_FAMILY_ORDER)


def _parse_full_model_id(model_id: str) -> tuple[str, str, str] | None:
    """完整 id → (family, resolution, ratio_suffix)；失败 None。

    形态：firefly-<family>-<1k|2k|4k>-<ratio>
    注意 family 本身可含连字符与点号（gpt-image-1.5）。
    """
    text = str(model_id or "").strip().lower()
    if not text:
        return None
    # 先按最长 family 前缀匹配，避免歧义
    for family in sorted(FIREFLY_IMAGE_FAMILIES.keys(), key=len, reverse=True):
        prefix = family.lower() + "-"
        if not text.startswith(prefix):
            continue
        rest = text[len(prefix) :]
        # rest = "2k-16x9"
        parts = rest.split("-", 1)
        if len(parts) != 2:
            continue
        res, ratio = parts[0].strip(), parts[1].strip()
        if res not in _RESOLUTIONS:
            continue
        fam_conf = FIREFLY_IMAGE_FAMILIES[family]
        if ratio not in fam_conf["ratios"]:
            continue
        return family, res, ratio
    return None


def _infer_res_ratio_from_size(
    size: str | None,
    family: str,
) -> tuple[str, str]:
    """从 size 参数推断 resolution + ratio；失败用默认。"""
    fam = FIREFLY_IMAGE_FAMILIES[family]
    table = SIZE_TABLE_GPT if fam["pixel_table"] == "gpt" else SIZE_TABLE_NANO
    text = str(size or "").strip().lower().replace("×", "x")

    # 纯分辨率关键词
    if text in _RESOLUTIONS:
        return text, DEFAULT_RATIO if DEFAULT_RATIO in fam["ratios"] else fam["ratios"][0]
    if text in ("1k", "2k", "4k", "hd", "ultra"):
        mapped = {"hd": "2k", "ultra": "4k"}.get(text, text)
        if mapped in _RESOLUTIONS:
            ratio = DEFAULT_RATIO if DEFAULT_RATIO in fam["ratios"] else fam["ratios"][0]
            return mapped, ratio

    # WxH 精确反查像素表
    if "x" in text:
        try:
            w_s, h_s = text.split("x", 1)
            w_i, h_i = int(w_s), int(h_s)
        except (TypeError, ValueError):
            w_i = h_i = 0
        if w_i > 0 and h_i > 0:
            for (res, ratio), (pw, ph) in table.items():
                if pw == w_i and ph == h_i and ratio in fam["ratios"]:
                    return res, ratio
            # 粗映射比例 + 按长边估分辨率
            ratio = ratio_from_size(w_i, h_i)
            if ratio not in fam["ratios"]:
                ratio = DEFAULT_RATIO if DEFAULT_RATIO in fam["ratios"] else fam["ratios"][0]
            long_edge = max(w_i, h_i)
            if long_edge >= 3000:
                res = "4k"
            elif long_edge >= 1600:
                res = "2k"
            else:
                res = "1k"
            return res, ratio

    return DEFAULT_RESOLUTION, (
        DEFAULT_RATIO if DEFAULT_RATIO in fam["ratios"] else fam["ratios"][0]
    )


def resolve_firefly_image_model(
    model_id: str | None = None,
    size: str | None = None,
) -> dict[str, Any] | None:
    """解析完整 id 或族级 id(+size) → 模型信息 dict；未知返回 None。

    返回字段：
      family, resolution, ratio, width, height,
      modelId, modelVersion, upstreamModel, full_id, aspect_ratio
    """
    raw = str(model_id or "").strip()
    if not raw:
        family = DEFAULT_MODEL
        resolution = DEFAULT_RESOLUTION
        ratio = DEFAULT_RATIO
    else:
        # 完整 id
        parsed = _parse_full_model_id(raw)
        if parsed is not None:
            family, resolution, ratio = parsed
            # size 若给出，可覆盖分辨率/比例（族级语义）
            if size:
                resolution, ratio = _infer_res_ratio_from_size(size, family)
        elif raw.lower() in FIREFLY_IMAGE_FAMILIES:
            family = raw.lower() if raw.lower() in FIREFLY_IMAGE_FAMILIES else raw
            # 保持原始 key 大小写敏感的官方 key
            for key in FIREFLY_IMAGE_FAMILIES:
                if key.lower() == raw.lower():
                    family = key
                    break
            resolution, ratio = _infer_res_ratio_from_size(size, family)
        else:
            return None

    fam = FIREFLY_IMAGE_FAMILIES.get(family)
    if fam is None:
        return None

    resolution = (resolution or DEFAULT_RESOLUTION).lower()
    ratio = ratio_to_suffix(ratio or DEFAULT_RATIO)
    if resolution not in fam["resolutions"]:
        resolution = DEFAULT_RESOLUTION
    if ratio not in fam["ratios"]:
        ratio = DEFAULT_RATIO if DEFAULT_RATIO in fam["ratios"] else fam["ratios"][0]

    table = SIZE_TABLE_GPT if fam["pixel_table"] == "gpt" else SIZE_TABLE_NANO
    pixels = _lookup_pixels(table, resolution, ratio)
    if pixels is None:
        # gpt 不支持该比例
        if fam["pixel_table"] == "gpt":
            return None
        pixels = SIZE_TABLE_NANO.get((resolution, "16x9")) or (2752, 1536)

    width, height = int(pixels[0]), int(pixels[1])
    aspect = ratio_to_colon(ratio)
    full_id = f"{family}-{resolution}-{ratio}"

    return {
        "family": family,
        "resolution": resolution,
        "ratio": ratio,
        "aspect_ratio": aspect,
        "width": width,
        "height": height,
        "modelId": fam["modelId"],
        "modelVersion": fam["modelVersion"],
        "upstreamModel": fam["upstreamModel"],
        # 测试兼容别名（snake_case）
        "upstream_model_id": fam["modelId"],
        "upstream_model_version": fam["modelVersion"],
        "upstreamModelId": fam["modelId"],
        "upstreamModelVersion": fam["modelVersion"],
        "full_id": full_id,
        "pixel_table": fam["pixel_table"],
        "output_resolution": resolution.upper(),
        "outputResolution": resolution.upper(),
        "description": f"{fam['description']} ({resolution.upper()} {aspect})",
    }
