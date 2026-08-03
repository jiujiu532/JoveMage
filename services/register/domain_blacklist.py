from __future__ import annotations

import copy
import json
import re
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from services.config import DATA_DIR
from services.json_file import write_json_file

EXCLUDED_PROVIDER_TYPES = frozenset({"outlook_token", "outlook_email_api"})
DOMAIN_BLACKLIST_FILE = DATA_DIR / "domain_blacklist.json"
_RAW_HINT_MAX = 500
_SCHEMA_VERSION = 1

_LOCK = threading.Lock()

# 内置硬规则：只读导出，供 UI / 文档展示；实际判定见 should_ban_from_error
# match 字段即错误文案子串（忽略大小写）；勿再放仅状态码 / 单独 type 名以免误导
BUILTIN_BAN_RULES: list[dict[str, Any]] = [
    {
        "id": "create_account_rejected",
        "label": "OpenAI 拒绝创建账号（given information）",
        "description": "错误文案包含 cannot create your account with the given information 时绝对拉黑",
        "match": "cannot create your account with the given information",
        "builtin": True,
    },
    {
        "id": "failed_to_create_account",
        "label": "Failed to create account",
        "description": "错误文案包含 Failed to create account. Please try again.",
        "match": "Failed to create account. Please try again.",
        "builtin": True,
    },
    {
        "id": "email_not_supported",
        "label": "邮箱不被支持（email not supported）",
        "description": "错误文案包含 The email you provided is not supported 时绝对拉黑（常见 create_account HTTP 400）",
        "match": "The email you provided is not supported",
        "builtin": True,
    },
]

_CANNOT_CREATE_PHRASE = "cannot create your account with the given information"
_FAILED_CREATE_PHRASE = "failed to create account. please try again."
_EMAIL_NOT_SUPPORTED_PHRASE = "the email you provided is not supported"

_DOMAIN_RE = re.compile(
    r"^(?=.{1,253}$)(?!-)[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?"
    r"(?:\.(?!-)[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?)+$"
)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _idna_encode_host(raw: str) -> str:
    """将可能含非 ASCII 的主机名转为 punycode（小写）；非法抛 ValueError。"""
    text = str(raw or "").strip().lower()
    if not text:
        raise ValueError("domain is empty")
    labels = text.split(".")
    out: list[str] = []
    for lab in labels:
        if not lab:
            raise ValueError("invalid domain label")
        try:
            lab.encode("ascii")
            out.append(lab)
        except UnicodeEncodeError:
            try:
                out.append(lab.encode("idna").decode("ascii").lower())
            except Exception as exc:
                raise ValueError(f"invalid idn label: {lab!r}") from exc
    return ".".join(out)


def normalize_domain(value: str) -> str:
    """小写；若是邮箱取 @ 右侧；支持 *.example.com 通配；IDN 转 punycode；非法抛 ValueError。"""
    raw = str(value or "").strip().lower()
    if not raw:
        raise ValueError("domain is empty")
    if "@" in raw:
        _local, _, host = raw.rpartition("@")
        if not host:
            raise ValueError("invalid email domain")
        raw = host.strip()
    # 去掉可能的尖括号包裹 / 尾随点
    raw = raw.strip("<>").strip().rstrip(".")
    wildcard = False
    if raw.startswith("*.") and len(raw) > 2:
        wildcard = True
        raw = raw[2:].strip().rstrip(".")
    try:
        raw = _idna_encode_host(raw)
    except ValueError as exc:
        raise ValueError(f"invalid domain: {value!r}") from exc
    if not raw or not _DOMAIN_RE.match(raw):
        raise ValueError(f"invalid domain: {value!r}")
    return f"*.{raw}" if wildcard else raw


def _strip_wildcard(domain: str) -> tuple[str, bool]:
    """返回 (base, is_wildcard)。"""
    text = str(domain or "").strip().lower()
    if text.startswith("*.") and len(text) > 2:
        return text[2:], True
    return text, False


def domain_matches_ban(candidate: str, banned: str) -> bool:
    """
    banned 是否覆盖 candidate。
    - 精确匹配
    - banned 为父域时覆盖子域（example.com → a.example.com）
    - banned 为 *.base 时覆盖 base 及其任意子域
    """
    try:
        cand = normalize_domain(candidate)
        ban = normalize_domain(banned)
    except ValueError:
        return False
    cand_base, cand_wild = _strip_wildcard(cand)
    ban_base, ban_wild = _strip_wildcard(ban)
    if cand_wild:
        # 候选本身是通配配置项：交给 config_domain_blocked
        return False
    if ban_wild:
        return cand_base == ban_base or cand_base.endswith("." + ban_base)
    if cand_base == ban_base:
        return True
    # 父域 ban 覆盖子域
    return cand_base.endswith("." + ban_base)


def config_domain_blocked(config_domain: str, banned: str) -> bool:
    """
    配置侧域名（含 *.base）是否因某条 ban 而不可再选。
    - 配置为 *.base：任意 ban 落在 base / 其子域 → 整池不可用（避免随机子域绕过）
    - 配置为具体域：被 ban 覆盖，或其子域已被 ban（避免基域继续发叶子）
    """
    try:
        conf = normalize_domain(config_domain)
        ban = normalize_domain(banned)
    except ValueError:
        return False
    conf_base, conf_wild = _strip_wildcard(conf)
    ban_base, ban_wild = _strip_wildcard(ban)

    if conf_wild:
        if ban_wild:
            # *.a 与 *.b：任一方覆盖另一方 base
            return (
                conf_base == ban_base
                or conf_base.endswith("." + ban_base)
                or ban_base.endswith("." + conf_base)
            )
        return ban_base == conf_base or ban_base.endswith("." + conf_base)

    # 具体配置域
    if domain_matches_ban(conf_base, ban):
        return True
    # 叶子已 ban → 基域配置也停用（防 random_subdomain / 同基域再发）
    if ban_wild:
        return conf_base == ban_base or conf_base.endswith("." + ban_base)
    return ban_base == conf_base or ban_base.endswith("." + conf_base)


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
    for excluded in EXCLUDED_PROVIDER_TYPES:
        if pref_l.startswith(f"{excluded}:") or pref_l.startswith(f"{excluded}#") or pref_l.startswith(f"{excluded}~"):
            return True
    return False


def _empty_store() -> dict[str, Any]:
    return {"version": _SCHEMA_VERSION, "entries": []}


def _backup_path(path: Path) -> Path:
    return path.with_suffix(path.suffix + ".bak")


def _try_parse_store(candidate: Path) -> dict[str, Any] | None:
    """解析候选文件；成功返回 dict，不可读/非 dict 返回 None。"""
    if not candidate.exists() or candidate.is_dir():
        return None
    try:
        data = json.loads(candidate.read_text(encoding="utf-8"))
    except Exception:
        return None
    if not isinstance(data, dict):
        return None
    return data


def _load_unlocked(path: Path | None = None) -> dict[str, Any]:
    """
    加载黑名单。
    - 主文件与 .bak 均不存在：合法空库（新部署）。
    - 任一存在但均无法解析为 dict：fail-closed，抛 ValueError（调用方按检查失败处理）。
    - 主文件损坏但 .bak 可用：与 json_file 一致，从备份恢复。
    """
    target = path or DOMAIN_BLACKLIST_FILE
    backup = _backup_path(target)
    primary_exists = target.exists() and not target.is_dir()
    backup_exists = backup.exists() and not backup.is_dir()

    # 文件不存在 = 合法空库；勿与「损坏」混为一谈
    if not primary_exists and not backup_exists:
        return _empty_store()

    data = _try_parse_store(target)
    if data is None:
        data = _try_parse_store(backup)
    if data is None:
        # 主文件或备份存在却都不可用：禁止 fail-open 成空表
        raise ValueError(
            f"domain_blacklist 不可用: '{target.name}' 损坏或不可解析"
        )

    entries = data.get("entries")
    if not isinstance(entries, list):
        entries = []
    cleaned: list[dict[str, Any]] = []
    for item in entries:
        if isinstance(item, dict):
            cleaned.append(dict(item))
    try:
        version = int(data.get("version") or _SCHEMA_VERSION)
    except (TypeError, ValueError):
        version = _SCHEMA_VERSION
    return {"version": version, "entries": cleaned}


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
    """
    查询域名是否在黑名单。
    fail-closed：
    - 空 provider_ref：无法绑定账号来源，视为已 ban（返回 True）
    - 黑名单文件损坏：_load_unlocked 抛 ValueError，由调用方按检查失败处理
    非法 domain 属调用方入参错误，返回 False（无法形成有效匹配）。
    """
    pref = str(provider_ref or "").strip()
    if not pref:
        # 无 provider 上下文时不可安全放行
        return True
    try:
        cand = normalize_domain(domain)
    except ValueError:
        # 非法域名：调用方 bug，不视为「在黑名单中」
        return False
    with _LOCK:
        store = _load_unlocked()
        for item in store["entries"]:
            if str(item.get("status") or "active").lower() not in {"", "active"}:
                continue
            if str(item.get("provider_ref") or "").strip() != pref:
                continue
            banned_dom = str(item.get("domain") or "")
            try:
                ban_n = normalize_domain(banned_dom)
            except ValueError:
                continue
            if domain_matches_ban(cand, ban_n) or config_domain_blocked(cand, ban_n):
                return True
    return False


def filter_domains(provider_ref: str, domains: list[str]) -> list[str]:
    """去掉已 ban 的域名（含父子域 / 通配），保持原顺序。"""
    pref = str(provider_ref or "").strip()
    if not domains:
        return []
    # 空 provider_ref：无法判定归属，fail-closed 全部剔除
    if not pref:
        return []
    with _LOCK:
        store = _load_unlocked()
        banned: list[str] = []
        for item in store["entries"]:
            if str(item.get("provider_ref") or "").strip() != pref:
                continue
            if str(item.get("status") or "active").lower() not in {"", "active"}:
                continue
            try:
                banned.append(normalize_domain(str(item.get("domain") or "")))
            except ValueError:
                continue
    result: list[str] = []
    for d in domains:
        blocked = False
        for ban_dom in banned:
            if config_domain_blocked(d, ban_dom) or domain_matches_ban(d, ban_dom):
                blocked = True
                break
        if blocked:
            continue
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

    # 全量 replace 且无有效条目：拒绝整表清空，避免误操作 / 空文件擦库
    if mode_s == "replace" and scope is None and not incoming:
        raise ValueError("replace 模式需要非空 entries，已拒绝清空全部黑名单")

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
    内置：cannot-create / failed-to-create / email-not-supported 短语（不依赖 HTTP 状态前缀）。
    自定义 match 子串包含（忽略大小写），长度 >= 8。
    """
    text = str(error_text or "")
    if not text.strip():
        return False, ""
    lower = text.lower()

    # 绝对拉黑短语：不要求 create_account_http_xxx 前缀，覆盖 400/403/user_register 等变体
    if _CANNOT_CREATE_PHRASE in lower:
        return True, "create_account_rejected"
    if _FAILED_CREATE_PHRASE in lower:
        return True, "failed_to_create_account"
    if _EMAIL_NOT_SUPPORTED_PHRASE in lower:
        return True, "email_not_supported"

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
