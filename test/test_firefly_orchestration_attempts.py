# -*- coding: utf-8 -*-
"""Firefly 编排公共骨架 _run_firefly_account_attempts 回归。

覆盖：占槽/释放成对、错误分类、last_error 保留、钉选不换号。
不打真实上游；mock account_service / backends。
"""
from __future__ import annotations

import os
import unittest
from types import SimpleNamespace
from typing import Any
from unittest import mock

os.environ.setdefault("CHATGPT2API_AUTH_KEY", "test-auth")

from services.backends.firefly_errors import (  # noqa: E402
    FireflyAuthError,
    FireflyQuotaExhausted,
    FireflyRequestError,
    FireflyUpstreamTemporary,
)
from services.protocol.conversation_types import (  # noqa: E402
    ConversationRequest,
    ImageGenerationError,
    ImageOutput,
)
from test._firefly_helpers import first_callable  # noqa: E402


def _load_orchestration():
    """容错加载 firefly_orchestration 模块。"""
    try:
        from services.protocol import firefly_orchestration as fo
    except Exception as exc:  # pragma: no cover
        raise unittest.SkipTest(f"cannot import firefly_orchestration: {exc}") from exc
    return fo


def _run_fn(fo):
    fn = first_callable(
        fo,
        "_run_firefly_account_attempts",
        "run_firefly_account_attempts",
        required=False,
    )
    if fn is None:
        raise unittest.SkipTest("missing _run_firefly_account_attempts")
    return fn


def _make_request(**kwargs) -> ConversationRequest:
    base = {
        "model": "firefly-image",
        "prompt": "a cat",
        "n": 1,
        "response_format": "b64_json",
    }
    base.update(kwargs)
    return ConversationRequest(**base)


class _InflightTracker:
    """模拟 image inflight：select 占槽，release/mark/report 释放。"""

    def __init__(self) -> None:
        self.inflight: dict[str, int] = {}
        self.mark_calls: list[dict[str, Any]] = []
        self.report_calls: list[dict[str, Any]] = []
        self.update_calls: list[dict[str, Any]] = []
        self.release_calls: list[str] = []
        self.accounts: dict[str, dict[str, Any]] = {}

    def total(self) -> int:
        return sum(int(v) for v in self.inflight.values())

    def acquire(self, token: str) -> str:
        self.inflight[token] = int(self.inflight.get(token, 0)) + 1
        return token

    def release(self, token: str) -> None:
        self.release_calls.append(token)
        cur = int(self.inflight.get(token, 0))
        if cur <= 1:
            self.inflight.pop(token, None)
        else:
            self.inflight[token] = cur - 1

    def mark_image_result(
        self,
        token: str,
        success: bool,
        *,
        failure=None,
        quota_consumed=None,
        expected_access_token=None,
        expected_refresh_token=None,
        **_kwargs,
    ) -> None:
        self.mark_calls.append(
            {
                "token": token,
                "success": success,
                "failure": failure,
                "quota_consumed": quota_consumed,
            }
        )
        # 与生产 mark_image_result 一致：无论成败都释放槽
        self.release(token)

    def report_exhausted(self, token: str, reason: str = "") -> None:
        self.report_calls.append({"token": token, "reason": reason})
        self.release(token)

    def update_account(self, token: str, fields: dict, quiet: bool = False) -> None:
        self.update_calls.append({"token": token, "fields": dict(fields), "quiet": quiet})
        self.accounts.setdefault(token, {}).update(fields)

    def get_account(self, token: str):
        return self.accounts.get(token) or {
            "email": f"{token}@example.com",
            "proxy": "socks5://proxy.example:1080",
            "refresh_token": f"rt-{token}",
        }


class RunFireflyAccountAttemptsTests(unittest.TestCase):
    """直接测公共骨架。"""

    def setUp(self) -> None:
        self.fo = _load_orchestration()
        self.run = _run_fn(self.fo)
        self.tracker = _InflightTracker()
        self.request = _make_request()
        # 屏蔽埋点/取消检查
        self._patches = [
            mock.patch.object(self.fo, "_monitor_image_stage", return_value=None),
            mock.patch.object(self.fo, "_raise_if_request_cancelled", return_value=None),
            mock.patch.object(self.fo.account_service, "get_account", side_effect=self.tracker.get_account),
            mock.patch.object(self.fo.account_service, "mark_image_result", side_effect=self.tracker.mark_image_result),
            mock.patch.object(self.fo.account_service, "release_image_slot", side_effect=self.tracker.release),
            mock.patch.object(self.fo.account_service, "report_exhausted", side_effect=self.tracker.report_exhausted),
            mock.patch.object(self.fo.account_service, "update_account", side_effect=self.tracker.update_account),
        ]
        for p in self._patches:
            p.start()
        self.addCleanup(self._stop_all)

    def _stop_all(self) -> None:
        for p in reversed(self._patches):
            try:
                p.stop()
            except RuntimeError:
                pass

    def _select_sequence(self, tokens: list[str]):
        """按序返回 token 并占槽；耗尽后抛 ImageAccountSelectionError。"""
        from services.account_service import ImageAccountSelectionError

        it = iter(tokens)

        def select(attempted: set[str]) -> str:
            try:
                token = next(it)
            except StopIteration as exc:
                raise ImageAccountSelectionError("unavailable", "pool empty") from exc
            return self.tracker.acquire(token)

        return select

    def _ok_execute(self, label: str = "ok"):
        def execute(token, account, finalize, **_kwargs):
            finalize(True, quota_consumed=False)
            return [
                ImageOutput(
                    kind="result",
                    model="m",
                    index=1,
                    total=1,
                    data=[{"url": f"https://x/{label}/{token}"}],
                    account_email=str(account.get("email") or ""),
                )
            ]

        return execute

    def test_success_slot_paired(self) -> None:
        """成功路径：占槽后 mark 释放，inflight 归零。"""
        outputs = self.run(
            self.request,
            index=1,
            total=1,
            channel="firefly",
            execute=self._ok_execute(),
            max_attempts=2,
            select_token=self._select_sequence(["tok-a"]),
        )
        self.assertEqual(len(outputs), 1)
        self.assertEqual(self.tracker.total(), 0)
        self.assertEqual(len(self.tracker.mark_calls), 1)
        self.assertTrue(self.tracker.mark_calls[0]["success"])
        self.assertEqual(self.tracker.mark_calls[0]["quota_consumed"], False)

    def test_quota_report_exhausted_and_rotate(self) -> None:
        """Quota → report_exhausted；可换号时继续下一次。"""
        calls = {"n": 0}

        def execute(token, account, finalize, **_kwargs):
            calls["n"] += 1
            if calls["n"] == 1:
                raise FireflyQuotaExhausted("taste gone")
            finalize(True, quota_consumed=False)
            return [
                ImageOutput(kind="result", model="m", index=1, total=1, data=[{"url": "ok"}])
            ]

        outputs = self.run(
            self.request,
            index=1,
            total=1,
            channel="firefly",
            execute=execute,
            max_attempts=3,
            select_token=self._select_sequence(["tok-a", "tok-b"]),
        )
        self.assertEqual(len(outputs), 1)
        self.assertEqual(self.tracker.total(), 0)
        self.assertEqual(len(self.tracker.report_calls), 1)
        self.assertEqual(self.tracker.report_calls[0]["token"], "tok-a")
        self.assertEqual(self.tracker.report_calls[0]["reason"], "taste_exhausted")
        # 第二次成功走 mark
        self.assertTrue(any(c["success"] for c in self.tracker.mark_calls))

    def test_auth_marks_local_abnormal_without_auth_invalid_failure(self) -> None:
        """Auth → update_account(异常)；finalize 不带 auth_invalid failure（避免 OpenAI verify）。"""
        calls = {"n": 0}

        def execute(token, account, finalize, **_kwargs):
            calls["n"] += 1
            if calls["n"] == 1:
                raise FireflyAuthError("token dead")
            finalize(True, quota_consumed=False)
            return [ImageOutput(kind="result", model="m", index=1, total=1, data=[{"url": "ok"}])]

        outputs = self.run(
            self.request,
            index=1,
            total=1,
            channel="firefly",
            execute=execute,
            max_attempts=3,
            select_token=self._select_sequence(["tok-a", "tok-b"]),
        )
        self.assertEqual(len(outputs), 1)
        self.assertEqual(self.tracker.total(), 0)
        self.assertEqual(len(self.tracker.update_calls), 1)
        self.assertEqual(self.tracker.update_calls[0]["fields"].get("status"), "异常")
        # auth 路径 finalize(False) 不带 failure
        auth_marks = [c for c in self.tracker.mark_calls if not c["success"]]
        self.assertTrue(auth_marks)
        for c in auth_marks:
            self.assertIsNone(c["failure"])

    def test_temporary_rotates(self) -> None:
        """Temporary → finalize + continue 换号。"""
        calls = {"n": 0}

        def execute(token, account, finalize, **_kwargs):
            calls["n"] += 1
            if calls["n"] == 1:
                raise FireflyUpstreamTemporary("503 boom")
            finalize(True, quota_consumed=False)
            return [ImageOutput(kind="result", model="m", index=1, total=1, data=[{"url": "ok"}])]

        outputs = self.run(
            self.request,
            index=1,
            total=1,
            channel="firefly",
            execute=execute,
            max_attempts=3,
            select_token=self._select_sequence(["tok-a", "tok-b"]),
        )
        self.assertEqual(len(outputs), 1)
        self.assertEqual(self.tracker.total(), 0)
        self.assertEqual(calls["n"], 2)
        fail_marks = [c for c in self.tracker.mark_calls if not c["success"]]
        self.assertTrue(fail_marks)
        failure = fail_marks[0]["failure"]
        self.assertIsNotNone(failure)
        self.assertEqual(getattr(failure, "code", None), "upstream_unavailable")

    def test_request_error_raises(self) -> None:
        """Request 错误：立即 raise，不换号。"""

        def execute(token, account, finalize, **_kwargs):
            raise FireflyRequestError("bad prompt", status_code=400)

        with self.assertRaises(ImageGenerationError) as ctx:
            self.run(
                self.request,
                index=1,
                total=1,
                channel="firefly",
                execute=execute,
                max_attempts=3,
                select_token=self._select_sequence(["tok-a", "tok-b"]),
            )
        self.assertEqual(ctx.exception.status_code, 400)
        # FireflyRequestError 无 code 字段时骨架回退 upstream_error
        self.assertEqual(ctx.exception.code, "upstream_error")
        self.assertEqual(self.tracker.total(), 0)
        # 只尝试一次
        self.assertEqual(len(self.tracker.mark_calls), 1)
        self.assertFalse(self.tracker.mark_calls[0]["success"])

    def test_duplicate_token_keeps_last_error(self) -> None:
        """同 token 重复被分到：保留既有 401/429 last_error，不用 503 覆盖。"""
        # select 始终返回同一 token（第二次会命中 attempted_tokens 分支）
        def select(_attempted: set[str]) -> str:
            return self.tracker.acquire("tok-dup")

        def execute(token, account, finalize, **_kwargs):
            raise FireflyAuthError("dead")

        with self.assertRaises(ImageGenerationError) as ctx:
            self.run(
                self.request,
                index=1,
                total=1,
                channel="firefly",
                execute=execute,
                max_attempts=3,
                select_token=select,
            )
        self.assertEqual(ctx.exception.status_code, 401)
        self.assertEqual(ctx.exception.code, "auth_invalid")
        self.assertEqual(self.tracker.total(), 0)

    def test_allow_rotate_false_stops_on_quota(self) -> None:
        """allow_rotate=False：quota 也不换号，立即抛出。"""
        calls = {"n": 0}

        def execute(token, account, finalize, **_kwargs):
            calls["n"] += 1
            raise FireflyQuotaExhausted("pinned exhausted")

        with self.assertRaises(ImageGenerationError) as ctx:
            self.run(
                self.request,
                index=1,
                total=1,
                channel="firefly-video",
                execute=execute,
                max_attempts=3,
                select_token=self._select_sequence(["tok-pinned", "tok-other"]),
                allow_rotate=False,
                log_kind="video",
                subject="firefly video",
            )
        self.assertEqual(ctx.exception.status_code, 429)
        self.assertEqual(calls["n"], 1)
        self.assertEqual(self.tracker.total(), 0)
        self.assertEqual(len(self.tracker.report_calls), 1)

    def test_allow_rotate_false_stops_on_temporary(self) -> None:
        """allow_rotate=False：temporary 也不换号。"""
        calls = {"n": 0}

        def execute(token, account, finalize, **_kwargs):
            calls["n"] += 1
            raise FireflyUpstreamTemporary("tmp")

        with self.assertRaises(ImageGenerationError) as ctx:
            self.run(
                self.request,
                index=1,
                total=1,
                channel="firefly-video",
                execute=execute,
                max_attempts=3,
                select_token=self._select_sequence(["tok-pinned", "tok-other"]),
                allow_rotate=False,
                log_kind="video",
            )
        self.assertEqual(ctx.exception.status_code, 503)
        self.assertEqual(ctx.exception.code, "upstream_unavailable")
        self.assertEqual(calls["n"], 1)
        self.assertEqual(self.tracker.total(), 0)

    def test_exception_path_releases_slot(self) -> None:
        """非 Firefly 异常且不可轮换：finalize 后 raise，inflight 归零。"""

        def execute(token, account, finalize, **_kwargs):
            raise RuntimeError("boom unexpected")

        with mock.patch.object(self.fo, "is_rotatable_error", return_value=False):
            with self.assertRaises(ImageGenerationError):
                self.run(
                    self.request,
                    index=1,
                    total=1,
                    channel="firefly",
                    execute=execute,
                    max_attempts=2,
                    select_token=self._select_sequence(["tok-a"]),
                )
        self.assertEqual(self.tracker.total(), 0)

    def test_rotatable_generic_exception_rotates(self) -> None:
        """通用异常 is_rotatable_error=True 且未达上限 → 换号。"""
        calls = {"n": 0}

        def execute(token, account, finalize, **_kwargs):
            calls["n"] += 1
            if calls["n"] == 1:
                raise RuntimeError("network blip")
            finalize(True, quota_consumed=False)
            return [ImageOutput(kind="result", model="m", index=1, total=1, data=[{"url": "ok"}])]

        with mock.patch.object(self.fo, "is_rotatable_error", return_value=True):
            outputs = self.run(
                self.request,
                index=1,
                total=1,
                channel="firefly",
                execute=execute,
                max_attempts=3,
                select_token=self._select_sequence(["tok-a", "tok-b"]),
            )
        self.assertEqual(len(outputs), 1)
        self.assertEqual(calls["n"], 2)
        self.assertEqual(self.tracker.total(), 0)

    def test_allow_rotate_false_blocks_rotatable_generic(self) -> None:
        """钉选：即使 is_rotatable_error=True 也不换号。"""
        calls = {"n": 0}

        def execute(token, account, finalize, **_kwargs):
            calls["n"] += 1
            raise RuntimeError("network blip")

        with mock.patch.object(self.fo, "is_rotatable_error", return_value=True):
            with self.assertRaises(ImageGenerationError):
                self.run(
                    self.request,
                    index=1,
                    total=1,
                    channel="firefly-video",
                    execute=execute,
                    max_attempts=3,
                    select_token=self._select_sequence(["tok-pinned", "tok-other"]),
                    allow_rotate=False,
                    log_kind="video",
                )
        self.assertEqual(calls["n"], 1)
        self.assertEqual(self.tracker.total(), 0)


class GenerateSingleImageFireflySkeletonTests(unittest.TestCase):
    """经文生图薄封装走骨架：成功 + quota 分类。"""

    def setUp(self) -> None:
        self.fo = _load_orchestration()
        self.gen = first_callable(
            self.fo,
            "_generate_single_image_firefly",
            "generate_single_image_firefly",
            required=False,
        )
        if self.gen is None:
            raise unittest.SkipTest("missing _generate_single_image_firefly")
        self.tracker = _InflightTracker()
        # ConfigStore 属性是 property，不能 patch.object；替换模块级 config 引用
        fake_config = SimpleNamespace(
            firefly_enabled=True,
            firefly_retry_max_attempts=3,
            firefly_gen_timeout_sec=30,
            firefly_poll_interval_sec=0.1,
        )
        self._patches = [
            mock.patch.object(self.fo, "_monitor_image_stage", return_value=None),
            mock.patch.object(self.fo, "_raise_if_request_cancelled", return_value=None),
            mock.patch.object(self.fo, "config", fake_config),
            mock.patch.object(
                self.fo,
                "resolve_firefly_image_model",
                return_value={
                    "modelId": "gemini-flash",
                    "modelVersion": "nano-banana-2",
                    "width": 1024,
                    "height": 1024,
                },
            ),
            mock.patch.object(
                self.fo,
                "build_text2image_payload",
                return_value={"prompt": "x"},
            ),
            mock.patch.object(self.fo.account_service, "get_account", side_effect=self.tracker.get_account),
            mock.patch.object(self.fo.account_service, "mark_image_result", side_effect=self.tracker.mark_image_result),
            mock.patch.object(self.fo.account_service, "release_image_slot", side_effect=self.tracker.release),
            mock.patch.object(self.fo.account_service, "report_exhausted", side_effect=self.tracker.report_exhausted),
            mock.patch.object(self.fo.account_service, "update_account", side_effect=self.tracker.update_account),
        ]
        for p in self._patches:
            p.start()
        self.addCleanup(self._stop_all)

    def _stop_all(self) -> None:
        for p in reversed(self._patches):
            try:
                p.stop()
            except RuntimeError:
                pass

    def test_text2image_success_releases_slot(self) -> None:
        """文生图成功：generate 被调、slot 归零。"""
        png = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32

        def select(attempted):
            return self.tracker.acquire("tok-img")

        with mock.patch.object(self.fo, "firefly_generate", return_value=png), mock.patch.object(
            self.fo.account_service,
            "get_available_access_token",
            side_effect=lambda **kw: select(kw.get("excluded_tokens") or set()),
        ), mock.patch.object(
            self.fo,
            "_firefly_image_result_output",
            return_value=ImageOutput(
                kind="result", model="m", index=1, total=1, data=[{"b64_json": "x"}]
            ),
        ):
            outputs = self.gen(_make_request(), 1, 1)
        self.assertEqual(len(outputs), 1)
        self.assertEqual(self.tracker.total(), 0)
        self.assertTrue(self.tracker.mark_calls)
        self.assertTrue(self.tracker.mark_calls[-1]["success"])

    def test_text2image_auth_no_openai_verify_failure(self) -> None:
        """文生图 Auth：本地异常 + finalize 不带 failure。"""

        def select(attempted):
            # 每次返回新 token，便于观察换号；第二次再成功
            token = f"tok-{len(attempted)}"
            return self.tracker.acquire(token)

        gen_calls = {"n": 0}

        def fake_gen(*_a, **_k):
            gen_calls["n"] += 1
            if gen_calls["n"] == 1:
                raise FireflyAuthError("nope")
            return b"\x89PNG\r\n\x1a\n" + b"\x00" * 8

        with mock.patch.object(self.fo, "firefly_generate", side_effect=fake_gen), mock.patch.object(
            self.fo.account_service,
            "get_available_access_token",
            side_effect=lambda **kw: select(kw.get("excluded_tokens") or set()),
        ), mock.patch.object(
            self.fo,
            "_firefly_image_result_output",
            return_value=ImageOutput(
                kind="result", model="m", index=1, total=1, data=[{"b64_json": "x"}]
            ),
        ):
            outputs = self.gen(_make_request(), 1, 1)
        self.assertEqual(len(outputs), 1)
        self.assertEqual(self.tracker.total(), 0)
        self.assertTrue(self.tracker.update_calls)
        self.assertEqual(self.tracker.update_calls[0]["fields"].get("status"), "异常")
        # 失败 mark 无 failure
        fail_marks = [c for c in self.tracker.mark_calls if not c["success"]]
        self.assertTrue(fail_marks)
        self.assertIsNone(fail_marks[0]["failure"])


if __name__ == "__main__":
    unittest.main()
