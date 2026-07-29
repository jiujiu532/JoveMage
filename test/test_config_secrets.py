from __future__ import annotations

import os
import unittest

os.environ.setdefault("CHATGPT2API_AUTH_KEY", "test-auth")

from services.config import (  # noqa: E402
    _preserve_masked_secrets,
    _promote_legacy_proxy_runtime,
    _normalize_proxy_runtime_settings,
    _normalize_backup_settings,
    _normalize_image_storage_settings,
    _public_backup_settings,
    _public_image_storage_settings,
)


class PromoteIdempotentTests(unittest.TestCase):
    """B14：promote 只读、幂等，不用扁平键反复强制开启已接管的 nested。"""

    def test_flat_keys_no_nested_promote_once(self) -> None:
        data = {
            "clearance_mode": "flaresolverr",
            "flaresolverr_url": "http://jovemage-flaresolverr:8191",
        }
        promoted = _promote_legacy_proxy_runtime(data)
        runtime = _normalize_proxy_runtime_settings(promoted.get("proxy_runtime"))
        self.assertTrue(runtime["enabled"])
        self.assertTrue(runtime["clearance"]["enabled"])
        self.assertEqual(runtime["clearance"]["mode"], "flaresolverr")
        self.assertEqual(runtime["clearance"]["flaresolverr_url"], "http://jovemage-flaresolverr:8191")

    def test_idempotent_repeated_calls_same_result(self) -> None:
        data = {
            "clearance_mode": "flaresolverr",
            "flaresolverr_url": "http://flare:8191",
        }
        once = _promote_legacy_proxy_runtime(data)
        twice = _promote_legacy_proxy_runtime(once)
        self.assertEqual(once, twice)

    def test_existing_nested_disabled_not_force_enabled(self) -> None:
        """用户 UI 关掉清障（nested.enabled=false）后，扁平键残留不得再强制打开。"""
        data = {
            "clearance_mode": "flaresolverr",
            "flaresolverr_url": "http://flare:8191",
            "proxy_runtime": {
                "enabled": True,
                "egress_mode": "direct",
                "clearance": {"enabled": False, "mode": "none", "flaresolverr_url": ""},
            },
        }
        promoted = _promote_legacy_proxy_runtime(data)
        runtime = _normalize_proxy_runtime_settings(promoted.get("proxy_runtime"))
        self.assertFalse(runtime["clearance"]["enabled"])
        self.assertEqual(runtime["clearance"]["mode"], "none")

    def test_new_install_flat_plus_nested_keeps_nested(self) -> None:
        """新 install.sh 同时写扁平键与 nested（关闭态），不得被扁平键覆盖。"""
        data = {
            "clearance_mode": "flaresolverr",
            "flaresolverr_url": "http://flare:8191",
            "proxy_runtime": {
                "enabled": True,
                "egress_mode": "direct",
                "clearance": {"enabled": True, "mode": "flaresolverr", "flaresolverr_url": "http://flare:8191"},
            },
        }
        promoted = _promote_legacy_proxy_runtime(data)
        runtime = _normalize_proxy_runtime_settings(promoted.get("proxy_runtime"))
        self.assertTrue(runtime["clearance"]["enabled"])
        self.assertEqual(runtime["clearance"]["flaresolverr_url"], "http://flare:8191")

    def test_no_flat_keys_no_inject(self) -> None:
        self.assertNotIn("proxy_runtime", _promote_legacy_proxy_runtime({"auth-key": "x"}))


class MaskedSecretsTests(unittest.TestCase):
    """B15：backup/image_storage/ai_review 密钥脱敏回传 + 保存时空值/哨兵保留旧值。"""

    def test_public_backup_masks_secrets(self) -> None:
        settings = _normalize_backup_settings(
            {"secret_access_key": "real-secret", "passphrase": "real-pass", "bucket": "b"}
        )
        public = _public_backup_settings(settings)
        self.assertEqual(public["secret_access_key"], "")
        self.assertEqual(public["passphrase"], "")
        self.assertTrue(public["has_secret_access_key"])
        self.assertTrue(public["has_passphrase"])

    def test_public_image_storage_masks_password(self) -> None:
        settings = _normalize_image_storage_settings({"webdav_password": "real-pass", "enabled": True, "mode": "webdav"})
        public = _public_image_storage_settings(settings)
        self.assertEqual(public["webdav_password"], "")
        self.assertTrue(public["has_webdav_password"])

    def test_preserve_empty_keeps_previous(self) -> None:
        prev = {"backup": {"secret_access_key": "old-secret", "passphrase": "old-pass"}}
        nxt = {"backup": {"secret_access_key": "", "passphrase": "", "has_secret_access_key": True, "has_passphrase": True}}
        _preserve_masked_secrets(prev, nxt)
        self.assertEqual(nxt["backup"]["secret_access_key"], "old-secret")
        self.assertEqual(nxt["backup"]["passphrase"], "old-pass")
        self.assertNotIn("has_secret_access_key", nxt["backup"])

    def test_preserve_sentinel_keeps_previous(self) -> None:
        prev = {"backup": {"secret_access_key": "old-secret"}}
        nxt = {"backup": {"secret_access_key": "********"}}
        _preserve_masked_secrets(prev, nxt)
        self.assertEqual(nxt["backup"]["secret_access_key"], "old-secret")

    def test_preserve_new_value_overrides(self) -> None:
        prev = {"backup": {"secret_access_key": "old-secret"}}
        nxt = {"backup": {"secret_access_key": "brand-new"}}
        _preserve_masked_secrets(prev, nxt)
        self.assertEqual(nxt["backup"]["secret_access_key"], "brand-new")

    def test_preserve_image_storage_and_ai_review(self) -> None:
        prev = {
            "image_storage": {"webdav_password": "old-wp"},
            "ai_review": {"api_key": "old-key"},
        }
        nxt = {
            "image_storage": {"webdav_password": "", "has_webdav_password": True},
            "ai_review": {"api_key": "", "has_api_key": True},
        }
        _preserve_masked_secrets(prev, nxt)
        self.assertEqual(nxt["image_storage"]["webdav_password"], "old-wp")
        self.assertEqual(nxt["ai_review"]["api_key"], "old-key")

    def test_preserve_no_section_untouched(self) -> None:
        prev = {"backup": {"secret_access_key": "old"}}
        nxt = {"other": 1}
        _preserve_masked_secrets(prev, nxt)
        self.assertEqual(nxt, {"other": 1})


if __name__ == "__main__":
    unittest.main()
