"""Firefly 测试公共辅助：多名称 fallback / mapping 访问 / HTTP patch / JWT。

仅供 test_firefly_*.py 使用，不进生产路径。
"""
from __future__ import annotations

import base64
import json
from typing import Any, Callable
from unittest import mock

# 图像 + 视频 catalog conf 可能出现的字段（hasattr 回退用）
_CONF_KEYS: tuple[str, ...] = (
    "family",
    "engine",
    "duration",
    "ratio",
    "aspect_ratio",
    "aspectRatio",
    "resolution",
    "output_resolution",
    "outputResolution",
    "width",
    "height",
    "size",
    "max_input_images",
    "maxInputImages",
    "reference_mode",
    "referenceMode",
    "generate_audio",
    "generateAudio",
    "full_id",
    "fullId",
    "model_id",
    "modelId",
    "modelVersion",
    "upstream_model",
    "upstreamModel",
    "upstream_model_id",
    "upstreamModelId",
    "upstream_model_version",
    "upstreamModelVersion",
    "description",
)


def first_callable(
    mod: object,
    *names: str,
    required: bool = True,
) -> Callable[..., Any] | None:
    """多名称 getattr fallback；都找不到时默认 AssertionError。

    required=False 时返回 None（可选符号探测）。
    """
    for name in names:
        fn = getattr(mod, name, None)
        if callable(fn):
            return fn
    if required:
        mod_name = getattr(mod, "__name__", repr(mod))
        raise AssertionError(f"missing callable among {names!r} on {mod_name}")
    return None


def as_mapping(conf: object) -> dict:
    """把 dict / dataclass / SimpleNamespace 统一成可下标访问的 mapping。"""
    if conf is None:
        raise AssertionError("expected model conf, got None")
    if isinstance(conf, dict):
        return conf
    if hasattr(conf, "__dict__"):
        return dict(vars(conf))
    data: dict = {}
    for key in _CONF_KEYS:
        if hasattr(conf, key):
            data[key] = getattr(conf, key)
    if not data:
        raise AssertionError(f"unsupported conf type: {type(conf)!r}")
    return data


def get_field(conf: object, *keys: str, default: object = None) -> object:
    """从 conf 取字段，兼容 snake/camel 多 key；size 子 dict / 二元组回退。"""
    data = as_mapping(conf)
    for key in keys:
        if key in data and data[key] is not None:
            return data[key]
    size = data.get("size")
    if isinstance(size, dict):
        for key in keys:
            if key in size and size[key] is not None:
                return size[key]
    if isinstance(size, (list, tuple)) and len(size) >= 2:
        if "width" in keys:
            return size[0]
        if "height" in keys:
            return size[1]
    return default


def first_payload_candidate(result: object) -> dict:
    """兼容返回 list[dict] 或单 dict。"""
    if isinstance(result, list):
        if not result:
            raise AssertionError("expected at least one payload candidate")
        first = result[0]
    else:
        first = result
    if not isinstance(first, dict):
        raise AssertionError(f"payload candidate must be dict, got {type(first)!r}")
    return first


def patch_firefly_http(
    *targets: str,
    side_effect: object = None,
    return_value: object = None,
) -> list:
    """对多个 HTTP 入口路径做 mock.patch.start()，跳过不存在的 target。

    返回已 start 的 patch 列表；调用方负责 stop。
    """
    patch_kwargs: dict = {}
    if side_effect is not None:
        patch_kwargs["side_effect"] = side_effect
    if return_value is not None:
        patch_kwargs["return_value"] = return_value

    active: list = []
    for target in targets:
        try:
            p = mock.patch(target, **patch_kwargs)
            p.start()
            active.append(p)
        except (AttributeError, ModuleNotFoundError, ImportError):
            continue
    return active


def stop_patches(patches: list) -> None:
    """逆序 stop 一组 mock.patch。"""
    for p in reversed(list(patches)):
        try:
            p.stop()
        except RuntimeError:
            pass


def b64url(data: bytes) -> str:
    """URL-safe base64，去 padding。"""
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def make_jwt(claims: dict) -> str:
    """构造无签名校验的 mock JWT（header.payload.sig）。"""
    header = b64url(json.dumps({"alg": "none", "typ": "JWT"}).encode("utf-8"))
    payload = b64url(json.dumps(claims, separators=(",", ":")).encode("utf-8"))
    return f"{header}.{payload}.sig"


# 兼容设计文档里的下划线命名
_b64url = b64url
_make_jwt = make_jwt


def loose_model_info(
    *,
    aspect_ratio: str = "16:9",
    output_resolution: str = "2K",
    upstream_model_id: str = "",
    upstream_model_version: str = "",
) -> dict[str, Any]:
    """测试用：散参数 → 对齐 resolve 生产键的 model_info。

    生产已删除 _model_info_from_loose_params / candidates 壳；
    测试通过本 helper + build_text2image_payload / build_image2image_payload。
    """
    from services.backends.firefly_catalog import (
        SIZE_TABLE_GPT,
        SIZE_TABLE_NANO,
        ratio_to_suffix,
    )

    model_id = upstream_model_id or "gemini-flash"
    model_version = upstream_model_version or "nano-banana-2"
    is_gpt = model_id.lower() == "gpt-image"
    table = SIZE_TABLE_GPT if is_gpt else SIZE_TABLE_NANO
    res = str(output_resolution or "2k").strip().lower()
    res = res if res in {"1k", "2k", "4k"} else "2k"
    ratio_sfx = ratio_to_suffix(aspect_ratio)
    pixels = table.get((res, ratio_sfx)) or table.get(("2k", "16x9")) or (2752, 1536)

    return {
        "modelId": model_id,
        "modelVersion": model_version,
        "width": int(pixels[0]),
        "height": int(pixels[1]),
        "pixel_table": "gpt" if is_gpt else "nano",
        "output_resolution": res.upper(),
        "aspect_ratio": str(aspect_ratio or "").replace("x", ":"),
        "ratio": ratio_sfx,
        "resolution": res,
    }


# 设计文档 / 旧测试命名
_loose_model_info = loose_model_info


def build_image_payload_from_loose(
    *,
    prompt: str,
    aspect_ratio: str = "16:9",
    output_resolution: str = "2K",
    upstream_model_id: str = "",
    upstream_model_version: str = "",
    quality_level: str = "medium",
    seeds: list[int] | None = None,
    n: int = 1,
) -> dict[str, Any]:
    """测试用：散参数 → 文生图 payload（单 dict，非 list candidates）。"""
    from services.backends.firefly_payloads import build_text2image_payload

    model_info = loose_model_info(
        aspect_ratio=aspect_ratio,
        output_resolution=output_resolution,
        upstream_model_id=upstream_model_id,
        upstream_model_version=upstream_model_version,
    )
    return build_text2image_payload(
        model_info, prompt, n=n, quality=quality_level, seeds=seeds
    )


def build_image2image_payload_from_loose(
    *,
    prompt: str,
    aspect_ratio: str = "16:9",
    output_resolution: str = "2K",
    upstream_model_id: str = "",
    upstream_model_version: str = "",
    reference_image_ids: list[str] | None = None,
    quality_level: str = "medium",
    seeds: list[int] | None = None,
    n: int = 1,
) -> dict[str, Any]:
    """测试用：散参数 → 图生图 payload（单 dict）。"""
    from services.backends.firefly_payloads import build_image2image_payload

    model_info = loose_model_info(
        aspect_ratio=aspect_ratio,
        output_resolution=output_resolution,
        upstream_model_id=upstream_model_id,
        upstream_model_version=upstream_model_version,
    )
    return build_image2image_payload(
        model_info,
        prompt,
        list(reference_image_ids or []),
        n=n,
        quality=quality_level,
        seeds=seeds,
    )
