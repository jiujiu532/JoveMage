from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

os.environ.setdefault("CHATGPT2API_AUTH_KEY", "test-auth")

from services.register import domain_blacklist as db


class DomainBlacklistFailClosedTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmpdir.cleanup)
        self.file_path = Path(self._tmpdir.name) / "domain_blacklist.json"
        self._patcher = mock.patch.object(db, "DOMAIN_BLACKLIST_FILE", self.file_path)
        self._patcher.start()
        self.addCleanup(self._patcher.stop)

    def test_missing_file_is_empty_store(self) -> None:
        """文件不存在 = 合法空库，未 ban 的域名应放行。"""
        self.assertFalse(self.file_path.exists())
        self.assertFalse(db.is_banned("gptmail:p1", "mail-a.com"))
        self.assertEqual(
            db.filter_domains("gptmail:p1", ["mail-a.com", "mail-b.com"]),
            ["mail-a.com", "mail-b.com"],
        )
        self.assertEqual(db.list_entries(), [])

    def test_corrupt_json_is_banned_fail_closed(self) -> None:
        """主文件损坏且无可用备份：is_banned / filter_domains fail-closed。"""
        self.file_path.write_text("{not-valid-json", encoding="utf-8")
        with self.assertRaises(ValueError) as ctx:
            db.is_banned("gptmail:p1", "mail-a.com")
        self.assertIn("不可用", str(ctx.exception))
        with self.assertRaises(ValueError):
            db.filter_domains("gptmail:p1", ["mail-a.com"])

    def test_corrupt_json_with_good_backup_recovers(self) -> None:
        """主文件损坏但 .bak 可用：应从备份恢复，不 fail-closed。"""
        good = {
            "version": 1,
            "entries": [
                {
                    "provider_ref": "gptmail:p1",
                    "domain": "banned.com",
                    "status": "active",
                    "hit_count": 1,
                }
            ],
        }
        bak = self.file_path.with_suffix(self.file_path.suffix + ".bak")
        self.file_path.write_text("CORRUPT!!!", encoding="utf-8")
        bak.write_text(
            __import__("json").dumps(good, ensure_ascii=False),
            encoding="utf-8",
        )
        self.assertTrue(db.is_banned("gptmail:p1", "banned.com"))
        self.assertFalse(db.is_banned("gptmail:p1", "ok.com"))

    def test_non_dict_json_fail_closed(self) -> None:
        """顶层非 dict（如数组）视为不可解析。"""
        self.file_path.write_text("[1, 2, 3]", encoding="utf-8")
        with self.assertRaises(ValueError):
            db.is_banned("gptmail:p1", "mail-a.com")

    def test_empty_provider_ref_fail_closed(self) -> None:
        """空 provider_ref：is_banned 返回 True；filter_domains 返回空。"""
        self.assertTrue(db.is_banned("", "mail-a.com"))
        self.assertTrue(db.is_banned("   ", "mail-a.com"))
        self.assertEqual(db.filter_domains("", ["mail-a.com", "x.com"]), [])
        self.assertEqual(db.filter_domains("  ", ["mail-a.com"]), [])

    def test_invalid_domain_stays_false(self) -> None:
        """非法 domain 入参属调用方错误：is_banned 返回 False（非黑名单命中）。"""
        self.assertFalse(db.is_banned("gptmail:p1", ""))
        self.assertFalse(db.is_banned("gptmail:p1", "not a domain"))


if __name__ == "__main__":
    unittest.main()
