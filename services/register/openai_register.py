from __future__ import annotations

import base64
import json
import random
import re
import secrets
import string
import threading
import time
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Literal
from urllib.parse import parse_qs, urlencode, urljoin, urlparse

from curl_cffi import requests
from curl_cffi.requests import BrowserTypeLiteral
from curl_cffi.requests.session import HttpMethod

from services.account_service import account_service
from services.json_file import read_json_object
from services.proxy_service import ClearanceBundle, proxy_settings
from services.register import mail_provider
from utils.diagnostics import redact_auth_diagnostic
from utils.pkce import generate_pkce as _generate_pkce
from utils.sentinel import (
    SentinelTokenGenerator as SentinelTokenGenerator,
    build_sentinel_token as _build_sentinel_token_tuple,
    build_sentinel_with_so_token as _build_sentinel_with_so_token_tuple,
)
from utils.timezone import TIME_FORMAT, beijing_now_str

base_dir = Path(__file__).resolve().parent
config = {
    "mail": {
        "request_timeout": 30,
        "wait_timeout": 30,
        "wait_interval": 2,
        "api_use_register_proxy": True,
        "providers": [],
    },
    "proxy": "",
    "proxy_pool": [],
    "total": 10,
    "threads": 3,
    "max_relogin_retries": 3,
}
register_config_file = base_dir.parents[1] / "data" / "register.json"
try:
    saved_config = read_json_object(register_config_file, name="register.json")
    config.update({key: saved_config[key] for key in ("mail", "proxy", "proxy_pool", "total", "threads", "max_relogin_retries") if key in saved_config})
    raw_proxy_pool = config.get("proxy_pool")
    if isinstance(raw_proxy_pool, list):
        config["proxy_pool"] = [str(item).strip() for item in raw_proxy_pool if str(item or "").strip()]
    else:
        config["proxy_pool"] = []
    legacy_proxy = str(config.get("proxy") or "").strip()
    config["proxy"] = legacy_proxy
    if legacy_proxy and not config["proxy_pool"]:
        config["proxy_pool"] = [legacy_proxy]
except Exception:
    pass

auth_base = "https://auth.openai.com"
platform_base = "https://platform.openai.com"
platform_oauth_client_id = "app_2SKx67EdpoN0G6j64rFvigXD"
platform_oauth_redirect_uri = f"{platform_base}/auth/callback"
platform_oauth_audience = "https://api.openai.com/v1"
platform_auth0_client = "eyJuYW1lIjoiYXV0aDAtc3BhLWpzIiwidmVyc2lvbiI6IjEuMjEuMCJ9"
REGISTER_BROWSER_PROFILES: tuple[dict[str, str], ...] = (
    {
        "impersonate": "chrome142",
        "major": "142",
        "full_version": "142.0.0.0",
        "platform_version": "10.0.0",
        "accept_language": "en-US,en;q=0.9",
    },
    {
        "impersonate": "chrome136",
        "major": "136",
        "full_version": "136.0.0.0",
        "platform_version": "10.0.0",
        "accept_language": "en-US,en;q=0.9",
    },
    {
        "impersonate": "chrome131",
        "major": "131",
        "full_version": "131.0.0.0",
        "platform_version": "10.0.0",
        "accept_language": "en-US,en;q=0.9",
    },
)


def _chrome_user_agent(major: str, full_version: str) -> str:
    return (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        f"Chrome/{full_version} Safari/537.36"
    )


def _chrome_sec_ch_ua(major: str) -> str:
    return f'"Chromium";v="{major}", "Google Chrome";v="{major}", "Not_A Brand";v="99"'


def _chrome_sec_ch_ua_full_version_list(major: str, full_version: str) -> str:
    return (
        f'"Chromium";v="{full_version}", '
        f'"Google Chrome";v="{full_version}", '
        '"Not_A Brand";v="99.0.0.0"'
    )


def _complete_browser_fingerprint(profile: dict[str, str]) -> dict[str, str]:
    major = str(profile.get("major") or "142").strip()
    full_version = str(profile.get("full_version") or f"{major}.0.0.0").strip()
    return {
        **profile,
        "major": major,
        "full_version": full_version,
        "user_agent": str(profile.get("user_agent") or _chrome_user_agent(major, full_version)),
        "sec_ch_ua": str(profile.get("sec_ch_ua") or _chrome_sec_ch_ua(major)),
        "sec_ch_ua_full_version_list": str(
            profile.get("sec_ch_ua_full_version_list") or _chrome_sec_ch_ua_full_version_list(major, full_version)
        ),
        "accept_language": str(profile.get("accept_language") or "en-US,en;q=0.9"),
        "platform_version": str(profile.get("platform_version") or "10.0.0"),
        "impersonate": str(profile.get("impersonate") or "chrome"),
    }


DEFAULT_BROWSER_FINGERPRINT = _complete_browser_fingerprint(REGISTER_BROWSER_PROFILES[0])
user_agent = DEFAULT_BROWSER_FINGERPRINT["user_agent"]
sec_ch_ua = DEFAULT_BROWSER_FINGERPRINT["sec_ch_ua"]
sec_ch_ua_full_version_list = DEFAULT_BROWSER_FINGERPRINT["sec_ch_ua_full_version_list"]
default_timeout = 30
print_lock = threading.Lock()
stats_lock = threading.Lock()
stats = {"done": 0, "success": 0, "fail": 0, "start_time": 0.0}
register_log_sink = None

common_headers = {
    "accept": "application/json",
    "accept-encoding": "gzip, deflate, br",
    "accept-language": "en-US,en;q=0.9",
    "cache-control": "no-cache",
    "connection": "keep-alive",
    "content-type": "application/json",
    "dnt": "1",
    "origin": auth_base,
    "priority": "u=1, i",
    "sec-gpc": "1",
    "sec-ch-ua": sec_ch_ua,
    "sec-ch-ua-arch": '"x86_64"',
    "sec-ch-ua-bitness": '"64"',
    "sec-ch-ua-full-version-list": sec_ch_ua_full_version_list,
    "sec-ch-ua-mobile": "?0",
    "sec-ch-ua-model": '""',
    "sec-ch-ua-platform": '"Windows"',
    "sec-ch-ua-platform-version": '"10.0.0"',
    "sec-fetch-dest": "empty",
    "sec-fetch-mode": "cors",
    "sec-fetch-site": "same-origin",
    "user-agent": user_agent,
}

navigate_headers = {
    "accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "accept-encoding": "gzip, deflate, br",
    "accept-language": "en-US,en;q=0.9",
    "cache-control": "max-age=0",
    "connection": "keep-alive",
    "dnt": "1",
    "sec-gpc": "1",
    "sec-ch-ua": sec_ch_ua,
    "sec-ch-ua-arch": '"x86_64"',
    "sec-ch-ua-bitness": '"64"',
    "sec-ch-ua-full-version-list": sec_ch_ua_full_version_list,
    "sec-ch-ua-mobile": "?0",
    "sec-ch-ua-model": '""',
    "sec-ch-ua-platform": '"Windows"',
    "sec-ch-ua-platform-version": '"10.0.0"',
    "sec-fetch-dest": "document",
    "sec-fetch-mode": "navigate",
    "sec-fetch-site": "same-origin",
    "sec-fetch-user": "?1",
    "upgrade-insecure-requests": "1",
    "user-agent": user_agent,
}


def _browser_fingerprint(fingerprint: dict[str, str] | None = None) -> dict[str, str]:
    return _complete_browser_fingerprint(fingerprint or DEFAULT_BROWSER_FINGERPRINT)


def _header_fingerprint(headers: dict[str, str], fingerprint: dict[str, str] | None = None) -> dict[str, str]:
    fp = _browser_fingerprint(fingerprint)
    next_headers = dict(headers)
    next_headers["user-agent"] = fp["user_agent"]
    next_headers["sec-ch-ua"] = fp["sec_ch_ua"]
    if "sec-ch-ua-full-version-list" in next_headers:
        next_headers["sec-ch-ua-full-version-list"] = fp["sec_ch_ua_full_version_list"]
    if "sec-ch-ua-platform-version" in next_headers:
        next_headers["sec-ch-ua-platform-version"] = f'"{fp["platform_version"]}"'
    if "accept-language" in next_headers:
        next_headers["accept-language"] = fp["accept_language"]
    return next_headers


def _extract_chrome_version_from_user_agent(value: str) -> tuple[str, str]:
    ua = str(value or "")
    for marker in ("Chrome/", "Chromium/", "Edg/"):
        if marker not in ua:
            continue
        tail = ua.split(marker, 1)[1]
        version = tail.split(" ", 1)[0].strip()
        major = version.split(".", 1)[0].strip()
        if major.isdigit():
            return major, version or f"{major}.0.0.0"
    return "", ""


def _fingerprint_with_user_agent(fingerprint: dict[str, str] | None, value: str) -> dict[str, str]:
    ua = str(value or "").strip()
    if not ua:
        return _browser_fingerprint(fingerprint)
    fp = _browser_fingerprint(fingerprint)
    major, full_version = _extract_chrome_version_from_user_agent(ua)
    major = major or fp["major"]
    full_version = full_version or f"{major}.0.0.0"
    return {
        **fp,
        "major": major,
        "full_version": full_version,
        "user_agent": ua,
        "sec_ch_ua": _chrome_sec_ch_ua(major),
        "sec_ch_ua_full_version_list": _chrome_sec_ch_ua_full_version_list(major, full_version),
    }


def _make_browser_fingerprint() -> dict[str, str]:
    return _complete_browser_fingerprint(secrets.choice(REGISTER_BROWSER_PROFILES))


def _session_impersonate(value: str) -> BrowserTypeLiteral:
    match value:
        case "chrome142":
            return "chrome142"
        case "chrome136":
            return "chrome136"
        case "chrome131":
            return "chrome131"
        case _:
            return "chrome"


def log(text: str, color: str = "") -> None:
    colors = {"red": "\033[31m", "green": "\033[32m", "yellow": "\033[33m"}
    if register_log_sink:
        try:
            register_log_sink(text, color)
        except Exception:
            pass
    with print_lock:
        prefix = colors.get(color, "")
        suffix = "\033[0m" if prefix else ""
        print(f"{prefix}{beijing_now_str(TIME_FORMAT)} {text}{suffix}")


def step(index: int, text: str, color: str = "") -> None:
    log(f"[任务{index}] {text}", color)


def _make_trace_headers() -> dict[str, str]:
    trace_id = str(random.getrandbits(64))
    parent_id = str(random.getrandbits(64))
    return {
        "traceparent": f"00-{uuid.uuid4().hex}-{format(int(parent_id), '016x')}-01",
        "tracestate": "dd=s:1;o:rum",
        "x-datadog-origin": "rum",
        "x-datadog-parent-id": parent_id,
        "x-datadog-sampling-priority": "1",
        "x-datadog-trace-id": trace_id,
    }


def _random_password(length: int = 16) -> str:
    chars = string.ascii_letters + string.digits + "!@#$%"
    value = list(
        secrets.choice(string.ascii_uppercase)
        + secrets.choice(string.ascii_lowercase)
        + secrets.choice(string.digits)
        + secrets.choice("!@#$%")
        + "".join(secrets.choice(chars) for _ in range(max(0, length - 4)))
    )
    random.shuffle(value)
    return "".join(value)


# 注册资料用名：英美常见名扩大池，降低高并发撞名概率（非完整人口统计）
_FIRST_NAMES = (
    "James", "Robert", "John", "Michael", "David", "William", "Richard", "Joseph", "Thomas", "Christopher",
    "Charles", "Daniel", "Matthew", "Anthony", "Mark", "Donald", "Steven", "Paul", "Andrew", "Joshua",
    "Kenneth", "Kevin", "Brian", "George", "Timothy", "Ronald", "Edward", "Jason", "Jeffrey", "Ryan",
    "Jacob", "Gary", "Nicholas", "Eric", "Jonathan", "Stephen", "Larry", "Justin", "Scott", "Brandon",
    "Benjamin", "Samuel", "Raymond", "Gregory", "Frank", "Alexander", "Patrick", "Jack", "Dennis", "Jerry",
    "Tyler", "Aaron", "Jose", "Adam", "Nathan", "Henry", "Douglas", "Zachary", "Peter", "Kyle",
    "Noah", "Ethan", "Jeremy", "Walter", "Christian", "Keith", "Roger", "Terry", "Austin", "Sean",
    "Mary", "Patricia", "Jennifer", "Linda", "Elizabeth", "Barbara", "Susan", "Jessica", "Sarah", "Karen",
    "Lisa", "Nancy", "Betty", "Margaret", "Sandra", "Ashley", "Kimberly", "Emily", "Donna", "Michelle",
    "Dorothy", "Carol", "Amanda", "Melissa", "Deborah", "Stephanie", "Rebecca", "Sharon", "Laura", "Cynthia",
    "Kathleen", "Amy", "Angela", "Shirley", "Anna", "Brenda", "Pamela", "Emma", "Nicole", "Helen",
    "Samantha", "Katherine", "Christine", "Debra", "Rachel", "Carolyn", "Janet", "Catherine", "Maria", "Heather",
    "Diane", "Ruth", "Julie", "Olivia", "Joyce", "Virginia", "Victoria", "Kelly", "Lauren", "Christina",
    "Joan", "Evelyn", "Judith", "Megan", "Andrea", "Cheryl", "Hannah", "Jacqueline", "Martha", "Gloria",
    "Teresa", "Ann", "Sara", "Madison", "Frances", "Kathryn", "Janice", "Jean", "Abigail", "Alice",
    "Judy", "Sophia", "Grace", "Denise", "Amber", "Doris", "Marilyn", "Danielle", "Beverly", "Isabella",
    "Theresa", "Diana", "Natalie", "Brittany", "Charlotte", "Marie", "Kayla", "Alexis", "Lori", "Julia",
)

_LAST_NAMES = (
    "Smith", "Johnson", "Williams", "Brown", "Jones", "Garcia", "Miller", "Davis", "Rodriguez", "Martinez",
    "Hernandez", "Lopez", "Gonzalez", "Wilson", "Anderson", "Thomas", "Taylor", "Moore", "Jackson", "Martin",
    "Lee", "Perez", "Thompson", "White", "Harris", "Sanchez", "Clark", "Ramirez", "Lewis", "Robinson",
    "Walker", "Young", "Allen", "King", "Wright", "Scott", "Torres", "Nguyen", "Hill", "Flores",
    "Green", "Adams", "Nelson", "Baker", "Hall", "Rivera", "Campbell", "Mitchell", "Carter", "Roberts",
    "Gomez", "Phillips", "Evans", "Turner", "Diaz", "Parker", "Cruz", "Edwards", "Collins", "Reyes",
    "Stewart", "Morris", "Morales", "Murphy", "Cook", "Rogers", "Gutierrez", "Ortiz", "Morgan", "Cooper",
    "Peterson", "Bailey", "Reed", "Kelly", "Howard", "Ramos", "Kim", "Cox", "Ward", "Richardson",
    "Watson", "Brooks", "Chavez", "Wood", "James", "Bennett", "Gray", "Mendoza", "Ruiz", "Hughes",
    "Price", "Alvarez", "Castillo", "Sanders", "Patel", "Myers", "Long", "Ross", "Foster", "Jimenez",
    "Powell", "Jenkins", "Perry", "Russell", "Sullivan", "Bell", "Coleman", "Butler", "Henderson", "Barnes",
    "Gonzales", "Fisher", "Vasquez", "Simmons", "Romero", "Jordan", "Patterson", "Alexander", "Hamilton", "Graham",
    "Reynolds", "Griffin", "Wallace", "Moreno", "West", "Cole", "Hayes", "Bryant", "Herrera", "Gibson",
)


def _random_name() -> tuple[str, str]:
    return random.choice(_FIRST_NAMES), random.choice(_LAST_NAMES)


def _random_birthdate() -> str:
    # 成人区间略放宽；日按月份天数，避免固定 1–28 的模式感
    year = random.randint(1985, 2005)
    month = random.randint(1, 12)
    if month in {1, 3, 5, 7, 8, 10, 12}:
        day_max = 31
    elif month in {4, 6, 9, 11}:
        day_max = 30
    else:
        leap = year % 4 == 0 and (year % 100 != 0 or year % 400 == 0)
        day_max = 29 if leap else 28
    day = random.randint(1, day_max)
    return f"{year:04d}-{month:02d}-{day:02d}"


def _response_json(resp) -> dict:
    try:
        data = resp.json()
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _response_debug_detail(resp, limit: int = 800) -> str:
    if resp is None:
        return ""
    data = _response_json(resp)
    parts = [
        f"url={str(getattr(resp, 'url', '') or '')[:300]}",
        f"content_type={str(getattr(resp, 'headers', {}).get('content-type') or '')}",
    ]
    for key in ("cf-ray", "x-request-id", "openai-processing-ms"):
        value = str(getattr(resp, "headers", {}).get(key) or "").strip()
        if value:
            parts.append(f"{key}={value}")
    if data:
        parts.append(f"json={json.dumps(data, ensure_ascii=False)[:limit]}")
    else:
        parts.append(f"body={str(getattr(resp, 'text', '') or '')[:limit]}")
    return redact_auth_diagnostic(", ".join(parts), limit)


def _is_cloudflare_challenge(resp) -> bool:
    if resp is None:
        return False
    try:
        status_code = int(getattr(resp, "status_code", 0) or 0)
    except (TypeError, ValueError):
        status_code = 0
    if status_code not in (403, 503):
        return False
    text = str(getattr(resp, "text", "") or "").lower()
    return (
        "<title>just a moment" in text
        or "<title>attention required! | cloudflare" in text
        or "cf-chl-" in text
        or "__cf_chl_" in text
        or "cf-browser-verification" in text
    )


def _truthy(value: object, fallback: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    if text in {"1", "true", "yes", "on"}:
        return True
    if text in {"0", "false", "no", "off"}:
        return False
    return fallback


def _mail_config(register_proxy: str = "") -> dict:
    mail = config["mail"] if isinstance(config.get("mail"), dict) else {}
    use_register_proxy = _truthy(mail.get("api_use_register_proxy"), True)
    proxy = str(register_proxy or "").strip() if use_register_proxy else ""
    return {**mail, "api_use_register_proxy": use_register_proxy, "proxy": proxy}


def _pick_register_proxy() -> str:
    raw_pool = config.get("proxy_pool")
    candidates = [str(item).strip() for item in raw_pool if str(item or "").strip()] if isinstance(raw_pool, list) else []
    if not candidates:
        return str(config.get("proxy") or "").strip()

    bound_count = dict.fromkeys(candidates, 0)
    for account in account_service.list_accounts():
        bound_proxy = str(account.get("proxy") or "").strip()
        if bound_proxy in bound_count:
            bound_count[bound_proxy] += 1
    min_count = min(bound_count.values())
    least_bound = [proxy for proxy, count in bound_count.items() if count == min_count]
    return random.choice(least_bound)


def _authorize_landed_page(resp) -> str:
    """诊断用：粗判 authorize 之后落在哪个页面。返回 signup / login / "" 仅供日志。

    注意：email-verification / email_otp_verification 在注册和登录流程里都会出现，
    无法据此可靠区分，所以这里只用于打日志，绝不据此中断注册流程。
    """
    if resp is None:
        return ""
    final_url = str(getattr(resp, "url", "") or "").lower()
    data = _response_json(resp)
    page_type = ""
    page = data.get("page") if isinstance(data, dict) else None
    if isinstance(page, dict):
        page_type = str(page.get("type") or "").lower()
    if "create-account" in final_url or "signup" in final_url or "create_account" in page_type:
        return "signup"
    if "/log-in" in final_url or "/login" in final_url or page_type in {"login", "password_verification"}:
        return "login"
    return ""


def _load_domain_ban_rules() -> list | None:
    """从主 config 读取自定义域名拉黑规则；失败返回 None。"""
    try:
        from services.config import config as app_config

        rules = None
        if hasattr(app_config, "data") and isinstance(getattr(app_config, "data", None), dict):
            rules = app_config.data.get("domain_ban_rules")
        if rules is None and hasattr(app_config, "get"):
            try:
                snapshot = app_config.get()
                if isinstance(snapshot, dict):
                    rules = snapshot.get("domain_ban_rules")
            except Exception:
                pass
        if isinstance(rules, list):
            return rules
    except Exception:
        pass
    return None


def _maybe_ban_domain_from_error(mailbox: dict | None, error: Exception | str | None, *, index: int | None = None) -> None:
    """注册失败时按错误文案自动拉黑邮箱域名（outlook 类排除）。"""
    if not mailbox or error is None:
        return
    try:
        from services.register.domain_blacklist import (
            ban,
            is_excluded_provider,
            should_ban_from_error,
        )
    except Exception:
        return

    provider_ref = str(mailbox.get("provider_ref") or "").strip()
    provider_type = str(mailbox.get("provider") or "").strip()
    email = str(mailbox.get("address") or "").strip()
    if not provider_ref or not email or "@" not in email:
        return
    if is_excluded_provider(provider_type=provider_type, provider_ref=provider_ref):
        return

    domain = email.rsplit("@", 1)[-1].strip()
    if not domain:
        return

    try:
        error_text = redact_auth_diagnostic(error)
    except Exception:
        error_text = str(error or "")
    custom_rules = _load_domain_ban_rules()
    ok, reason = should_ban_from_error(error_text, custom_rules)
    if not ok:
        return

    try:
        ban(
            provider_ref,
            domain,
            reason=reason or "auto",
            source="auto",
            sample_email=email,
            raw_hint=error_text[:500],
            provider_type=provider_type,
            provider_label=str(mailbox.get("label") or ""),
        )
    except Exception as ban_exc:
        # 自动拉黑失败不得打断注册失败收尾
        msg = f"自动拉黑失败: {domain} ({ban_exc})"
        if index is not None:
            step(index, msg, "yellow")
        else:
            log(msg, "yellow")
        return

    msg = f"域名已拉黑: {domain} ({reason})"
    if index is not None:
        step(index, msg, "yellow")
    else:
        log(msg, "yellow")


def create_mailbox(username: str | None = None, register_proxy: str = "") -> dict:
    purpose = str(config.get("mail_purpose") or "daily")
    return mail_provider.create_mailbox(_mail_config(register_proxy), username, purpose=purpose)


def wait_for_code(mailbox: dict, register_proxy: str = "") -> str | None:
    return mail_provider.wait_for_code(_mail_config(register_proxy), mailbox)


def _extract_otp_from_text(text: str) -> str | None:
    match = re.search(r"(?<!\d)(\d{6})(?!\d)", str(text or ""))
    return match.group(1) if match else None


def _ahem_candidate_urls(api_base: str, email: str, prefix: str) -> list[str]:
    base = str(api_base or "").rstrip("/")
    if not base:
        return []
    encoded_email = email.replace("@", "%40")
    return [
        f"{base}/api/emails/{encoded_email}",
        f"{base}/api/mailbox/{encoded_email}",
        f"{base}/api/messages/{encoded_email}",
        f"{base}/api/{encoded_email}",
        f"{base}/mailbox/{encoded_email}",
        f"{base}/mailbox/{prefix}",
        f"{base}/{encoded_email}",
        f"{base}/{prefix}",
    ]


def _wait_for_ahem_code(mailbox: dict, register_proxy: str = "") -> str | None:
    api_base = str(mailbox.get("api_base") or "").strip()
    email = str(mailbox.get("address") or "").strip()
    prefix = str(mailbox.get("prefix") or email.partition("@")[0]).strip()
    if not api_base or not email or not prefix:
        return None
    mail_config = _mail_config(register_proxy)
    timeout = int(mail_config.get("wait_timeout", 30) or 30)
    interval = max(1, int(mail_config.get("wait_interval", 2) or 2))
    profile = proxy_settings.get_profile(
        proxy=str(mail_config.get("proxy") or ""),
        upstream=False,
    )
    session = requests.Session(
        proxy=profile.proxy_url or None,
        verify=not profile.skip_ssl_verify,
    )
    deadline = time.time() + timeout
    try:
        urls = _ahem_candidate_urls(api_base, email, prefix)
        while time.time() < deadline:
            for url in urls:
                try:
                    resp = session.get(url, timeout=int(mail_config.get("request_timeout", 30) or 30))
                except Exception:
                    continue
                if resp.status_code == 404:
                    continue
                code = _extract_otp_from_text(str(getattr(resp, "text", "") or ""))
                if code:
                    return code
            time.sleep(interval)
    finally:
        session.close()
    return None


def _wait_for_relogin_code(mailbox: dict, register_proxy: str = "") -> str | None:
    try:
        code = wait_for_code(mailbox, register_proxy=register_proxy)
        if code:
            return code
    except Exception:
        if str(mailbox.get("provider") or "") != "ahem":
            raise
    if str(mailbox.get("provider") or "") == "ahem":
        return _wait_for_ahem_code(mailbox, register_proxy=register_proxy)
    return None


def build_sentinel_token(
    session: requests.Session,
    device_id: str,
    flow: str,
    fingerprint: dict[str, str] | None = None,
) -> str:
    """请求 sentinel token，返回 sentinel header 字符串（兼容旧接口）。"""
    fp = _browser_fingerprint(fingerprint)
    sentinel_val, _oai_sc_val = _build_sentinel_token_tuple(
        session,
        device_id,
        flow,
        user_agent=fp["user_agent"],
        sec_ch_ua=fp["sec_ch_ua"],
    )
    return sentinel_val


def build_sentinel_with_so_token(
    session: requests.Session,
    device_id: str,
    flow: str,
    fingerprint: dict[str, str] | None = None,
) -> tuple[str, str, str]:
    """返回 create_account 所需的 Sentinel、SO token 与 oai-sc。"""
    fp = _browser_fingerprint(fingerprint)
    return _build_sentinel_with_so_token_tuple(
        session,
        device_id,
        flow,
        user_agent=fp["user_agent"],
        sec_ch_ua=fp["sec_ch_ua"],
    )


def create_session(proxy: str = "", fingerprint: dict[str, str] | None = None) -> Any:
    fp = _browser_fingerprint(fingerprint)
    profile = proxy_settings.get_profile(
        proxy=proxy,
        upstream=True,
    )
    session = requests.Session(
        proxy=profile.proxy_url or None,
        impersonate=_session_impersonate(fp["impersonate"]),
        verify=not profile.skip_ssl_verify,
    )
    session.headers.update({"user-agent": fp["user_agent"]})
    return session


def _apply_clearance_to_session(session: requests.Session, bundle: ClearanceBundle | None) -> None:
    if bundle is None:
        return
    if bundle.user_agent:
        session.headers["user-agent"] = bundle.user_agent
    for name, value in bundle.cookies.items():
        try:
            session.cookies.set(name, value, domain=f".{bundle.target_host or 'openai.com'}")
            session.cookies.set(name, value, domain=bundle.target_host or "auth.openai.com")
        except Exception:
            continue


def _headers_with_clearance(
    headers: dict[str, str],
    target_url: str,
    proxy: str = "",
    user_agent_override: str = "",
) -> dict[str, str]:
    merged = proxy_settings.build_headers(
        headers=headers,
        target_url=target_url,
        proxy=proxy,
        upstream=True,
    )
    normalized = {str(key): str(value) for key, value in merged.items()}
    if user_agent_override:
        ua_key = next((key for key in normalized if key.lower() == "user-agent"), "user-agent")
        normalized[ua_key] = user_agent_override
    return normalized


def _cloudflare_block_message(resp, prefix: str = "被 Cloudflare 拦截", reason: str = "") -> str:
    status = getattr(resp, "status_code", "unknown")
    debug = _response_debug_detail(resp)
    reason = reason or "clearance 刷新失败或重试后仍失败，请更换 IP/代理重试"
    return f"{prefix}，{reason}: status={status}, {debug}"


LocalRequestMethod = Literal["get", "post"]


def _http_method(method: LocalRequestMethod) -> HttpMethod:
    match method:
        case "get":
            return "GET"
        case "post":
            return "POST"


def request_with_local_retry(
    session: requests.Session,
    method: LocalRequestMethod,
    url: str,
    retry_attempts: int = 3,
    **kwargs,
):
    last_error = ""
    for _ in range(max(1, retry_attempts)):
        try:
            return session.request(_http_method(method), url, timeout=default_timeout, **kwargs), ""
        except Exception as error:
            last_error = str(error)
            time.sleep(1)
    return None, last_error


def validate_otp(
    session: requests.Session,
    device_id: str,
    code: str,
    fingerprint: dict[str, str] | None = None,
):
    headers = _header_fingerprint(common_headers, fingerprint)
    headers["referer"] = f"{auth_base}/email-verification"
    headers["oai-device-id"] = device_id
    headers.update(_make_trace_headers())
    resp, error = request_with_local_retry(session, "post", f"{auth_base}/api/accounts/email-otp/validate", json={"code": code}, headers=headers)
    if resp is not None and resp.status_code == 200:
        return resp, ""
    fp = _browser_fingerprint(fingerprint)
    sentinel_token, oai_sc = _build_sentinel_token_tuple(
        session,
        device_id,
        "authorize_continue",
        user_agent=fp["user_agent"],
        sec_ch_ua=fp["sec_ch_ua"],
    )
    headers["openai-sentinel-token"] = sentinel_token
    _set_oai_sc_cookie(session, oai_sc)
    resp, error = request_with_local_retry(session, "post", f"{auth_base}/api/accounts/email-otp/validate", json={"code": code}, headers=headers)
    return resp, error


def _set_oai_sc_cookie(session: requests.Session, value: str) -> None:
    if not value:
        return
    for domain in (".openai.com", "auth.openai.com"):
        session.cookies.set("oai-sc", value, domain=domain)


def extract_oauth_callback_params_from_url(url: str) -> dict[str, str] | None:
    if not url:
        return None
    try:
        params = parse_qs(urlparse(url).query)
    except Exception:
        return None
    code = str((params.get("code") or [""])[0]).strip()
    if not code:
        return None
    return {"code": code, "state": str((params.get("state") or [""])[0]).strip(), "scope": str((params.get("scope") or [""])[0]).strip()}


def extract_continue_url(data: dict[str, Any] | None) -> str:
    if not isinstance(data, dict):
        return ""
    direct = str(data.get("continue_url") or data.get("continueUrl") or "").strip()
    if direct:
        return direct
    page = data.get("page")
    if isinstance(page, dict):
        payload = page.get("payload")
        if isinstance(payload, dict):
            nested = str(
                payload.get("continue_url")
                or payload.get("continueUrl")
                or payload.get("next_url")
                or payload.get("nextUrl")
                or ""
            ).strip()
            if nested:
                return nested
    session_info = data.get("oai-client-auth-session")
    if isinstance(session_info, dict):
        return str(session_info.get("continue_url") or session_info.get("continueUrl") or "").strip()
    return ""


def validate_continuation_url(url: str) -> str:
    value = str(url or "")
    if not value or any(character.isspace() or ord(character) == 127 for character in value) or "\\" in value:
        raise ValueError("invalid continuation URL")
    if value.startswith("//"):
        raise ValueError("scheme-relative continuation URL is not allowed")
    raw_parsed = urlparse(value)
    if raw_parsed.scheme and not raw_parsed.netloc:
        raise ValueError("continuation URL authority is required with a scheme")
    absolute = urljoin(f"{auth_base}/", value)
    parsed = urlparse(absolute)
    try:
        port = parsed.port
    except ValueError as error:
        raise ValueError("invalid continuation URL port") from error
    if (
        parsed.scheme != "https"
        or parsed.hostname not in {"auth.openai.com", "platform.openai.com"}
        or parsed.username is not None
        or parsed.password is not None
        or port not in (None, 443)
    ):
        raise ValueError("continuation URL is not allowed")
    return absolute


def _absolute_auth_url(url: str) -> str:
    return validate_continuation_url(url)


def _safe_url_for_log(url: str) -> str:
    value = str(url or "").strip()
    if not value:
        return "-"
    try:
        parsed = urlparse(value)
    except Exception:
        return redact_auth_diagnostic(value, 160)
    if parsed.scheme and parsed.netloc:
        return f"{parsed.netloc}{parsed.path}"[:160]
    return parsed.path[:160] if parsed.path else value[:160]


def _url_path(url: str) -> str:
    value = _absolute_auth_url(url)
    try:
        return urlparse(value).path.rstrip("/") or "/"
    except Exception:
        return ""


def _append_exchange_error(errors: list[str] | None, message: str) -> None:
    if errors is not None and message:
        errors.append(redact_auth_diagnostic(message))


def request_platform_oauth_token(
    session: requests.Session,
    code: str,
    code_verifier: str,
    errors: list[str] | None = None,
    fingerprint: dict[str, str] | None = None,
) -> dict | None:
    fp = _browser_fingerprint(fingerprint)
    headers = {
        "accept": "*/*",
        "accept-language": fp["accept_language"],
        "auth0-client": platform_auth0_client,
        "cache-control": "no-cache",
        "content-type": "application/json",
        "origin": platform_base,
        "pragma": "no-cache",
        "priority": "u=1, i",
        "referer": f"{platform_base}/",
        "sec-ch-ua": fp["sec_ch_ua"],
        "sec-ch-ua-mobile": "?0",
        "sec-ch-ua-platform": '"Windows"',
        "sec-fetch-dest": "empty",
        "sec-fetch-mode": "cors",
        "sec-fetch-site": "same-site",
        "user-agent": fp["user_agent"],
    }
    try:
        resp = session.post(
            f"{auth_base}/api/accounts/oauth/token",
            headers=headers,
            json={
                "client_id": platform_oauth_client_id,
                "code_verifier": code_verifier,
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": platform_oauth_redirect_uri,
            },
            timeout=60,
        )
    except Exception as error:
        _append_exchange_error(errors, f"api token 请求异常: {str(error)[:300]}")
        return None
    if resp.status_code != 200:
        _append_exchange_error(errors, f"api token 接口拒绝: status={resp.status_code}, {_response_debug_detail(resp, 500)}")
        return None
    data = _response_json(resp)
    missing = [key for key in ("access_token", "refresh_token") if not data.get(key)]
    if missing:
        _append_exchange_error(errors, f"api token 返回缺少字段: {', '.join(missing)}")
        return None
    return data


def request_platform_oauth_token_legacy(
    session: requests.Session,
    code: str,
    code_verifier: str,
    proxy: str = "",
    errors: list[str] | None = None,
    fresh_session: bool = False,
    fingerprint: dict[str, str] | None = None,
) -> dict | None:
    token_session = create_session(proxy, fingerprint) if fresh_session else session
    resp = None
    try:
        resp = token_session.post(
            f"{auth_base}/oauth/token",
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            data={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": platform_oauth_redirect_uri,
                "client_id": platform_oauth_client_id,
                "code_verifier": code_verifier,
            },
            timeout=60,
        )
    except Exception as error:
        _append_exchange_error(errors, f"legacy token 请求异常: {str(error)[:300]}")
        return None
    finally:
        if fresh_session:
            try:
                token_session.close()
            except Exception:
                pass
    if resp is None:
        _append_exchange_error(errors, "legacy token 未返回响应")
        return None
    data = _response_json(resp)
    if resp.status_code != 200:
        _append_exchange_error(errors, f"legacy token 接口拒绝: status={resp.status_code}, {_response_debug_detail(resp, 500)}")
        return None
    missing = [key for key in ("access_token", "refresh_token", "id_token") if not data.get(key)]
    if missing:
        _append_exchange_error(errors, f"legacy token 返回缺少字段: {', '.join(missing)}")
        return None
    return data


def extract_callback_via_consent(
    session: requests.Session,
    consent_url: str,
    device_id: str,
    proxy: str = "",
    user_agent_override: str = "",
    fingerprint: dict[str, str] | None = None,
) -> dict[str, str] | None:
    current = _absolute_auth_url(consent_url)
    if not current:
        return None
    fp = _fingerprint_with_user_agent(fingerprint, user_agent_override) if user_agent_override else _browser_fingerprint(fingerprint)
    for _ in range(10):
        headers = _headers_with_clearance(_header_fingerprint(navigate_headers, fp), current, proxy, user_agent_override)
        resp, _error = request_with_local_retry(session, "get", current, headers=headers, allow_redirects=False)
        if resp is None:
            return None
        callback = extract_oauth_callback_params_from_url(str(getattr(resp, "url", "") or ""))
        location = str(getattr(resp, "headers", {}).get("Location") or "").strip()
        validated_location = validate_continuation_url(location) if location else ""
        callback = callback or extract_oauth_callback_params_from_url(validated_location)
        if callback:
            return callback
        if getattr(resp, "status_code", 0) not in (301, 302, 303, 307, 308) or not location:
            break
        current = validated_location

    raw = session.cookies.get("oai-client-auth-session", domain=".auth.openai.com") or session.cookies.get("oai-client-auth-session")
    if not raw:
        return None
    try:
        first = raw.split(".")[0]
        pad = 4 - len(first) % 4
        if pad != 4:
            first += "=" * pad
        payload = json.loads(base64.urlsafe_b64decode(first))
        workspace_id = payload["workspaces"][0]["id"]
    except Exception:
        return None

    url = f"{auth_base}/api/accounts/workspace/select"
    headers = _header_fingerprint(common_headers, fp)
    headers["referer"] = current
    headers["oai-device-id"] = device_id
    headers.update(_make_trace_headers())
    headers = _headers_with_clearance(headers, url, proxy, user_agent_override)
    ws_resp, _error = request_with_local_retry(session, "post", url, json={"workspace_id": workspace_id}, headers=headers, allow_redirects=False)
    if ws_resp is None:
        return None
    ws_location = str(getattr(ws_resp, "headers", {}).get("Location") or "").strip()
    callback = extract_oauth_callback_params_from_url(validate_continuation_url(ws_location)) if ws_location else None
    if callback:
        return callback

    ws_data = _response_json(ws_resp)
    orgs = ((ws_data.get("data") or {}).get("orgs") or []) if isinstance(ws_data, dict) else []
    if not orgs:
        return None
    org_id = str((orgs[0] or {}).get("id") or "").strip()
    project_id = str(((orgs[0] or {}).get("projects") or [{}])[0].get("id") or "").strip()
    if not org_id:
        return None
    org_url = f"{auth_base}/api/accounts/organization/select"
    org_headers = _header_fingerprint(common_headers, fp)
    org_headers["referer"] = str(ws_data.get("continue_url") or current)
    org_headers["oai-device-id"] = device_id
    org_headers.update(_make_trace_headers())
    org_headers = _headers_with_clearance(org_headers, org_url, proxy, user_agent_override)
    body = {"org_id": org_id}
    if project_id:
        body["project_id"] = project_id
    org_resp, _error = request_with_local_retry(session, "post", org_url, json=body, headers=org_headers, allow_redirects=False)
    if org_resp is None:
        return None
    org_location = str(getattr(org_resp, "headers", {}).get("Location") or "").strip()
    return extract_oauth_callback_params_from_url(validate_continuation_url(org_location)) if org_location else None


def exchange_tokens_from_continue_url(
    session: requests.Session,
    device_id: str,
    code_verifier: str,
    continue_url: str,
    proxy: str = "",
    user_agent_override: str = "",
    errors: list[str] | None = None,
    fingerprint: dict[str, str] | None = None,
) -> dict | None:
    current = validate_continuation_url(continue_url)
    callback = extract_oauth_callback_params_from_url(current)
    fp = _fingerprint_with_user_agent(fingerprint, user_agent_override) if user_agent_override else _browser_fingerprint(fingerprint)
    callback = callback or extract_callback_via_consent(
        session,
        current,
        device_id,
        proxy,
        user_agent_override,
        fp,
    )
    if not callback:
        resp = None
        try:
            for _ in range(10):
                headers = _headers_with_clearance(_header_fingerprint(navigate_headers, fp), current, proxy, user_agent_override)
                resp = session.get(current, headers=headers, allow_redirects=False, timeout=30)
                callback = extract_oauth_callback_params_from_url(str(getattr(resp, "url", "") or ""))
                location = str(getattr(resp, "headers", {}).get("Location") or "").strip()
                validated_location = validate_continuation_url(location) if location else ""
                callback = callback or extract_oauth_callback_params_from_url(validated_location)
                if callback:
                    break
                if getattr(resp, "status_code", 0) not in (301, 302, 303, 307, 308) or not location:
                    break
                current = validated_location
            if not callback:
                _append_exchange_error(
                    errors,
                    f"跟随 continue_url 后仍未拿到 callback: status={getattr(resp, 'status_code', 'unknown')}, final={_safe_url_for_log(str(getattr(resp, 'url', '') or ''))}",
                )
        except ValueError:
            raise
        except Exception as error:
            _append_exchange_error(errors, f"跟随 continue_url 异常: {str(error)[:300]}")
            callback = None
    code = str((callback or {}).get("code") or "").strip()
    if not code:
        _append_exchange_error(errors, f"未拿到 OAuth callback code: continue={_safe_url_for_log(continue_url)}")
        return None
    return request_platform_oauth_token_legacy(session, code, code_verifier, proxy, errors, fresh_session=True, fingerprint=fp)


class PlatformRegistrar:
    def __init__(self, proxy: str = "", fingerprint: dict[str, str] | None = None) -> None:
        self.proxy = str(proxy or "").strip()
        self.fingerprint = _browser_fingerprint(fingerprint) if fingerprint else _make_browser_fingerprint()
        self.session = create_session(self.proxy, self.fingerprint)
        self.clearance_user_agent = ""
        self.clearance_failure_reason = ""
        self.device_id = str(uuid.uuid4())
        self.code_verifier = ""
        self.platform_auth_code = ""
        self.last_otp_continue_url = ""
        self.passwordless_signup = False

    def close(self) -> None:
        self.session.close()

    def _navigate_headers(self, referer: str = "") -> dict[str, str]:
        headers = _header_fingerprint(navigate_headers, self.fingerprint)
        if referer:
            headers["referer"] = referer
        return headers

    def _json_headers(self, referer: str) -> dict[str, str]:
        headers = _header_fingerprint(common_headers, self.fingerprint)
        headers["referer"] = referer
        headers["oai-device-id"] = self.device_id
        headers.update(_make_trace_headers())
        return headers

    def _refresh_cloudflare_clearance(self, target_url: str, index: int) -> ClearanceBundle | None:
        self.clearance_failure_reason = ""
        profile = proxy_settings.get_profile(proxy=self.proxy, upstream=True)
        if not profile.clearance_enabled:
            self.clearance_failure_reason = (
                "可尝试使用 FlareSolverr 清障方式，注意需要 Docker 部署 flaresolverr、privoxy、warp-proxy 等相关容器"
            )
            step(index, f"检测到 Cloudflare 拦截，{self.clearance_failure_reason}", "yellow")
            return None
        step(index, "检测到 Cloudflare 拦截，尝试刷新 clearance", "yellow")
        bundle = proxy_settings.refresh_clearance(
            target_url=target_url,
            proxy=self.proxy,
            force=True,
            upstream=True,
        )
        if bundle is not None:
            _apply_clearance_to_session(self.session, bundle)
            self.clearance_user_agent = bundle.user_agent or self.clearance_user_agent
            if bundle.user_agent:
                self.fingerprint = _fingerprint_with_user_agent(self.fingerprint, bundle.user_agent)
            step(index, "Cloudflare clearance 刷新完成，重试当前请求", "yellow")
        else:
            self.clearance_failure_reason = "clearance 刷新未返回可用 Cookie，请检查 FlareSolverr URL、代理和出口 IP"
            step(index, f"Cloudflare clearance 刷新失败：{self.clearance_failure_reason}", "yellow")
        return bundle

    def _platform_authorize(self, email: str, index: int, screen_hint: str = "login_or_signup") -> str:
        step(index, "开始 platform authorize")
        self.session.cookies.set("oai-did", self.device_id, domain=".auth.openai.com")
        self.session.cookies.set("oai-did", self.device_id, domain="auth.openai.com")
        self.code_verifier, code_challenge = _generate_pkce()
        params = {
            "issuer": auth_base,
            "client_id": platform_oauth_client_id,
            "audience": platform_oauth_audience,
            "redirect_uri": platform_oauth_redirect_uri,
            "device_id": self.device_id,
            # 官网当前的新账号流程使用 passwordless signup。
            "screen_hint": screen_hint,
            "max_age": "0",
            "login_hint": email,
            "scope": "openid profile email offline_access",
            "response_type": "code",
            "response_mode": "query",
            "state": secrets.token_urlsafe(32),
            "nonce": secrets.token_urlsafe(32),
            "code_challenge": code_challenge,
            "code_challenge_method": "S256",
            "auth0Client": platform_auth0_client,
        }
        target_url = f"{auth_base}/api/accounts/authorize?{urlencode(params)}"
        headers = self._navigate_headers(f"{platform_base}/")
        headers = _headers_with_clearance(headers, target_url, self.proxy, self.clearance_user_agent)
        resp, error = request_with_local_retry(self.session, "get", target_url, headers=headers, allow_redirects=True)
        if _is_cloudflare_challenge(resp):
            bundle = self._refresh_cloudflare_clearance(auth_base, index)
            if bundle is None:
                raise RuntimeError(_cloudflare_block_message(resp, reason=self.clearance_failure_reason))
            retry_headers = _headers_with_clearance(self._navigate_headers(f"{platform_base}/"), target_url, self.proxy, self.clearance_user_agent)
            resp, error = request_with_local_retry(self.session, "get", target_url, headers=retry_headers, allow_redirects=True)
            if _is_cloudflare_challenge(resp):
                raise RuntimeError(_cloudflare_block_message(resp, "Cloudflare clearance 重试仍被拦截"))
        if resp is None or resp.status_code != 200:
            err = _response_json(resp).get("error", {}) if resp is not None else {}
            detail = f": {err.get('code', '')} - {err.get('message', '')}".strip(" -") if err else ""
            debug = _response_debug_detail(resp)
            status = getattr(resp, "status_code", "unknown")
            raise RuntimeError(
                redact_auth_diagnostic(error or f"platform_authorize_http_{status}{detail}, {debug}")
            )
        landed = _authorize_landed_page(resp)
        final_url = str(getattr(resp, "url", "") or "")
        self.passwordless_signup = "/email-verification" in final_url.lower()
        mode = "passwordless" if self.passwordless_signup else "password"
        safe_final_url = _safe_url_for_log(final_url)
        step(index, f"platform authorize 完成[{landed or '?'}] mode={mode} url={safe_final_url}")
        return landed

    def _reset_auth_cookies(self) -> None:
        jar = getattr(self.session.cookies, "jar", self.session.cookies)
        for cookie in list(jar):
            domain = str(getattr(cookie, "domain", "") or "")
            if "auth.openai.com" not in domain:
                continue
            try:
                self.session.cookies.delete(
                    str(getattr(cookie, "name", "") or ""),
                    domain=domain,
                    path=str(getattr(cookie, "path", "/") or "/"),
                )
            except Exception:
                continue
        self.session.cookies.set("oai-did", self.device_id, domain=".auth.openai.com")
        self.session.cookies.set("oai-did", self.device_id, domain="auth.openai.com")

    def _authorize_continue_login(self, email: str, index: int) -> dict:
        step(index, "提交 Microsoft 邮箱进入登录验证")
        url = f"{auth_base}/api/accounts/authorize/continue"

        def send():
            headers = self._json_headers(f"{auth_base}/log-in?usernameKind=email")
            headers["openai-sentinel-token"] = build_sentinel_token(self.session, self.device_id, "authorize_continue", self.fingerprint)
            headers = _headers_with_clearance(headers, url, self.proxy, self.clearance_user_agent)
            return request_with_local_retry(
                self.session,
                "post",
                url,
                json={"username": {"kind": "email", "value": email}},
                headers=headers,
                allow_redirects=False,
            )

        resp, error = send()
        if resp is not None and resp.status_code == 409:
            step(index, "登录会话过期，重新发起登录授权", "yellow")
            self._reset_auth_cookies()
            self._platform_authorize(email, index, screen_hint="login_or_signup")
            resp, error = send()
        if resp is None or resp.status_code != 200:
            detail = _response_json(resp) if resp is not None else {}
            raise RuntimeError(
                redact_auth_diagnostic(
                    error
                    or f"login_continue_http_{getattr(resp, 'status_code', 'unknown')}, detail={json.dumps(detail, ensure_ascii=False)[:300]}"
                )
            )
        data = _response_json(resp)
        if ((data.get("page") or {}).get("payload") or {}).get("passwordless_disabled"):
            raise RuntimeError("Microsoft 邮箱登录流不支持 passwordless，请换邮箱或使用已有密码重登")
        return data

    def _send_passwordless_otp(self, index: int) -> None:
        step(index, "发送 Microsoft 登录验证码")
        url = f"{auth_base}/api/accounts/passwordless/send-otp"
        headers = self._json_headers(f"{auth_base}/log-in/password")
        headers = _headers_with_clearance(headers, url, self.proxy, self.clearance_user_agent)
        resp, error = request_with_local_retry(self.session, "post", url, json={}, headers=headers, allow_redirects=False)
        if resp is None or resp.status_code not in (200, 201, 204):
            detail = _response_json(resp) if resp is not None else {}
            raise RuntimeError(
                redact_auth_diagnostic(
                    error
                    or f"passwordless_send_otp_http_{getattr(resp, 'status_code', 'unknown')}, detail={json.dumps(detail, ensure_ascii=False)[:300]}"
                )
            )

    @staticmethod
    def _is_passwordless_invalid_state(resp) -> bool:
        if resp is None or getattr(resp, "status_code", None) != 409:
            return False
        data = _response_json(resp)
        error = data.get("error") if isinstance(data, dict) else None
        if not isinstance(error, dict):
            return False
        code = str(error.get("code") or "").strip().lower()
        message = str(error.get("message") or "").strip().lower()
        return code == "invalid_state" or "sign-in session is no longer valid" in message

    def _passwordless_login(self, email: str, mailbox: dict, index: int) -> dict:
        step(index, "OpenAI 返回登录流，转入 passwordless 登录", "yellow")
        resp = None
        for attempt in range(2):
            if attempt:
                step(index, "登录会话失效，重新发起 passwordless 登录", "yellow")
                self._reset_auth_cookies()
                self._platform_authorize(email, index, screen_hint="login_or_signup")
            self._authorize_continue_login(email, index)
            mailbox["_received_after"] = (datetime.now(timezone.utc) - timedelta(seconds=5)).isoformat()
            self._send_passwordless_otp(index)
            step(index, "开始等待 passwordless 登录验证码")
            code = _wait_for_relogin_code(mailbox, register_proxy=self.proxy)
            if not code:
                raise RuntimeError("等待 passwordless 登录验证码超时")
            step(index, "收到 passwordless 登录验证码")
            resp, error = validate_otp(self.session, self.device_id, code, self.fingerprint)
            if resp is not None and resp.status_code == 200:
                break
            body = ""
            try:
                body = (resp.text or "")[:500] if resp is not None else ""
            except Exception:
                pass
            if attempt == 0 and self._is_passwordless_invalid_state(resp):
                continue
            raise RuntimeError(
                redact_auth_diagnostic(
                    error or f"passwordless_validate_otp_http_{getattr(resp, 'status_code', 'unknown')}_body={body}"
                )
            )
        data = _response_json(resp)
        continue_url = str(data.get("continue_url") or "").strip() or f"{auth_base}/sign-in-with-chatgpt/platform/consent"
        if _url_path(continue_url) == "/about-you":
            first_name, last_name = _random_name()
            step(index, "Passwordless 登录验证完成，需要完善账号资料")
            self._create_account(f"{first_name} {last_name}", _random_birthdate(), index)
            return self._exchange_registered_tokens(index)
        step(index, "Passwordless 登录验证完成，开始换 token")
        exchange_errors: list[str] = []
        tokens = exchange_tokens_from_continue_url(
            self.session,
            self.device_id,
            self.code_verifier,
            continue_url,
            self.proxy,
            self.clearance_user_agent,
            exchange_errors,
            self.fingerprint,
        )
        if not tokens:
            detail = "；".join(exchange_errors[-4:]) if exchange_errors else "未返回 token"
            raise RuntimeError(redact_auth_diagnostic(f"passwordless token 换取失败: {detail}"))
        step(index, "passwordless token 换取完成")
        return tokens

    def _start_passwordless_signup(self, index: int) -> None:
        step(index, "开始切换 passwordless signup 并发送验证码")
        url = f"{auth_base}/api/accounts/passwordless/send-otp"

        def send():
            headers = self._json_headers(f"{auth_base}/create-account/password")
            headers = _headers_with_clearance(headers, url, self.proxy, self.clearance_user_agent)
            return request_with_local_retry(self.session, "post", url, headers=headers)

        resp, error = send()
        if _is_cloudflare_challenge(resp):
            bundle = self._refresh_cloudflare_clearance(auth_base, index)
            if bundle is None:
                raise RuntimeError(_cloudflare_block_message(resp, reason=self.clearance_failure_reason))
            resp, error = send()
            if _is_cloudflare_challenge(resp):
                raise RuntimeError(_cloudflare_block_message(resp, "Cloudflare clearance 重试仍被拦截"))
        if resp is None or resp.status_code not in (200, 201, 204):
            data = _response_json(resp) if resp is not None else {}
            detail = f", detail={json.dumps(data, ensure_ascii=False)[:300]}" if data else ""
            raise RuntimeError(
                redact_auth_diagnostic(
                    error or f"passwordless_send_otp_http_{getattr(resp, 'status_code', 'unknown')}{detail}"
                )
            )
        self.passwordless_signup = True
        step(index, "passwordless signup 验证码发送完成")

    def _login_and_exchange_tokens(self, email: str, password: str, mailbox: dict, index: int) -> dict:
        step(index, "开始独立登录换 token")
        self._reset_auth_cookies()
        self._platform_authorize(email, index, screen_hint="login_or_signup")

        continue_url = ""
        for attempt in range(2):
            url = f"{auth_base}/api/accounts/authorize/continue"
            headers = self._json_headers(f"{auth_base}/log-in?usernameKind=email")
            headers["openai-sentinel-token"] = build_sentinel_token(self.session, self.device_id, "authorize_continue", self.fingerprint)
            headers = _headers_with_clearance(headers, url, self.proxy, self.clearance_user_agent)
            step(index, "开始提交邮箱")
            resp, error = request_with_local_retry(
                self.session,
                "post",
                url,
                json={"username": {"kind": "email", "value": email}},
                headers=headers,
                allow_redirects=False,
            )
            if resp is not None and resp.status_code == 409 and attempt == 0:
                step(index, "邮箱提交 invalid_state，重新 authorize 后重试", "yellow")
                self._reset_auth_cookies()
                self._platform_authorize(email, index, screen_hint="login_or_signup")
                continue
            if resp is not None and resp.status_code == 429:
                raise RuntimeError("email_submit_http_429: rate limited, relogin discarded")
            if resp is None or resp.status_code != 200:
                data = _response_json(resp) if resp is not None else {}
                detail = json.dumps(data, ensure_ascii=False) if data else ""
                diagnostic = error or f"email_submit_http_{getattr(resp, 'status_code', 'unknown')}" + (
                    f": {detail}" if detail else ""
                )
                raise RuntimeError(redact_auth_diagnostic(diagnostic))
            step(index, "邮箱提交完成")
            break

        step(index, "开始密码校验")
        password_url = f"{auth_base}/api/accounts/password/verify"
        headers = self._json_headers(f"{auth_base}/log-in/password")
        headers["openai-sentinel-token"] = build_sentinel_token(self.session, self.device_id, "password_verify", self.fingerprint)
        headers = _headers_with_clearance(headers, password_url, self.proxy, self.clearance_user_agent)
        resp, error = request_with_local_retry(
            self.session,
            "post",
            password_url,
            json={"password": password},
            headers=headers,
            allow_redirects=False,
        )
        if resp is None or resp.status_code != 200:
            body = ""
            try:
                body = (resp.text or "")[:500] if resp is not None else ""
            except Exception:
                pass
            raise RuntimeError(
                redact_auth_diagnostic(
                    error or f"password_verify_http_{getattr(resp, 'status_code', '')}_body={body}"
                )
            )
        step(index, "密码校验完成")

        payload = _response_json(resp)
        continue_url = str(payload.get("continue_url") or "").strip()
        page_type = str(((payload.get("page") or {}).get("type")) or "")
        if page_type == "email_otp_verification" or "email-verification" in continue_url or "email-otp" in continue_url:
            step(index, "独立登录需要邮箱验证码")
            original_timeout = int(config["mail"].get("wait_timeout", 30) or 30)
            config["mail"]["wait_timeout"] = max(original_timeout, 60)
            try:
                code = _wait_for_relogin_code(mailbox, register_proxy=self.proxy)
            finally:
                config["mail"]["wait_timeout"] = original_timeout
            if not code:
                raise RuntimeError("独立登录等待验证码超时")
            step(index, "收到登录验证码")
            resp, reason = validate_otp(self.session, self.device_id, code, self.fingerprint)
            if resp is None or resp.status_code != 200:
                data = _response_json(resp) if resp is not None else {}
                message = str((data.get("error") or {}).get("message") or data.get("message") or "").strip()
                raise RuntimeError(
                    redact_auth_diagnostic(
                        reason or f"独立登录验证码校验失败{': ' + message if message else ''}"
                    )
                )
            otp_payload = _response_json(resp)
            continue_url = str(otp_payload.get("continue_url") or continue_url).strip()
            step(index, "独立登录验证码校验完成")

        if not continue_url:
            continue_url = f"{auth_base}/sign-in-with-chatgpt/platform/consent"
        exchange_errors: list[str] = []
        tokens = exchange_tokens_from_continue_url(
            self.session,
            self.device_id,
            self.code_verifier,
            continue_url,
            self.proxy,
            self.clearance_user_agent,
            exchange_errors,
            self.fingerprint,
        )
        if not tokens:
            detail = "；".join(exchange_errors[-4:]) if exchange_errors else "未返回 token"
            raise RuntimeError(redact_auth_diagnostic(f"token换取失败: {detail}"))
        expires_in = int(tokens.get("expires_in") or 86400)
        tokens["token_expires_at"] = (datetime.now(timezone.utc) + timedelta(seconds=expires_in)).strftime("%Y-%m-%d %H:%M:%S")
        step(index, "token 换取完成")
        return tokens

    def _register_user(self, email: str, password: str, index: int) -> None:
        step(index, "开始提交注册密码")
        url = f"{auth_base}/api/accounts/user/register"
        headers = self._json_headers(f"{auth_base}/create-account/password")
        headers["openai-sentinel-token"] = build_sentinel_token(self.session, self.device_id, "username_password_create", self.fingerprint)
        headers = _headers_with_clearance(headers, url, self.proxy, self.clearance_user_agent)
        resp, error = request_with_local_retry(self.session, "post", url, json={"username": email, "password": password}, headers=headers)
        if _is_cloudflare_challenge(resp):
            bundle = self._refresh_cloudflare_clearance(auth_base, index)
            if bundle is None:
                raise RuntimeError(_cloudflare_block_message(resp, reason=self.clearance_failure_reason))
            headers = self._json_headers(f"{auth_base}/create-account/password")
            headers["openai-sentinel-token"] = build_sentinel_token(self.session, self.device_id, "username_password_create", self.fingerprint)
            headers = _headers_with_clearance(headers, url, self.proxy, self.clearance_user_agent)
            resp, error = request_with_local_retry(self.session, "post", url, json={"username": email, "password": password}, headers=headers)
            if _is_cloudflare_challenge(resp):
                raise RuntimeError(_cloudflare_block_message(resp, "Cloudflare clearance 重试仍被拦截"))
        if resp is None or resp.status_code != 200:
            data = _response_json(resp) if resp is not None else {}
            if data.get("message") == "Failed to create account. Please try again.":
                step(index, "注册失败提示: 邮箱域名很可能因滥用被封禁，请更换邮箱域名", "yellow")
            detail = f", detail={json.dumps(data, ensure_ascii=False)}" if data else ""
            raise RuntimeError(
                redact_auth_diagnostic(
                    error or f"user_register_http_{getattr(resp, 'status_code', 'unknown')}{detail}"
                )
            )
        step(index, "提交注册密码完成")

    def _send_otp(self, index: int) -> None:
        step(index, "开始发送验证码")
        url = f"{auth_base}/api/accounts/email-otp/send"
        headers = _headers_with_clearance(self._navigate_headers(f"{auth_base}/create-account/password"), url, self.proxy, self.clearance_user_agent)
        resp, error = request_with_local_retry(self.session, "get", url, headers=headers, allow_redirects=True)
        if _is_cloudflare_challenge(resp):
            bundle = self._refresh_cloudflare_clearance(auth_base, index)
            if bundle is None:
                raise RuntimeError(_cloudflare_block_message(resp, reason=self.clearance_failure_reason))
            headers = _headers_with_clearance(self._navigate_headers(f"{auth_base}/create-account/password"), url, self.proxy, self.clearance_user_agent)
            resp, error = request_with_local_retry(self.session, "get", url, headers=headers, allow_redirects=True)
            if _is_cloudflare_challenge(resp):
                raise RuntimeError(_cloudflare_block_message(resp, "Cloudflare clearance 重试仍被拦截"))
        if resp is None or resp.status_code not in (200, 302):
            raise RuntimeError(
                redact_auth_diagnostic(error or f"send_otp_http_{getattr(resp, 'status_code', 'unknown')}")
            )
        step(index, "发送验证码完成")

    def _validate_otp(self, code: str, index: int) -> None:
        step(index, "开始校验验证码")
        resp, error = validate_otp(self.session, self.device_id, code, self.fingerprint)
        if resp is None or resp.status_code != 200:
            body = ""
            try:
                body = (resp.text or "")[:500] if resp is not None else ""
            except Exception:
                pass
            raise RuntimeError(
                redact_auth_diagnostic(
                    error or f"validate_otp_http_{getattr(resp, 'status_code', 'unknown')}_body={body}"
                )
            )
        data = _response_json(resp)
        continue_url = extract_continue_url(data)
        if continue_url:
            self.last_otp_continue_url = continue_url
            self._authorize_continue(continue_url, index)
        step(index, "验证码校验完成")

    def _authorize_continue(self, continue_url: str, index: int) -> None:
        if not str(continue_url or "").strip():
            return
        url = validate_continuation_url(continue_url)

        def send():
            headers = self._navigate_headers(f"{auth_base}/email-verification")
            headers = _headers_with_clearance(headers, url, self.proxy, self.clearance_user_agent)
            return request_with_local_retry(
                self.session,
                "get",
                url,
                headers=headers,
                allow_redirects=False,
            )

        step(index, "开始继续注册授权")
        resp, error = send()
        if _is_cloudflare_challenge(resp):
            bundle = self._refresh_cloudflare_clearance(auth_base, index)
            if bundle is None:
                raise RuntimeError(_cloudflare_block_message(resp, reason=self.clearance_failure_reason))
            resp, error = send()
            if _is_cloudflare_challenge(resp):
                raise RuntimeError(_cloudflare_block_message(resp, "Cloudflare clearance 重试仍被拦截"))
        for _ in range(10):
            if resp is None or resp.status_code not in (301, 302, 303, 307, 308):
                break
            location = str(getattr(resp, "headers", {}).get("Location") or "").strip()
            if not location:
                break
            url = validate_continuation_url(location)
            resp, error = send()
        else:
            raise RuntimeError("authorize_continue_redirect_limit")
        if resp is None or resp.status_code not in (200, 302):
            debug = _response_debug_detail(resp)
            raise RuntimeError(
                redact_auth_diagnostic(
                    error or f"authorize_continue_http_{getattr(resp, 'status_code', 'unknown')}, {debug}"
                )
            )
        step(index, f"继续注册授权完成 url={_safe_url_for_log(str(getattr(resp, 'url', '') or ''))}")

    def _create_account(self, name: str, birthdate: str, index: int) -> None:
        step(index, "开始创建账号资料")
        url = f"{auth_base}/api/accounts/create_account"
        headers = self._json_headers(f"{auth_base}/about-you")
        sentinel_token, so_token, oai_sc = build_sentinel_with_so_token(
            self.session,
            self.device_id,
            "oauth_create_account",
            self.fingerprint,
        )
        _set_oai_sc_cookie(self.session, oai_sc)
        headers["openai-sentinel-token"] = sentinel_token
        if so_token:
            headers["openai-sentinel-so-token"] = so_token
        headers = _headers_with_clearance(headers, url, self.proxy, self.clearance_user_agent)
        resp, error = request_with_local_retry(self.session, "post", url, json={"name": name, "birthdate": birthdate}, headers=headers)
        if _is_cloudflare_challenge(resp):
            bundle = self._refresh_cloudflare_clearance(auth_base, index)
            if bundle is None:
                raise RuntimeError(_cloudflare_block_message(resp, reason=self.clearance_failure_reason))
            headers = self._json_headers(f"{auth_base}/about-you")
            sentinel_token, so_token, oai_sc = build_sentinel_with_so_token(
                self.session,
                self.device_id,
                "oauth_create_account",
                self.fingerprint,
            )
            _set_oai_sc_cookie(self.session, oai_sc)
            headers["openai-sentinel-token"] = sentinel_token
            if so_token:
                headers["openai-sentinel-so-token"] = so_token
            headers = _headers_with_clearance(headers, url, self.proxy, self.clearance_user_agent)
            resp, error = request_with_local_retry(self.session, "post", url, json={"name": name, "birthdate": birthdate}, headers=headers)
            if _is_cloudflare_challenge(resp):
                raise RuntimeError(_cloudflare_block_message(resp, "Cloudflare clearance 重试仍被拦截"))
        if resp is None or resp.status_code not in (200, 302):
            data = _response_json(resp) if resp is not None else {}
            if data.get("message") == "Failed to create account. Please try again.":
                step(index, "创建账号失败提示: 邮箱域名很可能因滥用被封禁，请更换邮箱域名", "yellow")
            detail = f", detail={json.dumps(data, ensure_ascii=False)}" if data else ""
            raise RuntimeError(
                redact_auth_diagnostic(
                    error or f"create_account_http_{getattr(resp, 'status_code', 'unknown')}{detail}"
                )
            )
        data = _response_json(resp)
        continuation = str(data.get("continue_url") or "").strip()
        location = str(getattr(resp, "headers", {}).get("Location") or "").strip()
        response_url = str(getattr(resp, "url", "") or "").strip()
        callback_params = (
            extract_oauth_callback_params_from_url(validate_continuation_url(continuation)) if continuation else None
        ) or (
            extract_oauth_callback_params_from_url(validate_continuation_url(location)) if location else None
        ) or (
            extract_oauth_callback_params_from_url(validate_continuation_url(response_url)) if response_url else None
        )
        self.platform_auth_code = str((callback_params or {}).get("code") or "").strip()
        if not self.platform_auth_code:
            continue_hint = str(data.get("continue_url") or getattr(resp, "headers", {}).get("Location") or getattr(resp, "url", "") or "")
            raise RuntimeError(f"create_account_missing_callback: continue={_safe_url_for_log(continue_hint)}")
        step(index, "创建账号资料完成")

    def _exchange_registered_tokens(self, index: int) -> dict:
        step(index, "开始换 token")
        if not self.platform_auth_code:
            raise RuntimeError("token换取失败: 缺少 OAuth callback code")
        exchange_errors: list[str] = []
        tokens = request_platform_oauth_token(self.session, self.platform_auth_code, self.code_verifier, exchange_errors, self.fingerprint)
        if not tokens:
            detail = "；".join(exchange_errors[-3:]) if exchange_errors else "未返回 token"
            raise RuntimeError(redact_auth_diagnostic(f"token换取失败: {detail}"))
        step(index, "token 换取完成")
        return tokens

    def register(self, index: int) -> dict:
        step(index, "开始创建邮箱")
        mailbox = create_mailbox(register_proxy=self.proxy)
        email = str(mailbox.get("address") or "").strip()
        if not email:
            mail_provider.release_mailbox(mailbox)
            raise RuntimeError("邮箱服务未返回 address")
        label = str(mailbox.get("label") or "")
        step(index, f"邮箱创建完成[{label}]: {email}")
        try:
            first_name, last_name = _random_name()
            mailbox["_received_after"] = (datetime.now(timezone.utc) - timedelta(seconds=5)).isoformat()
            landed = self._platform_authorize(email, index)
            source_type = "web"
            if landed == "login":
                tokens = self._passwordless_login(email, mailbox, index)
                source_type = "microsoft"
            else:
                if not self.passwordless_signup:
                    mailbox["_received_after"] = (datetime.now(timezone.utc) - timedelta(seconds=5)).isoformat()
                    self._start_passwordless_signup(index)
                step(index, "已进入 passwordless signup，不创建本地不可用的随机密码")
                step(index, "开始等待注册验证码")
                code = wait_for_code(mailbox, register_proxy=self.proxy)
                if not code:
                    raise RuntimeError("等待注册验证码超时")
                step(index, "收到注册验证码")
                self._validate_otp(code, index)
                self._create_account(f"{first_name} {last_name}", _random_birthdate(), index)
                tokens = self._exchange_registered_tokens(index)
        except Exception as error:
            try:
                _maybe_ban_domain_from_error(mailbox, error, index=index)
            except Exception:
                pass
            mail_provider.mark_mailbox_result(mailbox, success=False, error=error)
            raise
        mail_provider.mark_mailbox_result(mailbox, success=True)
        return {
            "email": email,
            "password": "",
            "access_token": str(tokens.get("access_token") or "").strip(),
            "refresh_token": str(tokens.get("refresh_token") or "").strip(),
            "id_token": str(tokens.get("id_token") or "").strip(),
            "source_type": source_type,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }


def worker(index: int) -> dict:
    start = time.time()
    register_proxy = _pick_register_proxy()
    registrar = PlatformRegistrar(register_proxy)
    try:
        step(index, "任务启动")
        result = registrar.register(index)
        cost = time.time() - start
        access_token = str(result["access_token"])
        account_payload = {**result, "proxy": registrar.proxy, "fp": registrar.fingerprint}
        account_service.add_account_items([account_payload])
        refresh_result = account_service.refresh_accounts([access_token])
        if refresh_result.get("errors"):
            step(index, f"账号已保存，刷新状态暂未成功，稍后可重试: {refresh_result['errors']}", "yellow")
        configured_max_retries = config.get("max_relogin_retries")
        max_retries = max(
            0,
            min(10, int(3 if configured_max_retries in (None, "") else configured_max_retries)),
        )
        if max_retries > 0:
            _verify_and_fix(index, access_token, account_payload, registrar.proxy, registrar.fingerprint, max_retries)
        with stats_lock:
            stats["done"] += 1
            stats["success"] += 1
            avg = (time.time() - stats["start_time"]) / stats["success"]
        log(f'{result["email"]} 注册成功，本次耗时{cost:.1f}s，全局平均每个号注册耗时{avg:.1f}s', "green")
        return {"ok": True, "index": index, "result": result}
    except Exception as e:
        cost = time.time() - start
        safe_error = redact_auth_diagnostic(e)
        with stats_lock:
            stats["done"] += 1
            stats["fail"] += 1
        log(f"任务{index} 注册失败，本次耗时{cost:.1f}s，原因: {safe_error}", "red")
        return {"ok": False, "index": index, "error": safe_error}
    finally:
        registrar.close()


def _reconstruct_mailbox(email: str) -> dict:
    """从 email 重建 relogin 所需 mailbox；当前只支持不会被删除的 AHEM。"""
    if "@" not in email:
        return {}
    local_part, _, domain = email.partition("@")
    local_part = local_part.strip()
    domain = domain.strip().lower()
    if not local_part or not domain:
        return {}

    raw_mail_config = config.get("mail")
    mail_config: dict = raw_mail_config if isinstance(raw_mail_config, dict) else {}
    raw_providers = mail_config.get("providers")
    providers: list[dict] = (
        [entry for entry in raw_providers if isinstance(entry, dict)]
        if isinstance(raw_providers, list)
        else []
    )
    for index, entry in enumerate(providers, start=1):
        if not entry.get("enable") and not entry.get("schedule_enable") and not entry.get("enable_scheduled"):
            continue
        provider_type = str(entry.get("type") or "").strip().lower()
        if provider_type == "ahem":
            configured_domains = [str(item).strip().lower() for item in (entry.get("domain") or [])]
            if domain in configured_domains:
                return {
                    "provider": "ahem",
                    "provider_ref": f"ahem#{index}",
                    "address": email,
                    "prefix": local_part,
                    "domain": domain,
                    "api_base": str(entry.get("api_base") or "").rstrip("/"),
                }
        if provider_type == "stalwart":
            configured_domains = [str(item).strip().lower() for item in (entry.get("domain") or [])]
            if domain in configured_domains:
                return {
                    "provider": "stalwart",
                    "provider_ref": f"stalwart#{index}",
                    "address": email,
                }
    return {}


def relogin(email: str, password: str, proxy: str = "", fp: dict | None = None) -> dict:
    """重新登录并换取 token；无密码的 AHEM 账号使用 Passwordless OTP。"""
    mailbox = _reconstruct_mailbox(email)
    if not mailbox:
        raise RuntimeError(f"无法为 {email} 重建收件箱，该邮箱的 provider 不支持 relogin")
    if str(mailbox.get("provider") or "") == "stalwart":
        raise RuntimeError("Stalwart 邮箱注册后已删除，无法接收 relogin 验证码")
    registrar = PlatformRegistrar(proxy=proxy, fingerprint=fp if isinstance(fp, dict) else None)
    try:
        if password:
            return registrar._login_and_exchange_tokens(email, password, mailbox, 0)
        registrar._platform_authorize(email, 0, screen_hint="login_or_signup")
        return registrar._passwordless_login(email, mailbox, 0)
    finally:
        registrar.close()


def _verify_and_fix(index: int, access_token: str, result: dict, proxy: str, fp: dict, max_retries: int) -> None:
    """注册成功后验证 token；仅 401 时按上限 relogin 并旋转账号池 token。"""
    from services.openai_backend_api import InvalidAccessTokenError, OpenAIBackendAPI

    email = str(result.get("email") or "").strip()
    password = str(result.get("password") or "").strip()
    if not email:
        return

    current_token = str(access_token or "").strip()
    for attempt in range(max_retries + 1):
        try:
            with OpenAIBackendAPI(access_token=current_token) as backend:
                info = backend.get_user_info()
            updates = {key: value for key, value in info.items() if value is not None}
            if updates:
                account_service.update_account(current_token, updates, quiet=True)
            step(index, f"注册后验证通过 (attempt={attempt})", "green")
            return
        except InvalidAccessTokenError:
            if attempt >= max_retries:
                step(index, f"注册后验证失败，已达最大重试次数 {max_retries}", "yellow")
                return
            step(index, f"注册后验证 401，尝试 relogin (attempt={attempt + 1}/{max_retries})", "yellow")
            try:
                tokens = relogin(email, password, proxy=proxy, fp=fp)
                new_token = str(tokens.get("access_token") or "").strip()
                if not new_token:
                    step(index, "relogin 返回空 token", "yellow")
                    return
                tokens = {**tokens, "email": email, "password": password, "proxy": proxy, "fp": fp}
                current_token = str(
                    account_service.apply_relogin_tokens(current_token, tokens, "register_relogin_verify")
                    or new_token
                )
                step(index, "relogin 成功，已替换 token")
            except Exception as relogin_error:
                step(index, f"relogin 失败: {redact_auth_diagnostic(relogin_error)}", "yellow")
                return
        except Exception as error:
            step(index, f"注册后验证出错（非401），跳过: {redact_auth_diagnostic(error)}", "yellow")
            return
