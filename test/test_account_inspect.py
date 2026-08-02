"""账号全局批量：ids 列表 / 一键巡检统计 / 重登预检 单测。

覆盖：
- GET /api/accounts/ids 同款过滤 + 排除 demo
- inspect 任务统计（auto_remove 开/关两态）
- relogin precheck（AHEM 空 domain / 非 AHEM / Firefly / 无邮箱）
"""
from __future__ import annotations

import os
import unittest
from types import SimpleNamespace
from unittest import mock

os.environ.setdefault("CHATGPT2API_AUTH_KEY", "test-auth")

from api import accounts as accounts_api
from services.register import openai_register
from services.task_manager import BackgroundTask


def _acct(
    token: str,
    *,
    status: str = "正常",
    source_type: str = "web",
    email: str | None = None,
    group_id: str = "",
    is_demo: bool = False,
    last_remote_check_result: str | None = None,
) -> dict:
    item = {
        "access_token": token,
        "status": status,
        "source_type": source_type,
        "email": email,
        "group_id": group_id,
        "is_demo": is_demo,
    }
    if last_remote_check_result is not None:
        item["last_remote_check_result"] = last_remote_check_result
    return item


class FilterAndIdsLogicTests(unittest.TestCase):
    def test_filter_accounts_excludes_demo_and_matches_keyword_status_group_source(self) -> None:
        items = [
            _acct("t-normal", status="正常", email="a@x.test", group_id="g1"),
            _acct("t-limited", status="限流", email="b@x.test", group_id="g1"),
            _acct("t-demo", status="正常", email="demo@x.test", is_demo=True),
            _acct("t-firefly", status="正常", email="ff@x.test", source_type="firefly"),
            _acct("t-other-group", status="正常", email="c@x.test", group_id="g2"),
        ]
        with mock.patch.object(accounts_api.account_service, "list_accounts", return_value=items):
            filtered = accounts_api._filter_accounts(
                keyword="x.test",
                status="normal",
                group_id="g1",
                source_type="chatgpt",
                exclude_demo=True,
            )
        tokens = [a["access_token"] for a in filtered]
        self.assertEqual(tokens, ["t-normal"])

    def test_filter_accounts_exclude_firefly_for_inspect(self) -> None:
        items = [
            _acct("t-web", source_type="web"),
            _acct("t-oauth", source_type="oauth_login"),
            _acct("t-ff", source_type="firefly"),
        ]
        filtered = accounts_api._filter_accounts(
            source_type="all",
            exclude_firefly=True,
            items=items,
        )
        self.assertEqual(
            sorted(a["access_token"] for a in filtered),
            ["t-oauth", "t-web"],
        )

    def test_ids_logic_returns_tokens_and_total(self) -> None:
        items = [
            _acct("tok-1", email="u1@a.test"),
            _acct("tok-2", email="u2@a.test", is_demo=True),
            _acct("tok-3", email="u3@b.test", status="异常"),
        ]
        with mock.patch.object(accounts_api.account_service, "list_accounts", return_value=items):
            filtered = accounts_api._filter_accounts(
                keyword="",
                status="all",
                group_id="all",
                source_type="all",
                exclude_demo=True,
            )
        tokens = [a["access_token"] for a in filtered]
        self.assertEqual(set(tokens), {"tok-1", "tok-3"})
        self.assertEqual(len(tokens), 2)

    def test_resolve_inspect_filter_params_by_scope(self) -> None:
        self.assertEqual(
            accounts_api._resolve_inspect_filter_params("all", keyword="x", status="normal"),
            {"keyword": "", "status": "all", "group_id": "all", "source_type": "all"},
        )
        self.assertEqual(
            accounts_api._resolve_inspect_filter_params(
                "channel", keyword="x", status="normal", source_type="chatgpt"
            ),
            {"keyword": "", "status": "all", "group_id": "all", "source_type": "chatgpt"},
        )
        self.assertEqual(
            accounts_api._resolve_inspect_filter_params(
                "filter", keyword="kw", status="limited", group_id="g1", source_type="web"
            ),
            {"keyword": "kw", "status": "limited", "group_id": "g1", "source_type": "web"},
        )


class InspectStatsTests(unittest.TestCase):
    def _run_inspect(self, tokens: list[str], side_effect) -> dict:
        task = BackgroundTask("test-inspect", "account_inspect", total=len(tokens))
        with mock.patch.object(
            accounts_api.account_service, "fetch_remote_info", side_effect=side_effect
        ), mock.patch.object(accounts_api.log_service, "add"):
            accounts_api._run_account_inspect(task, tokens, scope="all")
        self.assertEqual(task.status, "completed")
        return dict(task.result)

    def test_auto_remove_on_removed_invalid_and_exhausted(self) -> None:
        """auto_remove 开：invalid 消失 → removed_invalid；额度尽消失 → removed_quota_exhausted。"""
        store = {
            "tok-ok": _acct("tok-ok", status="正常"),
            "tok-bad": _acct("tok-bad", status="正常"),
            "tok-exhausted": _acct("tok-exhausted", status="正常"),
        }

        def get_account(token: str):
            item = store.get(token)
            return dict(item) if item else None

        def fetch(token: str, event: str = "inspect", remove_invalid=None):
            if token == "tok-ok":
                store["tok-ok"] = _acct("tok-ok", status="正常")
                return store["tok-ok"]
            if token == "tok-bad":
                # 模拟 handle_invalid_token 删除后 re-raise
                store.pop("tok-bad", None)
                raise RuntimeError("invalid access token")
            if token == "tok-exhausted":
                # 模拟 update_account 因额度尽自动移除，不抛错
                store.pop("tok-exhausted", None)
                return {"access_token": token, "_removed_after_refresh": True}
            raise AssertionError(f"unexpected token {token}")

        with mock.patch.object(accounts_api.account_service, "get_account", side_effect=get_account):
            result = self._run_inspect(
                ["tok-ok", "tok-bad", "tok-exhausted"],
                fetch,
            )

        self.assertEqual(result["total"], 3)
        self.assertEqual(result["processed"], 3)
        self.assertEqual(result["ok"], 1)
        self.assertEqual(result["removed_invalid"], 1)
        self.assertEqual(result["removed_quota_exhausted"], 1)
        self.assertEqual(result["marked_invalid"], 0)
        self.assertEqual(result["marked_rate_limited"], 0)
        self.assertEqual(result["refresh_failed"], 0)

    def test_auto_remove_off_marks_without_delete(self) -> None:
        """auto_remove 关：invalid → marked_invalid；额度尽 → marked_rate_limited。"""
        store = {
            "tok-ok": _acct("tok-ok", status="正常"),
            "tok-bad": _acct("tok-bad", status="正常"),
            "tok-exhausted": _acct("tok-exhausted", status="正常"),
            "tok-net": _acct("tok-net", status="正常"),
        }

        def get_account(token: str):
            item = store.get(token)
            return dict(item) if item else None

        def fetch(token: str, event: str = "inspect", remove_invalid=None):
            if token == "tok-ok":
                store["tok-ok"] = _acct("tok-ok", status="正常")
                return store["tok-ok"]
            if token == "tok-bad":
                # 模拟 _record_invalid_token_seen 标异常后 re-raise，不删
                store["tok-bad"] = _acct(
                    "tok-bad", status="异常", last_remote_check_result="invalid"
                )
                raise RuntimeError("invalid access token")
            if token == "tok-exhausted":
                store["tok-exhausted"] = _acct(
                    "tok-exhausted", status="限流", last_remote_check_result="exhausted"
                )
                return store["tok-exhausted"]
            if token == "tok-net":
                # 网络失败：状态不变
                raise ConnectionError("proxy timeout")
            raise AssertionError(f"unexpected token {token}")

        with mock.patch.object(accounts_api.account_service, "get_account", side_effect=get_account):
            result = self._run_inspect(
                ["tok-ok", "tok-bad", "tok-exhausted", "tok-net"],
                fetch,
            )

        self.assertEqual(result["total"], 4)
        self.assertEqual(result["processed"], 4)
        self.assertEqual(result["ok"], 1)
        self.assertEqual(result["removed_invalid"], 0)
        self.assertEqual(result["removed_quota_exhausted"], 0)
        self.assertEqual(result["marked_invalid"], 1)
        self.assertEqual(result["marked_rate_limited"], 1)
        self.assertEqual(result["refresh_failed"], 1)
        self.assertTrue(any("proxy timeout" in e or "timeout" in e for e in result["errors"]))

    def test_classify_removed_account_helpers(self) -> None:
        self.assertEqual(
            accounts_api._classify_removed_account("异常", ""),
            "removed_invalid",
        )
        self.assertEqual(
            accounts_api._classify_removed_account("限流", ""),
            "removed_quota_exhausted",
        )
        self.assertEqual(
            accounts_api._classify_removed_account("正常", "exhausted"),
            "removed_quota_exhausted",
        )
        self.assertEqual(
            accounts_api._classify_removed_account("正常", "invalid"),
            "removed_invalid",
        )
        self.assertEqual(
            accounts_api._classify_removed_account("正常", ""),
            "removed_invalid",
        )


class ReloginPrecheckTests(unittest.TestCase):
    def setUp(self) -> None:
        self.previous_mail = openai_register.config.get("mail")
        openai_register.config["mail"] = {
            "providers": [
                {
                    "type": "ahem",
                    "enable": True,
                    "api_base": "https://ahem.example/api",
                    "domain": [],  # 空 domain = 任意后缀可重建
                }
            ]
        }

    def tearDown(self) -> None:
        openai_register.config["mail"] = self.previous_mail

    def test_precheck_ahem_empty_domain_can(self) -> None:
        accounts = {
            "tok-ahem": _acct("tok-ahem", email="user@baidu.jojoy.bond"),
        }

        def get_account(token: str):
            item = accounts.get(token)
            return dict(item) if item else None

        with mock.patch.object(accounts_api.account_service, "get_account", side_effect=get_account):
            result = accounts_api._precheck_relogin_tokens(["tok-ahem"])
        self.assertEqual(result["can"], 1)
        self.assertEqual(result["skip"], 0)
        self.assertEqual(result["can_tokens"], ["tok-ahem"])
        self.assertEqual(result["skip_reasons"], {})

    def test_precheck_non_ahem_domain_skipped(self) -> None:
        # 配置限定域名后，其它后缀不可重建
        openai_register.config["mail"] = {
            "providers": [
                {
                    "type": "ahem",
                    "enable": True,
                    "api_base": "https://ahem.example/api",
                    "domain": ["allowed.test"],
                }
            ]
        }
        accounts = {
            "tok-other": _acct("tok-other", email="user@other.test"),
        }

        def get_account(token: str):
            item = accounts.get(token)
            return dict(item) if item else None

        with mock.patch.object(accounts_api.account_service, "get_account", side_effect=get_account):
            result = accounts_api._precheck_relogin_tokens(["tok-other"])
        self.assertEqual(result["can"], 0)
        self.assertEqual(result["skip"], 1)
        self.assertEqual(result["skip_reasons"].get("非 AHEM 邮箱"), 1)

    def test_precheck_firefly_and_no_email(self) -> None:
        accounts = {
            "tok-ff": _acct("tok-ff", email="ff@x.test", source_type="firefly"),
            "tok-no-mail": _acct("tok-no-mail", email=None),
            "tok-missing": None,  # get_account 返回 None
        }

        def get_account(token: str):
            if token == "tok-missing":
                return None
            item = accounts.get(token)
            return dict(item) if item else None

        with mock.patch.object(accounts_api.account_service, "get_account", side_effect=get_account):
            result = accounts_api._precheck_relogin_tokens(
                ["tok-ff", "tok-no-mail", "tok-missing"]
            )
        self.assertEqual(result["can"], 0)
        self.assertEqual(result["skip"], 3)
        self.assertEqual(result["skip_reasons"].get("Firefly 账号不支持重登"), 1)
        self.assertEqual(result["skip_reasons"].get("无邮箱"), 2)


if __name__ == "__main__":
    unittest.main()
