import asyncio
import secrets
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Callable
from urllib.parse import parse_qs, urlparse

import questionary
from authlib.integrations.requests_client import OAuth2Session

AUTHORIZATION_URL = "https://auth.openai.com/oauth/authorize"
TOKEN_URL = "https://auth.openai.com/oauth/token"
CLIENT_ID = "app_EMoamEEZ73f0CkXaXp7hrann"
REDIRECT_URI = "http://localhost:1455/auth/callback"
SCOPES = "openid profile email offline_access"

oauth = OAuth2Session(
    client_id=CLIENT_ID,
    redirect_uri=REDIRECT_URI,
    scope=SCOPES,
    token_endpoint_auth_method="none",
    code_challenge_method="S256",
)

# Authlib sends an S256 hash of this value in the authorization request.
code_verifier = secrets.token_urlsafe(64)


authorization_url, state = oauth.create_authorization_url(
    AUTHORIZATION_URL,
    code_verifier=code_verifier,
    id_token_add_organizations="true",
    codex_cli_simplified_flow="true",
    prompt="login",
    originator="glassbox",
)

def is_callback_url(value: str | None) -> bool:
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

            if is_callback_url(callback_url):
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
) -> threading.Thread:
    server_thread = threading.Thread(
        target=run_callback_server,
        args=(stop_event, on_callback_received),
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


async def get_callback_url() -> str:
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
            if is_callback_url(pasted_url):
                stop_callback_server(server_stop_event, server_thread)
                return pasted_url.strip()

            print("That is not a valid callback URL. Please paste the complete URL.")
            pasted_callback = asyncio.create_task(prompt_for_callback())


def run_login() -> dict:
    # this URL contains authorisation code, openID, etc
    validated_url = asyncio.run(get_callback_url())
    
    # the fetch_toekn will contain the access_token, refresh_token, id_token: openID JWT, expiry_info, etc
    return oauth.fetch_token(
        TOKEN_URL,
        authorization_response=validated_url,
        state=state,
        code_verifier=code_verifier,
    )


def main() -> None:
    token = run_login()
    print(token)


if __name__ == "__main__":
    main()
