from dataclasses import dataclass
from typing import Literal
from litellm import litellm
import requests


@dataclass
class AuthenticationSession:
    provider: str
    model: str
    auth_method: str
    api_key: str

class Authenticator:
    """Handle authentication for supported LLM providers."""

    def __init__(self, provider: str, auth_method: Literal["Oauth", "api_key"]) -> None:
        self.provider = provider
        self.auth_method = auth_method
        self.MODEL_LIST_URLS = {"deepseek": "https://api.deepseek.com/models",
                                "openrouter": "https://openrouter.ai/api/v1/models"}

    def fetch_models(self, api_key: str) -> list[str] | str:
        """Return model identifiers available from the authenticated provider."""
        endpoint = self.MODEL_LIST_URLS.get(self.provider.lower())
        if endpoint is None:
            return f"Model discovery is not supported for provider '{self.provider}'."

        try:
            response = requests.get(
                endpoint,
                headers={"Authorization": f"Bearer {api_key}"},
                timeout=15,
            )
            response.raise_for_status()
            payload = response.json()
        except requests.HTTPError as error:
            status_code = error.response.status_code if error.response is not None else None
            if status_code in (401, 403):
                return "Authentication failed: the API key was rejected."
            return f"Could not fetch models: provider returned HTTP {status_code}."
        except requests.RequestException as error:
            return f"Could not fetch models: network error ({error})."
        except ValueError as error:
            return f"Could not fetch models: {error}."

        model_ids = [item["id"] for item in payload.get("data", []) if item.get("id")]
        if not model_ids:
            return "No models were returned for this API key."

        prefix = self.provider.lower()
        return [f"{prefix}/{model_id}" for model_id in model_ids]

    def authenticate(
        self,
        model: str | None = None,
        api_key: str | None = None,
        login_token: str | None = None,
    ) -> AuthenticationSession | str | None:
        if self.auth_method.strip().lower() == "api_key":
            if not model or not api_key:
                return "Authentication failed: MODEL and API_KEY are required."

            kwargs = {
                "model": model,
                "api_key": api_key,
                "messages": [{"role": "user", "content": "Reply with OK."}],
                "max_tokens": 5,
                "temperature": 0.1,
                "extra_body": {"thinking": {"type": "disabled"}},
            }
            try:
                litellm.completion(**kwargs)
            except litellm.AuthenticationError:
                return "Authentication failed: the API key was rejected."
            except litellm.RateLimitError:
                return "Credential validation could not complete: the provider rate-limited the request."
            except Exception as error:
                return f"Credential validation failed: {error}"

            return AuthenticationSession(self.provider, model, self.auth_method, api_key)

        elif self.auth_method.strip().lower() == "oauth":
            pass
