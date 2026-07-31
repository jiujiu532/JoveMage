from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

os.environ.setdefault("CHATGPT2API_AUTH_KEY", "test-auth")

from services.backends import firefly_entities as entities  # noqa: E402


def _first_callable(*names):
    for name in names:
        fn = getattr(entities, name, None)
        if callable(fn):
            return fn
    return None


def _parse_entity_mentions(prompt: str):
    fn = _first_callable(
        "parse_entity_mentions",
        "parse_entity_names",
        "entity_names_from_prompt",
        "extract_entity_mentions",
    )
    if fn is None:
        raise AssertionError(
            "missing parse_entity_mentions "
            "(expected parse_entity_mentions / entity_names_from_prompt)"
        )
    return fn(prompt)


def _build_entity_blob(entity: dict, **kwargs):
    fn = _first_callable(
        "build_entity_blob",
        "build_entity_reference_blob",
        "entity_to_blob",
        "build_kling_entity_blob",
    )
    if fn is None:
        raise AssertionError(
            "missing build_entity_blob "
            "(expected build_entity_blob / build_entity_reference_blob)"
        )
    try:
        return fn(entity, **kwargs)
    except TypeError:
        return fn(entity)


def _required_account_id(prompt: str):
    fn = _first_callable(
        "required_account_id_for_prompt",
        "account_id_for_prompt",
        "resolve_account_id_for_prompt",
        "pinned_account_id_for_prompt",
    )
    if fn is None:
        raise AssertionError(
            "missing required_account_id_for_prompt "
            "(expected required_account_id_for_prompt / account_id_for_prompt)"
        )
    return fn(prompt)


def _bind_entity(*args, **kwargs):
    fn = _first_callable("bind_entity", "upsert_entity", "save_entity")
    if fn is None:
        raise AssertionError("missing bind_entity")
    return fn(*args, **kwargs)


def _get_entity(name: str):
    fn = _first_callable("get_entity", "find_entity", "get_entity_by_name")
    if fn is None:
        raise AssertionError("missing get_entity")
    return fn(name)


def _list_entities():
    fn = _first_callable("list_entities", "list_all_entities", "all_entities")
    if fn is None:
        raise AssertionError("missing list_entities")
    return fn()


def _unbind_entity(name: str):
    fn = _first_callable(
        "unbind_entity",
        "remove_entity",
        "delete_entity_binding",
        "delete_entity",
    )
    if fn is None:
        raise AssertionError("missing unbind_entity")
    return fn(name)


def _clear_cache():
    fn = _first_callable(
        "clear_entities_cache",
        "reset_entities_cache",
        "reload_entities",
    )
    if fn is not None:
        fn()


class ParseEntityMentionsTests(unittest.TestCase):
    """parse_entity_mentions：提取 @entity:Name。"""

    def test_parse_single_entity_name(self) -> None:
        """'a cat @entity:Fluffy walking' → ['Fluffy']。"""
        names = _parse_entity_mentions("a cat @entity:Fluffy walking")
        self.assertEqual(list(names), ["Fluffy"])

    def test_parse_multiple_and_dedupe(self) -> None:
        """多引用保序去重。"""
        names = _parse_entity_mentions(
            "@entity:Alpha meets @entity:Beta and @entity:Alpha again"
        )
        self.assertEqual(list(names), ["Alpha", "Beta"])

    def test_parse_none(self) -> None:
        """无实体引用返回空列表。"""
        self.assertEqual(list(_parse_entity_mentions("plain prompt")), [])
        self.assertEqual(list(_parse_entity_mentions("")), [])


class BuildEntityBlobTests(unittest.TestCase):
    """build_entity_blob：usage=element + 字段齐。"""

    def test_build_entity_blob_fields(self) -> None:
        """creativeCloudFileId + mention_id → usage=element 且字段齐全。"""
        blob = _build_entity_blob(
            {
                "creativeCloudFileId": "urn:aaid:sc:US:file-1",
                "mention_id": "m-123",
            }
        )
        self.assertIsInstance(blob, dict)
        self.assertEqual(blob.get("usage"), "element")
        self.assertEqual(
            str(blob.get("creativeCloudFileId") or ""),
            "urn:aaid:sc:US:file-1",
        )
        mention = blob.get("mention") or {}
        self.assertEqual(str(mention.get("id") or ""), "m-123")


class RequiredAccountIdForPromptTests(unittest.TestCase):
    """required_account_id_for_prompt：绑定实体 → account_id；否则 None。"""

    def setUp(self) -> None:
        self._tmpdir = tempfile.TemporaryDirectory()
        self._path = Path(self._tmpdir.name) / "firefly_entities.json"
        self._path.write_text("{}", encoding="utf-8")
        # 指向临时文件，避免污染 data/
        self._patches = []
        if hasattr(entities, "ENTITIES_FILE"):
            self._patches.append(
                mock.patch.object(entities, "ENTITIES_FILE", self._path)
            )
        if hasattr(entities, "_STORE"):
            self._patches.append(mock.patch.object(entities, "_STORE", None))
        for p in self._patches:
            p.start()
        _clear_cache()

    def tearDown(self) -> None:
        for p in reversed(self._patches):
            p.stop()
        _clear_cache()
        self._tmpdir.cleanup()

    def test_bound_entity_returns_account_id(self) -> None:
        """prompt 含已绑定实体 → 返回 account_id。"""
        _bind_entity(
            "Fluffy",
            "acct-42",
            "urn:aaid:sc:US:fluffy",
        )
        aid = _required_account_id("a cat @entity:Fluffy walking")
        self.assertEqual(str(aid or ""), "acct-42")

    def test_no_entity_returns_none(self) -> None:
        """无实体 → None。"""
        self.assertIsNone(_required_account_id("just a sunset"))

    def test_unbound_entity_raises_or_none(self) -> None:
        """未绑定实体：抛错或返回 None（实现二选一，不可静默串号）。"""
        try:
            result = _required_account_id("hello @entity:Ghost")
        except (ValueError, KeyError, RuntimeError):
            return
        self.assertIsNone(result)


class EntityStorageTests(unittest.TestCase):
    """存储：bind → get/list → unbind（临时文件，不打真实 Adobe）。"""

    def setUp(self) -> None:
        self._tmpdir = tempfile.TemporaryDirectory()
        self._path = Path(self._tmpdir.name) / "firefly_entities.json"
        self._path.write_text("{}", encoding="utf-8")
        self._patches = []
        if hasattr(entities, "ENTITIES_FILE"):
            self._patches.append(
                mock.patch.object(entities, "ENTITIES_FILE", self._path)
            )
        if hasattr(entities, "_STORE"):
            self._patches.append(mock.patch.object(entities, "_STORE", None))
        for p in self._patches:
            p.start()
        _clear_cache()

    def tearDown(self) -> None:
        for p in self._patches:
            p.stop()
        _clear_cache()
        self._tmpdir.cleanup()

    def test_bind_get_list_unbind(self) -> None:
        """bind → get/list 可见 → unbind 后消失。"""
        _bind_entity(
            name="Hero",
            account_id="acct-hero",
            creativeCloudFileId="urn:aaid:sc:US:hero",
            entity_type="character",
        )

        got = _get_entity("Hero")
        self.assertIsNotNone(got)
        self.assertIsInstance(got, dict)
        self.assertEqual(str(got.get("account_id") or ""), "acct-hero")
        file_id = str(
            got.get("creativeCloudFileId")
            or got.get("urn")
            or got.get("id")
            or ""
        )
        self.assertEqual(file_id, "urn:aaid:sc:US:hero")

        listed = _list_entities()
        if isinstance(listed, dict):
            names = set(listed.keys())
            items = list(listed.values())
        else:
            items = list(listed)
            names = set()
            for item in items:
                if isinstance(item, dict):
                    names.add(str(item.get("name") or ""))
                else:
                    names.add(str(item))
        self.assertIn("Hero", names)

        removed = _unbind_entity("Hero")
        # 返回 True/None 均可，关键是后续 get 为空
        self.assertNotIn(removed, (False,), "unbind should succeed when present")
        _clear_cache()
        self.assertIsNone(_get_entity("Hero"))


if __name__ == "__main__":
    unittest.main()
