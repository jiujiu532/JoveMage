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


class AhemMailProviderTests(unittest.TestCase):
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

    def test_requires_api_base(self):
        with self.assertRaisesRegex(RuntimeError, "api_base"):
            mail_provider.AhemMailProvider({"domain": ["example.test"]}, self.conf)

    def test_create_mailbox_uses_configured_domain(self):
        provider = mail_provider.AhemMailProvider(
            {"api_base": "https://mail.example/api", "domain": ["example.test"], "provider_ref": "p1"},
            self.conf,
        )
        mailbox = provider.create_mailbox("alice")
        self.assertEqual(mailbox["provider"], "ahem")
        self.assertEqual(mailbox["provider_ref"], "p1")
        self.assertEqual(mailbox["address"], "alice@example.test")
        self.assertEqual(mailbox["mailbox_name"], "alice")
        self.assertEqual(mailbox["domain"], "example.test")
        self.session.request.assert_not_called()

    def test_create_mailbox_falls_back_to_properties_domains(self):
        self.session.request.return_value = _FakeResponse(
            payload={"allowedDomains": ["remote.example"]}
        )
        provider = mail_provider.AhemMailProvider(
            {"api_base": "https://mail.example/api/", "domain": []},
            self.conf,
        )
        mailbox = provider.create_mailbox("bob")
        self.assertEqual(mailbox["address"], "bob@remote.example")
        self.session.request.assert_called_once()
        args, kwargs = self.session.request.call_args
        self.assertEqual(args[0], "GET")
        self.assertEqual(args[1], "https://mail.example/api/properties")

    def test_api_base_without_api_suffix_is_normalized(self):
        self.session.request.return_value = _FakeResponse(
            payload={"allowedDomains": ["remote.example"]}
        )
        provider = mail_provider.AhemMailProvider(
            {"api_base": "https://mail.example", "domain": []},
            self.conf,
        )
        self.assertEqual(provider.api_base, "https://mail.example/api")
        mailbox = provider.create_mailbox("bob")
        self.assertEqual(mailbox["address"], "bob@remote.example")
        args, _ = self.session.request.call_args
        self.assertEqual(args[1], "https://mail.example/api/properties")

    def test_empty_properties_raises_clear_error(self):
        self.session.request.return_value = _FakeResponse(payload={"serverBaseUri": "x"})
        provider = mail_provider.AhemMailProvider(
            {"api_base": "https://mail.example/api", "domain": []},
            self.conf,
        )
        with self.assertRaisesRegex(RuntimeError, "allowedDomains"):
            provider.create_mailbox("bob")

    def test_fetch_latest_message_reads_text_body(self):
        list_item = {
            "emailId": "msg-1",
            "subject": "Your code",
            "timestamp": 1_700_000_000_000,
            "sender": {"address": "noreply@openai.com", "name": ""},
        }
        detail = {
            "_id": "msg-1",
            "subject": "Your code",
            "text": "Your verification code is 123456\n",
            "html": False,
            "timestamp": 1_700_000_000_000,
            "from": {"text": "noreply@openai.com", "value": [{"address": "noreply@openai.com", "name": ""}]},
            "to": {"text": "alice@example.test", "value": [{"address": "alice@example.test", "name": ""}]},
        }
        self.session.request.side_effect = [
            _FakeResponse(payload=[list_item]),
            _FakeResponse(payload=detail),
        ]
        provider = mail_provider.AhemMailProvider(
            {"api_base": "https://mail.example/api", "domain": ["example.test"]},
            self.conf,
        )
        message = provider.fetch_latest_message(
            {"address": "alice@example.test", "mailbox_name": "alice"}
        )
        self.assertIsNotNone(message)
        assert message is not None
        self.assertEqual(message["message_id"], "msg-1")
        self.assertEqual(message["subject"], "Your code")
        self.assertEqual(message["sender"], "noreply@openai.com")
        self.assertIn("123456", message["text_content"])
        self.assertEqual(message["html_content"], "")
        self.assertIsInstance(message["received_at"], datetime)
        self.assertEqual(message["received_at"].tzinfo, timezone.utc)

        first_call = self.session.request.call_args_list[0]
        second_call = self.session.request.call_args_list[1]
        self.assertEqual(first_call.args[1], "https://mail.example/api/mailbox/alice/email")
        self.assertEqual(second_call.args[1], "https://mail.example/api/mailbox/alice/email/msg-1")

    def test_fetch_latest_message_treats_empty_mailbox_404_as_no_mail(self):
        """部分 AHEM 部署空邮箱返回 404 + MAILBOX IS EMPTY，应继续轮询而非失败。"""
        self.session.request.return_value = _FakeResponse(
            status_code=404,
            payload={"error": "MAILBOX IS EMPTY!"},
            text='{"error":"MAILBOX IS EMPTY!"}',
        )
        provider = mail_provider.AhemMailProvider(
            {"api_base": "https://mail.example/api", "domain": ["example.test"]},
            self.conf,
        )
        message = provider.fetch_latest_message(
            {"address": "alice@example.test", "mailbox_name": "alice"}
        )
        self.assertIsNone(message)
        self.session.request.assert_called_once()
        args, _ = self.session.request.call_args
        self.assertEqual(args[1], "https://mail.example/api/mailbox/alice/email")

    def test_fetch_latest_message_empty_list_is_no_mail(self):
        self.session.request.return_value = _FakeResponse(payload=[])
        provider = mail_provider.AhemMailProvider(
            {"api_base": "https://mail.example/api", "domain": ["example.test"]},
            self.conf,
        )
        message = provider.fetch_latest_message(
            {"address": "alice@example.test", "mailbox_name": "alice"}
        )
        self.assertIsNone(message)

    def test_factory_creates_ahem_provider(self):
        provider = mail_provider._create_provider(
            {
                "providers": [
                    {
                        "enable": True,
                        "type": "ahem",
                        "api_base": "https://mail.example/api",
                        "domain": ["example.test"],
                        "id": "ahem-1",
                    }
                ]
            }
        )
        try:
            self.assertIsInstance(provider, mail_provider.AhemMailProvider)
            self.assertEqual(provider.name, "ahem")
        finally:
            provider.close()


if __name__ == "__main__":
    unittest.main()
