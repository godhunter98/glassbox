from dataclasses import dataclass
from typing import Literal, Optional
from agent.providers.providers import SUPPORTED_PROVIDERS, SUPPORTED_MODELS

@dataclass
class AuthenticationSession:
    provider: str
    model: str
    auth_method: str
    api_key: Optional[str]

class Authenticator:
    """Handle authentication for supported LLM providers."""

    def __init__(self, provider: str, auth_method: Literal["oauth", "api_key"]) -> None:
        self.provider = provider.strip().casefold()
        self.auth_method = auth_method
        self.MODEL_LIST_URLS = {"deepseek": "https://api.deepseek.com/models",
                                "openrouter": "https://openrouter.ai/api/v1/models",}

    def fetch_models(self, api_key: str | None) -> list[str] | str:
        """Return model identifiers available from the authenticated provider."""
        if self.auth_method.strip().lower() == "api_key" and api_key is not None:
            endpoint = self.MODEL_LIST_URLS.get(self.provider.lower())
            if endpoint is None:
                return f"Model discovery is not supported for provider '{self.provider}'."

            try:
                import requests
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

        else:
            models = SUPPORTED_MODELS.get(self.provider)
            if models is None:
                return f"Model discovery is not supported for provider '{self.provider}'."
            return models

    def authenticate(
        self,
        model: str | None = None,
        api_key: str | None = None,
    ) -> AuthenticationSession | str | None:
        if self.auth_method.strip().lower() == "api_key":
            if not model or not api_key:
                return "Authentication failed: MODEL and API_KEY are required."
            from litellm import litellm
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

        if self.auth_method.strip().lower() == "oauth":
            if self.provider not in SUPPORTED_PROVIDERS:
                return f"Provider '{self.provider}' is not supported."
            if not model:
                return "Authentication failed: MODEL is required."
            if model not in SUPPORTED_MODELS.get(self.provider.casefold(), []):
                return f"Model '{model}' is not supported for provider '{self.provider}'."
            if self.provider != "openai":
                return f"OAuth authentication is not supported for provider '{self.provider}'."

            try:
                from agent.providers.openai_codex.codex_auth import fetch_credentials_for_request

                # This loads valid stored credentials, refreshes them when needed,
                # or starts the browser login flow when no credentials exist.
                fetch_credentials_for_request()
            except Exception as error:
                return f"OAuth authentication failed: {error}"

            return AuthenticationSession(self.provider, model, self.auth_method, api_key=None)

        return f"Authentication method '{self.auth_method}' is not supported."
