"""Canonical provider identifiers and their display labels/model catalog."""

import json
from pathlib import Path


PROVIDER_LABELS = {
    "deepseek": "DeepSeek",
    "openrouter": "OpenRouter",
    "openai": "OpenAI",
}
SUPPORTED_PROVIDERS = tuple(PROVIDER_LABELS)

with (Path(__file__).parent / "provider_models.json").open(encoding="utf-8") as file:
    SUPPORTED_MODELS: dict[str, list[str]] = json.load(file)
