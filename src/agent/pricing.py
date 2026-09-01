"""DeepSeek V4 pricing, vision-token estimation, and concurrency limits.

Rates are expressed in USD per million tokens.  DeepSeek's peak window is in
UTC and applies only on weekdays.
"""

from __future__ import annotations

import base64
import struct
from datetime import datetime, timezone
from math import ceil
from typing import Any, Iterable

PEAK_HOURS_UTC = frozenset((1, 2, 3, 6, 7, 8, 9))

# Off-peak prices from the V4 pricing table.  Peak prices are exactly 2x.
OFF_PEAK_RATES = {
    "deepseek-v4-flash": {"cache_hit": 0.007, "cache_miss": 0.22, "output": 0.66},
    "deepseek-v4-pro": {"cache_hit": 0.022, "cache_miss": 0.66, "output": 1.98},
    "deepseek-v4-flash-vision-exp": {"cache_hit": 0.007, "cache_miss": 0.22, "output": 0.66},
}

CONCURRENCY_LIMITS = {
    "deepseek-v4-flash": 2500,
    "deepseek-v4-flash-vision-exp": 2500,
    "deepseek-v4-pro": 500,
}


def normalize_model(model: str) -> str:
    """Normalize LiteLLM names such as ``deepseek/deepseek-v4-flash``."""
    return model.rsplit("/", 1)[-1].lower()

def is_peak_time(at: datetime | None = None) -> bool:
    """Return whether *at* falls in a weekday peak hour (UTC)."""
    at = at or datetime.now(timezone.utc)
    if at.tzinfo is None:
        at = at.replace(tzinfo=timezone.utc)
    at = at.astimezone(timezone.utc)
    return at.weekday() < 5 and at.hour in PEAK_HOURS_UTC

def rates_for(model: str, at: datetime | None = None) -> dict[str, float]:
    model_name = normalize_model(model)
    try:
        rates = OFF_PEAK_RATES[model_name].copy()
    except KeyError as exc:
        raise ValueError(f"Unsupported DeepSeek pricing model: {model}") from exc
    if is_peak_time(at):
        rates = {kind: rate * 2 for kind, rate in rates.items()}
    return rates

def calculate_cost(
    model: str,
    *,
    input_tokens: int | None = 0,
    output_tokens: int = 0,
    cache_hit_tokens: int = 0,
    cache_miss_tokens: int | None = None,
    at: datetime | None = None,
) -> float:
    """Calculate USD cost from token counts using the UTC peak schedule."""
    if cache_miss_tokens is None:
        cache_miss_tokens = max(0, input_tokens - cache_hit_tokens)
    rates = rates_for(model, at)
    # we can break down inputs tokens into 2 categories - cache_hit or cache_miss
    return (
        cache_hit_tokens * rates["cache_hit"]
        + cache_miss_tokens * rates["cache_miss"]
        + output_tokens * rates["output"]
    ) / 1_000_000

def concurrency_limit(model: str) -> int:
    """Return the account-level concurrent-request limit for a model."""
    try:
        return CONCURRENCY_LIMITS[normalize_model(model)]
    except KeyError as exc:
        raise ValueError(f"Unsupported DeepSeek concurrency model: {model}") from exc

def _dimensions(part: Mapping[str, Any]) -> tuple[int, int] | None:
    """Read dimensions supplied by a harness payload, if present."""
    candidates = (part, part.get("image_url", {}) if isinstance(part.get("image_url"), Mapping) else {})
    for item in candidates:
        width, height = item.get("width"), item.get("height")
        if isinstance(width, int) and isinstance(height, int) and width > 0 and height > 0:
            return width, height

    # OpenAI-format inline ima!ges commonly carry no explicit dimensions. The
    # dimensions can still be read without decoding the full image.
    image_url = part.get("image_url")
    url = image_url.get("url") if isinstance(image_url, Mapping) else None
    if isinstance(url, str) and url.startswith("data:") and "," in url:
        try:
            raw = base64.b64decode(url.split(",", 1)[1], validate=True)
            if raw.startswith(b"\x89PNG\r\n\x1a\n") and len(raw) >= 24:
                return struct.unpack(">II", raw[16:24])
            if raw.startswith((b"GIF87a", b"GIF89a")) and len(raw) >= 10:
                return struct.unpack("<HH", raw[6:10])
            if raw.startswith(b"RIFF") and raw[8:12] == b"WEBP" and raw[12:16] == b"VP8X" and len(raw) >= 30:
                return (1 + int.from_bytes(raw[24:27], "little"), 1 + int.from_bytes(raw[27:30], "little"))
            if raw.startswith(b"\xff\xd8"):
                index = 2
                while index + 9 < len(raw):
                    if raw[index] != 0xFF:
                        index += 1
                        continue
                    marker = raw[index + 1]
                    index += 2
                    if marker in {0xD8, 0xD9}:
                        continue
                    size = int.from_bytes(raw[index:index + 2], "big")
                    if marker in range(0xC0, 0xC4) or marker in range(0xC5, 0xC8) or marker in range(0xC9, 0xCC) or marker in range(0xCD, 0xD0):
                        return (int.from_bytes(raw[index + 5:index + 7], "big"), int.from_bytes(raw[index + 3:index + 5], "big"))
                    index += size
        except (ValueError, IndexError, struct.error):
            pass
    return None

def image_tokens(width: int, height: int) -> int:
    """Estimate DeepSeek vision input tokens for one image.

    DeepSeek scales images by aspect ratio to an area between 384x384 and
    800x800, then charges at most 384 tokens per image.  The area conversion
    is the documented calculator rule, rounded up to a whole token.
    """
    if width <= 0 or height <= 0:
        raise ValueError("image dimensions must be positive")
    area = width * height
    area = max(384 * 384, min(area, 800 * 800))
    return max(1, min(384, ceil(area * 384 / (800 * 800))))

def image_tokens_in_messages(messages: Iterable[Mapping[str, Any]]) -> int:
    """Sum image tokens for dimensions carried in multimodal message parts."""
    total = 0
    for message in messages:
        content = message.get("content")
        if not isinstance(content, list):
            continue
        for part in content:
            if not isinstance(part, Mapping) or part.get("type") not in {"image", "image_url"}:
                continue
            dimensions = _dimensions(part)
            if dimensions:
                total += image_tokens(*dimensions)
    return total
