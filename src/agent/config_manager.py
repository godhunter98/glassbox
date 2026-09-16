"""Interactive loading and saving of provider configuration."""

import os
import sys
from pathlib import Path
from typing import Literal


from dotenv import load_dotenv

from agent.authenticator import AuthenticationSession, Authenticator
from agent.providers.providers import PROVIDER_LABELS, SUPPORTED_MODELS


class ConfigManager:
    """Create authenticated provider sessions from saved or interactive settings."""

    def __init__(self, env_path: Path | None = None) -> None:
        self.env_path = env_path or Path.cwd() / ".env"
        self.auth_method = ""

    def get_session(self) -> AuthenticationSession | None:
        """Load a saved configuration, prompting only when it is incomplete."""
        load_dotenv()
        provider, self.auth_method, model, api_key, api_base = self._load_values()

        if provider and model and self.auth_method == "oauth":
               return self._authenticate(provider, model, None, "oauth")

        if provider and model and api_key:
            return AuthenticationSession(provider, model, "api_key", api_key)

        if provider and model and self.auth_method == "oauth":
            return AuthenticationSession(provider, model, "oauth", None)

        if not sys.stdin.isatty():
            print("Missing API configuration. Create a .env file or run GlassBox interactively to configure it.")
            return None

        return self._configure(provider, model, api_key, api_base)

    def configure(self) -> AuthenticationSession | None:
        """Interactively choose a provider, credential, and model."""
        if not sys.stdin.isatty():
            print("Configuration requires an interactive terminal.")
            return None

        return self._configure("", "", "", "")

    def _configure(
        self,
        provider: str,
        model: str,
        api_key: str | None,
        api_base: str,
    ) -> AuthenticationSession | None:
        print("GlassBox configuration\n")
        import questionary
        if not provider:
            provider = questionary.select(
                "Select a provider:",
                choices=[
                    questionary.Choice(title=label, value=provider_id)
                    for provider_id, label in PROVIDER_LABELS.items()
                ],
                qmark="🤖",
            ).ask()
            if not self.auth_method:
                if provider == "openai":
                    choices = [" 1. Use an API key", " 2. Use a ChatGPT Plus/Pro account (Codex)"]
                    selected_method = questionary.select(
                        "How would you like to authenticate?",
                        choices=choices,
                        qmark="\n🔐",
                    ).ask()
                    self.auth_method = "oauth" if selected_method == choices[1] else "api_key"
                else:
                    self.auth_method = "api_key"

        if not api_key and self.auth_method!= "oauth" :
            api_key = (questionary.password(f"{provider} API key:", qmark="🔑").ask() or "").strip()
            if not api_key:
                print("API key is required to start GlassBox.")
                return None

        if not model:
            models = Authenticator(provider, self.auth_method).fetch_models(api_key if self.auth_method == "api_key" else None)
            if isinstance(models, str):
                print(models)
                return None

            model = questionary.select(
                "Select a model:",
                choices=models,
                qmark="🤖",
            ).ask()
            if model is None:
                return None

            save_model = questionary.confirm(
                f"Use {model} as the default model?",
                default=True,
            ).ask()
            if save_model is None:
                return None
        else:
            save_model = True

        if not api_base:
            api_base = input("API base URL (optional): ").strip()

        values = {"PROVIDER": provider, "API_KEY": api_key if self.auth_method == "api_key" else "", "AUTH_METHOD": self.auth_method}
        if save_model:
            values["MODEL"] = model
        if api_base:
            values["API_BASE"] = api_base

        save_config = input("Save this configuration to .env? [Y/n]: ").strip().lower()
        if save_config in ("", "y", "yes"):
            self._save_values(values, remove_model=not save_model)
            print("Configuration saved.")
        else:
            print("Using configuration for this session only.")

        os.environ.update(values)
        if not save_model:
            os.environ.pop("MODEL", None)

        return self._authenticate(provider, model, api_key, self.auth_method)

    def _load_values(self) -> tuple[str, str, str, str, str]:
        return (
            os.getenv("PROVIDER", "").strip().lower(),
            os.getenv("AUTH_METHOD", "").strip().lower(),
            os.getenv("MODEL", "").strip(),
            os.getenv("API_KEY", "").strip(),
            os.getenv("API_BASE", "").strip(),
        )

    def _authenticate(self, provider: str, model: str, api_key: str | None, auth_method: Literal["oauth", "api_key"]) -> AuthenticationSession | None:
            result = Authenticator(provider, auth_method).authenticate(model, api_key, )
            if isinstance(result, AuthenticationSession):
                return result

            if isinstance(result, str):
                print(result)
            return None


    def _save_values(self, values: dict[str, str], *, remove_model: bool) -> None:
        existing_lines = self.env_path.read_text(encoding="utf-8").splitlines() if self.env_path.exists() else []
        updated_lines: list[str] = []
        seen_keys: set[str] = set()

        for line in existing_lines:
            stripped = line.strip()
            key = stripped.split("=", 1)[0] if "=" in stripped and not stripped.startswith("#") else None
            if key == "MODEL" and remove_model:
                continue
            if key in values:
                updated_lines.append(f"{key}={self._quote(values[key])}")
                seen_keys.add(key)
            else:
                updated_lines.append(line)

        for key, value in values.items():
            if key not in seen_keys:
                updated_lines.append(f"{key}={self._quote(value)}")

        self.env_path.write_text("\n".join(updated_lines) + "\n", encoding="utf-8")

    @staticmethod
    def _quote(value: str) -> str:
        return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'
