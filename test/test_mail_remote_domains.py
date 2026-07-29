"""留空域名：拉远端可用域 → 黑名单过滤 → 轮询后显式建箱。"""
from __future__ import annotations

import os
import unittest
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


class AhemRemoteDomainTests(unittest.TestCase):
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

    def test_empty_domain_fetches_properties_and_filters_ban(self):
        self.session.request.return_value = _FakeResponse(
            payload={"allowedDomains": ["ok.example", "banned.example", "ok.example"]}
        )
        provider = mail_provider.AhemMailProvider(
            {"api_base": "https://mail.example/api", "domain": [], "provider_ref": "ahem:1"},
            self.conf,
        )
        with mock.patch(
            "services.register.domain_blacklist.filter_domains",
            side_effect=lambda ref, domains: [d for d in domains if d != "banned.example"],
        ) as filt:
            mailbox = provider.create_mailbox("alice")
        self.assertEqual(mailbox["address"], "alice@ok.example")
        filt.assert_called()
        args, _ = self.session.request.call_args
        self.assertEqual(args[0], "GET")
        self.assertTrue(str(args[1]).endswith("/properties"))

    def test_empty_domain_all_banned_raises(self):
        self.session.request.return_value = _FakeResponse(
            payload={"allowedDomains": ["banned.example"]}
        )
        provider = mail_provider.AhemMailProvider(
            {"api_base": "https://mail.example/api", "domain": [], "provider_ref": "ahem:1"},
            self.conf,
        )
        with mock.patch(
            "services.register.domain_blacklist.filter_domains",
            return_value=[],
        ):
            with self.assertRaisesRegex(RuntimeError, "域名已拉黑"):
                provider.create_mailbox("alice")


class JoveMailRemoteDomainTests(unittest.TestCase):
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
            "provider_ref": "jovemail:1",
            **extra,
        }
        return mail_provider.JoveMailProvider(entry, self.conf)

    def test_empty_domain_uses_available_then_generate(self):
        available = {
            "success": True,
            "data": {
                "domains": ["pub.example"],
                "public_domains": [
                    {"domain": "pub.example", "root_ready": True, "capabilities": ["root_mailbox"]},
                    {"domain": "banned.example", "root_ready": True, "capabilities": ["root_mailbox"]},
                ],
                "private_domains": [],
            },
        }
        generated = {
            "success": True,
            "data": {
                "email": "alice@pub.example",
                "local_part": "alice",
                "host": "pub.example",
                "domain_id": 1,
            },
        }
        self.session.request.side_effect = [
            _FakeResponse(payload=available),
            _FakeResponse(status_code=201, payload=generated),
        ]
        provider = self._provider(domain=[])
        with mock.patch(
            "services.register.domain_blacklist.filter_domains",
            side_effect=lambda ref, domains: [d for d in domains if d != "banned.example"],
        ):
            mailbox = provider.create_mailbox("alice")
        self.assertEqual(mailbox["address"], "alice@pub.example")
        calls = self.session.request.call_args_list
        self.assertEqual(calls[0][0][0], "GET")
        self.assertTrue(str(calls[0][0][1]).endswith("/api/domains/available"))
        self.assertEqual(calls[1][0][0], "POST")
        self.assertTrue(str(calls[1][0][1]).endswith("/api/generate-email"))
        self.assertEqual(calls[1][1]["json"]["domain"], "pub.example")

    def test_configured_domain_skips_available(self):
        self.session.request.return_value = _FakeResponse(
            status_code=201,
            payload={
                "success": True,
                "data": {
                    "email": "alice@cfg.example",
                    "local_part": "alice",
                    "host": "cfg.example",
                },
            },
        )
        provider = self._provider(domain=["cfg.example"])
        mailbox = provider.create_mailbox("alice")
        self.assertEqual(mailbox["address"], "alice@cfg.example")
        self.assertEqual(self.session.request.call_count, 1)
        args, kwargs = self.session.request.call_args
        self.assertTrue(str(args[1]).endswith("/api/generate-email"))
        self.assertEqual(kwargs["json"]["domain"], "cfg.example")


class YydsRemoteDomainTests(unittest.TestCase):
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

    def test_api_base_without_v1_is_normalized(self):
        provider = mail_provider.YydsMailProvider(
            {"api_base": "https://maliapi.example/", "api_key": "AC-test", "domain": []},
            self.conf,
        )
        self.assertEqual(provider.api_base, "https://maliapi.example/v1")

    def test_api_base_with_v1_not_doubled(self):
        provider = mail_provider.YydsMailProvider(
            {"api_base": "https://maliapi.example/v1/", "api_key": "AC-test", "domain": []},
            self.conf,
        )
        self.assertEqual(provider.api_base, "https://maliapi.example/v1")

    def test_empty_domain_lists_then_creates(self):
        domains_payload = {
            "success": True,
            "data": [
                {
                    "domain": "ok.example",
                    "isVerified": True,
                    "isMxValid": True,
                    "isPublic": True,
                },
                {
                    "domain": "bad.example",
                    "isVerified": True,
                    "isMxValid": True,
                    "isPublic": True,
                },
                {
                    "domain": "unverified.example",
                    "isVerified": False,
                    "isMxValid": True,
                    "isPublic": True,
                },
            ],
        }
        create_payload = {
            "success": True,
            "data": {"address": "alice@ok.example", "token": "tok-1", "id": "acc-1"},
        }
        self.session.request.side_effect = [
            _FakeResponse(payload=domains_payload),
            _FakeResponse(status_code=201, payload=create_payload),
        ]
        provider = mail_provider.YydsMailProvider(
            {
                "api_base": "https://maliapi.example",
                "api_key": "AC-test",
                "domain": [],
                "provider_ref": "yyds:1",
            },
            self.conf,
        )
        with mock.patch(
            "services.register.domain_blacklist.filter_domains",
            side_effect=lambda ref, domains: [d for d in domains if d != "bad.example"],
        ):
            mailbox = provider.create_mailbox("alice")
        self.assertEqual(mailbox["address"], "alice@ok.example")
        self.assertEqual(mailbox["token"], "tok-1")
        calls = self.session.request.call_args_list
        self.assertEqual(str(calls[0][0][1]), "https://maliapi.example/v1/domains")
        self.assertEqual(str(calls[1][0][1]), "https://maliapi.example/v1/accounts")
        self.assertEqual(calls[1][1]["json"]["domain"], "ok.example")

    def test_empty_domain_no_usable_raises(self):
        self.session.request.return_value = _FakeResponse(
            payload={"success": True, "data": []}
        )
        provider = mail_provider.YydsMailProvider(
            {
                "api_base": "https://maliapi.example/v1",
                "api_key": "AC-test",
                "domain": [],
                "provider_ref": "yyds:1",
            },
            self.conf,
        )
        with self.assertRaisesRegex(RuntimeError, "无可用公共域"):
            provider.create_mailbox("alice")

    def test_html_response_raises_clear_error(self):
        class _HtmlResponse:
            status_code = 200
            text = "<!doctype html><html><body>SPA</body></html>"
            headers = {"content-type": "text/html"}

            def json(self):
                raise ValueError("Expecting value: line 1 column 1 (char 0)")

        self.session.request.return_value = _HtmlResponse()
        provider = mail_provider.YydsMailProvider(
            {
                "api_base": "https://mail.example/",
                "api_key": "AC-test",
                "domain": [],
                "provider_ref": "yyds:1",
            },
            self.conf,
        )
        with self.assertRaisesRegex(RuntimeError, "返回非 JSON"):
            provider.create_mailbox("alice")


class TempMailDomainTests(unittest.TestCase):
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

    def test_configured_domain_uses_round_robin_not_random(self):
        self.session.request.return_value = _FakeResponse(
            payload={"address": "x@a.example", "token": "t1"}
        )
        provider = mail_provider.TempMailLolProvider(
            {"api_key": "k", "domain": ["a.example", "b.example"], "provider_ref": "tm:1"},
            self.conf,
        )
        with mock.patch(
            "services.register.domain_blacklist.filter_domains",
            side_effect=lambda ref, domains: list(domains),
        ):
            provider.create_mailbox("user")
        args, kwargs = self.session.request.call_args
        self.assertIn(kwargs["json"]["domain"], ("a.example", "b.example"))
        self.assertEqual(kwargs["json"]["prefix"], "user")

    def test_empty_domain_post_create_ban_check(self):
        self.session.request.return_value = _FakeResponse(
            payload={"address": "x@banned.example", "token": "t1"}
        )
        provider = mail_provider.TempMailLolProvider(
            {"api_key": "k", "domain": [], "provider_ref": "tm:1"},
            self.conf,
        )
        with mock.patch.object(
            mail_provider,
            "_assert_domain_not_banned",
            side_effect=RuntimeError("域名已拉黑: banned.example"),
        ):
            with self.assertRaisesRegex(RuntimeError, "域名已拉黑"):
                provider.create_mailbox()


if __name__ == "__main__":
    unittest.main()
