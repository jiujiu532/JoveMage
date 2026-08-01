from __future__ import annotations

import copy
from dataclasses import dataclass
import os
import threading
from pathlib import Path
import time

from services.json_file import read_json_object, write_json_file
from services.storage.base import StorageBackend

BASE_DIR = Path(__file__).resolve().parents[1]
DATA_DIR = BASE_DIR / "data"
CONFIG_FILE = BASE_DIR / "config.json"
VERSION_FILE = BASE_DIR / "VERSION"
BACKUP_STATE_FILE = DATA_DIR / "backup_state.json"

DEFAULT_BACKUP_INCLUDE = {
    "config": True,
    "register": True,
    "cpa": True,
    "sub2api": True,
    "logs": True,
    "dashboard_metrics": True,
    "image_tasks": True,
    "accounts_snapshot": True,
    "auth_keys_snapshot": True,
    "images": False,
}

DEFAULT_IMAGE_STORAGE = {
    "enabled": False,
    "mode": "local",
    "webdav_url": "",
    "webdav_username": "",
    "webdav_password": "",
    "webdav_root_path": "chatgpt2api/images",
    "public_base_url": "",
}

DEFAULT_CHAT_COMPLETION_CACHE = {
    "enabled": True,
    "ttl_seconds": 60,
    "max_entries": 256,
    "dedupe_inflight": True,
    "stream_cache": True,
    "normalize_messages": True,
    "drop_adjacent_duplicates": True,
    "drop_assistant_history": False,
}

DEFAULT_IMAGE_ERROR_MESSAGES = {
    "fallback": "图片生成请求失败，请稍后重试。",
    "quota": "图片账号额度已用完，请稍后再试或联系管理员。",
    "no_account": "当前图片账号暂不可用，可能是账号池、并发或上游波动，请稍后重试。",
    "local_busy": "当前没有可用的图片账号或账号并发已满，请稍后重试。",
    "unsupported_model": "当前模型不支持图片生成，请检查 model 参数。",
    "poll_timeout": "图片任务暂未返回结果，可能仍在排队或上游处理较慢，请重试。",
    "stream_interrupted": "图片生成连接中断，可能是上游服务繁忙或网络波动，请重试。",
    "connection_failed": "连接上游图片服务失败，可能是网络或代理波动，请重试。",
    "connection_timeout": "连接上游图片服务超时，请稍后重试。",
    "token_invalid": "图片生成账号状态异常，请稍后重试。",
    "text_reply": "上游返回了文本说明，未生成图片。请调整提示词或重试。",
}

DEFAULT_PROXY_RUNTIME_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/145.0.0.0 Safari/537.36"
)

DEFAULT_PROXY_RUNTIME = {
    "enabled": False,
    "egress_mode": "direct",
    "proxy_url": "",
    "resource_proxy_url": "",
    "skip_ssl_verify": False,
    "reset_session_status_codes": [403],
    "clearance": {
        "enabled": False,
        "mode": "none",
        "cf_cookies": "",
        "cf_clearance": "",
        "user_agent": DEFAULT_PROXY_RUNTIME_USER_AGENT,
        "browser": "chrome",
        "flaresolverr_url": "",
        "timeout_sec": 60,
        "refresh_interval": 3600,
        "warm_up_on_start": False,
    },
}

DEFAULT_THIRD_PARTY_APPS = {
    "infinite_canvas": {
        "enabled": False,
        "url": "https://canvas.best",
    },
}

# 自定义自动拉黑规则（存 config.json，不进 domain_blacklist.json）
# 每项: {id?: str, match: str, enabled?: bool}；match 过短（<8）丢弃
DEFAULT_DOMAIN_BAN_RULES: list[dict[str, object]] = []
_DOMAIN_BAN_MATCH_MIN_LEN = 8


def _normalize_bool(value: object, default: bool = False) -> bool:
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"1", "true", "yes", "on"}:
            return True
        if lowered in {"0", "false", "no", "off"}:
            return False
        return default
    if value is None:
        return default
    return bool(value)


def _normalize_positive_int(value: object, default: int, minimum: int = 0) -> int:
    try:
        normalized = int(value)
    except (OverflowError, TypeError, ValueError):
        normalized = default
    return max(minimum, normalized)


def _normalize_backup_include(value: object) -> dict[str, bool]:
    source = value if isinstance(value, dict) else {}
    normalized = dict(DEFAULT_BACKUP_INCLUDE)
    for key in normalized:
        normalized[key] = _normalize_bool(source.get(key), normalized[key])
    return normalized


def _normalize_backup_settings(value: object) -> dict[str, object]:
    source = value if isinstance(value, dict) else {}
    return {
        "enabled": _normalize_bool(source.get("enabled"), False),
        "provider": "cloudflare_r2",
        "account_id": str(source.get("account_id") or "").strip(),
        "access_key_id": str(source.get("access_key_id") or "").strip(),
        "secret_access_key": str(source.get("secret_access_key") or "").strip(),
        "bucket": str(source.get("bucket") or "").strip(),
        "prefix": str(source.get("prefix") or "backups").strip().strip("/") or "backups",
        "interval_minutes": _normalize_positive_int(source.get("interval_minutes"), 360, 1),
        "rotation_keep": _normalize_positive_int(source.get("rotation_keep"), 10, 0),
        "encrypt": _normalize_bool(source.get("encrypt"), False),
        "passphrase": str(source.get("passphrase") or "").strip(),
        "include": _normalize_backup_include(source.get("include")),
    }


def _public_backup_settings(settings: dict[str, object]) -> dict[str, object]:
    """backup 对外脱敏：密钥不回传明文，仅给 has_* 标志（与 cf_clearance 同模式）。"""
    public = dict(settings)
    secret = str(public.get("secret_access_key") or "").strip()
    passphrase = str(public.get("passphrase") or "").strip()
    public["secret_access_key"] = ""
    public["passphrase"] = ""
    public["has_secret_access_key"] = bool(secret)
    public["has_passphrase"] = bool(passphrase)
    return public


def _normalize_backup_state(value: object) -> dict[str, object]:
    source = value if isinstance(value, dict) else {}
    return {
        "last_started_at": str(source.get("last_started_at") or "").strip() or None,
        "last_finished_at": str(source.get("last_finished_at") or "").strip() or None,
        "last_status": str(source.get("last_status") or "idle").strip() or "idle",
        "last_error": str(source.get("last_error") or "").strip() or None,
        "last_object_key": str(source.get("last_object_key") or "").strip() or None,
    }


def _normalize_image_storage_settings(value: object) -> dict[str, object]:
    source = value if isinstance(value, dict) else {}
    mode = str(source.get("mode") or "local").strip().lower()
    if mode not in {"local", "webdav", "both"}:
        mode = "local"
    enabled = _normalize_bool(source.get("enabled"), False)
    if not enabled:
        mode = "local"
    root_path = str(source.get("webdav_root_path") or DEFAULT_IMAGE_STORAGE["webdav_root_path"]).strip().strip("/")
    return {
        "enabled": enabled,
        "mode": mode,
        "webdav_url": str(source.get("webdav_url") or "").strip().rstrip("/"),
        "webdav_username": str(source.get("webdav_username") or "").strip(),
        "webdav_password": str(source.get("webdav_password") or "").strip(),
        "webdav_root_path": root_path or str(DEFAULT_IMAGE_STORAGE["webdav_root_path"]),
        "public_base_url": str(source.get("public_base_url") or "").strip().rstrip("/"),
    }


def _public_image_storage_settings(settings: dict[str, object]) -> dict[str, object]:
    """image_storage 对外脱敏：webdav 密码不回传明文，仅给 has_* 标志。"""
    public = dict(settings)
    password = str(public.get("webdav_password") or "").strip()
    public["webdav_password"] = ""
    public["has_webdav_password"] = bool(password)
    return public


def _normalize_chat_completion_cache_settings(value: object) -> dict[str, object]:
    source = value if isinstance(value, dict) else {}
    return {
        "enabled": _normalize_bool(source.get("enabled"), DEFAULT_CHAT_COMPLETION_CACHE["enabled"]),
        "ttl_seconds": _normalize_positive_int(
            source.get("ttl_seconds"),
            int(DEFAULT_CHAT_COMPLETION_CACHE["ttl_seconds"]),
            0,
        ),
        "max_entries": _normalize_positive_int(
            source.get("max_entries"),
            int(DEFAULT_CHAT_COMPLETION_CACHE["max_entries"]),
            1,
        ),
        "dedupe_inflight": _normalize_bool(
            source.get("dedupe_inflight"),
            bool(DEFAULT_CHAT_COMPLETION_CACHE["dedupe_inflight"]),
        ),
        "stream_cache": _normalize_bool(
            source.get("stream_cache"),
            bool(DEFAULT_CHAT_COMPLETION_CACHE["stream_cache"]),
        ),
        "normalize_messages": _normalize_bool(
            source.get("normalize_messages"),
            bool(DEFAULT_CHAT_COMPLETION_CACHE["normalize_messages"]),
        ),
        "drop_adjacent_duplicates": _normalize_bool(
            source.get("drop_adjacent_duplicates"),
            bool(DEFAULT_CHAT_COMPLETION_CACHE["drop_adjacent_duplicates"]),
        ),
        "drop_assistant_history": _normalize_bool(
            source.get("drop_assistant_history"),
            bool(DEFAULT_CHAT_COMPLETION_CACHE["drop_assistant_history"]),
        ),
    }


def _normalize_status_codes(value: object) -> list[int]:
    items = value if isinstance(value, list) else DEFAULT_PROXY_RUNTIME["reset_session_status_codes"]
    normalized: list[int] = []
    for item in items:
        if isinstance(item, bool):
            continue
        try:
            status = int(item)
        except (OverflowError, TypeError, ValueError):
            continue
        if 100 <= status <= 599 and status not in normalized:
            normalized.append(status)
    if not normalized:
        return list(DEFAULT_PROXY_RUNTIME["reset_session_status_codes"])
    return normalized


def _normalize_proxy_runtime_settings(value: object) -> dict[str, object]:
    source = value if isinstance(value, dict) else {}
    default_clearance = DEFAULT_PROXY_RUNTIME["clearance"]
    clearance_source = source.get("clearance") if isinstance(source.get("clearance"), dict) else {}

    egress_mode = str(source.get("egress_mode") or DEFAULT_PROXY_RUNTIME["egress_mode"]).strip().lower()
    if egress_mode not in {"direct", "single_proxy"}:
        egress_mode = str(DEFAULT_PROXY_RUNTIME["egress_mode"])

    clearance_mode = str(clearance_source.get("mode") or default_clearance["mode"]).strip().lower()
    if clearance_mode not in {"none", "manual", "flaresolverr"}:
        clearance_mode = str(default_clearance["mode"])

    user_agent = str(clearance_source.get("user_agent") or default_clearance["user_agent"]).strip()
    browser = str(clearance_source.get("browser") or default_clearance["browser"]).strip()

    existing_clearance_cookies = str(source.get("_existing_cf_cookies") or "").strip()
    existing_cf_clearance = str(source.get("_existing_cf_clearance") or "").strip()
    cf_cookies = str(clearance_source.get("cf_cookies") or "").strip()
    cf_clearance = str(clearance_source.get("cf_clearance") or "").strip()
    if not cf_cookies and _normalize_bool(clearance_source.get("has_cf_cookies"), False):
        cf_cookies = existing_clearance_cookies
    if not cf_clearance and _normalize_bool(clearance_source.get("has_cf_clearance"), False):
        cf_clearance = existing_cf_clearance

    return {
        "enabled": _normalize_bool(source.get("enabled"), bool(DEFAULT_PROXY_RUNTIME["enabled"])),
        "egress_mode": egress_mode,
        "proxy_url": str(source.get("proxy_url") or "").strip(),
        "resource_proxy_url": str(source.get("resource_proxy_url") or "").strip(),
        "skip_ssl_verify": _normalize_bool(
            source.get("skip_ssl_verify"),
            bool(DEFAULT_PROXY_RUNTIME["skip_ssl_verify"]),
        ),
        "reset_session_status_codes": _normalize_status_codes(source.get("reset_session_status_codes")),
        "clearance": {
            "enabled": _normalize_bool(clearance_source.get("enabled"), bool(default_clearance["enabled"])),
            "mode": clearance_mode,
            "cf_cookies": cf_cookies,
            "cf_clearance": cf_clearance,
            "user_agent": user_agent or str(default_clearance["user_agent"]),
            "browser": browser or str(default_clearance["browser"]),
            "flaresolverr_url": str(clearance_source.get("flaresolverr_url") or "").strip(),
            "timeout_sec": _normalize_positive_int(
                clearance_source.get("timeout_sec"),
                int(default_clearance["timeout_sec"]),
                1,
            ),
            "refresh_interval": _normalize_positive_int(
                clearance_source.get("refresh_interval"),
                int(default_clearance["refresh_interval"]),
                60,
            ),
            "warm_up_on_start": _normalize_bool(
                clearance_source.get("warm_up_on_start"),
                bool(default_clearance["warm_up_on_start"]),
            ),
        },
    }


def _normalize_third_party_apps_settings(value: object) -> dict[str, object]:
    source = value if isinstance(value, dict) else {}
    canvas_source = source.get("infinite_canvas") if isinstance(source.get("infinite_canvas"), dict) else {}
    return {
        "infinite_canvas": {
            "enabled": _normalize_bool(canvas_source.get("enabled"), False),
            "url": str(canvas_source.get("url") or DEFAULT_THIRD_PARTY_APPS["infinite_canvas"]["url"]).strip(),
        },
    }


def _normalize_domain_ban_rules(value: object) -> list[dict[str, object]]:
    """规范化自定义自动拉黑规则；空 match / 过短 match 丢弃，enabled 默认 True。"""
    if not isinstance(value, list):
        return list(DEFAULT_DOMAIN_BAN_RULES)
    result: list[dict[str, object]] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        match = str(item.get("match") or "").strip()
        if len(match) < _DOMAIN_BAN_MATCH_MIN_LEN:
            continue
        rule: dict[str, object] = {
            "match": match,
            "enabled": _normalize_bool(item.get("enabled"), True),
        }
        rid = str(item.get("id") or "").strip()
        if rid:
            rule["id"] = rid
        result.append(rule)
    return result


def _legacy_basic_from_settings(value: object, settings: dict[str, object]) -> dict[str, object]:
    source = dict(value) if isinstance(value, dict) else {}
    source["proxy"] = str(settings.get("proxy") or "").strip()
    source["base_url"] = str(settings.get("base_url") or "").strip().rstrip("/")
    try:
        source["image_expire_hours"] = max(
            1,
            int(settings.get("image_retention_days", source.get("image_expire_hours", 30)) or 30),
        )
    except (TypeError, ValueError):
        source["image_expire_hours"] = 30
    return source


def _promote_legacy_basic_settings(data: dict[str, object]) -> dict[str, object]:
    next_data = dict(data or {})
    basic = next_data.get("basic")
    if not isinstance(basic, dict):
        return next_data
    if "proxy" not in next_data and "proxy" in basic:
        next_data["proxy"] = str(basic.get("proxy") or "").strip()
    if "base_url" not in next_data and "base_url" in basic:
        next_data["base_url"] = str(basic.get("base_url") or "").strip().rstrip("/")
    if "image_retention_days" not in next_data and "image_expire_hours" in basic:
        next_data["image_retention_days"] = basic.get("image_expire_hours")
    return next_data


def _promote_legacy_proxy_runtime(data: dict[str, object]) -> dict[str, object]:
    """把 install.sh 旧版顶层 flaresolverr_url / clearance_mode 提升进 proxy_runtime。

    应用只读 proxy_runtime.clearance.*；旧安装脚本只写了扁平键，导致 UI 显示清障关闭。
    本函数为只读视图 promote（load/get 时调用），不落盘、不删扁平键，因此必须幂等：

    - 已完整配置的 nested proxy_runtime 不覆盖；
    - **若 nested 已存在（哪怕是默认全关），视作用户/程序已接管，不再用扁平键强制开启**，
      避免「UI 关掉清障后又被扁平键反复 force-enable」。
    只有完全没有 proxy_runtime 键时才从扁平键合成一份（且为幂等输出，重复调用结果一致）。
    """
    next_data = dict(data or {})
    flat_mode = str(next_data.get("clearance_mode") or "").strip().lower()
    flat_url = str(next_data.get("flaresolverr_url") or "").strip()
    flat_interval = next_data.get("clearance_refresh_interval")

    # 无有效扁平配置：不动
    if flat_mode not in {"flaresolverr", "manual"} and not flat_url:
        return next_data

    # 幂等关键：nested 键已存在即视为已接管，绝不根据扁平键强制开启。
    # 新 install.sh 会同时写扁平键（兼容镜像）与 nested；若这里用扁平键 force-enable，
    # 用户在 UI 关掉清障（nested.enabled=false）后，每次 load/get 都会被扁平键重新打开。
    raw_runtime = next_data.get("proxy_runtime")
    if isinstance(raw_runtime, dict):
        return next_data

    mode = flat_mode if flat_mode in {"flaresolverr", "manual"} else ("flaresolverr" if flat_url else "none")
    if mode == "none" and not flat_url:
        return next_data

    clearance: dict[str, object] = {
        "enabled": True,
        "mode": mode,
        "flaresolverr_url": flat_url if mode == "flaresolverr" else "",
    }
    if flat_interval is not None:
        try:
            clearance["refresh_interval"] = max(60, int(flat_interval))  # type: ignore[arg-type]
        except (OverflowError, TypeError, ValueError):
            pass

    # multi-WARP 出口仍走 proxy_pool，egress 保持 direct；clearance_enabled 依赖 runtime.enabled
    next_data["proxy_runtime"] = {
        "enabled": True,
        "egress_mode": "direct",
        "clearance": clearance,
    }
    return next_data


def _promote_legacy_settings(data: dict[str, object]) -> dict[str, object]:
    return _promote_legacy_proxy_runtime(_promote_legacy_basic_settings(data))


# Firefly 平铺键 → channels.firefly.* 命名空间（见 multi-channel/01 §1.2 / 03 §6）
FIREFLY_FLAT_CONFIG_KEYS: tuple[str, ...] = (
    "firefly_enabled",
    "firefly_poll_interval_sec",
    "firefly_gen_timeout_sec",
    "firefly_retry_max_attempts",
    "firefly_refresh_interval_hours",
    "firefly_default_model",
    "firefly_video_enabled",
    "firefly_video_poll_interval_sec",
    "firefly_video_timeout_sec",
    "firefly_video_default_model",
)

# channels.firefly 内字段名（去掉 firefly_ 前缀）
_FIREFLY_NS_KEY_BY_FLAT: dict[str, str] = {
    flat: flat.removeprefix("firefly_") for flat in FIREFLY_FLAT_CONFIG_KEYS
}


def _channels_firefly_dict(data: dict[str, object] | None) -> dict[str, object]:
    root = data if isinstance(data, dict) else {}
    channels = root.get("channels")
    if not isinstance(channels, dict):
        return {}
    firefly = channels.get("firefly")
    return dict(firefly) if isinstance(firefly, dict) else {}


def _firefly_config_value(
    data: dict[str, object] | None,
    flat_key: str,
    default: object = None,
) -> object:
    """新结构优先、旧平铺键兜底。channels.firefly.* > firefly_*。"""
    root = data if isinstance(data, dict) else {}
    ns_key = _FIREFLY_NS_KEY_BY_FLAT.get(flat_key, flat_key.removeprefix("firefly_"))
    nested = _channels_firefly_dict(root)
    if ns_key in nested:
        return nested.get(ns_key)
    if flat_key in root:
        return root.get(flat_key)
    return default


def migrate_firefly_flat_keys_to_namespace(
    data: dict[str, object] | None,
    *,
    drop_flat: bool = False,
) -> tuple[dict[str, object], bool]:
    """把 firefly_* 平铺键迁入 channels.firefly.*（幂等）。

    - 新结构已有字段不覆盖（以 nested 为准）
    - 默认**保留**旧平铺键，供存量读写兼容
    - drop_flat=True 时才删除旧键（本期默认 False）
    返回 (next_data, changed)。
    """
    next_data = dict(data or {})
    flat_present = {key: next_data[key] for key in FIREFLY_FLAT_CONFIG_KEYS if key in next_data}
    if not flat_present and not _channels_firefly_dict(next_data):
        return next_data, False

    channels = next_data.get("channels")
    channels_dict: dict[str, object] = dict(channels) if isinstance(channels, dict) else {}
    firefly = channels_dict.get("firefly")
    firefly_dict: dict[str, object] = dict(firefly) if isinstance(firefly, dict) else {}

    changed = False
    for flat_key, value in flat_present.items():
        ns_key = _FIREFLY_NS_KEY_BY_FLAT[flat_key]
        if ns_key not in firefly_dict:
            firefly_dict[ns_key] = value
            changed = True

    if firefly_dict != (firefly if isinstance(firefly, dict) else {}):
        channels_dict["firefly"] = firefly_dict
        if channels_dict != (channels if isinstance(channels, dict) else {}):
            next_data["channels"] = channels_dict
            changed = True
        elif "channels" not in next_data:
            next_data["channels"] = channels_dict
            changed = True

    if drop_flat:
        for flat_key in FIREFLY_FLAT_CONFIG_KEYS:
            if flat_key in next_data:
                next_data.pop(flat_key, None)
                changed = True

    return next_data, changed


def _sync_firefly_flat_into_namespace(next_data: dict[str, object], payload: dict[str, object]) -> None:
    """本次 update 的 payload 里出现的 firefly_* 平铺键，强制回写进 channels.firefly.*（就地改 next_data）。

    背景（review D3）：Settings 仍写平铺键，而读取是 nested 优先；migrate 只在 nested 缺省时
    填一次，之后 UI 改 flat 不会覆盖 nested → 改了不生效。这里让「本次提交的 flat 键」无条件
    同步到 nested，保证 nested 总是反映最新 UI 写入；flat 仍保留作只读兼容。
    """
    channels = next_data.setdefault("channels", {})
    if not isinstance(channels, dict):
        return
    firefly = channels.setdefault("firefly", {})
    if not isinstance(firefly, dict):
        return
    for flat_key, value in (payload or {}).items():
        if flat_key not in FIREFLY_FLAT_CONFIG_KEYS:
            continue
        ns_key = _FIREFLY_NS_KEY_BY_FLAT.get(flat_key, flat_key.removeprefix("firefly_"))
        firefly[ns_key] = value


# 设置项「********」哨兵：与 backup_service.get_settings 脱敏值一致，防止脱敏值被当真值写回
_SECRET_SENTINEL = "********"


def _masked_secret_keep_previous(incoming: object, has_flag: object, previous: str) -> str:
    """密钥字段「不回填不覆盖」：

    - 传入空串 / 「********」哨兵 / has_*=true 且未给新值 → 保留旧值；
    - 否则采用新值（允许显式改成新密钥；清空密钥需走专用接口，不在通用设置里误触发）。
    """
    text = str(incoming or "").strip()
    if not text or text == _SECRET_SENTINEL or _normalize_bool(has_flag, False):
        return previous
    return text


def _preserve_masked_secrets(previous_data: dict[str, object], next_data: dict[str, object]) -> None:
    """update 时把「脱敏/未改」的密钥字段还原为旧值，避免设置页改无关项后密钥被清空或写入哨兵字面量。

    覆盖 backup.secret_access_key / backup.passphrase、image_storage.webdav_password、ai_review.api_key。
    就地修改 next_data。
    """
    # backup
    if "backup" in next_data:
        prev_backup = previous_data.get("backup") if isinstance(previous_data.get("backup"), dict) else {}
        next_backup = next_data.get("backup")
        if isinstance(next_backup, dict) and isinstance(prev_backup, dict):
            next_backup = dict(next_backup)
            for field, flag in (("secret_access_key", "has_secret_access_key"), ("passphrase", "has_passphrase")):
                next_backup[field] = _masked_secret_keep_previous(
                    next_backup.get(field), next_backup.get(flag), str(prev_backup.get(field) or "").strip()
                )
                next_backup.pop(flag, None)
            next_data["backup"] = next_backup
    # image_storage
    if "image_storage" in next_data:
        prev_storage = previous_data.get("image_storage") if isinstance(previous_data.get("image_storage"), dict) else {}
        next_storage = next_data.get("image_storage")
        if isinstance(next_storage, dict) and isinstance(prev_storage, dict):
            next_storage = dict(next_storage)
            next_storage["webdav_password"] = _masked_secret_keep_previous(
                next_storage.get("webdav_password"),
                next_storage.get("has_webdav_password"),
                str(prev_storage.get("webdav_password") or "").strip(),
            )
            next_storage.pop("has_webdav_password", None)
            next_data["image_storage"] = next_storage
    # ai_review
    if "ai_review" in next_data:
        prev_review = previous_data.get("ai_review") if isinstance(previous_data.get("ai_review"), dict) else {}
        next_review = next_data.get("ai_review")
        if isinstance(next_review, dict) and isinstance(prev_review, dict):
            next_review = dict(next_review)
            next_review["api_key"] = _masked_secret_keep_previous(
                next_review.get("api_key"), next_review.get("has_api_key"), str(prev_review.get("api_key") or "").strip()
            )
            next_review.pop("has_api_key", None)
            next_data["ai_review"] = next_review


def _validate_image_storage_settings(settings: dict[str, object]) -> None:
    if not _normalize_bool(settings.get("enabled"), False):
        return
    if not str(settings.get("webdav_url") or "").strip():
        raise ValueError("启用 WebDAV 图片存储后必须填写 WebDAV URL")
    if not str(settings.get("webdav_password") or "").strip():
        raise ValueError("启用 WebDAV 图片存储后必须填写 WebDAV 密码")


@dataclass(frozen=True)
class LoadedSettings:
    auth_key: str
    refresh_account_interval_minute: int


def _normalize_auth_key(value: object) -> str:
    return str(value or "").strip()


def _is_invalid_auth_key(value: object) -> bool:
    return _normalize_auth_key(value) == ""


def _load_settings() -> LoadedSettings:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    raw_config = read_json_object(CONFIG_FILE, name="config.json")
    auth_key = _normalize_auth_key(os.getenv("CHATGPT2API_AUTH_KEY") or raw_config.get("auth-key"))
    if _is_invalid_auth_key(auth_key):
        raise ValueError(
            "❌ auth-key 未设置！\n"
            "请在环境变量 CHATGPT2API_AUTH_KEY 中设置，或者在 config.json 中填写 auth-key。"
        )

    try:
        refresh_interval = int(raw_config.get("refresh_account_interval_minute", 5))
    except (TypeError, ValueError):
        refresh_interval = 5

    return LoadedSettings(
        auth_key=auth_key,
        refresh_account_interval_minute=refresh_interval,
    )


class ConfigStore:
    def __init__(self, path: Path):
        self.path = path
        self._lock = threading.RLock()
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        self.data = _promote_legacy_settings(self._load())
        # 启动时幂等迁移 firefly_* → channels.firefly.*（保留旧键）
        self._maybe_migrate_firefly_namespace(persist=True)
        self._loaded_mtime_ns = self._config_mtime_ns()
        self._storage_backend: StorageBackend | None = None
        if _is_invalid_auth_key(self.auth_key):
            raise ValueError(
                "❌ auth-key 未设置！\n"
                "请按以下任意一种方式解决：\n"
                "1. 在 Render 的 Environment 变量中添加：\n"
                "   CHATGPT2API_AUTH_KEY = your_real_auth_key\n"
                "2. 或者在 config.json 中填写：\n"
                '   "auth-key": "your_real_auth_key"'
            )

    def _load(self) -> dict[str, object]:
        return read_json_object(self.path, name="config.json")

    def _config_mtime_ns(self) -> int:
        try:
            return self.path.stat().st_mtime_ns
        except OSError:
            return 0

    def _maybe_migrate_firefly_namespace(self, *, persist: bool = True) -> bool:
        """幂等迁移；已迁则跳过。返回是否发生写入。"""
        migrated, changed = migrate_firefly_flat_keys_to_namespace(self.data, drop_flat=False)
        if not changed:
            return False
        self.data = migrated
        if persist:
            self._save()
        return True

    def ensure_firefly_namespace_migrated(self) -> bool:
        """对外入口：起服务/测试可显式再跑一次（幂等）。"""
        with self._lock:
            self.reload_if_changed()
            return self._maybe_migrate_firefly_namespace(persist=True)

    def reload_if_changed(self) -> None:
        with self._lock:
            current_mtime_ns = self._config_mtime_ns()
            if current_mtime_ns and current_mtime_ns != self._loaded_mtime_ns:
                self.data = _promote_legacy_settings(self._load())
                # 外部改盘后也补齐命名空间（不强制写盘，避免抢写；下次 update/启动再落）
                migrated, changed = migrate_firefly_flat_keys_to_namespace(self.data, drop_flat=False)
                if changed:
                    self.data = migrated
                self._loaded_mtime_ns = current_mtime_ns

    def _save(self) -> None:
        write_json_file(self.path, self.data)
        self._loaded_mtime_ns = self._config_mtime_ns()

    def _read_firefly_value(self, flat_key: str, default: object = None) -> object:
        return _firefly_config_value(self.data, flat_key, default)

    @property
    def auth_key(self) -> str:
        return _normalize_auth_key(os.getenv("CHATGPT2API_AUTH_KEY") or self.data.get("auth-key"))

    @property
    def accounts_file(self) -> Path:
        return DATA_DIR / "accounts.json"

    @property
    def refresh_account_interval_minute(self) -> int:
        try:
            return int(self.data.get("refresh_account_interval_minute", 5))
        except (TypeError, ValueError):
            return 5

    @property
    def image_retention_days(self) -> int:
        try:
            return max(1, int(self.data.get("image_retention_days", 30)))
        except (TypeError, ValueError):
            return 30

    @property
    def log_retention_days(self) -> int:
        try:
            return max(1, int(self.data.get("log_retention_days", 30)))
        except (TypeError, ValueError):
            return 30

    @property
    def image_poll_timeout_secs(self) -> int:
        self.reload_if_changed()
        try:
            return max(1, int(self.data.get("image_poll_timeout_secs", 120)))
        except (TypeError, ValueError):
            return 120

    @property
    def image_stream_timeout_secs(self) -> int:
        self.reload_if_changed()
        try:
            return max(1, int(self.data.get("image_stream_timeout_secs", 300)))
        except (TypeError, ValueError):
            return 300

    @property
    def image_poll_interval_secs(self) -> float:
        try:
            return max(0.5, float(self.data.get("image_poll_interval_secs", 10.0)))
        except (TypeError, ValueError):
            return 10.0

    @property
    def image_poll_initial_wait_secs(self) -> float:
        """Image generation upstream takes ~30s; polling immediately wastes requests
        and trips a transient 429. Default 10s gives the conversation document time
        to commit before the first poll."""
        try:
            return max(0.0, float(self.data.get("image_poll_initial_wait_secs", 10.0)))
        except (TypeError, ValueError):
            return 10.0

    @property
    def image_account_concurrency(self) -> int:
        try:
            return max(1, int(self.data.get("image_account_concurrency", 3)))
        except (TypeError, ValueError):
            return 3

    @property
    def image_parallel_generation(self) -> bool:
        value = self.data.get("image_parallel_generation", True)
        if isinstance(value, str):
            return value.strip().lower() in {"1", "true", "yes", "on"}
        return bool(value)

    # ---- Adobe Firefly 渠道（环境变量 CHATGPT2API_FIREFLY_* 覆盖 config.json）----
    # 读路径：env > channels.firefly.* > 旧 firefly_* 平铺键 > 默认值

    @property
    def firefly_enabled(self) -> bool:
        self.reload_if_changed()
        env = os.getenv("CHATGPT2API_FIREFLY_ENABLED")
        if env is not None and str(env).strip() != "":
            return _normalize_bool(env, False)
        return _normalize_bool(self._read_firefly_value("firefly_enabled", False), False)

    @property
    def firefly_poll_interval_sec(self) -> int:
        self.reload_if_changed()
        env = os.getenv("CHATGPT2API_FIREFLY_POLL_INTERVAL_SEC")
        raw = (
            env
            if env is not None and str(env).strip() != ""
            else self._read_firefly_value("firefly_poll_interval_sec", 3)
        )
        return _normalize_positive_int(raw, 3, 1)

    @property
    def firefly_gen_timeout_sec(self) -> int:
        self.reload_if_changed()
        env = os.getenv("CHATGPT2API_FIREFLY_GEN_TIMEOUT_SEC")
        raw = (
            env
            if env is not None and str(env).strip() != ""
            else self._read_firefly_value("firefly_gen_timeout_sec", 180)
        )
        return _normalize_positive_int(raw, 180, 1)

    @property
    def firefly_retry_max_attempts(self) -> int:
        self.reload_if_changed()
        env = os.getenv("CHATGPT2API_FIREFLY_RETRY_MAX_ATTEMPTS")
        raw = (
            env
            if env is not None and str(env).strip() != ""
            else self._read_firefly_value("firefly_retry_max_attempts", 3)
        )
        return _normalize_positive_int(raw, 3, 1)

    @property
    def firefly_refresh_interval_hours(self) -> int:
        self.reload_if_changed()
        env = os.getenv("CHATGPT2API_FIREFLY_REFRESH_INTERVAL_HOURS")
        raw = (
            env
            if env is not None and str(env).strip() != ""
            else self._read_firefly_value("firefly_refresh_interval_hours", 15)
        )
        return _normalize_positive_int(raw, 15, 1)

    @property
    def firefly_default_model(self) -> str:
        self.reload_if_changed()
        env = os.getenv("CHATGPT2API_FIREFLY_DEFAULT_MODEL")
        if env is not None and str(env).strip():
            return str(env).strip()
        value = str(self._read_firefly_value("firefly_default_model") or "firefly-nano-banana-pro").strip()
        return value or "firefly-nano-banana-pro"

    @property
    def firefly_video_enabled(self) -> bool:
        """Firefly 视频渠道开关（默认关）。环境变量 CHATGPT2API_FIREFLY_VIDEO_ENABLED 覆盖。"""
        self.reload_if_changed()
        env = os.getenv("CHATGPT2API_FIREFLY_VIDEO_ENABLED")
        if env is not None and str(env).strip() != "":
            return _normalize_bool(env, False)
        return _normalize_bool(self._read_firefly_value("firefly_video_enabled", False), False)

    @property
    def firefly_video_poll_interval_sec(self) -> int:
        self.reload_if_changed()
        env = os.getenv("CHATGPT2API_FIREFLY_VIDEO_POLL_INTERVAL_SEC")
        raw = (
            env
            if env is not None and str(env).strip() != ""
            else self._read_firefly_value("firefly_video_poll_interval_sec", 3)
        )
        return _normalize_positive_int(raw, 3, 1)

    @property
    def firefly_video_timeout_sec(self) -> int:
        self.reload_if_changed()
        env = os.getenv("CHATGPT2API_FIREFLY_VIDEO_TIMEOUT_SEC")
        raw = (
            env
            if env is not None and str(env).strip() != ""
            else self._read_firefly_value("firefly_video_timeout_sec", 600)
        )
        return _normalize_positive_int(raw, 600, 1)

    @property
    def firefly_video_default_model(self) -> str:
        self.reload_if_changed()
        env = os.getenv("CHATGPT2API_FIREFLY_VIDEO_DEFAULT_MODEL")
        if env is not None and str(env).strip():
            return str(env).strip()
        value = str(self._read_firefly_value("firefly_video_default_model") or "firefly-sora2-4s-16x9").strip()
        return value or "firefly-sora2-4s-16x9"

    @property
    def image_remove_conversation_after_result(self) -> bool:
        self.reload_if_changed()
        return _normalize_bool(self.data.get("image_remove_conversation_after_result"), False)

    @property
    def image_error_friendly_enabled(self) -> bool:
        self.reload_if_changed()
        value = self.data.get("image_error_friendly_enabled", False)
        if isinstance(value, str):
            return value.strip().lower() in {"1", "true", "yes", "on"}
        return bool(value)

    def get_image_error_messages(self) -> dict[str, str]:
        self.reload_if_changed()
        value = self.data.get("image_error_messages")
        source = value if isinstance(value, dict) else {}
        messages: dict[str, str] = {}
        for key, default in DEFAULT_IMAGE_ERROR_MESSAGES.items():
            custom = str(source.get(key) or "").strip()
            messages[key] = custom or default
        return messages

    @property
    def image_settle_enabled(self) -> bool:
        """图片二次确认机制：找到 file_ids 后等待一段时间再次确认。"""
        value = self.data.get("image_settle_enabled", True)
        if isinstance(value, str):
            return value.strip().lower() in {"1", "true", "yes", "on"}
        return bool(value)

    @property
    def image_check_before_hit_enabled(self) -> bool:
        """先check再hit：通过轮询确认 file_ids 存在后再返回，而非仅依赖 SSE 事件。"""
        value = self.data.get("image_check_before_hit_enabled", True)
        if isinstance(value, str):
            return value.strip().lower() in {"1", "true", "yes", "on"}
        return bool(value)

    @property
    def image_settle_secs(self) -> float:
        """二次确认等待时间（秒）。"""
        try:
            return max(0.5, float(self.data.get("image_settle_secs", 5.0)))
        except (TypeError, ValueError):
            return 5.0

    @property
    def image_upscale_enabled(self) -> bool:
        """是否在图片交付前自动放大到请求尺寸。"""
        self.reload_if_changed()
        return _normalize_bool(self.data.get("image_upscale_enabled"), False)

    @property
    def image_upscale_engine(self) -> str:
        """图片放大引擎：sharp_lanczos3（优先，失败回退 pillow）或 pillow_lanczos。"""
        self.reload_if_changed()
        value = str(self.data.get("image_upscale_engine") or "sharp_lanczos3").strip().lower()
        return value if value in {"sharp_lanczos3", "pillow_lanczos"} else "sharp_lanczos3"

    @property
    def auto_remove_invalid_accounts(self) -> bool:
        value = self.data.get("auto_remove_invalid_accounts", False)
        if isinstance(value, str):
            return value.strip().lower() in {"1", "true", "yes", "on"}
        return bool(value)

    @property
    def auto_remove_rate_limited_accounts(self) -> bool:
        value = self.data.get("auto_remove_rate_limited_accounts", False)
        if isinstance(value, str):
            return value.strip().lower() in {"1", "true", "yes", "on"}
        return bool(value)

    @property
    def log_levels(self) -> list[str]:
        levels = self.data.get("log_levels")
        if not isinstance(levels, list):
            return []
        allowed = {"debug", "info", "warning", "error"}
        return [level for item in levels if (level := str(item or "").strip().lower()) in allowed]

    @property
    def sensitive_words(self) -> list[str]:
        words = self.data.get("sensitive_words")
        return [word for item in words if (word := str(item or "").strip())] if isinstance(words, list) else []

    @property
    def ai_review(self) -> dict[str, object]:
        value = self.data.get("ai_review")
        return value if isinstance(value, dict) else {}

    def get_public_ai_review_settings(self) -> dict[str, object]:
        """ai_review 对外脱敏：api_key 不回传明文，仅给 has_* 标志。"""
        public = dict(self.ai_review)
        api_key = str(public.get("api_key") or "").strip()
        public["api_key"] = ""
        public["has_api_key"] = bool(api_key)
        return public

    @property
    def global_system_prompt(self) -> str:
        return str(self.data.get("global_system_prompt") or "").strip()

    @property
    def images_dir(self) -> Path:
        path = DATA_DIR / "images"
        path.mkdir(parents=True, exist_ok=True)
        return path

    @property
    def image_thumbnails_dir(self) -> Path:
        path = DATA_DIR / "image_thumbnails"
        path.mkdir(parents=True, exist_ok=True)
        return path

    def cleanup_old_images(self) -> int:
        cutoff = time.time() - self.image_retention_days * 86400
        removed = 0
        for path in self.images_dir.rglob("*"):
            if path.is_file() and path.stat().st_mtime < cutoff:
                path.unlink()
                removed += 1
        for path in sorted((p for p in self.images_dir.rglob("*") if p.is_dir()), key=lambda p: len(p.parts), reverse=True):
            try:
                path.rmdir()
            except OSError:
                pass
        return removed

    @property
    def base_url(self) -> str:
        return str(
            os.getenv("CHATGPT2API_BASE_URL")
            or self.data.get("base_url")
            or ""
        ).strip().rstrip("/")

    @property
    def app_version(self) -> str:
        try:
            value = VERSION_FILE.read_text(encoding="utf-8").strip()
        except FileNotFoundError:
            return "0.0.0"
        return value or "0.0.0"

    def get(self) -> dict[str, object]:
        with self._lock:
            self.reload_if_changed()
            data = dict(self.data)
            data["refresh_account_interval_minute"] = self.refresh_account_interval_minute
            data["image_retention_days"] = self.image_retention_days
            data["log_retention_days"] = self.log_retention_days
            data["image_poll_timeout_secs"] = self.image_poll_timeout_secs
            data["image_stream_timeout_secs"] = self.image_stream_timeout_secs
            data["image_poll_interval_secs"] = self.image_poll_interval_secs
            data["image_poll_initial_wait_secs"] = self.image_poll_initial_wait_secs
            data["image_account_concurrency"] = self.image_account_concurrency
            data["image_parallel_generation"] = self.image_parallel_generation
            data["firefly_enabled"] = self.firefly_enabled
            data["firefly_poll_interval_sec"] = self.firefly_poll_interval_sec
            data["firefly_gen_timeout_sec"] = self.firefly_gen_timeout_sec
            data["firefly_retry_max_attempts"] = self.firefly_retry_max_attempts
            data["firefly_refresh_interval_hours"] = self.firefly_refresh_interval_hours
            data["firefly_default_model"] = self.firefly_default_model
            data["firefly_video_enabled"] = self.firefly_video_enabled
            data["firefly_video_poll_interval_sec"] = self.firefly_video_poll_interval_sec
            data["firefly_video_timeout_sec"] = self.firefly_video_timeout_sec
            data["firefly_video_default_model"] = self.firefly_video_default_model
            data["image_remove_conversation_after_result"] = self.image_remove_conversation_after_result
            data["image_error_friendly_enabled"] = self.image_error_friendly_enabled
            data["image_error_messages"] = self.get_image_error_messages()
            data["image_upscale_enabled"] = self.image_upscale_enabled
            data["image_upscale_engine"] = self.image_upscale_engine
            data["auto_remove_invalid_accounts"] = self.auto_remove_invalid_accounts
            data["auto_remove_rate_limited_accounts"] = self.auto_remove_rate_limited_accounts
            data["log_levels"] = self.log_levels
            data["sensitive_words"] = self.sensitive_words
            data["ai_review"] = self.get_public_ai_review_settings()
            data["global_system_prompt"] = self.global_system_prompt
            data["backup"] = _public_backup_settings(self.get_backup_settings())
            data["image_storage"] = _public_image_storage_settings(self.get_image_storage_settings())
            data["chat_completion_cache"] = self.get_chat_completion_cache_settings()
            data["proxy_runtime"] = self.get_public_proxy_runtime_settings()
            data["fallback_proxy"] = self.get_proxy_fallback_settings()
            data["third_party_apps"] = self.get_third_party_apps_settings()
            data["domain_ban_rules"] = self.get_domain_ban_rules()
            data["basic"] = _legacy_basic_from_settings(data.get("basic"), data)
            data.pop("auth-key", None)
            return data

    def get_proxy_settings(self) -> str:
        return str(self.data.get("proxy") or "").strip()

    def get_proxy_fallback_settings(self) -> str:
        return str(self.data.get("fallback_proxy") or "").strip()

    def get_proxy_runtime_settings(self) -> dict[str, object]:
        promoted = _promote_legacy_proxy_runtime(self.data if isinstance(self.data, dict) else {})
        return _normalize_proxy_runtime_settings(promoted.get("proxy_runtime"))

    def get_public_proxy_runtime_settings(self) -> dict[str, object]:
        runtime = copy.deepcopy(self.get_proxy_runtime_settings())
        clearance = runtime.get("clearance") if isinstance(runtime.get("clearance"), dict) else {}
        if isinstance(clearance, dict):
            cf_cookies = str(clearance.get("cf_cookies") or "").strip()
            cf_clearance = str(clearance.get("cf_clearance") or "").strip()
            clearance["cf_cookies"] = ""
            clearance["cf_clearance"] = ""
            clearance["has_cf_cookies"] = bool(cf_cookies)
            clearance["has_cf_clearance"] = bool(cf_clearance)
        return runtime

    def get_third_party_apps_settings(self) -> dict[str, object]:
        return _normalize_third_party_apps_settings(self.data.get("third_party_apps"))

    def get_domain_ban_rules(self) -> list[dict[str, object]]:
        return _normalize_domain_ban_rules(self.data.get("domain_ban_rules"))

    def update(self, data: dict[str, object]) -> dict[str, object]:
        with self._lock:
            self.reload_if_changed()
            next_data = _promote_legacy_settings(self.data)
            next_data.update(_promote_legacy_settings(dict(data or {})))
            next_data = _promote_legacy_settings(next_data)
            _preserve_masked_secrets(self.data, next_data)
            if "backup" in next_data:
                next_data["backup"] = _normalize_backup_settings(next_data.get("backup"))
            if "image_storage" in next_data:
                next_data["image_storage"] = _normalize_image_storage_settings(next_data.get("image_storage"))
                _validate_image_storage_settings(next_data["image_storage"])
            if "chat_completion_cache" in next_data:
                next_data["chat_completion_cache"] = _normalize_chat_completion_cache_settings(
                    next_data.get("chat_completion_cache")
                )
            if "third_party_apps" in next_data:
                next_data["third_party_apps"] = _normalize_third_party_apps_settings(next_data.get("third_party_apps"))
            if "domain_ban_rules" in next_data:
                next_data["domain_ban_rules"] = _normalize_domain_ban_rules(next_data.get("domain_ban_rules"))
            if "proxy_runtime" in next_data:
                incoming_runtime = next_data.get("proxy_runtime")
                if isinstance(incoming_runtime, dict):
                    previous_clearance = self.get_proxy_runtime_settings().get("clearance")
                    if isinstance(previous_clearance, dict):
                        incoming_runtime = dict(incoming_runtime)
                        incoming_runtime["_existing_cf_cookies"] = previous_clearance.get("cf_cookies")
                        incoming_runtime["_existing_cf_clearance"] = previous_clearance.get("cf_clearance")
                next_data["proxy_runtime"] = _normalize_proxy_runtime_settings(incoming_runtime)
            # 本次提交的 firefly_* 平铺键先强制同步进 nested（review D3：UI 写 flat 要生效）
            _sync_firefly_flat_into_namespace(next_data, data if isinstance(data, dict) else {})
            # 写入后同步命名空间：新结构为主，旧键继续保留可读
            next_data, _ = migrate_firefly_flat_keys_to_namespace(next_data, drop_flat=False)
            next_data["basic"] = _legacy_basic_from_settings(next_data.get("basic"), next_data)
            next_data.pop("backup_state", None)
            self.data = next_data
            self._save()
        return self.get()

    def get_backup_settings(self) -> dict[str, object]:
        return _normalize_backup_settings(self.data.get("backup"))

    def get_image_storage_settings(self) -> dict[str, object]:
        return _normalize_image_storage_settings(self.data.get("image_storage"))

    def get_chat_completion_cache_settings(self) -> dict[str, object]:
        return _normalize_chat_completion_cache_settings(self.data.get("chat_completion_cache"))

    def get_storage_backend(self) -> StorageBackend:
        """获取存储后端实例（单例）"""
        if self._storage_backend is None:
            from services.storage.factory import create_storage_backend
            self._storage_backend = create_storage_backend(DATA_DIR)
        return self._storage_backend


def load_backup_state() -> dict[str, object]:
    return _normalize_backup_state(read_json_object(BACKUP_STATE_FILE, name="backup_state.json"))


def save_backup_state(state: dict[str, object]) -> dict[str, object]:
    normalized = _normalize_backup_state(state)
    write_json_file(BACKUP_STATE_FILE, normalized)
    return normalized


config = ConfigStore(CONFIG_FILE)
