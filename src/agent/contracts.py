from dataclasses import dataclass
from typing import Any

@dataclass
class CompletionMetrics:
    '''Represents the metrics for a completion request.'''
    input_tokens: int
    output_tokens: int
    total_tokens: int
    ttft_seconds: float
    duration_seconds: float
    approx_cost: float | None = None
    cached_tokens: int | None = None
    reasoning_tokens: int | None = None

@dataclass
class CompletionResult:
    response: Any
    metrics: CompletionMetrics | None
    error: Exception | None = None
