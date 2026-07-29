from __future__ import annotations

import copy
import re
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from services.config import DATA_DIR
from services.json_file import read_json_object, write_json_file

EXCLUDED_PROVIDER_TYPES = frozenset({"outlook_token", "outlook_email_api"})
DOMAIN_BLACKLIST_FILE = DATA_DIR / "domain_blacklist.json"
_RAW_HINT_MAX = 500
_SCHEMA_VERSION = 1

_LOCK = threading.Lock()

# 内置硬规则：只读导出，供 UI / 文档展示；实际判定见 should_ban_from_error
BUILTIN_BAN_RULES: list[dict[str, Any]] = [
    {
        "id": "create_account_rejected",
        "label": "OpenAI 拒绝创建账号（400/403 + given information）",
        "match": "cannot create your account with the given information",
        "builtin": True,
    },
    {
        "id": "failed_to_create_account",
        "label": "Failed to create account. Please try again.",
        "match": "Failed to create account. Please try again.",
        "builtin": True,
    },
    {
        "id": "invalid_request_cannot_create",
        "label": "invalid_request_error + cannot create account",
        "match": "invalid_request_error",
        "builtin": True,
    },
]

_HTTP_STATUS_HINTS = (
    "create_account_http_400",
    "create_account_http_403",
    "user_register_http_400",
)
_CANNOT_CREATE_PHRASE = "cannot create your account with the given information"
_FAILED_CREATE_PHRASE = "failed to create account. please try again."
_INVALID_REQUEST = "invalid_request_error"

_DOMAIN_RE = re.compile(
    r"^(?=.{1,253}$)(?!-)[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?"
    r"(?:\.(?!-)[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?)+$"
)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def normalize_domain(value: str) -> str:
    """小写；若是邮箱取 @ 右侧；去掉空白；非法抛 ValueError。"""
    raw = str(value or "").strip().lower()
    if not raw:
        raise ValueError("domain is empty")
    if "@" in raw:
        local, _, host = raw.rpartition("@")
        if not host:
            raise ValueError("invalid email domain")
        raw = host.strip()
    # 去掉可能的尖括号包裹 / 尾随点
    raw = raw.strip("<>").strip().rstrip(".")
    if not raw or not _DOMAIN_RE.match(raw):
        raise ValueError(f"invalid domain: {value!r}")
    return raw


def mask_email(email: str) -> str:
    """本地部分保留前 2 字符后接 ***，域名原样（小写）。"""
    text = str(email or "").strip()
    if not text:
        return ""
    if "@" not in text:
        # 非邮箱：短串全遮，长串前 2 + ***
        if len(text) <= 2:
            return "***"
        return f"{text[:2]}***"
    local, _, domain = text.partition("@")
    local = local.strip()
    try:
        domain_norm = normalize_domain(domain)
    except ValueError:
        domain_norm = domain.strip().lower()
    if not local:
        return f"***@{domain_norm}"
    prefix = local[:2] if len(local) >= 2 else local[:1]
    return f"{prefix}***@{domain_norm}"


def is_excluded_provider(provider_type: str = "", provider_ref: str = "") -> bool:
    """outlook_token / outlook_email_api 整类排除。"""
    ptype = str(provider_type or "").strip().lower()
    pref = str(provider_ref or "").strip()
    pref_l = pref.lower()
    if ptype in EXCLUDED_PROVIDER_TYPES:
        return True
    if pref_l.startswith("outlook_token:") or pref_l.startswith("outlook_email_api:"):
        return True
    if "outlook_token#" in pref_l:
        return True
    if pref_l.startswith("outlook_token#") or pref_l.startswith("outlook_email_api#"):
        return True
    return False


def _empty_store() -> dict[str, Any]:
    return {"version": _SCHEMA_VERSION, "entries": []}


def _load_unlocked(path: Path | None = None) -> dict[str, Any]:
    target = path or DOMAIN_BLACKLIST_FILE
    data = read_json_object(target, name="domain_blacklist.json")
    if not isinstance(data, dict):
        return _empty_store()
    entries = data.get("entries")
    if not isinstance(entries, list):
        entries = []
    cleaned: list[dict[str, Any]] = []
    for item in entries:
        if isinstance(item, dict):
            cleaned.append(dict(item))
    return {"version": int(data.get("version") or _SCHEMA_VERSION), "entries": cleaned}


def _save_unlocked(store: dict[str, Any], path: Path | None = None) -> None:
    target = path or DOMAIN_BLACKLIST_FILE
    payload = {
        "version": int(store.get("version") or _SCHEMA_VERSION),
        "entries": list(store.get("entries") or []),
    }
    write_json_file(target, payload)


def _entry_key(provider_ref: str, domain: str) -> tuple[str, str]:
    return str(provider_ref or "").strip(), normalize_domain(domain)


def _find_index(entries: list[dict[str, Any]], provider_ref: str, domain: str) -> int:
    pref = str(provider_ref or "").strip()
    dom = normalize_domain(domain)
    for idx, item in enumerate(entries):
        if str(item.get("provider_ref") or "").strip() != pref:
            continue
        try:
            if normalize_domain(str(item.get("domain") or "")) == dom:
                return idx
        except ValueError:
            continue
    return -1


def is_banned(provider_ref: str, domain: str) -> bool:
    pref = str(provider_ref or "").strip()
    if not pref:
        return False
    try:
        dom = normalize_domain(domain)
    except ValueError:
        return False
    with _LOCK:
        store = _load_unlocked()
        for item in store["entries"]:
            if str(item.get("status") or "active").lower() not in {"", "active"}:
                continue
            if str(item.get("provider_ref") or "").strip() != pref:
                continue
            try:
                if normalize_domain(str(item.get("domain") or "")) == dom:
                    return True
            except ValueError:
                continue
    return False


def filter_domains(provider_ref: str, domains: list[str]) -> list[str]:
    """去掉已 ban 的域名，保持原顺序。"""
    pref = str(provider_ref or "").strip()
    if not domains:
        return []
    # 先规范化能解析的，保留原字符串输出
    with _LOCK:
        store = _load_unlocked()
        banned: set[str] = set()
        for item in store["entries"]:
            if str(item.get("provider_ref") or "").strip() != pref:
                continue
            if str(item.get("status") or "active").lower() not in {"", "active"}:
                continue
            try:
                banned.add(normalize_domain(str(item.get("domain") or "")))
            except ValueError:
                continue
    result: list[str] = []
    for d in domains:
        try:
            if normalize_domain(d) in banned:
                continue
        except ValueError:
            # 非法域名原样保留，交给上游处理
            pass
        result.append(d)
    return result


def ban(
    provider_ref: str,
    domain: str,
    *,
    reason: str = "",
    source: str = "auto",
    sample_email: str = "",
    raw_hint: str = "",
    provider_type: str = "",
    provider_label: str = "",
) -> dict[str, Any]:
    """写入/累加 ban；排除类型 no-op 返回 skipped。"""
    pref = str(provider_ref or "").strip()
    ptype = str(provider_type or "").strip()
    if is_excluded_provider(ptype, pref):
        return {"skipped": True, "reason": "excluded_provider"}

    dom = normalize_domain(domain)
    if not pref:
        raise ValueError("provider_ref is required")

    src = str(source or "auto").strip() or "auto"
    if src not in {"auto", "manual", "import"}:
        src = "auto"
    reason_s = str(reason or "").strip()
    raw = str(raw_hint or "").strip()
    if len(raw) > _RAW_HINT_MAX:
        raw = raw[:_RAW_HINT_MAX]
    sample = mask_email(sample_email) if sample_email else ""
    label = str(provider_label or "").strip()
    now = _now_iso()

    with _LOCK:
        store = _load_unlocked()
        entries: list[dict[str, Any]] = store["entries"]
        idx = _find_index(entries, pref, dom)
        if idx >= 0:
            item = dict(entries[idx])
            item["hit_count"] = int(item.get("hit_count") or 0) + 1
            item["last_banned_at"] = now
            item["status"] = "active"
            if reason_s:
                item["reason"] = reason_s
            if raw:
                item["raw_hint"] = raw
            if sample:
                item["sample_email"] = sample
            if ptype:
                item["provider_type"] = ptype
            if label:
                item["provider_label"] = label
            if src:
                item["source"] = src
            entries[idx] = item
            store["entries"] = entries
            _save_unlocked(store)
            return copy.deepcopy(item)

        item = {
            "provider_ref": pref,
            "provider_type": ptype,
            "provider_label": label or pref,
            "domain": dom,
            "status": "active",
            "reason": reason_s,
            "source": src,
            "sample_email": sample,
            "raw_hint": raw,
            "hit_count": 1,
            "first_banned_at": now,
            "last_banned_at": now,
        }
        entries.append(item)
        store["entries"] = entries
        _save_unlocked(store)
        return copy.deepcopy(item)


def unban(provider_ref: str, domain: str) -> bool:
    """删除条目，返回是否删过。"""
    pref = str(provider_ref or "").strip()
    if not pref:
        return False
    try:
        dom = normalize_domain(domain)
    except ValueError:
        return False
    with _LOCK:
        store = _load_unlocked()
        entries: list[dict[str, Any]] = store["entries"]
        idx = _find_index(entries, pref, dom)
        if idx < 0:
            return False
        del entries[idx]
        store["entries"] = entries
        _save_unlocked(store)
        return True


def list_entries(
    provider_ref: str | None = None,
    *,
    include_inactive: bool = False,
) -> list[dict[str, Any]]:
    pref = None if provider_ref is None else str(provider_ref).strip()
    with _LOCK:
        store = _load_unlocked()
        result: list[dict[str, Any]] = []
        for item in store["entries"]:
            if pref is not None and str(item.get("provider_ref") or "").strip() != pref:
                continue
            status = str(item.get("status") or "active").lower()
            if not include_inactive and status not in {"", "active"}:
                continue
            result.append(copy.deepcopy(item))
        return result


def export_payload(provider_ref: str | None = None) -> dict[str, Any]:
    return {
        "version": _SCHEMA_VERSION,
        "entries": list_entries(provider_ref, include_inactive=True),
    }


def _coerce_import_entries(payload: dict | list) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        raw_items = payload
    elif isinstance(payload, dict):
        raw_items = payload.get("entries")
        if raw_items is None and any(k in payload for k in ("domain", "provider_ref")):
            raw_items = [payload]
        if not isinstance(raw_items, list):
            raw_items = []
    else:
        raise ValueError("payload must be dict or list")
    entries: list[dict[str, Any]] = []
    for item in raw_items:
        if isinstance(item, dict):
            entries.append(dict(item))
    return entries


def import_payload(
    payload: dict | list,
    *,
    mode: str = "merge",
    provider_ref: str | None = None,
) -> dict[str, int]:
    """merge | replace；replace 且带 provider_ref 时只清该组。"""
    mode_s = str(mode or "merge").strip().lower()
    if mode_s not in {"merge", "replace"}:
        raise ValueError("mode must be merge or replace")
    scope = None if provider_ref is None else str(provider_ref).strip() or None
    incoming = _coerce_import_entries(payload)

    added = updated = removed = skipped = 0

    with _LOCK:
        store = _load_unlocked()
        entries: list[dict[str, Any]] = list(store["entries"])

        if mode_s == "replace":
            if scope is not None:
                before = len(entries)
                entries = [
                    e
                    for e in entries
                    if str(e.get("provider_ref") or "").strip() != scope
                ]
                removed = before - len(entries)
            else:
                removed = len(entries)
                entries = []

        for raw in incoming:
            pref = str(raw.get("provider_ref") or scope or "").strip()
            ptype = str(raw.get("provider_type") or "").strip()
            if not pref:
                skipped += 1
                continue
            if scope is not None and pref != scope:
                # 限定组导入时跳过其它组
                skipped += 1
                continue
            if is_excluded_provider(ptype, pref):
                skipped += 1
                continue
            try:
                dom = normalize_domain(str(raw.get("domain") or ""))
            except ValueError:
                skipped += 1
                continue

            idx = -1
            for i, item in enumerate(entries):
                if str(item.get("provider_ref") or "").strip() != pref:
                    continue
                try:
                    if normalize_domain(str(item.get("domain") or "")) == dom:
                        idx = i
                        break
                except ValueError:
                    continue

            now = _now_iso()
            reason_s = str(raw.get("reason") or "").strip()
            src = str(raw.get("source") or "import").strip() or "import"
            if src not in {"auto", "manual", "import"}:
                src = "import"
            raw_hint = str(raw.get("raw_hint") or "").strip()
            if len(raw_hint) > _RAW_HINT_MAX:
                raw_hint = raw_hint[:_RAW_HINT_MAX]
            sample = str(raw.get("sample_email") or "").strip()
            if sample and "@" in sample and "***" not in sample:
                sample = mask_email(sample)
            label = str(raw.get("provider_label") or "").strip()

            if idx >= 0:
                item = dict(entries[idx])
                item["hit_count"] = int(item.get("hit_count") or 0) + 1
                item["last_banned_at"] = now
                item["status"] = "active"
                if reason_s:
                    item["reason"] = reason_s
                if raw_hint:
                    item["raw_hint"] = raw_hint
                if sample:
                    item["sample_email"] = sample
                if ptype:
                    item["provider_type"] = ptype
                if label:
                    item["provider_label"] = label
                item["source"] = src
                entries[idx] = item
                updated += 1
            else:
                entries.append(
                    {
                        "provider_ref": pref,
                        "provider_type": ptype,
                        "provider_label": label or pref,
                        "domain": dom,
                        "status": "active",
                        "reason": reason_s,
                        "source": src,
                        "sample_email": sample,
                        "raw_hint": raw_hint,
                        "hit_count": int(raw.get("hit_count") or 1) or 1,
                        "first_banned_at": str(raw.get("first_banned_at") or now),
                        "last_banned_at": now,
                    }
                )
                added += 1

        store["entries"] = entries
        _save_unlocked(store)

    return {"added": added, "updated": updated, "removed": removed, "skipped": skipped}


def should_ban_from_error(
    error_text: str,
    custom_rules: list[dict] | None = None,
) -> tuple[bool, str]:
    """
    返回 (是否应 ban, reason_id_or_label)。
    内置硬规则始终生效；自定义 match 子串包含（忽略大小写），长度 >= 8。
    """
    text = str(error_text or "")
    if not text.strip():
        return False, ""
    lower = text.lower()

    has_status_hint = any(h in lower for h in _HTTP_STATUS_HINTS)
    has_cannot_create = _CANNOT_CREATE_PHRASE in lower
    has_invalid_request = _INVALID_REQUEST in lower

    if has_status_hint and has_cannot_create:
        return True, "create_account_rejected"
    if _FAILED_CREATE_PHRASE in lower:
        return True, "failed_to_create_account"
    if has_cannot_create and has_invalid_request:
        return True, "invalid_request_cannot_create"

    for rule in custom_rules or []:
        if not isinstance(rule, dict):
            continue
        if rule.get("enabled") is False:
            continue
        match = str(rule.get("match") or "").strip()
        if len(match) < 8:
            continue
        if match.lower() in lower:
            rid = str(rule.get("id") or rule.get("label") or match).strip()
            return True, rid

    return False, ""
