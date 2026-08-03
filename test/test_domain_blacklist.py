from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

os.environ.setdefault("CHATGPT2API_AUTH_KEY", "test-auth")

from services.register import domain_blacklist as db


class DomainBlacklistTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmpdir.cleanup)
        self.file_path = Path(self._tmpdir.name) / "domain_blacklist.json"
        self._patcher = mock.patch.object(db, "DOMAIN_BLACKLIST_FILE", self.file_path)
        self._patcher.start()
        self.addCleanup(self._patcher.stop)

    def test_normalize_domain_email_and_lower(self) -> None:
        self.assertEqual(db.normalize_domain("Alice@Mail-A.COM"), "mail-a.com")
        self.assertEqual(db.normalize_domain("  Example.ORG.  "), "example.org")
        with self.assertRaises(ValueError):
            db.normalize_domain("")
        with self.assertRaises(ValueError):
            db.normalize_domain("not a domain")

    def test_mask_email(self) -> None:
        self.assertEqual(db.mask_email("ab123@mail-a.com"), "ab***@mail-a.com")
        self.assertEqual(db.mask_email("a@mail-a.com"), "a***@mail-a.com")

    def test_ban_hit_count_and_is_banned(self) -> None:
        pref = "gptmail:abc"
        first = db.ban(
            pref,
            "Mail-A.COM",
            reason="create_account_rejected",
            source="auto",
            sample_email="ab123@mail-a.com",
            raw_hint="create_account_http_400,...",
            provider_type="gptmail",
            provider_label="gptmail#1",
        )
        self.assertEqual(first["domain"], "mail-a.com")
        self.assertEqual(first["hit_count"], 1)
        self.assertEqual(first["sample_email"], "ab***@mail-a.com")
        self.assertTrue(db.is_banned(pref, "mail-a.com"))
        self.assertFalse(db.is_banned(pref, "other.com"))
        self.assertFalse(db.is_banned("other:ref", "mail-a.com"))

        second = db.ban(pref, "mail-a.com", reason="again", source="manual")
        self.assertEqual(second["hit_count"], 2)
        self.assertEqual(second["reason"], "again")
        self.assertEqual(second["source"], "manual")

        entries = db.list_entries(pref)
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["hit_count"], 2)

    def test_filter_domains(self) -> None:
        pref = "gptmail:abc"
        db.ban(pref, "mail-a.com")
        db.ban(pref, "mail-b.com")
        kept = db.filter_domains(
            pref,
            ["Mail-A.com", "keep.example", "mail-b.com", "also.ok"],
        )
        self.assertEqual(kept, ["keep.example", "also.ok"])
        # 其它 provider 不受影响
        self.assertEqual(
            db.filter_domains("other:1", ["mail-a.com", "x.com"]),
            ["mail-a.com", "x.com"],
        )

    def test_unban(self) -> None:
        pref = "gptmail:abc"
        db.ban(pref, "mail-a.com")
        self.assertTrue(db.is_banned(pref, "mail-a.com"))
        self.assertTrue(db.unban(pref, "mail-a.com"))
        self.assertFalse(db.is_banned(pref, "mail-a.com"))
        self.assertFalse(db.unban(pref, "mail-a.com"))

    def test_import_merge_and_replace(self) -> None:
        pref = "gptmail:abc"
        db.ban(pref, "old.com", reason="seed")
        db.ban("other:1", "keep-other.com", reason="other")

        stats = db.import_payload(
            {
                "version": 1,
                "entries": [
                    {
                        "provider_ref": pref,
                        "domain": "new.com",
                        "reason": "import-new",
                        "provider_type": "gptmail",
                    },
                    {
                        "provider_ref": pref,
                        "domain": "old.com",
                        "reason": "import-update",
                    },
                ],
            },
            mode="merge",
        )
        self.assertEqual(stats["added"], 1)
        self.assertEqual(stats["updated"], 1)
        self.assertTrue(db.is_banned(pref, "new.com"))
        entries = db.list_entries(pref)
        old = next(e for e in entries if e["domain"] == "old.com")
        self.assertEqual(old["reason"], "import-update")
        self.assertGreaterEqual(old["hit_count"], 2)

        # replace 限定组：只清 pref，其它组保留
        stats2 = db.import_payload(
            {
                "entries": [
                    {"provider_ref": pref, "domain": "only.com", "reason": "solo"},
                ]
            },
            mode="replace",
            provider_ref=pref,
        )
        self.assertGreaterEqual(stats2["removed"], 1)
        self.assertEqual(stats2["added"], 1)
        self.assertEqual(
            sorted(e["domain"] for e in db.list_entries(pref)),
            ["only.com"],
        )
        self.assertTrue(db.is_banned("other:1", "keep-other.com"))

        # 全量 replace
        stats3 = db.import_payload(
            [{"provider_ref": "x:1", "domain": "fresh.com"}],
            mode="replace",
        )
        self.assertGreaterEqual(stats3["removed"], 1)
        self.assertEqual(stats3["added"], 1)
        self.assertEqual(len(db.list_entries()), 1)
        self.assertTrue(db.is_banned("x:1", "fresh.com"))

    def test_outlook_ban_skipped(self) -> None:
        self.assertTrue(db.is_excluded_provider("outlook_token", "outlook_token:abc"))
        self.assertTrue(db.is_excluded_provider("", "outlook_email_api:xyz"))
        self.assertTrue(db.is_excluded_provider("", "outlook_token#0"))

        result = db.ban(
            "outlook_token:abc",
            "hotmail.com",
            provider_type="outlook_token",
            reason="should-skip",
        )
        self.assertTrue(result.get("skipped"))
        self.assertFalse(db.is_banned("outlook_token:abc", "hotmail.com"))
        self.assertEqual(db.list_entries(), [])

        result2 = db.ban(
            "outlook_email_api:1",
            "outlook.com",
            reason="skip2",
        )
        self.assertTrue(result2.get("skipped"))

    def test_should_ban_from_error_user_samples(self) -> None:
        samples_true = [
            (
                'create_account_http_400: {"message":"You cannot create your account with the given information"}',
                "create_account_rejected",
            ),
            (
                "create_account_http_403 cannot create your account with the given information",
                "create_account_rejected",
            ),
            (
                "user_register_http_400 detail=You cannot create your account with the given information",
                "create_account_rejected",
            ),
            (
                "user_register_http_403 cannot create your account with the given information",
                "create_account_rejected",
            ),
            (
                # 无 HTTP 状态前缀，纯短语仍绝对拉黑
                "Sorry, we cannot create your account with the given information.",
                "create_account_rejected",
            ),
            (
                "Failed to create account. Please try again.",
                "failed_to_create_account",
            ),
            (
                'invalid_request_error: cannot create your account with the given information',
                "create_account_rejected",
            ),
            (
                # create_account HTTP 400 常见：邮箱域名不被 OpenAI 接受
                'create_account_http400,detail={"error":{"message":"The email you provided is not supported.","type":"invalid_request_error"}}',
                "email_not_supported",
            ),
            (
                "The email you provided is not supported.",
                "email_not_supported",
            ),
        ]
        for text, expected_reason in samples_true:
            ok, reason = db.should_ban_from_error(text)
            self.assertTrue(ok, msg=text)
            self.assertEqual(reason, expected_reason, msg=text)

        samples_false = [
            "rate limited 429 too many requests",
            "invalid_state token expired",
            "otp code invalid or expired",
            "cloudflare challenge failed",
            "create_account_http_500 internal error",
            "connection timeout",
            # 单独 type 名不再触发 ban
            "invalid_request_error only",
        ]
        for text in samples_false:
            ok, reason = db.should_ban_from_error(text)
            self.assertFalse(ok, msg=text)
            self.assertEqual(reason, "")

        # 自定义规则
        ok, reason = db.should_ban_from_error(
            "upstream said DOMAIN_PERMANENTLY_BLOCKED for this host",
            custom_rules=[{"id": "custom_block", "match": "DOMAIN_PERMANENTLY_BLOCKED"}],
        )
        self.assertTrue(ok)
        self.assertEqual(reason, "custom_block")

        # match 太短忽略
        ok, _ = db.should_ban_from_error(
            "short xx hit",
            custom_rules=[{"id": "x", "match": "short"}],
        )
        self.assertFalse(ok)

    def test_subdomain_and_wildcard_matching(self) -> None:
        pref = "tempmail:1"
        # 父域 ban 覆盖子域
        db.ban(pref, "example.com", source="manual")
        self.assertTrue(db.is_banned(pref, "example.com"))
        self.assertTrue(db.is_banned(pref, "a.example.com"))
        self.assertTrue(db.is_banned(pref, "x.y.example.com"))
        self.assertFalse(db.is_banned(pref, "notexample.com"))
        self.assertFalse(db.is_banned(pref, "example.org"))

        kept = db.filter_domains(
            pref,
            ["example.com", "a.example.com", "*.example.com", "keep.org", "other.com"],
        )
        self.assertEqual(kept, ["keep.org", "other.com"])

        # 叶子 ban → 基域 / 通配配置停用；兄弟叶子本身未写入时 is_banned 为 False，
        # 但 filter_domains 会去掉基域与 *.base，避免随机子域再发
        pref2 = "tempmail:2"
        db.ban(pref2, "rand.base.mail", source="auto")
        self.assertTrue(db.is_banned(pref2, "rand.base.mail"))
        self.assertTrue(db.is_banned(pref2, "base.mail"))
        self.assertTrue(db.is_banned(pref2, "*.base.mail"))
        self.assertFalse(db.is_banned(pref2, "other.base.mail"))  # 兄弟叶子未单独写入
        kept2 = db.filter_domains(pref2, ["base.mail", "*.base.mail", "ok.com", "rand.base.mail", "other.base.mail"])
        # 基域与通配被拦；兄弟叶子 other.base.mail 仍可能出现在配置列表中（精确条目）
        self.assertEqual(kept2, ["ok.com", "other.base.mail"])

        # 通配 ban
        pref3 = "tempmail:3"
        db.ban(pref3, "*.wild.test", source="manual")
        self.assertTrue(db.is_banned(pref3, "a.wild.test"))
        self.assertTrue(db.is_banned(pref3, "wild.test"))
        self.assertFalse(db.is_banned(pref3, "other.test"))
        kept3 = db.filter_domains(pref3, ["*.wild.test", "x.wild.test", "safe.com"])
        self.assertEqual(kept3, ["safe.com"])

        # normalize 支持通配
        self.assertEqual(db.normalize_domain("*.Example.COM"), "*.example.com")

    def test_import_replace_empty_global_rejected(self) -> None:
        pref = "gptmail:abc"
        db.ban(pref, "keep.com", reason="seed")
        with self.assertRaises(ValueError):
            db.import_payload({"entries": []}, mode="replace")
        # 库未被清空
        self.assertTrue(db.is_banned(pref, "keep.com"))

        # 限定组 replace 空列表允许（清该组）
        stats = db.import_payload({"entries": []}, mode="replace", provider_ref=pref)
        self.assertGreaterEqual(stats["removed"], 1)
        self.assertFalse(db.is_banned(pref, "keep.com"))

    def test_export_payload(self) -> None:
        db.ban("gptmail:1", "a.com")
        payload = db.export_payload("gptmail:1")
        self.assertEqual(payload["version"], 1)
        self.assertEqual(len(payload["entries"]), 1)
        self.assertEqual(payload["entries"][0]["domain"], "a.com")

    def test_raw_hint_truncated(self) -> None:
        long_hint = "x" * 800
        item = db.ban("gptmail:1", "z.com", raw_hint=long_hint)
        self.assertEqual(len(item["raw_hint"]), 500)

    def test_builtin_rules_metadata(self) -> None:
        self.assertTrue(len(db.BUILTIN_BAN_RULES) >= 3)
        ids = {str(rule.get("id") or "") for rule in db.BUILTIN_BAN_RULES}
        self.assertIn("email_not_supported", ids)
        for rule in db.BUILTIN_BAN_RULES:
            self.assertTrue(rule.get("label") or rule.get("description"))
            self.assertNotEqual(rule.get("match"), "invalid_request_error")

    def test_idn_domain_normalize_and_ban(self) -> None:
        pref = "gptmail:idn"
        # 中文域名 → punycode
        puny = db.normalize_domain("例子.com")
        self.assertTrue(puny.startswith("xn--"))
        self.assertEqual(puny, "xn--fsqu00a.com")
        # 邮箱右侧
        self.assertEqual(db.normalize_domain("user@例子.com"), "xn--fsqu00a.com")
        # 通配 + IDN
        self.assertEqual(db.normalize_domain("*.例子.com"), "*.xn--fsqu00a.com")

        db.ban(pref, "例子.com", source="manual")
        self.assertTrue(db.is_banned(pref, "xn--fsqu00a.com"))
        self.assertTrue(db.is_banned(pref, "例子.com"))
        self.assertTrue(db.is_banned(pref, "a.例子.com"))
        kept = db.filter_domains(pref, ["例子.com", "ok.com", "*.例子.com"])
        self.assertEqual(kept, ["ok.com"])

    def test_excluded_provider_fingerprint_ref(self) -> None:
        self.assertTrue(db.is_excluded_provider("", "outlook_token~abc123def456"))
        self.assertTrue(db.is_excluded_provider("", "outlook_email_api~deadbeefcafe"))
        self.assertFalse(db.is_excluded_provider("", "gptmail~abc123def456"))


class ProviderRefStabilityTests(unittest.TestCase):
    def test_build_provider_ref_stable_without_id(self) -> None:
        from services.register.mail_provider import _entries, build_provider_ref

        a = {
            "type": "gptmail",
            "label": "primary",
            "api_base": "https://mail.example/",
            "domain": ["b.com", "a.com"],
            "enable": True,
        }
        b = {
            "type": "gptmail",
            "label": "primary",
            "api_base": "https://mail.example",
            "domain": ["a.com", "b.com"],  # 顺序不同
            "enable": True,
        }
        ref_a = build_provider_ref(a, 1)
        ref_b = build_provider_ref(b, 99)
        self.assertTrue(ref_a.startswith("gptmail~"))
        self.assertEqual(ref_a, ref_b)

        # 有 id 时优先
        with_id = {**a, "id": "stable-1"}
        self.assertEqual(build_provider_ref(with_id), "gptmail:stable-1")

        # 重排 providers 后 ref 不变
        mail = {"providers": [a, {"type": "tempmail_lol", "domain": ["x.com"], "enable": True}]}
        refs1 = [e["provider_ref"] for e in _entries(mail)]
        mail2 = {"providers": [{"type": "tempmail_lol", "domain": ["x.com"], "enable": True}, a]}
        refs2 = [e["provider_ref"] for e in _entries(mail2)]
        self.assertIn(ref_a, refs1)
        self.assertIn(ref_a, refs2)
        # 内容不同 → ref 不同
        other = {**a, "label": "secondary"}
        self.assertNotEqual(build_provider_ref(a), build_provider_ref(other))


if __name__ == "__main__":
    unittest.main()
