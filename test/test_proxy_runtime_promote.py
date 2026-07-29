from __future__ import annotations

import os
import unittest

os.environ.setdefault("CHATGPT2API_AUTH_KEY", "test-auth")

from services.config import (  # noqa: E402
    _normalize_proxy_runtime_settings,
    _promote_legacy_proxy_runtime,
)
from services.proxy_service import ProxyRuntimeProfile  # noqa: E402


class PromoteLegacyProxyRuntimeTests(unittest.TestCase):
    def test_flat_flaresolverr_keys_promoted(self) -> None:
        data = {
            "auth-key": "x",
            "clearance_mode": "flaresolverr",
            "flaresolverr_url": "http://jovemage-flaresolverr:8191",
            "clearance_refresh_interval": 3600,
        }
        promoted = _promote_legacy_proxy_runtime(data)
        runtime = _normalize_proxy_runtime_settings(promoted.get("proxy_runtime"))
        clearance = runtime["clearance"]
        self.assertTrue(runtime["enabled"])
        self.assertTrue(clearance["enabled"])
        self.assertEqual(clearance["mode"], "flaresolverr")
        self.assertEqual(clearance["flaresolverr_url"], "http://jovemage-flaresolverr:8191")
        self.assertEqual(clearance["refresh_interval"], 3600)

        profile = ProxyRuntimeProfile(
            runtime_enabled=bool(runtime["enabled"]),
            clearance=dict(clearance),
        )
        self.assertTrue(profile.clearance_enabled)

    def test_nested_ready_not_overwritten(self) -> None:
        data = {
            "clearance_mode": "flaresolverr",
            "flaresolverr_url": "http://old-flat:8191",
            "proxy_runtime": {
                "enabled": True,
                "egress_mode": "direct",
                "clearance": {
                    "enabled": True,
                    "mode": "flaresolverr",
                    "flaresolverr_url": "http://nested:8191",
                },
            },
        }
        promoted = _promote_legacy_proxy_runtime(data)
        clearance = promoted["proxy_runtime"]["clearance"]
        self.assertEqual(clearance["flaresolverr_url"], "http://nested:8191")

    def test_nested_disabled_with_flat_url_promoted(self) -> None:
        """旧脚本写了扁平键，nested 仍是默认关闭 → 应提升。"""
        data = {
            "flaresolverr_url": "http://jovemage-flaresolverr:8191",
            "clearance_mode": "flaresolverr",
            "proxy_runtime": {
                "enabled": False,
                "egress_mode": "direct",
                "clearance": {
                    "enabled": False,
                    "mode": "none",
                    "flaresolverr_url": "",
                },
            },
        }
        promoted = _promote_legacy_proxy_runtime(data)
        runtime = _normalize_proxy_runtime_settings(promoted.get("proxy_runtime"))
        self.assertTrue(runtime["enabled"])
        self.assertTrue(runtime["clearance"]["enabled"])
        self.assertEqual(runtime["clearance"]["mode"], "flaresolverr")
        self.assertEqual(
            runtime["clearance"]["flaresolverr_url"],
            "http://jovemage-flaresolverr:8191",
        )

    def test_no_flat_keys_unchanged(self) -> None:
        data = {"auth-key": "x", "proxy_pool": []}
        promoted = _promote_legacy_proxy_runtime(data)
        self.assertNotIn("proxy_runtime", promoted)

    def test_clearance_enabled_requires_runtime_enabled(self) -> None:
        """回归：仅开 clearance.enabled 而 runtime.enabled=false 时清障仍关闭。"""
        profile = ProxyRuntimeProfile(
            runtime_enabled=False,
            clearance={"enabled": True, "mode": "flaresolverr", "flaresolverr_url": "http://x:8191"},
        )
        self.assertFalse(profile.clearance_enabled)


if __name__ == "__main__":
    unittest.main()
