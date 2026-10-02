"""OAuth 2.0 / OIDC engine for ChatGPT Plus/Pro subscription connections (§4, §5).

Follows specifications from
docs/new_features/agentic-os-feature-model-plan-connect-v2.md
(AO-MODEL-PLAN-CONNECT-01).
"""

from __future__ import annotations

import base64
import hashlib
import json
import secrets
import sys
import threading
import urllib.error
import urllib.parse
import urllib.request
import webbrowser
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any

import jwt
from pydantic import BaseModel, ConfigDict, Field

from myagentos.gateway.credential_store import CredentialStore, PlanCredentialSecret
from myagentos.gateway.plan_connection import (
    ConnectionAuthKind,
    ConnectionPlatform,
    ConnectionServiceStatus,
    PlanAuthenticationError,
    PlanConnectionProfile,
)


class OpenAIOAuthConfig(BaseModel):
    """Configuration for Sign in with ChatGPT OAuth/OIDC (§5)."""

    model_config = ConfigDict(frozen=True)

    auth_url: str = "https://auth.openai.com/authorize"
    token_url: str = "https://auth.openai.com/oauth/token"
    revoke_url: str = "https://auth.openai.com/oauth/revoke"
    issuer: str = "https://auth.openai.com"
    jwks_url: str = "https://auth.openai.com/.well-known/jwks.json"
    client_id: str = "dynamic_agent_client"
    scopes: list[str] = Field(
        default_factory=lambda: ["openid", "profile", "email", "model.request", "offline_access"]
    )
    redirect_host: str = "127.0.0.1"


class PKCEContext(BaseModel):
    """Cryptographic parameters for PKCE S256 and state validation (§5)."""

    model_config = ConfigDict(frozen=True)

    code_verifier: str
    code_challenge: str
    state: str
    nonce: str
    port: int
    redirect_uri: str


def generate_pkce_context(port: int, host: str = "127.0.0.1") -> PKCEContext:
    """Generates PKCE S256 verifier, challenge, state and nonce (§5)."""
    # 64 bytes produces ~86 characters (within 43..128 range required by RFC 7636)
    code_verifier = secrets.token_urlsafe(64)
    digest = hashlib.sha256(code_verifier.encode("ascii")).digest()
    code_challenge = base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")
    state = secrets.token_urlsafe(32)
    nonce = secrets.token_urlsafe(32)
    redirect_uri = f"http://{host}:{port}/callback"

    return PKCEContext(
        code_verifier=code_verifier,
        code_challenge=code_challenge,
        state=state,
        nonce=nonce,
        port=port,
        redirect_uri=redirect_uri,
    )


def _decode_jwt_unverified_claims(jwt_str: str) -> dict[str, Any]:
    """Decodes JWT payload without cryptographic verification for identity info extraction."""
    parts = jwt_str.split(".")
    if len(parts) != 3:
        return {}
    payload_b64 = parts[1]
    # Add padding if needed
    rem = len(payload_b64) % 4
    if rem:
        payload_b64 += "=" * (4 - rem)
    try:
        raw = base64.urlsafe_b64decode(payload_b64).decode("utf-8")
        parsed = json.loads(raw)
        return parsed if isinstance(parsed, dict) else {}
    except Exception:
        return {}


class _CallbackHandler(BaseHTTPRequestHandler):
    """Temporary HTTP handler capturing OAuth 2.0 loopback redirect."""

    def log_message(self, format: str, *args: Any) -> None:
        """Suppress stdout access logging of tokens/queries."""

    def do_GET(self) -> None:
        parsed_url = urllib.parse.urlparse(self.path)
        if parsed_url.path != "/callback":
            self.send_response(404)
            self.end_headers()
            self.wfile.write(b"Not Found")
            return

        query_params = urllib.parse.parse_qs(parsed_url.query)
        self.server.received_params = query_params

        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        html = (
            "<!DOCTYPE html><html><head><title>myAgentOS - Autenticado</title></head>"
            "<body style='font-family: sans-serif; text-align: center; margin-top: 50px;'>"
            "<h2>Autenticación con ChatGPT completada</h2>"
            "<p>Puedes cerrar esta pestaña y volver a la terminal de myAgentOS.</p>"
            "</body></html>"
        )
        self.wfile.write(html.encode("utf-8"))


class _LoopbackServer(HTTPServer):
    """HTTPServer with typed received_params attribute."""

    received_params: dict[str, list[str]]


class OAuthLoopbackListener:
    """Ephemeral single-use HTTP server on 127.0.0.1 for loopback OAuth callback (§5)."""

    def __init__(self, host: str = "127.0.0.1") -> None:
        self.host = host
        # Port 0 instructs OS to bind to an available ephemeral port
        self.server = _LoopbackServer((self.host, 0), _CallbackHandler)
        self.port: int = self.server.server_address[1]
        self.server.received_params = {}

    def wait_for_callback(self, timeout_seconds: float = 120.0) -> dict[str, list[str]]:
        """Waits for a single HTTP GET /callback request and returns parsed parameters."""
        self.server.timeout = timeout_seconds
        self.server.handle_request()
        return getattr(self.server, "received_params", {})

    def close(self) -> None:
        self.server.server_close()


class OAuthOpenAIEngine:
    """Manages the full lifecycle of ChatGPT Plan OAuth connections (§5, §9)."""

    def __init__(
        self,
        config: OpenAIOAuthConfig | None = None,
        store: CredentialStore | None = None,
    ) -> None:
        self.config = config or OpenAIOAuthConfig()
        self.store = store or CredentialStore()

    def build_authorization_url(self, context: PKCEContext) -> str:
        """Constructs the authorization URL with PKCE S256 parameters (§5)."""
        params = {
            "response_type": "code",
            "client_id": self.config.client_id,
            "redirect_uri": context.redirect_uri,
            "scope": " ".join(self.config.scopes),
            "state": context.state,
            "nonce": context.nonce,
            "code_challenge": context.code_challenge,
            "code_challenge_method": "S256",
        }
        return f"{self.config.auth_url}?{urllib.parse.urlencode(params)}"

    def _validate_id_token(
        self,
        id_token: str,
        expected_client_id: str,
        context: PKCEContext,
        http_client: Callable[..., Any] | None = None,
    ) -> dict[str, Any]:
        """Validates OIDC identity claims using remote JWKS and required OIDC invariants."""
        try:
            header = jwt.get_unverified_header(id_token)
            algorithm = header.get("alg") or "RS256"
        except Exception as exc:
            raise PlanAuthenticationError(
                "ID token is not a valid JWT",
                platform=ConnectionPlatform.CHATGPT_PLAN.value,
                error_code="invalid_id_token",
            ) from exc

        if algorithm not in {"RS256", "RS384", "RS512", "ES256", "ES384", "ES512"}:
            raise PlanAuthenticationError(
                f"Unsupported ID token signing algorithm '{algorithm}'",
                platform=ConnectionPlatform.CHATGPT_PLAN.value,
                error_code="unsupported_id_token_alg",
            )

        try:
            jwks_client = jwt.PyJWKClient(self.config.jwks_url)
            signing_key = jwks_client.get_signing_key_from_jwt(id_token)
        except Exception as exc:
            raise PlanAuthenticationError(
                "Unable to verify ID token signature against the configured JWKS",
                platform=ConnectionPlatform.CHATGPT_PLAN.value,
                error_code="jwks_unavailable",
            ) from exc

        try:
            claims = jwt.decode(
                id_token,
                signing_key.key,
                algorithms=[algorithm],
                audience=expected_client_id,
                issuer=self.config.issuer,
                options={
                    "require": ["exp", "iat", "iss", "aud", "sub", "nonce"],
                    "verify_exp": True,
                    "verify_aud": True,
                    "verify_iss": True,
                },
            )
        except jwt.InvalidTokenError as exc:
            raise PlanAuthenticationError(
                f"Invalid ID token: {exc}",
                platform=ConnectionPlatform.CHATGPT_PLAN.value,
                error_code="invalid_id_token",
            ) from exc

        if claims.get("nonce") != context.nonce:
            raise PlanAuthenticationError(
                "ID token nonce mismatch; possible replay or interception",
                platform=ConnectionPlatform.CHATGPT_PLAN.value,
                error_code="nonce_mismatch",
            )

        return claims

    def exchange_code_for_tokens(
        self,
        code: str,
        context: PKCEContext,
        http_client: Callable[..., Any] | None = None,
    ) -> PlanCredentialSecret:
        """Exchanges authorization code for tokens and extracts account identity (§5)."""
        body = {
            "grant_type": "authorization_code",
            "client_id": self.config.client_id,
            "code": code,
            "redirect_uri": context.redirect_uri,
            "code_verifier": context.code_verifier,
        }
        encoded_body = urllib.parse.urlencode(body).encode("utf-8")
        req = urllib.request.Request(
            self.config.token_url,
            data=encoded_body,
            headers={
                "Content-Type": "application/x-www-form-urlencoded",
                "Accept": "application/json",
            },
            method="POST",
        )

        try:
            if http_client:
                resp_data = http_client(req)
            else:
                with urllib.request.urlopen(req, timeout=30) as resp:
                    resp_data = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            err_body = e.read().decode("utf-8", errors="replace")
            raise PlanAuthenticationError(
                f"OAuth token exchange failed (HTTP {e.code}): {err_body}",
                platform=ConnectionPlatform.CHATGPT_PLAN.value,
                error_code=f"http_{e.code}",
            ) from e
        except Exception as e:
            raise PlanAuthenticationError(
                f"OAuth network error during token exchange: {e}",
                platform=ConnectionPlatform.CHATGPT_PLAN.value,
            ) from e

        access_token = resp_data.get("access_token")
        refresh_token = resp_data.get("refresh_token")
        id_token = resp_data.get("id_token")
        expires_in = int(resp_data.get("expires_in", 3600))
        issued_client_id = resp_data.get("client_id", self.config.client_id)
        scope_str = resp_data.get("scope", "")
        scopes = scope_str.split() if scope_str else self.config.scopes

        if not access_token:
            raise PlanAuthenticationError(
                "OAuth response missing access_token",
                platform=ConnectionPlatform.CHATGPT_PLAN.value,
            )

        claims: dict[str, Any] = {}
        if id_token:
            claims = self._validate_id_token(
                id_token=id_token,
                expected_client_id=issued_client_id,
                context=context,
                http_client=http_client,
            )

        account_label = claims.get("email") or claims.get("sub") or "ChatGPT Account"
        account_id = claims.get("sub")

        now = datetime.now(UTC)
        expires_at = now + timedelta(seconds=expires_in)

        connection_id = "conn-openai-chatgpt"
        secret = PlanCredentialSecret(
            connection_id=connection_id,
            provider="openai",
            platform=ConnectionPlatform.CHATGPT_PLAN.value,
            access_token=access_token,
            refresh_token=refresh_token,
            id_token=id_token,
            token_type=resp_data.get("token_type", "Bearer"),
            expires_at=expires_at,
            scope=scopes,
            client_id_issued=issued_client_id,
            account_id=account_id,
            account_label=account_label,
            metadata={"connected_at": now.isoformat()},
        )
        self.store.save_credential(secret)
        return secret

    def refresh_access_token(
        self,
        connection_id: str,
        http_client: Callable[..., Any] | None = None,
    ) -> PlanCredentialSecret:
        """Refreshes access token under cross-process lock with idempotency (§5)."""
        with self.store.lock():
            # 1. Re-read under lock: another process may have already refreshed it
            current = self.store.get_credential(connection_id)
            if not current:
                raise PlanAuthenticationError(
                    f"No credentials found for connection '{connection_id}'",
                    platform=ConnectionPlatform.CHATGPT_PLAN.value,
                )
            if not current.is_expired():
                return current

            if not current.refresh_token:
                raise PlanAuthenticationError(
                    f"Connection '{connection_id}' has expired and lacks a refresh token",
                    platform=ConnectionPlatform.CHATGPT_PLAN.value,
                    error_code="no_refresh_token",
                )

            client_id = current.client_id_issued or self.config.client_id
            body = {
                "grant_type": "refresh_token",
                "client_id": client_id,
                "refresh_token": current.refresh_token,
            }
            encoded_body = urllib.parse.urlencode(body).encode("utf-8")
            req = urllib.request.Request(
                self.config.token_url,
                data=encoded_body,
                headers={
                    "Content-Type": "application/x-www-form-urlencoded",
                    "Accept": "application/json",
                },
                method="POST",
            )

            try:
                if http_client:
                    resp_data = http_client(req)
                else:
                    with urllib.request.urlopen(req, timeout=30) as resp:
                        resp_data = json.loads(resp.read().decode("utf-8"))
            except urllib.error.HTTPError as e:
                err_body = e.read().decode("utf-8", errors="replace")
                if e.code in (400, 401) and (
                    "invalid_grant" in err_body or "revoked" in err_body
                ):
                    # Refresh token is revoked or obsolete -> clear local secrets to prevent loop
                    self.store.delete_credential(connection_id)
                    raise PlanAuthenticationError(
                        "ChatGPT Plan refresh token is invalid or revoked. Please reconnect.",
                        platform=ConnectionPlatform.CHATGPT_PLAN.value,
                        error_code="invalid_grant",
                    ) from e
                raise PlanAuthenticationError(
                    f"Token refresh failed (HTTP {e.code}): {err_body}",
                    platform=ConnectionPlatform.CHATGPT_PLAN.value,
                    error_code=f"http_{e.code}",
                ) from e
            except Exception as e:
                raise PlanAuthenticationError(
                    f"Network error refreshing token: {e}",
                    platform=ConnectionPlatform.CHATGPT_PLAN.value,
                ) from e

            new_access = resp_data.get("access_token")
            new_refresh = resp_data.get("refresh_token") or current.refresh_token
            new_id = resp_data.get("id_token") or current.id_token
            expires_in = int(resp_data.get("expires_in", 3600))
            now = datetime.now(UTC)

            updated = current.model_copy(
                update={
                    "access_token": new_access,
                    "refresh_token": new_refresh,
                    "id_token": new_id,
                    "expires_at": now + timedelta(seconds=expires_in),
                }
            )
            self.store.save_credential(updated)
            return updated

    def revoke_and_disconnect(
        self,
        connection_id: str,
        http_client: Callable[..., Any] | None = None,
    ) -> bool:
        """Revokes token remotely if possible and unconditionally purges local secrets (§5)."""
        secret = self.store.get_credential(connection_id)
        if secret and secret.refresh_token:
            client_id = secret.client_id_issued or self.config.client_id
            body = {
                "client_id": client_id,
                "token": secret.refresh_token,
                "token_type_hint": "refresh_token",
            }
            encoded_body = urllib.parse.urlencode(body).encode("utf-8")
            req = urllib.request.Request(
                self.config.revoke_url,
                data=encoded_body,
                headers={"Content-Type": "application/x-www-form-urlencoded"},
                method="POST",
            )
            try:
                if http_client:
                    http_client(req)
                else:
                    with urllib.request.urlopen(req, timeout=10):
                        pass
            except Exception:
                # Best-effort remote revocation; local purge proceeds regardless
                pass

        return self.store.delete_credential(connection_id)

    def connect_interactive(
        self,
        timeout_seconds: float = 120.0,
        open_browser: bool = True,
        on_url_ready: Callable[[str], None] | None = None,
        http_client: Callable[..., Any] | None = None,
    ) -> PlanConnectionProfile:
        """Executes full interactive loopback OAuth flow (§5)."""
        listener = OAuthLoopbackListener(host=self.config.redirect_host)
        context = generate_pkce_context(port=listener.port, host=self.config.redirect_host)
        auth_url = self.build_authorization_url(context)

        if on_url_ready:
            on_url_ready(auth_url)
        elif open_browser:
            opened_browser = webbrowser.open(auth_url)
            if not opened_browser:
                print(
                    "[WARN] Browser could not be opened automatically. Open this URL manually: "
                    f"{auth_url}",
                    file=sys.stderr,
                )

        try:
            params = listener.wait_for_callback(timeout_seconds=timeout_seconds)
        finally:
            listener.close()

        if "error" in params:
            err_code = params["error"][0]
            err_desc = (
                params.get("error_description", ["Authorization was denied"])[0]
            )
            raise PlanAuthenticationError(
                f"OAuth error: {err_desc} ({err_code})",
                platform=ConnectionPlatform.CHATGPT_PLAN.value,
                error_code=err_code,
            )

        if "code" not in params or "state" not in params:
            raise PlanAuthenticationError(
                "OAuth callback timed out or did not return an authorization code",
                platform=ConnectionPlatform.CHATGPT_PLAN.value,
                error_code="timeout",
            )

        received_state = params["state"][0]
        if received_state != context.state:
            raise PlanAuthenticationError(
                "OAuth state parameter mismatch; aborting authentication",
                platform=ConnectionPlatform.CHATGPT_PLAN.value,
                error_code="state_mismatch",
            )

        code = params["code"][0]
        secret = self.exchange_code_for_tokens(code, context, http_client=http_client)

        return PlanConnectionProfile(
            connection_id=secret.connection_id,
            provider="openai",
            platform=ConnectionPlatform.CHATGPT_PLAN,
            auth_kind=ConnectionAuthKind.OAUTH,
            account_label=secret.account_label or "ChatGPT User",
            account_id=secret.account_id,
            client_id_issued=secret.client_id_issued,
            status=ConnectionServiceStatus.READY,
            last_validated_at=datetime.now(UTC),
        )


OpenAIOAuthClient = OAuthOpenAIEngine
