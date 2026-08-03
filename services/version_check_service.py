"""云端版本检查：服务端拉取 GitHub VERSION / Releases，避免浏览器直连 403。

策略：
1. VERSION 走 raw.githubusercontent.com（最新版本主来源）
2. Releases 优先 api.github.com；遇 403/限流时回退 releases.atom
3. 可选环境变量 GITHUB_TOKEN / GH_TOKEN 提升 API 额度
"""
from __future__ import annotations

import html
import json
import os
import re
import threading
import time
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from typing import Any

REPO = "jiujiu532/JoveMage"
VERSION_URL = f"https://raw.githubusercontent.com/{REPO}/main/VERSION"
RELEASES_URL = f"https://api.github.com/repos/{REPO}/releases?per_page=20"
RELEASES_ATOM_URL = f"https://github.com/{REPO}/releases.atom"
RELEASE_PAGE_URL = f"https://github.com/{REPO}/releases"
USER_AGENT = "JoveMage-version-check/1.0"
CACHE_TTL_SECONDS = 300.0
HTTP_TIMEOUT_SECONDS = 10.0
ATOM_NS = {"atom": "http://www.w3.org/2005/Atom"}

_lock = threading.Lock()
_cache: dict[str, Any] = {"fetched_at": 0.0, "remote": None}


def normalize_version_tag(value: str) -> str:
    clean = str(value or "").strip()
    if not clean:
        return ""
    return clean if clean.startswith("v") else f"v{clean}"


def bare_version(value: str) -> str:
    return normalize_version_tag(value).lstrip("v")


def _version_parts(value: str) -> list[int] | None:
    match = re.match(r"^v?(\d+)\.(\d+)\.(\d+)", str(value or "").strip())
    if not match:
        return None
    return [int(part) for part in match.groups()]


def is_newer_version(latest_version: str, current_version: str) -> bool:
    latest = _version_parts(latest_version)
    current = _version_parts(current_version)
    if not latest or not current:
        return False
    for left, right in zip(latest, current):
        if left > right:
            return True
        if left < right:
            return False
    return False


def parse_release_body(body: str) -> list[dict[str, str]]:
    items: list[dict[str, str]] = []
    for raw in str(body or "").splitlines():
        line = raw.strip()
        if not line:
            continue
        typed = re.match(r"^[-*+]\s*\[(.+?)]\s+(.+)$", line)
        if typed:
            items.append({"type": typed.group(1).strip(), "content": typed.group(2).strip()})
            continue
        # 「修复：xxx」/ 「- 修复：xxx」
        labeled = re.match(r"^[-*+]?\s*(新增|优化|修复|变更|兼容|移除|删除|废弃)[：:]\s*(.+)$", line)
        if labeled:
            items.append({"type": labeled.group(1).strip(), "content": labeled.group(2).strip()})
            continue
        bullet = re.match(r"^[-*+]\s+(.+)$", line)
        if bullet:
            items.append({"type": "更新", "content": bullet.group(1).strip()})
    if not items and str(body or "").strip():
        summary = next((part.strip() for part in str(body).splitlines() if part.strip()), str(body).strip())
        items.append({"type": "更新", "content": summary[:200]})
    return items


def parse_github_releases(payload: Any) -> list[dict[str, Any]]:
    if not isinstance(payload, list):
        return []
    releases: list[dict[str, Any]] = []
    for item in payload:
        if not isinstance(item, dict) or item.get("draft"):
            continue
        version = str(item.get("tag_name") or item.get("name") or "").strip()
        if not version:
            continue
        body_items = parse_release_body(str(item.get("body") or ""))
        if not body_items:
            continue
        published = str(item.get("published_at") or "")
        releases.append(
            {
                "version": version,
                "date": published[:10],
                "items": body_items,
            }
        )
    return releases


def _strip_html_to_text(raw_html: str) -> str:
    text = html.unescape(str(raw_html or ""))
    text = re.sub(r"(?i)<br\s*/?>", "\n", text)
    text = re.sub(r"(?i)</p\s*>", "\n", text)
    text = re.sub(r"(?i)</li\s*>", "\n", text)
    text = re.sub(r"(?i)</h[1-6]\s*>", "\n", text)
    text = re.sub(r"(?i)<li[^>]*>", "- ", text)
    text = re.sub(r"<[^>]+>", "", text)
    lines = [re.sub(r"\s+", " ", line).strip() for line in text.splitlines()]
    return "\n".join(line for line in lines if line)


def parse_releases_atom(xml_text: str) -> list[dict[str, Any]]:
    """解析 GitHub releases.atom，绕过 api.github.com 限流。"""
    root = ET.fromstring(xml_text)
    releases: list[dict[str, Any]] = []
    for entry in root.findall("atom:entry", ATOM_NS):
        title = (entry.findtext("atom:title", default="", namespaces=ATOM_NS) or "").strip()
        version = title or ""
        if not version:
            entry_id = (entry.findtext("atom:id", default="", namespaces=ATOM_NS) or "").strip()
            version = entry_id.rsplit("/", 1)[-1] if entry_id else ""
        if not version:
            continue
        updated = (entry.findtext("atom:updated", default="", namespaces=ATOM_NS) or "").strip()
        content_el = entry.find("atom:content", ATOM_NS)
        content_html = content_el.text if content_el is not None and content_el.text else ""
        body_text = _strip_html_to_text(content_html)
        items = parse_release_body(body_text)
        if not items and body_text:
            items = [{"type": "更新", "content": body_text[:200]}]
        if not items:
            continue
        releases.append(
            {
                "version": version,
                "date": updated[:10],
                "items": items,
            }
        )
    return releases


def _github_token() -> str:
    return (
        str(os.environ.get("GITHUB_TOKEN") or "").strip()
        or str(os.environ.get("GH_TOKEN") or "").strip()
        or str(os.environ.get("CHATGPT2API_GITHUB_TOKEN") or "").strip()
    )


def _http_get_text(url: str, *, accept: str | None = None, auth_token: str | None = None) -> str:
    headers = {"User-Agent": USER_AGENT}
    if accept:
        headers["Accept"] = accept
    if auth_token:
        headers["Authorization"] = f"Bearer {auth_token}"
    request = urllib.request.Request(url, headers=headers, method="GET")
    try:
        with urllib.request.urlopen(request, timeout=HTTP_TIMEOUT_SECONDS) as response:
            status = int(getattr(response, "status", 200) or 200)
            body = response.read().decode("utf-8", errors="replace")
            if status < 200 or status >= 300:
                raise RuntimeError(f"HTTP {status}")
            return body
    except urllib.error.HTTPError as exc:
        detail = ""
        try:
            detail = exc.read().decode("utf-8", errors="replace")[:160]
        except Exception:
            detail = ""
        message = f"HTTP {exc.code}"
        if detail:
            message = f"{message}: {detail}"
        raise RuntimeError(message) from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(str(exc.reason or exc)) from exc


def _fetch_remote() -> dict[str, Any]:
    errors: list[str] = []
    latest_version = ""
    releases: list[dict[str, Any]] = []
    token = _github_token()

    try:
        latest_version = bare_version(_http_get_text(VERSION_URL))
    except Exception as exc:
        errors.append(f"VERSION {exc}")

    try:
        raw = _http_get_text(
            RELEASES_URL,
            accept="application/vnd.github+json",
            auth_token=token or None,
        )
        releases = parse_github_releases(json.loads(raw))
        if not latest_version and releases:
            latest_version = bare_version(str(releases[0].get("version") or ""))
    except Exception as api_exc:
        # API 限流/403 时回退 atom，仍可拿到版本与 changelog
        try:
            atom_xml = _http_get_text(RELEASES_ATOM_URL, accept="application/atom+xml")
            releases = parse_releases_atom(atom_xml)
            if not latest_version and releases:
                latest_version = bare_version(str(releases[0].get("version") or ""))
        except Exception as atom_exc:
            errors.append(f"releases {api_exc}；atom {atom_exc}")
        else:
            # atom 成功则不把 API 限流当致命错误（版本检查已可用）
            if not releases:
                errors.append(f"releases {api_exc}")

    return {
        "latest_version": latest_version,
        "releases": releases,
        "check_error": "；".join(errors) if errors else "",
        "fetched_at": time.time(),
    }


def check_remote_version(current_version: str) -> dict[str, Any]:
    """返回当前版本对比云端最新版本与 release notes。"""
    current_bare = bare_version(current_version)
    current_tag = normalize_version_tag(current_bare or current_version)

    with _lock:
        now = time.time()
        cached = _cache.get("remote")
        fetched_at = float(_cache.get("fetched_at") or 0.0)
        if not isinstance(cached, dict) or now - fetched_at >= CACHE_TTL_SECONDS:
            remote = _fetch_remote()
            _cache["remote"] = remote
            _cache["fetched_at"] = now
        else:
            remote = dict(cached)

    latest_bare = bare_version(str(remote.get("latest_version") or ""))
    if not latest_bare:
        latest_bare = current_bare
    latest_tag = normalize_version_tag(latest_bare)
    update_available = bool(latest_bare and current_bare and is_newer_version(latest_bare, current_bare))
    check_error = str(remote.get("check_error") or "").strip() or None
    releases = remote.get("releases") if isinstance(remote.get("releases"), list) else []

    return {
        "version": current_bare or str(current_version or "").strip(),
        "tag": current_tag,
        "commit": "",
        "repository": REPO,
        "latest_tag": latest_tag,
        "latest_version": latest_bare,
        "release_url": RELEASE_PAGE_URL,
        "is_latest": not update_available,
        "update_available": update_available,
        "check_error": check_error,
        "releases": releases,
    }
