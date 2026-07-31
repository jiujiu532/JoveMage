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
