from __future__ import annotations

import os
import unittest
from unittest import mock
from urllib.parse import parse_qs, urlparse

os.environ.setdefault("CHATGPT2API_AUTH_KEY", "test-auth")

from services.register import openai_register
from services.register import mail_provider
from services.oauth_login_service import OAuthLoginError, OAuthLoginService
from services.proxy_service import ProxyRuntimeProfile
from utils import sentinel
from utils.diagnostics import redact_auth_diagnostic


class FakeResponse:
    def __init__(
        self,
        *,
        status_code: int = 200,
        text: str = "{}",
        headers: dict[str, str] | None = None,
        url: str = "https://auth.openai.com/test",
        json_data: dict | None = None,
    ) -> None:
        self.status_code = status_code
        self.text = text
        self.headers = headers or {}
        self.url = url
        self.history: list[FakeResponse] = []
        self._json_data = json_data or {}

    def json(self) -> dict:
        return self._json_data


class FakeCookies:
    def __init__(self) -> None:
        self.values: dict[tuple[str | None, str], str] = {}

    def set(self, name: str, value: str, domain: str | None = None) -> None:
        self.values[(domain, name)] = value

    def get(self, name: str, domain: str | None = None) -> str | None:
        return self.values.get((domain, name)) or self.values.get((None, name))


class FakeSession:
    def __init__(self) -> None:
        self.headers: dict[str, str] = {}
        self.cookies = FakeCookies()

    def close(self) -> None:
        return


class PasswordlessRegistrationTests(unittest.TestCase):
    def test_auth_diagnostic_redacts_basic_authorization_credentials(self) -> None:
        secret = "basic-credential-secret"

        redacted = redact_auth_diagnostic(f"request failed: Authorization: Basic {secret}")

        self.assertNotIn(secret, redacted)
        self.assertIn("Authorization: [REDACTED]", redacted)

    def test_auth_diagnostic_redacts_labeled_secrets_and_keeps_safe_context(self) -> None:
        secret = "secret-value-123"
        diagnostic = (
            "status=401 path=/oauth/token request_id=req-7 "
            f"code={secret} otp: {secret} Cookie='{secret}' Authorization=Bearer {secret} "
            f"oai-sc={secret} json={{\"access_token\":\"{secret}\",\"refresh_token\": \"{secret}\",\"id_token\":\"{secret}\",\"oai-sc\":\"{secret}\"}} "
            f"url=https://auth.openai.com/callback?code={secret}&state={secret}&oai-sc={secret}&safe=visible oai-sc-extra=visible-oai-context"
        )

        redacted = redact_auth_diagnostic(diagnostic)

        self.assertNotIn(secret, redacted)
        self.assertIn("status=401", redacted)
        self.assertIn("path=/oauth/token", redacted)
        self.assertIn("request_id=req-7", redacted)
        self.assertIn("safe=visible", redacted)
        self.assertIn("oai-sc-extra=visible-oai-context", redacted)

    def test_response_debug_detail_redacts_url_and_json_credentials(self) -> None:
        secret = "response-secret-456"
        response = FakeResponse(
            status_code=401,
            url=f"https://auth.openai.com/callback?code={secret}&safe=visible",
            headers={"x-request-id": "req-safe", "content-type": "application/json"},
            json_data={"error": "invalid_grant", "access_token": secret},
        )

        detail = openai_register._response_debug_detail(response)

        self.assertNotIn(secret, detail)
        self.assertIn("/callback", detail)
        self.assertIn("req-safe", detail)
        self.assertIn("invalid_grant", detail)

    def test_oauth_callback_full_url_is_validated_but_raw_code_is_preserved(self) -> None:
        raw_code = "raw-code-input-789"

        self.assertEqual(OAuthLoginService._extract_code_from_callback(raw_code), (raw_code, ""))
        with self.assertRaises(OAuthLoginError):
            OAuthLoginService._extract_code_from_callback(
                f"https://evil.example/auth/callback?code={raw_code}"
            )

    def test_oauth_token_rejection_diagnostics_do_not_expose_credentials(self) -> None:
        secret = "upstream-token-secret"
        response = FakeResponse(
            status_code=401,
            text=f'{{"error":"invalid_grant","refresh_token":"{secret}"}}',
            json_data={"error": "invalid_grant", "refresh_token": secret},
        )
        session = mock.Mock()
        session.post.return_value = response

        with mock.patch("services.oauth_login_service.requests.Session", return_value=session), mock.patch(
            "builtins.print"
        ) as output, self.assertRaisesRegex(Exception, "invalid_grant") as raised:
            OAuthLoginService._exchange_code(
                "raw-code-input",
                "verifier-input",
                "https://platform.openai.com/auth/callback",
            )

        rendered_output = " ".join(str(arg) for call in output.call_args_list for arg in call.args)
        self.assertNotIn(secret, rendered_output)
        self.assertNotIn(secret, str(raised.exception))

    def test_registration_session_verification_follows_runtime_profile(self) -> None:
        profiles = (
            ProxyRuntimeProfile(skip_ssl_verify=False),
            ProxyRuntimeProfile(skip_ssl_verify=True),
        )

        with mock.patch.object(openai_register.proxy_settings, "get_profile", side_effect=profiles), mock.patch.object(
            openai_register.requests,
            "Session",
        ) as session_type:
            openai_register.create_session()
            openai_register.create_session()

        self.assertIs(session_type.call_args_list[0].kwargs["verify"], True)
        self.assertIs(session_type.call_args_list[1].kwargs["verify"], False)

    def test_mail_session_verification_follows_runtime_profile(self) -> None:
        profiles = (
            ProxyRuntimeProfile(skip_ssl_verify=False),
            ProxyRuntimeProfile(skip_ssl_verify=True),
        )

        with mock.patch.object(mail_provider.proxy_settings, "get_profile", side_effect=profiles), mock.patch.object(
            mail_provider.requests,
            "Session",
        ) as session_type:
            mail_provider._create_session({"proxy": ""})
            mail_provider._create_session({"proxy": ""})

        self.assertIs(session_type.call_args_list[0].kwargs["verify"], True)
        self.assertIs(session_type.call_args_list[1].kwargs["verify"], False)

    def test_mailbox_failure_state_redacts_authorization_credentials(self) -> None:
        secret = "mailbox-credential-secret"
        mailbox = {"provider": "outlook_token", "address": "user@example.test"}

        with mock.patch.object(mail_provider, "_set_outlook_token_state") as set_state:
            mail_provider.mark_mailbox_result(
                mailbox,
                success=False,
                error=RuntimeError(f"Authorization: Basic {secret}"),
            )

        persisted_reason = str(set_state.call_args.args[2])
        self.assertNotIn(secret, persisted_reason)

    def test_oauth_exchange_session_verification_follows_runtime_profile(self) -> None:
        response = FakeResponse(json_data={"access_token": "a", "refresh_token": "r"})
        session = mock.Mock()
        session.post.return_value = response
        profiles = (
            ProxyRuntimeProfile(skip_ssl_verify=False),
            ProxyRuntimeProfile(skip_ssl_verify=True),
        )

        with mock.patch.object(
            openai_register.proxy_settings,
            "get_profile",
            side_effect=profiles,
        ), mock.patch("services.oauth_login_service.requests.Session", return_value=session) as session_type:
            OAuthLoginService._exchange_code("code", "verifier", "https://platform.openai.com/auth/callback")
            OAuthLoginService._exchange_code("code", "verifier", "https://platform.openai.com/auth/callback")

        self.assertIs(session_type.call_args_list[0].kwargs["verify"], True)
        self.assertIs(session_type.call_args_list[1].kwargs["verify"], False)

    def test_sentinel_request_inherits_session_verification(self) -> None:
        session = mock.Mock()
        session.post.return_value = FakeResponse(json_data={"token": "challenge"}, text='{"token":"challenge"}')

        sentinel.build_sentinel_token(session, "device", "flow")

        self.assertNotIn("verify", session.post.call_args.kwargs)

    def test_continuation_url_allows_only_relative_or_exact_https_hosts(self) -> None:
        accepted = {
            "/authorize/continue?state=x": "https://auth.openai.com/authorize/continue?state=x",
            "https://auth.openai.com/authorize/continue": "https://auth.openai.com/authorize/continue",
            "https://platform.openai.com/auth/callback?code=x": "https://platform.openai.com/auth/callback?code=x",
        }

        for raw, expected in accepted.items():
            with self.subTest(raw=raw):
                self.assertEqual(openai_register.validate_continuation_url(raw), expected)

    def test_continuation_url_rejects_external_and_malformed_inputs(self) -> None:
        rejected = (
            "http://auth.openai.com/authorize",
            "https://evil.example/authorize",
            "https://auth.openai.com.evil.example/authorize",
            "https://user@auth.openai.com/authorize",
            "https://auth.openai.com:444/authorize",
            "//evil.example/authorize",
            "https:authorize/continue",
            "/\\evil.example/authorize",
            "/authorize\nnext",
        )

        for raw in rejected:
            with self.subTest(raw=raw), self.assertRaises(ValueError):
                openai_register.validate_continuation_url(raw)

    def test_authorize_continue_validates_each_redirect_before_request(self) -> None:
        first = FakeResponse(status_code=302, headers={"Location": "/next"})
        second = FakeResponse(status_code=302, headers={"Location": "https://evil.example/steal"})
        calls: list[str] = []

        def fake_request(_session, _method: str, url: str, **_kwargs):
            calls.append(url)
            return (first if len(calls) == 1 else second), ""

        with mock.patch.object(openai_register, "create_session", return_value=FakeSession()), mock.patch.object(
            openai_register,
            "request_with_local_retry",
            side_effect=fake_request,
        ):
            registrar = openai_register.PlatformRegistrar()
            with self.assertRaises(ValueError):
                registrar._authorize_continue("/start", 1)

        self.assertEqual(calls, ["https://auth.openai.com/start", "https://auth.openai.com/next"])

    def test_token_exchange_rejects_external_callback_redirect_before_following(self) -> None:
        response = FakeResponse(
            status_code=302,
            headers={"Location": "https://evil.example/callback?code=stolen"},
        )
        session = mock.Mock()
        session.request.return_value = response

        with self.assertRaises(ValueError):
            openai_register.exchange_tokens_from_continue_url(
                session,
                "device",
                "verifier",
                "/authorize/continue",
            )

        session.request.assert_called_once()

    def test_authorize_defaults_to_passwordless_signup(self) -> None:
        response = FakeResponse(url="https://auth.openai.com/email-verification")
        calls: list[dict] = []

        def fake_request(_session, method: str, url: str, **kwargs):
            calls.append({"method": method, "url": url, "kwargs": kwargs})
            return response, ""

        with mock.patch.object(openai_register, "create_session", return_value=FakeSession()), mock.patch.object(
            openai_register,
            "request_with_local_retry",
            side_effect=fake_request,
        ):
            registrar = openai_register.PlatformRegistrar()
            registrar._platform_authorize("new@example.test", 1)

        query = parse_qs(urlparse(calls[0]["url"]).query)
        self.assertEqual(query["screen_hint"], ["login_or_signup"])
        self.assertTrue(registrar.passwordless_signup)

    def test_platform_authorize_log_redacts_final_url_query(self) -> None:
        secret = "authorize-code-secret"
        response = FakeResponse(
            url=f"https://auth.openai.com/email-verification?code={secret}&safe=visible"
        )

        with mock.patch.object(openai_register, "create_session", return_value=FakeSession()), mock.patch.object(
            openai_register,
            "request_with_local_retry",
            return_value=(response, ""),
        ), mock.patch.object(openai_register, "step") as step:
            registrar = openai_register.PlatformRegistrar()
            registrar._platform_authorize("new@example.test", 1)

        rendered = " ".join(str(arg) for call in step.call_args_list for arg in call.args)
        self.assertNotIn(secret, rendered)
        self.assertIn("/email-verification", rendered)

    def test_new_account_skips_legacy_password_registration(self) -> None:
        mailbox = {"address": "new@example.test", "label": "test", "provider": "ahem"}
        tokens = {
            "access_token": "fake-access",
            "refresh_token": "fake-refresh",
            "id_token": "fake-id",
        }

        with mock.patch.object(openai_register, "create_session", return_value=FakeSession()), mock.patch.object(
            openai_register,
            "create_mailbox",
            return_value=mailbox,
        ), mock.patch.object(openai_register, "wait_for_code", return_value="123456"), mock.patch.object(
            openai_register.mail_provider,
            "mark_mailbox_result",
        ):
            registrar = openai_register.PlatformRegistrar()
            registrar.passwordless_signup = False
            with mock.patch.object(registrar, "_platform_authorize", return_value="signup"), mock.patch.object(
                registrar,
                "_start_passwordless_signup",
                create=True,
            ) as start_passwordless, mock.patch.object(registrar, "_register_user") as register_user, mock.patch.object(
                registrar,
                "_send_otp",
            ) as send_otp, mock.patch.object(registrar, "_validate_otp"), mock.patch.object(
                registrar,
                "_create_account",
            ), mock.patch.object(
                registrar,
                "_exchange_registered_tokens",
                return_value=tokens,
            ):
                result = registrar.register(1)

        start_passwordless.assert_called_once_with(1)
        register_user.assert_not_called()
        send_otp.assert_not_called()
        self.assertEqual(result["password"], "")
        self.assertEqual(result["access_token"], "fake-access")
        self.assertEqual(result["refresh_token"], "fake-refresh")

    def test_worker_preserves_zero_max_relogin_retries(self) -> None:
        registrar = mock.Mock()
        registrar.register.return_value = {
            "access_token": "fake-access",
            "email": "new@example.test",
        }
        registrar.proxy = ""
        registrar.fingerprint = {}

        with mock.patch.object(openai_register, "_pick_register_proxy", return_value=""), mock.patch.object(
            openai_register,
            "PlatformRegistrar",
            return_value=registrar,
        ), mock.patch.object(openai_register.account_service, "add_account_items"), mock.patch.object(
            openai_register.account_service,
            "refresh_accounts",
            return_value={"errors": []},
        ), mock.patch.object(openai_register, "_verify_and_fix") as verify_and_fix, mock.patch.dict(
            openai_register.config,
            {"max_relogin_retries": 0},
        ):
            result = openai_register.worker(1)

        self.assertTrue(result["ok"])
        verify_and_fix.assert_not_called()

    def test_otp_validation_sets_sentinel_cookie_on_fallback(self) -> None:
        session = mock.Mock(spec=openai_register.requests.Session)
        session.cookies = FakeCookies()
        responses = (
            FakeResponse(status_code=403),
            FakeResponse(status_code=200),
        )
        captured_headers: list[dict[str, str]] = []

        def fake_request(_session, _method: str, _url: str, **kwargs):
            captured_headers.append(dict(kwargs.get("headers") or {}))
            return responses[len(captured_headers) - 1], ""

        with mock.patch.object(
            openai_register,
            "_build_sentinel_token_tuple",
            return_value=("sentinel-token", "0challenge"),
        ) as build_sentinel, mock.patch.object(openai_register, "request_with_local_retry", side_effect=fake_request):
            response, error = openai_register.validate_otp(session, "device", "123456")

        if response is None:
            self.fail("expected successful OTP validation response")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(error, "")
        self.assertEqual(captured_headers[1]["openai-sentinel-token"], "sentinel-token")
        self.assertEqual(session.cookies.get("oai-sc", domain=".openai.com"), "0challenge")
        self.assertEqual(session.cookies.get("oai-sc", domain="auth.openai.com"), "0challenge")
        build_sentinel.assert_called_once()

    def test_otp_validation_follows_nested_continue_url(self) -> None:
        continue_url = "/authorize/continue?state=test-state"
        response = FakeResponse(
            json_data={"page": {"payload": {"continueUrl": continue_url}}},
        )
        with mock.patch.object(openai_register, "create_session", return_value=FakeSession()), mock.patch.object(
            openai_register,
            "validate_otp",
            return_value=(response, ""),
        ):
            registrar = openai_register.PlatformRegistrar()
            with mock.patch.object(registrar, "_authorize_continue", create=True) as authorize_continue:
                registrar._validate_otp("123456", 7)

        authorize_continue.assert_called_once_with(continue_url, 7)

    def test_create_account_sends_sentinel_and_so_token(self) -> None:
        captured_headers: list[dict[str, str]] = []

        def fake_request(_session, _method: str, _url: str, **kwargs):
            captured_headers.append(dict(kwargs.get("headers") or {}))
            return FakeResponse(
                json_data={
                    "continue_url": "https://platform.openai.com/auth/callback?code=fake-code",
                }
            ), ""

        with mock.patch.object(openai_register, "create_session", return_value=FakeSession()):
            registrar = openai_register.PlatformRegistrar()
        with mock.patch.object(openai_register, "build_sentinel_token", return_value="legacy-token"), mock.patch.object(
            openai_register,
            "build_sentinel_with_so_token",
            return_value=("sentinel-token", "so-token", "0challenge"),
            create=True,
        ), mock.patch.object(openai_register, "request_with_local_retry", side_effect=fake_request):
            registrar._create_account("Demo User", "2000-01-01", 3)

        lowered = {key.lower(): value for key, value in captured_headers[0].items()}
        self.assertEqual(lowered["openai-sentinel-token"], "sentinel-token")
        self.assertEqual(lowered["openai-sentinel-so-token"], "so-token")
        self.assertEqual(registrar.session.cookies.get("oai-sc", domain=".openai.com"), "0challenge")
        self.assertEqual(registrar.session.cookies.get("oai-sc", domain="auth.openai.com"), "0challenge")
        self.assertEqual(registrar.platform_auth_code, "fake-code")


class PasswordlessReloginTests(unittest.TestCase):
    def test_ahem_account_without_password_uses_passwordless_login(self) -> None:
        mailbox = {
            "provider": "ahem",
            "address": "new@example.test",
            "prefix": "new",
            "domain": "example.test",
        }
        tokens = {"access_token": "rotated-access", "refresh_token": "rotated-refresh"}

        with mock.patch.object(openai_register, "_reconstruct_mailbox", return_value=mailbox), mock.patch.object(
            openai_register,
            "create_session",
            return_value=FakeSession(),
        ), mock.patch.object(
            openai_register.PlatformRegistrar,
            "_platform_authorize",
            return_value="login",
        ) as authorize, mock.patch.object(
            openai_register.PlatformRegistrar,
            "_passwordless_login",
            return_value=tokens,
        ) as passwordless_login, mock.patch.object(
            openai_register.PlatformRegistrar,
            "_login_and_exchange_tokens",
            return_value=tokens,
        ) as password_login:
            result = openai_register.relogin("new@example.test", "")

        authorize.assert_called_once()
        passwordless_login.assert_called_once()
        password_login.assert_not_called()
        self.assertEqual(result["access_token"], "rotated-access")

    def test_stalwart_relogin_remains_rejected(self) -> None:
        mailbox = {"provider": "stalwart", "address": "new@example.test"}
        with mock.patch.object(openai_register, "_reconstruct_mailbox", return_value=mailbox):
            with self.assertRaisesRegex(RuntimeError, "Stalwart"):
                openai_register.relogin("new@example.test", "")


if __name__ == "__main__":
    unittest.main()
