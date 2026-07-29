from __future__ import annotations

import json
import os
import unittest
from collections.abc import Iterator

os.environ.setdefault("CHATGPT2API_AUTH_KEY", "test-auth")

from services.protocol.anthropic_v1_messages import stream_events
from utils.helper import anthropic_sse_stream, sse_json_stream


def _parse_openai_sse(frames: list[str]) -> list[str | dict]:
    """解析 sse_json_stream 输出为 data 负载列表（含 [DONE] 字符串）。"""
    payloads: list[str | dict] = []
    for frame in frames:
        for line in frame.splitlines():
            if not line.startswith("data: "):
                continue
            data = line[6:]
            if data == "[DONE]":
                payloads.append("[DONE]")
            else:
                payloads.append(json.loads(data))
    return payloads


def _parse_anthropic_sse(frames: list[str]) -> list[tuple[str, dict]]:
    """解析 anthropic_sse_stream 输出为 (event, data) 列表。"""
    events: list[tuple[str, dict]] = []
    pending_event = "message_delta"
    for frame in frames:
        for line in frame.splitlines():
            if line.startswith("event: "):
                pending_event = line[7:]
            elif line.startswith("data: "):
                events.append((pending_event, json.loads(line[6:])))
                pending_event = "message_delta"
    return events


def _failing_items_after(*items: object) -> Iterator[object]:
    yield from items
    raise RuntimeError("upstream mid-stream failure")


class SseJsonStreamFramingTests(unittest.TestCase):
    """B8: sse_json_stream 中途错误不再发 [DONE]。"""

    def test_error_path_yields_error_without_done(self) -> None:
        frames = list(sse_json_stream(_failing_items_after({"id": "c1"})))
        payloads = _parse_openai_sse(frames)
        self.assertTrue(any(isinstance(p, dict) and "error" in p for p in payloads), payloads)
        self.assertNotIn("[DONE]", payloads)
        # 错误帧应是最后一个 data 负载
        self.assertIsInstance(payloads[-1], dict)
        self.assertIn("error", payloads[-1])

    def test_success_path_still_yields_done(self) -> None:
        frames = list(sse_json_stream(iter([{"id": "ok"}, {"id": "ok2"}])))
        payloads = _parse_openai_sse(frames)
        self.assertIn("[DONE]", payloads)
        self.assertEqual(payloads[-1], "[DONE]")
        self.assertEqual(payloads.count("[DONE]"), 1)


class AnthropicSseStreamFramingTests(unittest.TestCase):
    """B9: anthropic_sse_stream 异常前补齐 content_block_stop / message_stop。"""

    def test_midstream_error_closes_open_blocks_then_error(self) -> None:
        items = _failing_items_after(
            {"type": "message_start", "message": {"id": "msg_1", "role": "assistant"}},
            {"type": "content_block_start", "index": 0, "content_block": {"type": "text", "text": ""}},
            {"type": "content_block_delta", "index": 0, "delta": {"type": "text_delta", "text": "hi"}},
        )
        events = _parse_anthropic_sse(list(anthropic_sse_stream(items)))
        types = [e[0] for e in events]
        self.assertIn("message_start", types)
        self.assertIn("content_block_start", types)
        self.assertIn("content_block_stop", types)
        self.assertIn("message_stop", types)
        self.assertIn("error", types)
        # 顺序：先 stop block，再 message_stop，最后 error
        stop_block_i = types.index("content_block_stop")
        stop_msg_i = types.index("message_stop")
        error_i = types.index("error")
        self.assertLess(stop_block_i, stop_msg_i)
        self.assertLess(stop_msg_i, error_i)
        self.assertEqual(events[stop_block_i][1]["index"], 0)
        self.assertEqual(events[error_i][1]["type"], "error")

    def test_success_path_unchanged(self) -> None:
        items = [
            {"type": "message_start", "message": {"id": "msg_1"}},
            {"type": "content_block_start", "index": 0, "content_block": {"type": "text", "text": ""}},
            {"type": "content_block_delta", "index": 0, "delta": {"type": "text_delta", "text": "ok"}},
            {"type": "content_block_stop", "index": 0},
            {"type": "message_stop"},
        ]
        events = _parse_anthropic_sse(list(anthropic_sse_stream(iter(items))))
        types = [e[0] for e in events]
        self.assertEqual(
            types,
            [
                "message_start",
                "content_block_start",
                "content_block_delta",
                "content_block_stop",
                "message_stop",
            ],
        )
        self.assertNotIn("error", types)


class AnthropicStreamEventsErrorCloseTests(unittest.TestCase):
    """B9: stream_events 中途异常时先产出 stop 再抛出。"""

    def test_midstream_exception_emits_stops_before_raise(self) -> None:
        def failing_chunks() -> Iterator[dict[str, object]]:
            yield {
                "choices": [{"delta": {"content": "partial"}, "finish_reason": None}],
            }
            raise RuntimeError("chunk source failed")

        emitted: list[str] = []
        with self.assertRaises(RuntimeError) as ctx:
            for event in stream_events(
                failing_chunks(),
                model="claude-test",
                input_tokens=1,
                output_tokens=lambda _t: 1,
                tools=None,
            ):
                emitted.append(str(event.get("type") or ""))
        self.assertEqual(str(ctx.exception), "chunk source failed")
        self.assertIn("message_start", emitted)
        self.assertIn("content_block_start", emitted)
        self.assertIn("content_block_delta", emitted)
        self.assertIn("content_block_stop", emitted)
        self.assertIn("message_stop", emitted)
        # error 前闭合顺序
        self.assertLess(emitted.index("content_block_stop"), emitted.index("message_stop"))
        self.assertEqual(emitted[-1], "message_stop")

    def test_normal_stream_still_ends_with_message_stop(self) -> None:
        chunks = [
            {
                "choices": [{"delta": {"content": "hello"}, "finish_reason": None}],
            },
            {
                "choices": [{"delta": {}, "finish_reason": "stop"}],
            },
        ]
        events = list(
            stream_events(
                chunks,
                model="claude-test",
                input_tokens=2,
                output_tokens=lambda text: max(1, len(text)),
                tools=None,
            )
        )
        types = [str(e.get("type") or "") for e in events]
        self.assertEqual(types[0], "message_start")
        self.assertIn("content_block_start", types)
        self.assertIn("content_block_delta", types)
        self.assertIn("content_block_stop", types)
        self.assertIn("message_delta", types)
        self.assertEqual(types[-1], "message_stop")
        # 正常路径不应重复 stop
        self.assertEqual(types.count("content_block_stop"), 1)
        self.assertEqual(types.count("message_stop"), 1)


if __name__ == "__main__":
    unittest.main()
