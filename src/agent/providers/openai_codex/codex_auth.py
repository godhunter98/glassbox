import asyncio
import base64
import hmac
import json
import math
import os
import secrets
import tempfile
import threading
import time
import webbrowser
from collections.abc import Callable, Mapping
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

import jwt
import questionary
import requests
from authlib.integrations.requests_client import OAuth2Session
from authlib.oauth2.rfc6749.errors import OAuth2Error

AUTHORIZATION_URL = "https://auth.openai.com/oauth/authorize"
TOKEN_URL = "https://auth.openai.com/oauth/token"
CLIENT_ID = "app_EMoamEEZ73f0CkXaXp7hrann"
REDIRECT_URI = "http://localhost:1455/auth/callback"
SCOPES = "openid profile email offline_access"

OIDC_ISSUER = "https://auth.openai.com"
OIDC_CONFIG_URL = f"{OIDC_ISSUER}/.well-known/openid-configuration"

CALLBACK_HOST = "127.0.0.1"
CALLBACK_PORT = 1455
CALLBACK_PATH = "/auth/callback"
TOKEN_EXPIRY_SKEW_SECONDS = 60

# token is a dict of str > str | Float
TokenRecord = dict[str, str | float]


class RefreshTokenError(RuntimeError):
    """Raised when OpenAI cannot exchange a stored refresh token."""


def _create_oauth_session() -> OAuth2Session:
    """Create the public OAuth client used for OpenAI Codex authentication."""
    return OAuth2Session(
        client_id=CLIENT_ID,
        redirect_uri=REDIRECT_URI,
        scope=SCOPES,
        token_endpoint_auth_method="none",
        code_challenge_method="S256",
    )

def is_callback_url(value: str | None, state: str) -> bool:
    """Return whether a redirect URL belongs to this OAuth login attempt."""
    if not value:
        return False

    try:
        parsed = urlparse(value.strip())
        port = parsed.port
    except ValueError:
        return False

    query = parse_qs(parsed.query)
    return (
        parsed.scheme == "http"
        and parsed.hostname in {"localhost", CALLBACK_HOST}
        and port == CALLBACK_PORT
        and parsed.path == CALLBACK_PATH
        and query.get("state") == [state]
        and ("code" in query or "error" in query)
    )


def run_callback_server(
    stop_event: threading.Event,
    on_callback_received: Callable[[str], None],
    state: str,
) -> None:
    """Listen for the browser OAuth redirect until a valid callback arrives."""

    class CallbackHandler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            parsed = urlparse(self.path)
            if parsed.path != CALLBACK_PATH:
                self.send_error(404)
                return

            callback_url = f"{REDIRECT_URI}?{parsed.query}"
            if not is_callback_url(callback_url, state):
                self.send_error(400, "Invalid OAuth callback.")
                return

            body = (
                b"<html><body><h2>Login complete!</h2>"
                b"<p>You can close this window and return to GlassBox.</p>"
                b"</body></html>"
            )
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

            stop_event.set()
            on_callback_received(callback_url)

        def log_message(self, format: str, *args: object) -> None:
            pass

    try:
        with HTTPServer((CALLBACK_HOST, CALLBACK_PORT), CallbackHandler) as server:
            server.timeout = 0.25
            while not stop_event.is_set():
                server.handle_request()
    except OSError as error:
        print(f"Local callback listener unavailable: {error}")


def start_callback_server(
    stop_event: threading.Event,
    on_callback_received: Callable[[str], None],
    state: str,
) -> threading.Thread:
    server_thread = threading.Thread(
        target=run_callback_server,
        args=(stop_event, on_callback_received, state),
        daemon=True,
    )
    server_thread.start()
    return server_thread


def stop_callback_server(stop_event: threading.Event, server_thread: threading.Thread) -> None:
    stop_event.set()
    server_thread.join(timeout=0.5)


def _set_future_result(future: asyncio.Future[str], callback_url: str) -> None:
    if not future.done():
        future.set_result(callback_url)


async def prompt_for_callback() -> str | None:
    return await questionary.password(
        "Or paste the complete callback URL here:\n",
        qmark="🔗",
    ).ask_async()


async def get_callback_url(authorization_url: str, state: str) -> str:
    """Wait for either the browser redirect or a pasted redirect URL."""

    try:
        webbrowser.open(authorization_url)
    except Exception:
        pass

    print("\nOpen the link below in your browser and log in with OpenAI:\n")
    print(f"{authorization_url}\n")

    server_stop_event = threading.Event()
    loop = asyncio.get_running_loop()
    browser_callback: asyncio.Future[str] = loop.create_future()

    def send_callback_to_main_thread(callback_url: str) -> None:
        loop.call_soon_threadsafe(_set_future_result, browser_callback, callback_url)

    server_thread = start_callback_server(server_stop_event, send_callback_to_main_thread, state)
    pasted_callback = asyncio.create_task(prompt_for_callback())

    try:
        while True:
            done, _ = await asyncio.wait(
                {browser_callback, pasted_callback},
                return_when=asyncio.FIRST_COMPLETED,
            )

            if browser_callback in done:
                return browser_callback.result()

            pasted_url = pasted_callback.result()
            if pasted_url is None:
                raise RuntimeError("Login cancelled before a callback URL was received.")
            if is_callback_url(pasted_url, state):
                return pasted_url.strip()

            print("That is not a valid callback URL. Please paste the complete URL.")
            pasted_callback = asyncio.create_task(prompt_for_callback())
    finally:
        pasted_callback.cancel()
        await asyncio.gather(pasted_callback, return_exceptions=True)
        stop_callback_server(server_stop_event, server_thread)


def run_login() -> Mapping[str, Any]:
    """Run browser OAuth with PKCE and return OpenAI's raw token response."""
    oauth = _create_oauth_session()
    code_verifier = secrets.token_urlsafe(64)
    authorization_url, state = oauth.create_authorization_url(
        AUTHORIZATION_URL,
        code_verifier=code_verifier,
        id_token_add_organizations="true",
        codex_cli_simplified_flow="true",
        prompt="login",
        originator="glassbox",
    )
    callback_url = asyncio.run(get_callback_url(authorization_url, state))

    return oauth.fetch_token(
        TOKEN_URL,
        authorization_response=callback_url,
        state=state,
        code_verifier=code_verifier,
    )


def fetch_oidc_config() -> Mapping[str, Any]:
    response = requests.get(OIDC_CONFIG_URL, timeout=10)
    response.raise_for_status()
    config = response.json()

    if not isinstance(config, dict) or config.get("issuer") != OIDC_ISSUER:
        raise ValueError("Unexpected OpenAI OIDC configuration.")
    if not isinstance(config.get("jwks_uri"), str):
        raise ValueError("OpenAI OIDC configuration is missing jwks_uri.")
    return config


def validate_at_hash(payload: Mapping[str, Any], header: Mapping[str, Any], access_token: str) -> bool:
    algorithm_name = header.get("alg")
    if not isinstance(algorithm_name, str):
        raise jwt.InvalidTokenError("ID token is missing an algorithm.")

    algorithm = jwt.get_algorithm_by_name(algorithm_name)
    digest = algorithm.compute_hash_digest(access_token.encode("ascii"))
    calculated_at_hash = base64.urlsafe_b64encode(digest[: len(digest) // 2]).rstrip(b"=").decode("ascii")
    token_at_hash = payload.get("at_hash")

    if not isinstance(token_at_hash, str):
        raise jwt.InvalidTokenError("ID token is missing at_hash.")
    if not hmac.compare_digest(calculated_at_hash, token_at_hash):
        raise jwt.InvalidTokenError("Invalid at_hash.")
    return True


def validate_id_token(id_token: str, access_token: str) -> None:
    """Verify the ID token and bind it to the received access token."""
    oidc_config = fetch_oidc_config()
    jwks_uri = oidc_config["jwks_uri"]
    signing_key = jwt.PyJWKClient(jwks_uri).get_signing_key_from_jwt(id_token)

    data = jwt.decode_complete(
        id_token,
        key=signing_key,
        audience=CLIENT_ID,
        algorithms=["RS256"],
        issuer=OIDC_ISSUER,
        options={"require": ["exp", "iat", "iss", "aud", "sub"]},
    )
    payload = data["payload"]
    header = data["header"]
    if not isinstance(payload, dict) or not isinstance(header, dict):
        raise jwt.InvalidTokenError("Malformed ID token.")
    validate_at_hash(payload, header, access_token)


def _require_token_string(token: Mapping[str, Any], field: str) -> str:
    value = token.get(field)
    if not isinstance(value, str) or not value:
        raise RuntimeError(f"OpenAI token response is missing a valid {field}.")
    return value


def _create_token_record(token: Mapping[str, Any]) -> TokenRecord:
    """Validate an OAuth token response and normalize it for local storage."""
    access_token = _require_token_string(token, "access_token")
    refresh_token = _require_token_string(token, "refresh_token")
    id_token = _require_token_string(token, "id_token")

    expires_in = token.get("expires_in")
    if (
        isinstance(expires_in, bool)
        or not isinstance(expires_in, (int, float))
        or not math.isfinite(expires_in)
        or expires_in <= 0
    ):
        raise RuntimeError("OpenAI token response did not include a valid expires_in.")

    validate_id_token(id_token, access_token)
    return {
        "access_token": access_token,
        "refresh_token": refresh_token,
        "id_token": id_token,
        "expires_at": time.time() + expires_in,
    }


def _auth_file_path() -> Path:
    return Path.home() / ".config" / "glassbox" / "auth.json"


def store_auth_token(token: TokenRecord) -> None:
    file_path = _auth_file_path()
    config_dir = file_path.parent
    config_dir.mkdir(parents=True, exist_ok=True)
    config_dir.chmod(0o700)

    temp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=config_dir,
            prefix=".auth-",
            suffix=".tmp",
            delete=False,
        ) as temp_file:
            temp_path = Path(temp_file.name)
            temp_path.chmod(0o600)
            json.dump(token, temp_file)
            temp_file.write("\n")
            temp_file.flush()
            os.fsync(temp_file.fileno())

        os.replace(temp_path, file_path)
        temp_path = None
    finally:
        if temp_path is not None:
            temp_path.unlink(missing_ok=True)


def load_auth_token() -> TokenRecord | None:
    """Load a complete stored OAuth token bundle, if one exists."""
    file_path = _auth_file_path()
    try:
        data = json.loads(file_path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    except OSError as error:
        raise RuntimeError(f"Could not read stored OpenAI credentials: {error}") from error
    except json.JSONDecodeError as error:
        raise RuntimeError("Stored OpenAI credentials are not valid JSON.") from error

    if not isinstance(data, dict):
        raise TypeError("Stored OpenAI credentials must be a JSON object.")

    access_token = _require_token_string(data, "access_token")
    refresh_token = _require_token_string(data, "refresh_token")
    id_token = _require_token_string(data, "id_token")
    expires_at = data.get("expires_at")
    if (
        isinstance(expires_at, bool)
        or not isinstance(expires_at, (int, float))
        or not math.isfinite(expires_at)
    ):
        raise RuntimeError("Stored OpenAI credentials are missing a valid expires_at.")

    return {
        "access_token": access_token,
        "refresh_token": refresh_token,
        "id_token": id_token,
        "expires_at": float(expires_at),
    }


def generate_and_store_token() -> TokenRecord:
    """Log in, validate OpenAI's response, and securely store the token record."""
    token_record = _create_token_record(run_login())
    store_auth_token(token_record)
    print("Successfully authenticated with OpenAI!")
    return token_record


def _is_access_token_usable(expires_at: float) -> bool:
    return expires_at > time.time() + TOKEN_EXPIRY_SKEW_SECONDS


def refresh_and_store_token(credentials: TokenRecord) -> TokenRecord:
    """Exchange a stored refresh token and atomically persist the new record."""
    refresh_token = credentials["refresh_token"]
    if not isinstance(refresh_token, str):
        raise RefreshTokenError("Stored OpenAI refresh token is invalid.")

    try:
        token = dict(
            _create_oauth_session().refresh_token(
                TOKEN_URL,
                refresh_token=refresh_token,
            )
        )
        # OpenAI may keep the same refresh token rather than rotate it.
        if not token.get("refresh_token"):
            token["refresh_token"] = refresh_token
        token_record = _create_token_record(token)
    except (OAuth2Error, requests.RequestException, RuntimeError, ValueError, jwt.PyJWTError) as error:
        raise RefreshTokenError("OpenAI refresh-token exchange failed.") from error

    store_auth_token(token_record)
    return token_record


def fetch_credentials_for_request() -> TokenRecord:
    """Return usable credentials, refreshing or logging in when required."""
    credentials = load_auth_token()
    if credentials is None:
        return generate_and_store_token()

    expires_at = credentials["expires_at"]
    if isinstance(expires_at, float) and _is_access_token_usable(expires_at):
        return credentials

    try:
        return refresh_and_store_token(credentials)
    except RefreshTokenError:
        print("Stored OpenAI credentials could not be refreshed; please log in again.")
        return generate_and_store_token()

def main() -> None:
    fetch_credentials_for_request()
    print("OpenAI credentials are ready for a request.")


if __name__ == "__main__":
    main()
