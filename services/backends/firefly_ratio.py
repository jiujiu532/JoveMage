"""Firefly 图像/视频共用比例字符串转换。

payload 用 "16:9"，完整 model id 后缀用 "16x9"。
"""

from __future__ import annotations

# 超集：图像目录全量 + 视频子集（16:9 / 9:16）
_RATIO_COLON_TO_X: dict[str, str] = {
    "1:1": "1x1",
    "1:8": "1x8",
    "1:4": "1x4",
    "5:4": "5x4",
    "9:16": "9x16",
    "21:9": "21x9",
    "4:1": "4x1",
    "16:9": "16x9",
    "4:3": "4x3",
    "3:2": "3x2",
    "4:5": "4x5",
    "3:4": "3x4",
    "8:1": "8x1",
    "2:3": "2x3",
}
_RATIO_X_TO_COLON: dict[str, str] = {v: k for k, v in _RATIO_COLON_TO_X.items()}


def ratio_to_colon(ratio: str) -> str:
    """'16x9' / '16:9' → '16:9'。"""
    text = str(ratio or "").strip().lower().replace("×", "x")
    if ":" in text:
        return text
    return _RATIO_X_TO_COLON.get(text, text.replace("x", ":") if text else "16:9")


def ratio_to_suffix(ratio: str) -> str:
    """'16:9' / '16x9' → '16x9'。"""
    text = str(ratio or "").strip().lower().replace("×", "x")
    if "x" in text and ":" not in text:
        return text
    return _RATIO_COLON_TO_X.get(text, text.replace(":", "x") if text else "16x9")
