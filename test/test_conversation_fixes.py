"""B6/B7/B10/B23 协议成功语义回归：部分失败、message 当错误、session close、历史复述。"""
from __future__ import annotations

import json
import os
import unittest
from unittest import mock

os.environ.setdefault("CHATGPT2API_AUTH_KEY", "test-auth")

from services.protocol.conversation import (
    ConversationRequest,
    ImageGenerationError,
    ImageOutput,
    collect_text,
    iter_conversation_payloads,
    stream_image_outputs_with_pool,
    stream_text_deltas,
    text_backend,
)
from services.protocol import openai_v1_chat_complete, openai_v1_response


def _assistant_message_payload(text: str) -> str:
    return json.dumps(
        {
            "message": {
                "author": {"role": "assistant"},
                "content": {"content_type": "text", "parts": [text]},
            }
        },
        ensure_ascii=False,
    )


class B6PartialImageFailureTests(unittest.TestCase):
    def test_parallel_partial_failure_raises(self):
        request = ConversationRequest(model="gpt-image-1", prompt="cats", n=2)

        def fake_generate(req, index, total):
            if index == 1:
                return [
                    ImageOutput(
                        kind="result",
                        model=req.model,
                        index=index,
                        total=total,
                        data=[{"b64_json": "eA=="}],
                    )
                ]
            raise RuntimeError(f"upstream failed at index {index}")

        with mock.patch(
            "services.protocol.conversation.is_supported_image_model",
            return_value=True,
        ), mock.patch(
            "services.protocol.conversation.config",
            mock.Mock(image_parallel_generation=True),
        ), mock.patch(
            "services.protocol.conversation._generate_single_image",
            side_effect=fake_generate,
        ):
            with self.assertRaises(ImageGenerationError) as ctx:
                list(stream_image_outputs_with_pool(request))

        err = ctx.exception
        self.assertEqual(getattr(err, "code", None), "partial_image_failure")
        self.assertIn("partial image generation failure", str(err))
        self.assertIn("1/2", str(err))

    def test_parallel_all_success_no_raise(self):
        request = ConversationRequest(model="gpt-image-1", prompt="cats", n=2)

        def fake_generate(req, index, total):
            return [
                ImageOutput(
                    kind="result",
                    model=req.model,
                    index=index,
                    total=total,
                    data=[{"b64_json": f"img{index}"}],
                )
            ]

        with mock.patch(
            "services.protocol.conversation.is_supported_image_model",
            return_value=True,
        ), mock.patch(
            "services.protocol.conversation.config",
            mock.Mock(image_parallel_generation=True),
        ), mock.patch(
            "services.protocol.conversation._generate_single_image",
            side_effect=fake_generate,
        ):
            outputs = list(stream_image_outputs_with_pool(request))

        results = [o for o in outputs if o.kind == "result"]
        self.assertEqual(len(results), 2)


class B7MessageAsErrorTests(unittest.TestCase):
    def test_chat_image_request_sets_message_as_error(self):
        captured: list[ConversationRequest] = []

        def fake_pool(request: ConversationRequest):
            captured.append(request)
            if request.message_as_error:
                raise ImageGenerationError(
                    "I cannot generate that image.",
                    status_code=400,
                    error_type="invalid_request_error",
                    code="no_image_generated",
                )
            yield ImageOutput(
                kind="message",
                model=request.model,
                index=1,
                total=1,
                text="I cannot generate that image.",
            )

        body = {
            "model": "gpt-image-1",
            "messages": [{"role": "user", "content": "draw something blocked"}],
            "stream": False,
        }
        with mock.patch(
            "services.protocol.openai_v1_chat_complete.stream_image_outputs_with_pool",
            side_effect=fake_pool,
        ), mock.patch(
            "services.protocol.openai_v1_chat_complete.is_image_chat_request",
            return_value=True,
        ), mock.patch(
            "services.protocol.openai_v1_chat_complete.chat_image_args",
            return_value=("gpt-image-1", "draw something blocked", 1, [], None),
        ), mock.patch(
            "services.protocol.openai_v1_chat_complete.encode_images",
            return_value=[],
        ):
            with self.assertRaises(ImageGenerationError) as ctx:
                openai_v1_chat_complete.image_chat_response(body)

        self.assertTrue(captured and captured[0].message_as_error is True)
        self.assertIn("cannot generate", str(ctx.exception).lower())

    def test_response_image_request_sets_message_as_error(self):
        captured: list[ConversationRequest] = []

        def fake_pool(request: ConversationRequest):
            captured.append(request)
            if request.message_as_error:
                raise ImageGenerationError(
                    "policy blocked",
                    status_code=400,
                    code="content_policy_violation",
                )
            yield ImageOutput(kind="message", model=request.model, index=1, total=1, text="policy blocked")

        body = {
            "model": "gpt-image-1",
            "input": "draw blocked",
            "tools": [{"type": "image_generation"}],
            "stream": False,
        }
        with mock.patch(
            "services.protocol.openai_v1_response.stream_image_outputs_with_pool",
            side_effect=fake_pool,
        ), mock.patch(
            "services.protocol.openai_v1_response.extract_response_prompt",
            return_value="draw blocked",
        ), mock.patch(
            "services.protocol.openai_v1_response.extract_response_image",
            return_value=None,
        ), mock.patch(
            "services.protocol.openai_v1_response.is_text_response_request",
            return_value=False,
        ):
            with self.assertRaises(ImageGenerationError):
                list(openai_v1_response.response_events(body))

        self.assertTrue(captured and captured[0].message_as_error is True)

    def test_generate_single_message_as_error_raises(self):
        """底层 message_as_error=True 时 kind=message 会 raise，不当成功。"""
        from services.protocol.conversation import _generate_single_image

        request = ConversationRequest(
            model="gpt-image-1",
            prompt="blocked",
            message_as_error=True,
        )
        account = {
            "access_token": "tok-1",
            "refresh_token": "rt-1",
            "email": "a@example.com",
            "status": "正常",
            "quota": 3,
        }
        backend = mock.Mock()
        backend.proxy_profile = mock.Mock(
            image_concurrency_limit=0,
            proxy_url="",
            proxy_source="direct",
            egress_key="direct",
            egress_label="",
            proxy_group_id="",
            proxy_node_id="",
            proxy_node_name="",
        )
        backend.close = mock.Mock()
        backend.pop_http_timing = mock.Mock(return_value={})

        def stream_message(backend, request, index, total):
            yield ImageOutput(
                kind="message",
                model=request.model,
                index=index,
                total=total,
                text="I can't create that image.",
            )

        with mock.patch(
            "services.protocol.conversation.account_service.get_available_access_token",
            return_value="tok-1",
        ), mock.patch(
            "services.protocol.conversation.account_service.get_account",
            return_value=account,
        ), mock.patch(
            "services.protocol.conversation.account_service.mark_image_result",
            return_value=account,
        ), mock.patch(
            "services.protocol.conversation.account_service.release_image_slot",
        ), mock.patch(
            "services.protocol.conversation.OpenAIBackendAPI",
            return_value=backend,
        ), mock.patch(
            "services.protocol.conversation.proxy_settings.acquire_image_egress",
            return_value=0,
        ), mock.patch(
            "services.protocol.conversation.proxy_settings.release_image_egress",
        ), mock.patch(
            "services.protocol.conversation.stream_image_outputs",
            side_effect=stream_message,
        ), mock.patch(
            "services.protocol.conversation.is_codex_image_model",
            return_value=False,
        ), mock.patch(
            "services.protocol.conversation._cleanup_image_conversations_after_success",
        ), mock.patch(
            "services.protocol.conversation._raise_if_request_cancelled",
        ), mock.patch(
            "services.protocol.conversation.proxy_settings.get_fallback_proxy_reference",
            return_value=None,
        ):
            with self.assertRaises(ImageGenerationError) as ctx:
                _generate_single_image(request, 1, 1)

        self.assertIn("can't create", str(ctx.exception).lower())


class B10TextBackendCloseTests(unittest.TestCase):
    def test_stream_text_deltas_closes_outer_backend(self):
        outer = mock.Mock()
        outer.access_token = "tok-outer"
        outer.close = mock.Mock()
        outer.account_email = "u@example.com"

        active = mock.Mock()
        active.close = mock.Mock()

        def fake_events(*args, **kwargs):
            yield {"type": "conversation.delta", "delta": "hi"}
            yield {"type": "conversation.done", "done": True}

        with mock.patch(
            "services.protocol.conversation.OpenAIBackendAPI",
            return_value=active,
        ), mock.patch(
            "services.protocol.conversation.conversation_events",
            side_effect=fake_events,
        ), mock.patch(
            "services.protocol.conversation.account_service.mark_text_used",
        ), mock.patch(
            "services.protocol.conversation._remember_text_account",
            return_value="u@example.com",
        ):
            text = "".join(stream_text_deltas(outer, ConversationRequest(model="gpt-4o", messages=[])))

        self.assertEqual(text, "hi")
        outer.close.assert_called()
        active.close.assert_called()

    def test_collect_text_closes_outer_backend(self):
        outer = mock.Mock()
        outer.access_token = "tok-outer"
        outer.close = mock.Mock()

        active = mock.Mock()
        active.close = mock.Mock()

        def fake_events(*args, **kwargs):
            yield {"type": "conversation.delta", "delta": "ok"}
            yield {"type": "conversation.done", "done": True}

        with mock.patch(
            "services.protocol.conversation.OpenAIBackendAPI",
            return_value=active,
        ), mock.patch(
            "services.protocol.conversation.conversation_events",
            side_effect=fake_events,
        ), mock.patch(
            "services.protocol.conversation.account_service.mark_text_used",
        ), mock.patch(
            "services.protocol.conversation._remember_text_account",
            return_value="",
        ):
            result = collect_text(outer, ConversationRequest(model="gpt-4o", messages=[]))

        self.assertEqual(result, "ok")
        outer.close.assert_called()

    def test_text_backend_factory_returns_backend_with_close(self):
        backend_instance = mock.Mock()
        backend_instance.close = mock.Mock()
        with mock.patch(
            "services.protocol.conversation.account_service.get_text_access_token",
            return_value="tok-1",
        ), mock.patch(
            "services.protocol.conversation.OpenAIBackendAPI",
            return_value=backend_instance,
        ), mock.patch(
            "services.protocol.conversation._remember_text_account",
            return_value="a@b.c",
        ):
            backend = text_backend()
        self.assertIs(backend, backend_instance)
        self.assertTrue(callable(getattr(backend, "close", None)))


class B23HistoryEchoSkipTests(unittest.TestCase):
    def test_history_replay_then_new_content(self):
        """正常回放 history 后仍输出新回答。"""
        payloads = [
            _assistant_message_payload("prev answer"),
            _assistant_message_payload("new answer"),
            "[DONE]",
        ]
        events = list(
            iter_conversation_payloads(
                iter(payloads),
                history_text="prev answer",
                history_messages=["prev answer"],
            )
        )
        deltas = [e.get("delta") for e in events if e.get("type") == "conversation.delta"]
        self.assertEqual(deltas, ["new answer"])

    def test_restate_last_history_not_dropped(self):
        """模型复述上一轮 assistant 原文时，不能被 history skip 整段丢掉。"""
        payloads = [
            _assistant_message_payload("same as before"),
            "[DONE]",
        ]
        events = list(
            iter_conversation_payloads(
                iter(payloads),
                history_text="same as before",
                history_messages=["same as before"],
            )
        )
        deltas = [e.get("delta") for e in events if e.get("type") == "conversation.delta"]
        self.assertEqual(deltas, ["same as before"])
        self.assertTrue(any(e.get("type") == "conversation.done" for e in events))

    def test_multi_history_replay_skips_all_then_new(self):
        payloads = [
            _assistant_message_payload("first"),
            _assistant_message_payload("second"),
            _assistant_message_payload("third new"),
            "[DONE]",
        ]
        events = list(
            iter_conversation_payloads(
                iter(payloads),
                history_text="firstsecond",
                history_messages=["first", "second"],
            )
        )
        deltas = [e.get("delta") for e in events if e.get("type") == "conversation.delta"]
        self.assertEqual(deltas, ["third new"])


if __name__ == "__main__":
    unittest.main()
