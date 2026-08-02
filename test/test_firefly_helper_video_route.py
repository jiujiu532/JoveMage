from __future__ import annotations

import os
import unittest

os.environ.setdefault("CHATGPT2API_AUTH_KEY", "test-auth")

from utils import helper  # noqa: E402
from test._firefly_helpers import first_callable  # noqa: E402


def _fn(*names):
    return first_callable(helper, *names)


def _is_supported_image_model(model: object) -> bool:
    return bool(
        _fn(
            "is_supported_image_model",
            "isSupportedImageModel",
            "supported_image_model",
        )(model)
    )


def _is_image_chat_request(body: dict) -> bool:
    return bool(
        _fn(
            "is_image_chat_request",
            "isImageChatRequest",
            "image_chat_request",
        )(body)
    )


def _is_firefly_video_model(model: object) -> bool:
    return bool(
        _fn(
            "is_firefly_video_model",
            "isFireflyVideoModel",
            "is_firefly_video",
        )(model)
    )


def _is_firefly_model(model: object) -> bool:
    return bool(first_callable(helper, "is_firefly_model")(model))


class HelperVideoRouteTests(unittest.TestCase):
    """B7：视频模型不得污染 chat / images 路由。"""

    def test_video_full_id_not_supported_image_model(self) -> None:
        """is_supported_image_model('firefly-sora2-4s-16x9') 为 False。"""
        self.assertFalse(
            _is_supported_image_model("firefly-sora2-4s-16x9"),
            "video full id must not be treated as image model",
        )

    def test_video_family_id_not_supported_image_model(self) -> None:
        """族级视频 id 也不进图像路由。"""
        for model in (
            "firefly-sora2",
            "firefly-veo31",
            "firefly-kling3",
            "firefly-kling-o3",
        ):
            with self.subTest(model=model):
                self.assertFalse(
                    _is_supported_image_model(model),
                    f"{model} must not be supported image model",
                )

    def test_image_family_still_supported(self) -> None:
        """is_supported_image_model('firefly-nano-banana-pro') 为 True。"""
        self.assertTrue(
            _is_supported_image_model("firefly-nano-banana-pro"),
            "image family must remain supported",
        )
        self.assertTrue(_is_supported_image_model("firefly-gpt-image-2"))
        self.assertTrue(_is_supported_image_model("firefly-nano-banana"))
        # 族名后直接接数字：不得误判为非图像
        self.assertTrue(
            _is_supported_image_model("firefly-nano-banana2"),
            "nano-banana2 must be treated as image family",
        )

    def test_image_chat_request_rejects_video_model(self) -> None:
        """is_image_chat_request 对视频模型返回 False。"""
        self.assertFalse(
            _is_image_chat_request({"model": "firefly-sora2-4s-16x9"}),
            "video model must not be image-chat request",
        )
        self.assertFalse(
            _is_image_chat_request({"model": "firefly-sora2"}),
        )
        self.assertFalse(
            _is_image_chat_request(
                {"model": "firefly-veo31-8s-9x16-1080p", "modalities": ["image"]}
            ),
            "even with modalities=image, video model must not be image-chat",
        )

    def test_image_chat_request_keeps_image_family(self) -> None:
        """图像族仍算聊天生图。"""
        self.assertTrue(
            _is_image_chat_request({"model": "firefly-nano-banana-pro"}),
        )
        self.assertTrue(
            _is_image_chat_request({"model": "firefly-gpt-image-2-2k-1x1"}),
        )

    def test_is_firefly_video_model_image_family_false(self) -> None:
        """is_firefly_video_model 对图像族返回 False。"""
        for model in (
            "firefly-nano-banana-pro",
            "firefly-nano-banana",
            "firefly-nano-banana2",
            "firefly-gpt-image-2",
            "firefly-gpt-image-1.5",
        ):
            with self.subTest(model=model):
                self.assertFalse(
                    _is_firefly_video_model(model),
                    f"image family {model} must not be video model",
                )

    def test_is_firefly_video_model_video_true(self) -> None:
        """视频族 / 完整 id 识别为视频。"""
        for model in (
            "firefly-sora2",
            "firefly-sora2-4s-16x9",
            "firefly-veo31-8s-9x16-1080p",
            "firefly-kling3-10s-16x9",
            "firefly-kling-o3-15s-9x16",
        ):
            with self.subTest(model=model):
                self.assertTrue(
                    _is_firefly_video_model(model),
                    f"{model} must be firefly video model",
                )
                # 仍是 firefly 渠道
                self.assertTrue(_is_firefly_model(model))


if __name__ == "__main__":
    unittest.main()
