import os
import unittest
from datetime import datetime, timedelta, timezone
from unittest import mock

os.environ.setdefault("CHATGPT2API_AUTH_KEY", "test-auth")

from services.register import mail_provider


class _StubProvider(mail_provider.BaseMailProvider):
    """用于 create_mailbox 顶层 failover 的桩 provider。"""

    name = "stub"

    def __init__(self, conf, provider_ref="stub-ref", address="user@banned.example", close_fn=None):
        super().__init__(conf, provider_ref)
        self._address = address
        self._close_fn = close_fn

    def create_mailbox(self, username: str | None = None) -> dict:
        return {
            "provider": self.name,
            "provider_ref": self.provider_ref,
            "address": self._address,
        }

    def fetch_latest_message(self, mailbox: dict) -> dict | None:
        return None

    def close(self) -> None:
        if self._close_fn:
            self._close_fn()


class CreateMailboxReleaseOnBanTests(unittest.TestCase):
    """B1: 建箱成功后域名 ban 必须 release，避免 Outlook in_use 泄漏。"""

    def test_domain_ban_releases_created_mailbox(self):
        conf = {
            "request_timeout": 5,
            "wait_timeout": 1,
            "wait_interval": 0.05,
            "user_agent": "test-agent",
            "proxy": "",
        }
        mailbox = {
            "provider": "outlook_token",
            "provider_ref": "outlook_token:p1",
            "address": "leaked@banned.example",
        }
        provider = mock.Mock()
        provider.name = "outlook_token"
        provider.provider_ref = "outlook_token:p1"
        provider.create_mailbox.return_value = dict(mailbox)
        provider.close = mock.Mock()

        mail_config = {
            "providers": [
                {"type": "outlook_token", "enable": True, "id": "p1", "mailboxes": []},
            ],
            "wait_timeout": 1,
            "wait_interval": 0.05,
            "request_timeout": 5,
            "user_agent": "test-agent",
            "proxy": "",
        }

        with (
            mock.patch.object(mail_provider, "_create_provider", return_value=provider),
            mock.patch.object(
                mail_provider,
                "_enabled_entries",
                return_value=[{"type": "outlook_token", "enable": True, "provider_ref": "outlook_token:p1"}],
            ),
            mock.patch(
                "services.register.domain_blacklist.is_excluded_provider",
                return_value=False,
            ),
            mock.patch(
                "services.register.domain_blacklist.is_banned",
                return_value=True,
            ),
            mock.patch.object(mail_provider, "release_mailbox") as release_mock,
        ):
            with self.assertRaisesRegex(RuntimeError, "域名已拉黑"):
                mail_provider.create_mailbox(mail_config)

        release_mock.assert_called_once()
        released = release_mock.call_args[0][0]
        self.assertEqual(released["address"], "leaked@banned.example")
        provider.close.assert_called()

    def test_successful_create_does_not_release(self):
        provider = mock.Mock()
        provider.name = "ahem"
        provider.provider_ref = "ahem:ok"
        provider.create_mailbox.return_value = {
            "provider": "ahem",
            "provider_ref": "ahem:ok",
            "address": "ok@allowed.example",
        }
        provider.close = mock.Mock()
        mail_config = {
            "providers": [{"type": "ahem", "enable": True, "id": "ok"}],
            "wait_timeout": 1,
            "wait_interval": 0.05,
            "request_timeout": 5,
            "user_agent": "test-agent",
            "proxy": "",
        }
        with (
            mock.patch.object(mail_provider, "_create_provider", return_value=provider),
            mock.patch.object(
                mail_provider,
                "_enabled_entries",
                return_value=[{"type": "ahem", "enable": True, "provider_ref": "ahem:ok"}],
            ),
            mock.patch(
                "services.register.domain_blacklist.is_excluded_provider",
                return_value=False,
            ),
            mock.patch(
                "services.register.domain_blacklist.is_banned",
                return_value=False,
            ),
            mock.patch.object(mail_provider, "release_mailbox") as release_mock,
        ):
            result = mail_provider.create_mailbox(mail_config)

        self.assertEqual(result["address"], "ok@allowed.example")
        self.assertIn("_code_not_before", result)
        release_mock.assert_not_called()


class WaitForCodeBoundaryTests(unittest.TestCase):
    """B12: 基类 wait_for_code 应跳过早于 _code_not_before / _received_after 的旧码。"""

    def setUp(self):
        self.conf = {
            "request_timeout": 5,
            "wait_timeout": 0.3,
            "wait_interval": 0.05,
            "user_agent": "test-agent",
            "proxy": "",
        }

    def test_base_skips_code_before_code_not_before(self):
        now = datetime.now(timezone.utc)
        old_msg = {
            "provider": "stub",
            "mailbox": "u@example.com",
            "message_id": "old-1",
            "subject": "Your code",
            "sender": "noreply@openai.com",
            "text_content": "Your verification code is 111111",
            "html_content": "",
            "received_at": now - timedelta(minutes=5),
        }
        new_msg = {
            "provider": "stub",
            "mailbox": "u@example.com",
            "message_id": "new-1",
            "subject": "Your code",
            "sender": "noreply@openai.com",
            "text_content": "Your verification code is 222222",
            "html_content": "",
            "received_at": now + timedelta(seconds=1),
        }
        provider = mail_provider.BaseMailProvider(self.conf, "stub")
        call_count = {"n": 0}

        def fetch(_mailbox):
            call_count["n"] += 1
            # 先返回旧信，再返回新信
            return old_msg if call_count["n"] == 1 else new_msg

        provider.fetch_latest_message = fetch  # type: ignore[method-assign]
        mailbox = {
            "address": "u@example.com",
            "_code_not_before": now,
        }
        code = provider.wait_for_code(mailbox)
        self.assertEqual(code, "222222")

    def test_base_skips_code_before_received_after_isoformat(self):
        now = datetime.now(timezone.utc)
        old_msg = {
            "provider": "stub",
            "mailbox": "u@example.com",
            "message_id": "old-2",
            "subject": "code",
            "sender": "noreply@openai.com",
            "text_content": "code 333333",
            "html_content": "",
            "received_at": now - timedelta(seconds=30),
        }
        new_msg = {
            "provider": "stub",
            "mailbox": "u@example.com",
            "message_id": "new-2",
            "subject": "code",
            "sender": "noreply@openai.com",
            "text_content": "code 444444",
            "html_content": "",
            "received_at": now + timedelta(seconds=2),
        }
        provider = mail_provider.BaseMailProvider(self.conf, "stub")
        msgs = [old_msg, new_msg]
        idx = {"i": 0}

        def fetch(_mailbox):
            i = min(idx["i"], len(msgs) - 1)
            idx["i"] += 1
            return msgs[i]

        provider.fetch_latest_message = fetch  # type: ignore[method-assign]
        mailbox = {
            "address": "u@example.com",
            # openai_register 写入的是 isoformat 字符串
            "_received_after": (now - timedelta(seconds=5)).isoformat(),
        }
        code = provider.wait_for_code(mailbox)
        self.assertEqual(code, "444444")

    def test_message_before_code_boundary_helper(self):
        now = datetime.now(timezone.utc)
        msg = {"received_at": now - timedelta(seconds=10)}
        self.assertTrue(
            mail_provider._message_before_code_boundary(
                {"_code_not_before": now},
                msg,
            )
        )
        self.assertTrue(
            mail_provider._message_before_code_boundary(
                {"_received_after": now.isoformat()},
                msg,
            )
        )
        self.assertFalse(
            mail_provider._message_before_code_boundary(
                {"_code_not_before": now - timedelta(minutes=1)},
                msg,
            )
        )


class ProviderRefStabilityTests(unittest.TestCase):
    """B13: mail_provider 内 build_provider_ref 不依赖列表下标。"""

    def test_build_provider_ref_prefers_stable_id(self):
        item = {"type": "ahem", "id": "abc", "domain": ["x.test"]}
        self.assertEqual(mail_provider.build_provider_ref(item, 0), "ahem:abc")
        self.assertEqual(mail_provider.build_provider_ref(item, 99), "ahem:abc")

    def test_build_provider_ref_fingerprint_stable_across_index(self):
        item = {"type": "gptmail", "domain": ["a.com", "b.com"], "api_base": "https://x"}
        r0 = mail_provider.build_provider_ref(item, 0)
        r1 = mail_provider.build_provider_ref(item, 1)
        self.assertEqual(r0, r1)
        self.assertTrue(r0.startswith("gptmail~"))
        self.assertNotIn("#", r0)

    def test_entries_use_build_provider_ref(self):
        cfg = {
            "providers": [
                {"type": "ahem", "id": "p1", "enable": True, "domain": ["a.test"]},
                {"type": "ahem", "id": "p2", "enable": True, "domain": ["b.test"]},
            ]
        }
        entries = mail_provider._entries(cfg)
        refs = [e["provider_ref"] for e in entries]
        self.assertEqual(refs, ["ahem:p1", "ahem:p2"])
        # label 仍可含 #，但 provider_ref 不应是 type#index
        for ref in refs:
            self.assertNotRegex(ref, r"^ahem#\d+$")


if __name__ == "__main__":
    unittest.main()
