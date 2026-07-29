import os
import unittest
from datetime import datetime, timezone
from unittest import mock

os.environ.setdefault("CHATGPT2API_AUTH_KEY", "test-auth")

from services.register import mail_provider


class _FakeResponse:
    def __init__(self, status_code=200, payload=None, text="", content_type="application/json"):
        self.status_code = status_code
        self._payload = payload
        self.text = text if text or payload is None else str(payload)
        self.headers = {"content-type": content_type}

    def json(self):
        return self._payload


class OutlookEmailApiProviderTests(unittest.TestCase):
    def setUp(self):
        self.conf = {
            "request_timeout": 5,
            "wait_timeout": 5,
            "wait_interval": 0.1,
            "user_agent": "test-agent",
            "proxy": "",
        }
        self.session = mock.Mock()
        self.session.headers = {}
        patcher = mock.patch.object(mail_provider, "_create_session", return_value=self.session)
        self.addCleanup(patcher.stop)
        patcher.start()
        # 隔离本地状态文件
        self.state_store: dict = {}
        load_patch = mock.patch.object(mail_provider, "_load_outlook_email_api_state", side_effect=lambda: dict(self.state_store))
        save_patch = mock.patch.object(
            mail_provider,
            "_save_outlook_email_api_state",
            side_effect=lambda state: self.state_store.clear() or self.state_store.update(state),
        )
        self.addCleanup(load_patch.stop)
        self.addCleanup(save_patch.stop)
        load_patch.start()
        save_patch.start()

    def _provider(self, **extra):
        entry = {
            "api_base": "https://mail.example",
            "api_key": "secret-key",
            "provider_ref": "p1",
            **extra,
        }
        return mail_provider.OutlookEmailApiProvider(entry, self.conf)

    def test_requires_api_base_and_key(self):
        with self.assertRaisesRegex(RuntimeError, "api_base"):
            mail_provider.OutlookEmailApiProvider({"api_key": "k"}, self.conf)
        with self.assertRaisesRegex(RuntimeError, "api_key"):
            mail_provider.OutlookEmailApiProvider({"api_base": "https://x"}, self.conf)

    def test_normalizes_api_base(self):
        provider = self._provider(api_base="https://mail.example/")
        self.assertEqual(provider.api_base, "https://mail.example/api")
        provider2 = self._provider(api_base="https://mail.example/api")
        self.assertEqual(provider2.api_base, "https://mail.example/api")

    def test_create_mailbox_claims_unused_account(self):
        self.session.request.return_value = _FakeResponse(
            payload={
                "success": True,
                "accounts": [
                    {"id": 1, "email": "used@example.com", "aliases": []},
                    {"id": 2, "email": "free@example.com", "aliases": ["alias@example.com"]},
                ],
            }
        )
        self.state_store["used@example.com"] = {
            "state": "used",
            "reason": "",
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        provider = self._provider()
        mailbox = provider.create_mailbox()
        self.assertEqual(mailbox["provider"], "outlook_email_api")
        self.assertEqual(mailbox["address"], "free@example.com")
        self.assertEqual(mailbox["login_email"], "free@example.com")
        self.assertEqual(self.state_store["free@example.com"]["state"], "in_use")
        args, kwargs = self.session.request.call_args
        self.assertEqual(args[0], "GET")
        self.assertEqual(args[1], "https://mail.example/api/external/accounts")
        self.assertEqual(self.session.headers.get("X-API-Key"), "secret-key")

    def test_fetch_latest_message_uses_body_preview(self):
        self.session.request.return_value = _FakeResponse(
            payload={
                "success": True,
                "emails": [
                    {
                        "id": "AAMk1",
                        "subject": "Your code",
                        "from": "noreply@openai.com",
                        "date": "2026-04-09T14:20:00Z",
                        "body_preview": "Your verification code is 654321",
                        "folder": "inbox",
                    }
                ],
            }
        )
        provider = self._provider(folder="inbox", message_limit=5)
        message = provider.fetch_latest_message({"address": "free@example.com"})
        self.assertIsNotNone(message)
        assert message is not None
        self.assertEqual(message["message_id"], "AAMk1")
        self.assertIn("654321", message["text_content"])
        self.assertEqual(message["sender"], "noreply@openai.com")
        args, kwargs = self.session.request.call_args
        self.assertEqual(args[1], "https://mail.example/api/external/emails")
        self.assertEqual(kwargs["params"]["email"], "free@example.com")
        self.assertEqual(kwargs["params"]["folder"], "inbox")
        self.assertEqual(kwargs["params"]["top"], 5)

    def test_factory_creates_provider(self):
        provider = mail_provider._create_provider(
            {
                "providers": [
                    {
                        "enable": True,
                        "type": "outlook_email_api",
                        "api_base": "https://mail.example",
                        "api_key": "k",
                        "id": "oe-1",
                    }
                ]
            }
        )
        try:
            self.assertIsInstance(provider, mail_provider.OutlookEmailApiProvider)
            self.assertEqual(provider.name, "outlook_email_api")
        finally:
            provider.close()

    def test_mark_and_release(self):
        mailbox = {"provider": "outlook_email_api", "address": "a@example.com"}
        self.state_store["a@example.com"] = {"state": "in_use", "reason": "", "updated_at": ""}
        mail_provider.release_mailbox(mailbox)
        self.assertNotIn("a@example.com", self.state_store)
        mail_provider.mark_mailbox_result(mailbox, success=True)
        self.assertEqual(self.state_store["a@example.com"]["state"], "used")


if __name__ == "__main__":
    unittest.main()
