from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

os.environ.setdefault("CHATGPT2API_AUTH_KEY", "test-auth")

from fastapi.testclient import TestClient

from api.register import create_router
from services.register import domain_blacklist


class DomainBlacklistApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmpdir = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmpdir.name)
        self.store_path = self.tmp / "domain_blacklist.json"

        self.path_patch = mock.patch.object(domain_blacklist, "DOMAIN_BLACKLIST_FILE", self.store_path)
        self.path_patch.start()
        self.addCleanup(self.path_patch.stop)
        self.addCleanup(self._tmpdir.cleanup)

        # 隔离 provider 列表：无 register 配置时 providers 为空
        self.register_patch = mock.patch(
            "api.register.register_service.get",
            return_value={"mail": {"providers": [
                {"id": "p1", "type": "gptmail", "enable": True, "label": "Gpt"},
                {"id": "o1", "type": "outlook_token", "enable": True},
            ]}},
        )
        self.register_patch.start()
        self.addCleanup(self.register_patch.stop)

        self.rules_patch = mock.patch(
            "api.register.config.get_domain_ban_rules",
            return_value=[{"id": "custom1", "match": "this is a long enough rule", "enabled": True}],
        )
        self.rules_patch.start()
        self.addCleanup(self.rules_patch.stop)

        # 绕过鉴权
        self.auth_patch = mock.patch("api.register.require_admin", return_value={"role": "admin"})
        self.auth_patch.start()
        self.addCleanup(self.auth_patch.stop)

        from fastapi import FastAPI

        app = FastAPI()
        app.include_router(create_router())
        self.client = TestClient(app)
        self.headers = {"Authorization": "Bearer test-auth"}

    def test_list_returns_entries_providers_and_rules(self) -> None:
        domain_blacklist.ban("gptmail:p1", "bad.example.com", reason="manual test", source="manual")
        resp = self.client.get("/api/register/domain-blacklist", headers=self.headers)
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIn("entries", data)
        self.assertIn("providers", data)
        self.assertIn("builtin_rules", data)
        self.assertIn("custom_rules", data)
        # outlook_token 应被排除
        refs = {p["provider_ref"] for p in data["providers"]}
        self.assertIn("gptmail:p1", refs)
        self.assertTrue(all(not str(r).startswith("outlook_token") for r in refs))
        self.assertTrue(any(e.get("domain") == "bad.example.com" for e in data["entries"]))
        self.assertTrue(len(data["builtin_rules"]) >= 1)
        self.assertEqual(data["custom_rules"][0]["id"], "custom1")

    def test_ban_and_unban(self) -> None:
        ban = self.client.post(
            "/api/register/domain-blacklist",
            headers=self.headers,
            json={"provider_ref": "gptmail:p1", "domain": "spam.test", "reason": "bad"},
        )
        self.assertEqual(ban.status_code, 200)
        entry = ban.json()["entry"]
        self.assertEqual(entry["domain"], "spam.test")
        self.assertEqual(entry["source"], "manual")
        self.assertTrue(domain_blacklist.is_banned("gptmail:p1", "spam.test"))

        unban = self.client.request(
            "DELETE",
            "/api/register/domain-blacklist",
            headers=self.headers,
            json={"provider_ref": "gptmail:p1", "domain": "spam.test"},
        )
        self.assertEqual(unban.status_code, 200)
        self.assertTrue(unban.json()["removed"])
        self.assertFalse(domain_blacklist.is_banned("gptmail:p1", "spam.test"))

    def test_export_import(self) -> None:
        domain_blacklist.ban("gptmail:p1", "a.example.com", source="manual")
        exp = self.client.get(
            "/api/register/domain-blacklist/export",
            headers=self.headers,
            params={"provider_ref": "gptmail:p1"},
        )
        self.assertEqual(exp.status_code, 200)
        payload = exp.json()
        self.assertTrue(any(e.get("domain") == "a.example.com" for e in payload["entries"]))

        domain_blacklist.unban("gptmail:p1", "a.example.com")
        imp = self.client.post(
            "/api/register/domain-blacklist/import",
            headers=self.headers,
            json={"payload": payload, "mode": "merge", "provider_ref": "gptmail:p1"},
        )
        self.assertEqual(imp.status_code, 200)
        result = imp.json()["result"]
        self.assertGreaterEqual(result.get("added", 0) + result.get("updated", 0), 1)
        self.assertTrue(domain_blacklist.is_banned("gptmail:p1", "a.example.com"))

    def test_import_replace_empty_global_rejected(self) -> None:
        domain_blacklist.ban("gptmail:p1", "keep.me", source="manual")
        resp = self.client.post(
            "/api/register/domain-blacklist/import",
            headers=self.headers,
            json={"payload": {"entries": []}, "mode": "replace"},
        )
        self.assertEqual(resp.status_code, 400)
        self.assertTrue(domain_blacklist.is_banned("gptmail:p1", "keep.me"))


class DomainBanRulesConfigTests(unittest.TestCase):
    def test_normalize_domain_ban_rules(self) -> None:
        from services.config import _normalize_domain_ban_rules

        rules = _normalize_domain_ban_rules(
            [
                {"id": "ok", "match": "long enough phrase", "enabled": False},
                {"match": "short"},  # 丢弃
                {"match": "   "},  # 丢弃
                "not-a-dict",
                {"match": "another valid match string"},
            ]
        )
        self.assertEqual(len(rules), 2)
        self.assertEqual(rules[0]["id"], "ok")
        self.assertFalse(rules[0]["enabled"])
        self.assertEqual(rules[1]["match"], "another valid match string")
        self.assertTrue(rules[1]["enabled"])


if __name__ == "__main__":
    unittest.main()
