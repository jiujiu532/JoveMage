"""Adobe Firefly Kling O3 实体：本地绑定存储 + Adobe CRUD/上传 + prompt 解析。

设计见 `.trellis/tasks/07-31-adobe-firefly-integration/design-phase3-video.md` §5。
对齐 adobe2api entity_store / adobe_client 实体链路：
- 实体与 Adobe 账号绑定（跨账号不可混用）
- prompt 用 `@entity:Name` 引用
- kling-o3 blob：usage="element" + creativeCloudFileId + mention.id
"""

from __future__ import annotations

import re
import secrets
import string
import threading
import time
import uuid
from pathlib import Path
from typing import Any
from urllib.parse import quote

from curl_cffi import requests as curl_requests

from services.backends.firefly_constants import (
    DEFAULT_USER_AGENT,
    GENERATE_API_KEY,
    IMPERSONATE,
    auth_headers,
    proxy_mapping,
)
from services.backends.firefly_errors import (
    FireflyRequestError,
    FireflyUpstreamTemporary,
)
from services.backends.firefly_http import header_get, raise_for_firefly_http
from services.config import DATA_DIR
from services.json_file import read_json_object, write_json_file
from utils.diagnostics import redact_auth_diagnostic
from utils.log import logger

ENTITY_API_BASE = "https://firefly-entity.adobe.io/api/entities/"
CS_INDEX_URL = "https://platform-cs-edge.adobe.io/index"
PLATFORM_CS_BASE = "https://platform-cs-va6.adobe.io/composite/component/path"

ENTITIES_FILE = DATA_DIR / "firefly_entities.json"
ENTITIES_LOCK = threading.RLock()

_API_KEY = GENERATE_API_KEY  # projectx_webapp

# prompt 中 @entity:Name（Name 不含空白与 @）
_ENTITY_MENTION_RE = re.compile(r"@entity:([^\s@]+)")

# 内存缓存：{entity_name: record}
_STORE: dict[str, dict[str, Any]] | None = None


# ---------------------------------------------------------------------------
# 内部工具
# ---------------------------------------------------------------------------


def _proxy_kwargs(proxy: str | None) -> dict[str, Any]:
    mapping = proxy_mapping(proxy)
    return {"proxies": mapping} if mapping else {}


def _entity_headers(access_token: str) -> dict[str, str]:
    return auth_headers(
        access_token,
        api_key=_API_KEY,
        content_type="application/json",
        extra={"accept": "application/json"},
    )


def _cs_index_headers(access_token: str) -> dict[str, str]:
    return auth_headers(
        access_token,
        api_key=_API_KEY,
        content_type="application/json",
    )


def _header_get(headers: Any, *names: str) -> str:
    return header_get(headers, *names)


def _raise_for_http(
    status_code: int,
    body: str,
    context: str,
    *,
    headers: Any = None,
) -> None:
    # 与 client 统一：401 + taste_exhausted → Quota，不再误标 Auth
    raise_for_firefly_http(status_code, headers, body, context)


def _json_or_empty(resp: Any) -> Any:
    text = str(getattr(resp, "text", "") or "").strip()
    if not text:
        return {}
    try:
        return resp.json()
    except Exception:
        return {}


def _entity_urn_from_data(data: Any) -> str:
    if isinstance(data, dict):
        for key in ("id", "urn", "entityId", "entityUrn", "creativeCloudFileId"):
            val = str(data.get(key) or "").strip()
            if val:
                return val
        entity = data.get("entity")
        if isinstance(entity, dict):
            return _entity_urn_from_data(entity)
    return ""


def _nanoid(size: int = 21) -> str:
    alphabet = string.ascii_letters + string.digits + "-_"
    return "".join(secrets.choice(alphabet) for _ in range(size))


def _normalize_name(name: str) -> str:
    return str(name or "").strip()


def _normalize_store(raw: Any) -> dict[str, dict[str, Any]]:
    """支持两种落盘形态：
    1) 任务约定：{name: record}
    2) 兼容：{"version":1,"entities":[...]} 列表
    """
    if not isinstance(raw, dict):
        return {}

    if isinstance(raw.get("entities"), list):
        out: dict[str, dict[str, Any]] = {}
        for item in raw["entities"]:
            if not isinstance(item, dict):
                continue
            name = _normalize_name(
                str(item.get("name") or item.get("displayName") or "")
            )
            if not name:
                continue
            record = dict(item)
            record["name"] = name
            out[name] = record
        return out

    # 直接 name→record
    out = {}
    for key, value in raw.items():
        if key in {"version", "entities"}:
            continue
        if not isinstance(value, dict):
            continue
        name = _normalize_name(str(value.get("name") or key))
        if not name:
            continue
        record = dict(value)
        record["name"] = name
        out[name] = record
    return out


def _disk_payload(store: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """落盘为 name→record，并附 version。"""
    cleaned: dict[str, Any] = {"version": 1}
    for name, record in store.items():
        key = _normalize_name(name)
        if not key or not isinstance(record, dict):
            continue
        item = dict(record)
        item["name"] = key
        cleaned[key] = item
    return cleaned


# ---------------------------------------------------------------------------
# 存储（内存 + 原子落盘 data/firefly_entities.json）
# ---------------------------------------------------------------------------


def load_entities() -> dict[str, dict[str, Any]]:
    """加载实体表：{entity_name: {account_id, creativeCloudFileId, urn, ...}}。"""
    global _STORE
    with ENTITIES_LOCK:
        if _STORE is not None:
            return {k: dict(v) for k, v in _STORE.items()}
        ENTITIES_FILE.parent.mkdir(parents=True, exist_ok=True)
        raw = read_json_object(ENTITIES_FILE, name="firefly_entities.json")
        _STORE = _normalize_store(raw)
        return {k: dict(v) for k, v in _STORE.items()}


def save_entities(store: dict) -> None:
    """覆盖写入实体表（原子写 + 内存同步）。"""
    global _STORE
    if not isinstance(store, dict):
        raise TypeError("store must be a dict")
    normalized = _normalize_store(store)
    with ENTITIES_LOCK:
        write_json_file(ENTITIES_FILE, _disk_payload(normalized))
        _STORE = normalized


def bind_entity(
    name: str,
    account_id: str,
    creativeCloudFileId: str,
    **meta: Any,
) -> None:
    """实体 ↔ Adobe 账号绑定（跨账号不可混用）。

    同一 name 若已绑定其它 account_id，会覆盖为新绑定（调用方应保证业务约束）。
    """
    entity_name = _normalize_name(name)
    aid = str(account_id or "").strip()
    file_id = str(creativeCloudFileId or "").strip()
    if not entity_name:
        raise ValueError("entity name is required")
    if not aid:
        raise ValueError("account_id is required")
    if not file_id:
        raise ValueError("creativeCloudFileId is required")

    now_ts = int(time.time())
    with ENTITIES_LOCK:
        store = load_entities()
        existing = store.get(entity_name) or {}
        record: dict[str, Any] = {
            **existing,
            **{k: v for k, v in meta.items() if v is not None},
            "name": entity_name,
            "account_id": aid,
            "creativeCloudFileId": file_id,
            "urn": str(meta.get("urn") or existing.get("urn") or file_id).strip(),
            "updated_at": now_ts,
        }
        if "created_at" not in record or not record.get("created_at"):
            record["created_at"] = int(existing.get("created_at") or now_ts)
        store[entity_name] = record
        save_entities(store)


def get_entity(name: str) -> dict[str, Any] | None:
    """按实体名取绑定记录；不存在返回 None。"""
    entity_name = _normalize_name(name)
    if not entity_name:
        return None
    store = load_entities()
    item = store.get(entity_name)
    return dict(item) if isinstance(item, dict) else None


def list_entities() -> list[dict[str, Any]]:
    """列出全部本地绑定实体（按 name 排序）。"""
    store = load_entities()
    items = [dict(v) for v in store.values() if isinstance(v, dict)]
    items.sort(key=lambda x: str(x.get("name") or "").lower())
    return items


def unbind_entity(name: str) -> bool:
    """解除本地绑定；返回是否确实删除了记录。"""
    entity_name = _normalize_name(name)
    if not entity_name:
        return False
    with ENTITIES_LOCK:
        store = load_entities()
        if entity_name not in store:
            return False
        del store[entity_name]
        save_entities(store)
        return True


def clear_entities_cache() -> None:
    """测试/运维：丢弃内存缓存，下次 load 重新读盘。"""
    global _STORE
    with ENTITIES_LOCK:
        _STORE = None


# ---------------------------------------------------------------------------
# Adobe 侧 CRUD + CS 上传
# ---------------------------------------------------------------------------


def resolve_cc_repository(access_token: str, *, proxy: str | None = None) -> str:
    """GET platform-cs-edge.adobe.io/index → repo repositoryId。"""
    token = str(access_token or "").strip()
    if not token:
        raise ValueError("access_token is required")

    try:
        resp = curl_requests.get(
            CS_INDEX_URL,
            headers=_cs_index_headers(token),
            timeout=30,
            impersonate=IMPERSONATE,
            **_proxy_kwargs(proxy),
        )
    except Exception as exc:
        logger.warning(
            "firefly resolve_cc_repository network error: %s",
            redact_auth_diagnostic(str(exc))[:300],
        )
        raise FireflyUpstreamTemporary(
            f"resolve repository network error: {exc}",
            error_type="network",
        ) from exc

    if resp.status_code != 200:
        _raise_for_http(
            resp.status_code,
            getattr(resp, "text", "") or "",
            "resolve repository failed",
            headers=getattr(resp, "headers", None),
        )

    data = _json_or_empty(resp)
    if not isinstance(data, dict):
        raise FireflyRequestError(
            "unable to resolve Adobe repository: invalid index response"
        )

    candidates: list[dict[str, Any]] = []

    def visit(value: Any) -> None:
        if isinstance(value, dict):
            repo_id = str(value.get("repo:repositoryId") or "").strip()
            if repo_id:
                candidates.append(value)
            for child in value.values():
                visit(child)
        elif isinstance(value, list):
            for child in value:
                visit(child)

    visit(data.get("children") or [])
    # 有些响应把仓库放在顶层 children 之外
    if not candidates:
        visit(data)

    def score(item: dict[str, Any]) -> tuple[int, int]:
        return (
            1 if str(item.get("repo:state") or "").upper() == "ACTIVE" else 0,
            1 if str(item.get("storage:directoryType") or "") == "assigned" else 0,
        )

    candidates.sort(key=score, reverse=True)
    for item in candidates:
        repo_id = str(item.get("repo:repositoryId") or "").strip()
        if repo_id:
            return repo_id
    raise FireflyRequestError("unable to resolve Adobe repository for current token")


def create_entity(
    access_token: str,
    name: str,
    *,
    entity_type: str = "character",
    description: str = "",
    proxy: str | None = None,
) -> dict[str, Any]:
    """POST firefly-entity.adobe.io/api/entities/。"""
    token = str(access_token or "").strip()
    display_name = _normalize_name(name)
    if not token:
        raise ValueError("access_token is required")
    if not display_name:
        raise ValueError("entity displayName is required")

    payload = {
        "entityType": str(entity_type or "character").strip() or "character",
        "entityValue": {
            "displayName": display_name,
            "description": str(description or ""),
            "metaAttrs": None,
        },
    }
    try:
        resp = curl_requests.post(
            ENTITY_API_BASE,
            headers=_entity_headers(token),
            json=payload,
            timeout=60,
            impersonate=IMPERSONATE,
            **_proxy_kwargs(proxy),
        )
    except Exception as exc:
        logger.warning(
            "firefly create_entity network error: %s",
            redact_auth_diagnostic(str(exc))[:300],
        )
        raise FireflyUpstreamTemporary(
            f"create entity network error: {exc}",
            error_type="network",
        ) from exc

    if resp.status_code not in (200, 201):
        _raise_for_http(
            resp.status_code,
            getattr(resp, "text", "") or "",
            "create entity failed",
            headers=getattr(resp, "headers", None),
        )

    data = _json_or_empty(resp)
    if isinstance(data, dict):
        urn = _entity_urn_from_data(data)
        if urn and "id" not in data:
            data = {**data, "id": urn}
        return data
    return {}


def entity_component_upload_href(entity_data: dict[str, Any] | None) -> str:
    """从 create_entity 响应里取 component 上传 href（可选）。"""
    if not isinstance(entity_data, dict):
        return ""
    upload_links = entity_data.get("uploadLinks")
    if not isinstance(upload_links, dict):
        return ""
    links = upload_links.get("http://ns.adobe.com/adobecloud/rel/component")
    if not isinstance(links, list):
        return ""
    for item in links:
        if isinstance(item, dict):
            href = str(item.get("href") or "").strip()
            if href:
                return href
    return ""


def upload_entity_image(
    access_token: str,
    repository_id: str,
    entity_name: str,
    image_bytes: bytes,
    mime: str,
    *,
    component_upload_href: str | None = None,
    proxy: str | None = None,
) -> dict[str, Any]:
    """PUT CS composite component，返回 etag/version/md5 等。"""
    token = str(access_token or "").strip()
    repo = str(repository_id or "").strip()
    name = _normalize_name(entity_name)
    mime_type = str(mime or "image/png").strip() or "image/png"
    if mime_type.lower() == "image/jpg":
        mime_type = "image/jpeg"

    if not token:
        raise ValueError("access_token is required")
    if not image_bytes:
        raise FireflyRequestError("entity image is empty")
    if not repo:
        raise FireflyRequestError(
            "Adobe repository is required for entity image upload"
        )
    if not name:
        raise FireflyRequestError("entity name is required for entity image upload")

    component_id = str(uuid.uuid4())
    upload_href = str(component_upload_href or "").strip()
    if upload_href:
        url = upload_href.split("{", 1)[0]
        separator = "&" if "?" in url else "?"
        url = f"{url}{separator}component_id={component_id}"
    else:
        url = (
            f"{PLATFORM_CS_BASE}/{quote(repo, safe='')}/"
            f"appassets/firefly/entities/{quote(name, safe='')}"
            f"?component_id={component_id}"
        )

    headers = {
        "Authorization": f"Bearer {token}",
        "x-api-key": _API_KEY,
        "content-type": mime_type,
        "accept": "application/json",
        "user-agent": DEFAULT_USER_AGENT,
    }
    try:
        resp = curl_requests.put(
            url,
            headers=headers,
            data=image_bytes,
            timeout=120,
            impersonate=IMPERSONATE,
            **_proxy_kwargs(proxy),
        )
    except Exception as exc:
        logger.warning(
            "firefly upload_entity_image network error: %s",
            redact_auth_diagnostic(str(exc))[:300],
        )
        raise FireflyUpstreamTemporary(
            f"upload entity image network error: {exc}",
            error_type="network",
        ) from exc

    if resp.status_code not in (200, 201):
        _raise_for_http(
            resp.status_code,
            getattr(resp, "text", "") or "",
            "upload entity image failed",
            headers=getattr(resp, "headers", None),
        )

    length_raw = _header_get(resp.headers, "resource-length", "content-length")
    try:
        length = int(length_raw)
    except Exception:
        length = len(image_bytes)

    return {
        "component_id": component_id,
        "etag": _header_get(resp.headers, "etag"),
        "version": _header_get(resp.headers, "revision", "x-revision"),
        "md5": _header_get(resp.headers, "content-md5", "x-content-md5"),
        "length": length,
        "type": mime_type,
    }


def register_entity_resource(
    access_token: str,
    entity_urn: str,
    component: dict[str, Any] | list[dict[str, Any]],
    *,
    proxy: str | None = None,
) -> dict[str, Any] | list[Any] | Any:
    """POST .../entities/{urn}/base-resources/ 绑定组件。

    component 可为单条 upload_entity_image 结果，或组件列表。
    """
    token = str(access_token or "").strip()
    urn = str(entity_urn or "").strip()
    if not token:
        raise ValueError("access_token is required")
    if not urn:
        raise FireflyRequestError("entity urn is required")

    if isinstance(component, dict):
        components = [component]
    elif isinstance(component, list):
        components = [c for c in component if isinstance(c, dict)]
    else:
        raise TypeError("component must be a dict or list of dicts")
    if not components:
        raise FireflyRequestError("entity components are required")

    url = f"{ENTITY_API_BASE}{quote(urn, safe='')}/base-resources/"
    body: list[dict[str, Any]] = []
    for idx, comp in enumerate(components):
        entry: dict[str, Any] = {
            "component": {
                "id": comp["component_id"] if "component_id" in comp else comp.get("id"),
                "type": comp.get("type") or "image/png",
                "length": comp.get("length") or 0,
                "etag": comp.get("etag") or "",
                "version": comp.get("version") or "",
                "md5": comp.get("md5") or "",
            }
        }
        if idx == 0:
            entry["is_primary"] = True
        body.append(entry)

    try:
        resp = curl_requests.post(
            url,
            headers=_entity_headers(token),
            json=body,
            timeout=60,
            impersonate=IMPERSONATE,
            **_proxy_kwargs(proxy),
        )
    except Exception as exc:
        logger.warning(
            "firefly register_entity_resource network error: %s",
            redact_auth_diagnostic(str(exc))[:300],
        )
        raise FireflyUpstreamTemporary(
            f"register entity resources network error: {exc}",
            error_type="network",
        ) from exc

    if resp.status_code not in (200, 201):
        _raise_for_http(
            resp.status_code,
            getattr(resp, "text", "") or "",
            "register entity resources failed",
            headers=getattr(resp, "headers", None),
        )
    return _json_or_empty(resp)


# ---------------------------------------------------------------------------
# prompt 集成
# ---------------------------------------------------------------------------


def parse_entity_mentions(prompt: str) -> list[str]:
    """提取 `@entity:Name` 引用（保序、去重）。"""
    names: list[str] = []
    seen: set[str] = set()
    for match in _ENTITY_MENTION_RE.finditer(str(prompt or "")):
        name = match.group(1).strip()
        if not name or name in seen:
            continue
        seen.add(name)
        names.append(name)
    return names


def build_entity_blob(entity: dict[str, Any], *, order: int = 0) -> dict[str, Any]:
    """kling-o3 实体 blob：usage=element + creativeCloudFileId + mention.id。

    entity 需含 creativeCloudFileId 或 urn/id；mention_id 可预置，否则自动生成。
    order 保留参数位（frame 用），element blob 默认不强制写入 order。
    """
    if not isinstance(entity, dict):
        raise TypeError("entity must be a dict")

    file_id = str(
        entity.get("creativeCloudFileId")
        or entity.get("urn")
        or entity.get("id")
        or ""
    ).strip()
    if not file_id:
        raise ValueError("entity missing creativeCloudFileId/urn")

    mention_id = str(
        entity.get("mention_id") or entity.get("mentionId") or ""
    ).strip()
    if not mention_id:
        mention = entity.get("mention")
        if isinstance(mention, dict):
            mention_id = str(mention.get("id") or "").strip()
    if not mention_id:
        mention_id = _nanoid()

    blob: dict[str, Any] = {
        "usage": "element",
        "creativeCloudFileId": file_id,
        "mention": {"id": mention_id},
    }
    # 仅当调用方显式传非 0 order 时附带，兼容扩展
    if order:
        blob["order"] = int(order)
    return blob


def required_account_id_for_prompt(prompt: str) -> str | None:
    """prompt 含 @entity 时返回绑定账号 account_id（用于钉选 token），否则 None。

    - 任一实体未绑定：抛 ValueError
    - 多实体绑定到不同账号：抛 ValueError（跨账号不可混用）
    """
    names = parse_entity_mentions(prompt)
    if not names:
        return None

    account_id: str | None = None
    for name in names:
        entity = get_entity(name)
        if not entity:
            raise ValueError(f"entity not bound: {name}")
        aid = str(entity.get("account_id") or "").strip()
        if not aid:
            raise ValueError(f"entity has no account_id: {name}")
        if account_id is None:
            account_id = aid
        elif account_id != aid:
            raise ValueError(
                "entities in prompt bind different Adobe accounts "
                f"(cannot mix: {account_id} vs {aid})"
            )
    return account_id


def rewrite_prompt_entity_mentions(
    prompt: str,
    replacements: dict[str, str],
) -> str:
    """把 `@entity:Name` 替换为 `@mentionId`（对齐 adobe2api 提交形态）。"""

    def _sub(match: re.Match[str]) -> str:
        name = match.group(1).strip()
        mid = replacements.get(name)
        if not mid:
            return match.group(0)
        return f"@{mid}"

    return _ENTITY_MENTION_RE.sub(_sub, str(prompt or ""))


def resolve_entity_refs_for_prompt(
    prompt: str,
) -> tuple[str, list[dict[str, Any]], str | None]:
    """解析 prompt 实体引用，返回 (改写后 prompt, entity_refs, account_id)。

    entity_refs 项：{name, urn, creativeCloudFileId, mention_id, account_id}
    无实体时 account_id=None、refs=[]、prompt 原样。
    """
    names = parse_entity_mentions(prompt)
    if not names:
        return str(prompt or ""), [], None

    account_id = required_account_id_for_prompt(prompt)
    refs: list[dict[str, Any]] = []
    replacements: dict[str, str] = {}
    for name in names:
        entity = get_entity(name) or {}
        file_id = str(
            entity.get("creativeCloudFileId")
            or entity.get("urn")
            or entity.get("id")
            or ""
        ).strip()
        if not file_id:
            raise ValueError(f"entity has no urn/creativeCloudFileId: {name}")
        mention_id = _nanoid()
        replacements[name] = mention_id
        refs.append(
            {
                "name": name,
                "urn": file_id,
                "creativeCloudFileId": file_id,
                "mention_id": mention_id,
                "account_id": str(entity.get("account_id") or "").strip(),
            }
        )

    rewritten = rewrite_prompt_entity_mentions(prompt, replacements)
    return rewritten, refs, account_id
