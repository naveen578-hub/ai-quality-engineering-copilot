"""
Approximate, illustrative per-token pricing for cost estimation in the
usage dashboard. These are NOT guaranteed to be current — LLM provider
pricing changes over time — and are meant to give a directionally useful
cost signal for a demo/portfolio tool, not a billing-accurate figure.
Override via env vars for a real deployment, or just treat the numbers as
"relative cost", not "exact dollars."

Rates are USD per 1,000 tokens.
"""
from __future__ import annotations

import os
from typing import Optional

# (input $/1K tokens, output $/1K tokens) — output is None for embedding models
_DEFAULT_PRICING = {
    "gpt-4o-mini": (0.00015, 0.0006),
    "gpt-4o": (0.0025, 0.01),
    "text-embedding-3-small": (0.00002, None),
    "text-embedding-3-large": (0.00013, None),
}


def _rate_from_env(model: str, direction: str) -> Optional[float]:
    env_key = f"QE_COPILOT_PRICE_{model.upper().replace('-', '_')}_{direction.upper()}"
    value = os.getenv(env_key)
    return float(value) if value else None


def estimate_cost(model: Optional[str], prompt_tokens: int, completion_tokens: int) -> float:
    if not model:
        return 0.0

    default_in, default_out = _DEFAULT_PRICING.get(model, (None, None))
    input_rate = _rate_from_env(model, "input") or default_in
    output_rate = _rate_from_env(model, "output") or default_out

    if input_rate is None:
        return 0.0  # unknown model — don't fabricate a cost figure

    cost = (prompt_tokens / 1000) * input_rate
    if output_rate and completion_tokens:
        cost += (completion_tokens / 1000) * output_rate
    return round(cost, 6)
