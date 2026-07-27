from __future__ import annotations

import base64
import json
import unittest
from unittest import mock

from utils import sentinel, turnstile


def encode_program(program: list) -> str:
    return base64.b64encode(json.dumps(program).encode()).decode()


class FakeResponse:
    status_code = 200
    text = "response"

    def json(self) -> dict:
        return {
            "token": "challenge-token",
            "proofofwork": {"required": False},
            "turnstile": {"required": True, "dx": "encoded-dx"},
        }


class FakeSession:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    def post(self, url: str, **kwargs) -> FakeResponse:
        self.calls.append({"url": url, **kwargs})
        return FakeResponse()


class SentinelTurnstileTests(unittest.TestCase):
    def test_regular_token_embeds_turnstile_solution(self) -> None:
        session = FakeSession()
        with mock.patch.object(sentinel, "solve_turnstile_token", return_value="so-token") as solve:
            token, oai_sc = sentinel.build_sentinel_token(
                session,
                "device-1",
                "authorize_continue",
            )

        request_payload = json.loads(session.calls[0]["data"])
        token_payload = json.loads(token)
        solve.assert_called_once_with("encoded-dx", request_payload["p"])
        self.assertEqual(token_payload["t"], "so-token")
        self.assertEqual(oai_sc, "0challenge-token")

    def test_create_account_builder_returns_separate_so_token(self) -> None:
        session = FakeSession()
        with mock.patch.object(sentinel, "solve_turnstile_token", return_value="so-token") as solve, mock.patch.object(
            sentinel.time,
            "sleep",
        ) as sleep:
            token, so_token, oai_sc = sentinel.build_sentinel_with_so_token(
                session,
                "device-1",
                "oauth_create_account",
            )

        request_payload = json.loads(session.calls[0]["data"])
        token_payload = json.loads(token)
        solve.assert_called_once_with("encoded-dx", request_payload["p"])
        sleep.assert_called_once_with(5.0)
        self.assertEqual(token_payload["t"], "so-token")
        self.assertEqual(so_token, "so-token")
        self.assertEqual(oai_sc, "0challenge-token")


class TurnstileVmTests(unittest.TestCase):
    def test_opcode_20_dereferences_callback_arguments(self) -> None:
        program = [
            [2, 40, "match"],
            [2, 41, "match"],
            [2, 42, "stored-value"],
            [20, 40, 41, 3, 42],
        ]

        result = turnstile.solve_turnstile_token(encode_program(program), "")

        self.assertEqual(result, base64.b64encode(b"stored-value").decode())

    def test_oversized_encoded_input_fails_before_decode(self) -> None:
        with mock.patch.object(turnstile.base64, "b64decode") as decode:
            result = turnstile.solve_turnstile_token("A" * 1_048_577, "")

        self.assertIsNone(result)
        decode.assert_not_called()

    def test_oversized_decoded_input_fails_before_json_parse(self) -> None:
        encoded = base64.b64encode(b"A" * 524_289).decode()
        with mock.patch.object(turnstile.json, "loads") as loads:
            result = turnstile.solve_turnstile_token(encoded, "")

        self.assertIsNone(result)
        loads.assert_not_called()

    def test_excessive_vm_steps_fail_closed(self) -> None:
        program = [[25] for _ in range(20_001)]

        result = turnstile.solve_turnstile_token(encode_program(program), "")

        self.assertIsNone(result)

    def test_nested_queues_share_global_step_budget(self) -> None:
        nested_queue = [[25] for _ in range(19_999)]
        program = [[30, 40, 0, nested_queue], [7, 40], [3, "unreachable"]]

        result = turnstile.solve_turnstile_token(encode_program(program), "")

        self.assertIsNone(result)

    def test_excessive_vm_nesting_fails_closed(self) -> None:
        queue = [[3, "unreachable"]]
        for register in range(40, 73):
            queue = [[30, register, 0, queue], [7, register]]

        result = turnstile.solve_turnstile_token(encode_program(queue), "")

        self.assertIsNone(result)


if __name__ == "__main__":
    unittest.main()
