import asyncio
import secrets
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Callable
from urllib.parse import parse_qs, urlparse

import questionary
from authlib.integrations.requests_client import OAuth2Session

import jwt
import base64

from pathlib import Path
import requests

import hmac
import json
import math
import os
import tempfile
import time
AUTHORIZATION_URL = "https://auth.openai.com/oauth/authorize"
TOKEN_URL = "https://auth.openai.com/oauth/token"
CLIENT_ID = "app_EMoamEEZ73f0CkXaXp7hrann"
REDIRECT_URI = "http://localhost:1455/auth/callback"
SCOPES = "openid profile email offline_access"



def is_callback_url(value: str | None, state: str) -> bool:
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
        and parsed.hostname in {"localhost", "127.0.0.1"}
        and port == 1455
        and parsed.path == "/auth/callback"
        and query.get("state") == [state]
        and ("code" in query or "error" in query)
    )


def run_callback_server(
    stop_event: threading.Event,
    on_callback_received: Callable[[str], None],
    state: str
) -> None:
    class CallbackHandler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            parsed = urlparse(self.path)

            if parsed.path != "/auth/callback":
                self.send_error(404)
                return

            callback_url = f"{REDIRECT_URI}?{parsed.query}"

            body = b"""
            <html>
                <body>
                    <h2>Login complete!</h2>
                    <p>You can close this window and return to GlassBox.</p>
                </body>
            </html>
            """

            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

            if is_callback_url(callback_url,state):
                stop_event.set()
                on_callback_received(callback_url)

        def log_message(self, format: str, *args: object) -> None:
            pass

    try:
        with HTTPServer(("127.0.0.1", 1455), CallbackHandler) as server:
            # Wake up periodically so the thread can notice stop_event.
            server.timeout = 0.25
            while not stop_event.is_set():
                server.handle_request()
    except OSError as error:
        print(f"Local callback listener unavailable: {error}")


def start_callback_server(
    stop_event: threading.Event,
    on_callback_received: Callable[[str], None],
    state
) -> threading.Thread:
    server_thread = threading.Thread(
        target=run_callback_server,
        args=(stop_event, on_callback_received,state),
        daemon=True,
    )
    server_thread.start()
    return server_thread


def stop_callback_server(
    stop_event: threading.Event,
    server_thread: threading.Thread,
) -> None:
    stop_event.set()
    server_thread.join(timeout=0.5)


def set_future_result(
    future: asyncio.Future[str],
    callback_url: str,
) -> None:
    if not future.done():
        future.set_result(callback_url)


async def prompt_for_callback() -> str | None:
    return await questionary.password(
        "Or paste the complete callback URL here:\n",
        qmark="🔗",
    ).ask_async()


async def get_callback_url(authorization_url: str, state:str ) -> str:
    print("\nOpen the link below in your browser and log in with OpenAI:\n")
    print(f"{authorization_url}\n")

    server_stop_event = threading.Event()
    loop = asyncio.get_running_loop()
    # empty future, nothing is in here yet
    browser_callback: asyncio.Future[str] = loop.create_future()

    # The server thread calls this function. It schedules the actual Future
    # update on the main asyncio thread.
    def send_callback_to_main_thread(callback_url: str) -> None:
        loop.call_soon_threadsafe(
            set_future_result, # set_future_result
            browser_callback, # browser_callback
            callback_url, # browser_callback
        )

    server_thread = start_callback_server(
        server_stop_event,
        send_callback_to_main_thread,
        state
    )
    pasted_callback = asyncio.create_task(prompt_for_callback())

    # The browser callback and the pasted callback race. The first valid one wins.
    while True:
        done, _ = await asyncio.wait(
            {browser_callback, pasted_callback},
            return_when=asyncio.FIRST_COMPLETED,
        )

        if browser_callback in done:
            pasted_callback.cancel()
            await asyncio.gather(pasted_callback, return_exceptions=True)
            stop_callback_server(server_stop_event, server_thread)
            return browser_callback.result()

        if pasted_callback in done:
            pasted_url = pasted_callback.result()
            if pasted_url is None:
                stop_callback_server(server_stop_event, server_thread)
                raise RuntimeError("Login cancelled before a callback URL was received.")
            if is_callback_url(pasted_url,state):
                stop_callback_server(server_stop_event, server_thread)
                return pasted_url.strip()

            print("That is not a valid callback URL. Please paste the complete URL.")
            pasted_callback = asyncio.create_task(prompt_for_callback())

def run_login() -> dict:
    oauth = OAuth2Session(
        client_id=CLIENT_ID,
        redirect_uri=REDIRECT_URI,
        scope=SCOPES,
        token_endpoint_auth_method="none",
        code_challenge_method="S256",
        )

    # Authlib sends an S256 hash of this value in the authorization request.
    code_verifier = secrets.token_urlsafe(64)

    # the PKCE code_challenge is just sha over our code_verifier and done by authlib while creating the url as per our code_challenge method
    # state is generated and sent alongside as a param by our client initially
    authorization_url, state = oauth.create_authorization_url(
        AUTHORIZATION_URL,
        code_verifier=code_verifier,
        id_token_add_organizations="true",
        codex_cli_simplified_flow="true",
        prompt="login",
        originator="glassbox",
        )

    # this URL contains authorisation code, state
    validated_url = asyncio.run(get_callback_url(authorization_url,state))

    # the fetch_token will return us the access_token, refresh_token, id_token: openID JWT, expiry_info, etc
    # openAI will issue us a token basis the state we recieve
    return oauth.fetch_token(
        TOKEN_URL,
        authorization_response=validated_url,
        state=state,
        code_verifier=code_verifier,
    )

def fetch_oidc_config(oidc_config_url,oidc_issuer) -> dict:
    response = requests.get(oidc_config_url, timeout=10)
    response.raise_for_status()

    config = response.json()

    if config.get("issuer") != oidc_issuer:
        raise ValueError("Unexpected OIDC issuer.")
    return config


def validate_at_hash(
    payload: dict,
    header: dict,
    access_token: str,
) -> bool:
    algorithm = jwt.get_algorithm_by_name(header["alg"])

    # hashing always done over bytes and this sha will always produce 32 bytes
    digest = algorithm.compute_hash_digest(
        access_token.encode("ascii")
    )

    # only grab the left half and encode in URL safe
    calculated_at_hash = (
        base64.urlsafe_b64encode(digest[: len(digest) // 2])
        .rstrip(b"=")
        .decode("ascii")
    )

    token_at_hash = payload.get("at_hash",None)

    if not isinstance(token_at_hash, str):
        raise jwt.InvalidTokenError("ID token is missing at_hash")

    if not hmac.compare_digest(calculated_at_hash, token_at_hash):
        raise jwt.InvalidTokenError("Invalid at_hash")

    else:
        return True

def validate_id_token(id_token: str, access_token) -> bool:

    AUTHORIZATION_URL = "https://auth.openai.com/oauth/authorize"
    TOKEN_URL = "https://auth.openai.com/oauth/token"
    CLIENT_ID = "app_EMoamEEZ73f0CkXaXp7hrann"
    REDIRECT_URI = "http://localhost:1455/auth/callback"
    SCOPES = "openid profile email offline_access"
    OIDC_ISSUER = "https://auth.openai.com"

    OIDC_CONFIG_URL = f"{OIDC_ISSUER}/.well-known/openid-configuration"

    oidc_config = fetch_oidc_config(OIDC_CONFIG_URL,OIDC_ISSUER)

    jwks_client = jwt.PyJWKClient(oidc_config["jwks_uri"])
    signing_key = jwks_client.get_signing_key_from_jwt(id_token)

    data = jwt.decode_complete(
        id_token,
        key=signing_key,
        audience=CLIENT_ID,
        algorithms=["RS256"],
        issuer=OIDC_ISSUER,
        options={
            "require": ["exp", "iat", "iss", "aud", "sub"],
        }
        )
    payload, header = data["payload"], data["header"]

    if validate_at_hash(payload,header,access_token) and payload["exp"] > time.time():
        return True


def _auth_file_path() -> Path:
    return Path.home() / ".config" / "glassbox" / "auth.json"


def store_auth_token(token: dict) -> None:
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


def load_auth_token() -> dict[str, object] | None:
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
        raise RuntimeError("Stored OpenAI credentials must be a JSON object.")

    for field in ("access_token", "refresh_token", "id_token"):
        if not isinstance(data.get(field), str) or not data[field]:
            raise RuntimeError(f"Stored OpenAI credentials are missing a valid {field}.")

    expires_at = data.get("expires_at")
    if (
        isinstance(expires_at, bool)
        or not isinstance(expires_at, (int, float))
        or not math.isfinite(expires_at)
    ):
        raise RuntimeError("Stored OpenAI credentials are missing a valid expires_at.")

    return data


def main() -> dict[str] | None:
    token = run_login()
    id_token = token.get("id_token")
    access_token = token.get("access_token")
    expires_in = token.get("expires_in")
    received_at = time.time()
    if not isinstance(expires_in, (int, float)):
        raise TypeError("OpenAI token response did not include a numeric expires_in.")
    expires_at = received_at + expires_in
    refresh_token = token.get("refresh_token")

    if id_token and validate_id_token(id_token,access_token):
            tokens_dict= {"access_token":access_token,
            "refresh_token":refresh_token,
            "id_token":id_token,
            "expires_at":expires_at,
            }
            store_auth_token(tokens_dict)
            print("Successfully authenticated with OpenAI!")

if __name__ == "__main__":
    main()
