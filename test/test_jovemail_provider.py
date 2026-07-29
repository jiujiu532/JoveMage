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


class JoveMailProviderTests(unittest.TestCase):
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

    def _provider(self, **extra):
        entry = {
            "api_base": "https://mail.example",
            "api_key": "key-jovemail-test",
            "provider_ref": "p1",
            **extra,
        }
        return mail_provider.JoveMailProvider(entry, self.conf)

    def test_requires_api_base_and_key(self):
        with self.assertRaisesRegex(RuntimeError, "api_base"):
            mail_provider.JoveMailProvider({"api_key": "k"}, self.conf)
        with self.assertRaisesRegex(RuntimeError, "api_key"):
            mail_provider.JoveMailProvider({"api_base": "https://x"}, self.conf)

    def test_normalizes_api_base(self):
        provider = self._provider(api_base="https://mail.example/")
        self.assertEqual(provider.api_base, "https://mail.example")
        provider2 = self._provider(api_base="https://mail.example/api")
        self.assertEqual(provider2.api_base, "https://mail.example")
        provider3 = self._provider(api_base="https://mail.example/api/")
        self.assertEqual(provider3.api_base, "https://mail.example")

    def test_create_mailbox_posts_generate_email(self):
        self.session.request.return_value = _FakeResponse(
            status_code=201,
            payload={
                "success": True,
                "data": {
                    "email": "alice@example.test",
                    "local_part": "alice",
                    "host": "example.test",
                    "domain_id": 7,
                },
            },
        )
        provider = self._provider(domain=["example.test"])
        mailbox = provider.create_mailbox("alice")
        self.assertEqual(mailbox["provider"], "jovemail")
        self.assertEqual(mailbox["provider_ref"], "p1")
        self.assertEqual(mailbox["address"], "alice@example.test")
        self.assertEqual(mailbox["mailbox_name"], "alice")
        self.assertEqual(mailbox["domain"], "example.test")
        args, kwargs = self.session.request.call_args
        self.assertEqual(args[0], "POST")
        self.assertEqual(args[1], "https://mail.example/api/generate-email")
        self.assertEqual(kwargs["json"]["prefix"], "alice")
        self.assertEqual(kwargs["json"]["domain"], "example.test")
        self.assertEqual(kwargs["json"]["share"], False)
        self.assertEqual(self.session.headers.get("X-API-Key"), "key-jovemail-test")

    def test_fetch_latest_message_uses_next(self):
        self.session.request.return_value = _FakeResponse(
            payload={
                "success": True,
                "data": {
                    "has_email": True,
                    "message": {
                        "id": "msg-1",
                        "subject": "Your code",
                        "from_address": "noreply@openai.com",
                        "text_content": "Your verification code is 998877",
                        "html_content": "<p>998877</p>",
                        "created_at": "2026-04-09T14:20:00Z",
                        "recipient": "alice@example.test",
                        "verification_code": "998877",
                    },
                },
            }
        )
        provider = self._provider()
        message = provider.fetch_latest_message({"address": "alice@example.test"})
        self.assertIsNotNone(message)
        assert message is not None
        self.assertEqual(message["message_id"], "msg-1")
        self.assertEqual(message["subject"], "Your code")
        self.assertEqual(message["sender"], "noreply@openai.com")
        self.assertIn("998877", message["text_content"])
        self.assertIn("998877", message["html_content"])
        self.assertIsInstance(message["received_at"], datetime)
        self.assertEqual(message["received_at"].tzinfo, timezone.utc)
        args, kwargs = self.session.request.call_args
        self.assertEqual(args[0], "GET")
        self.assertEqual(args[1], "https://mail.example/api/emails/next")
        self.assertEqual(kwargs["params"]["email"], "alice@example.test")

    def test_fetch_latest_message_empty_inbox(self):
        self.session.request.return_value = _FakeResponse(
            payload={"success": True, "data": {"has_email": False, "message": None}}
        )
        provider = self._provider()
        self.assertIsNone(provider.fetch_latest_message({"address": "alice@example.test"}))

    def test_factory_creates_provider(self):
        provider = mail_provider._create_provider(
            {
                "providers": [
                    {
                        "enable": True,
                        "type": "jovemail",
                        "api_base": "https://mail.example",
                        "api_key": "k",
                        "id": "jm-1",
                    }
                ]
            }
        )
        try:
            self.assertIsInstance(provider, mail_provider.JoveMailProvider)
            self.assertEqual(provider.name, "jovemail")
        finally:
            provider.close()


if __name__ == "__main__":
    unittest.main()
