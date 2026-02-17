"""
Cost estimation utilities for RAPTOR usage logging.

This is *not* a billing system. It provides a best-effort USD estimate from
logged token usage so we can enforce a safety budget during long builds.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class ModelPrice:
    # USD per 1M tokens
    input_per_1m: float
    output_per_1m: float


# Default prices (match the repo's k8s run cost report unless overridden).
# If you change these, keep them in sync with whatever you consider "truth"
# for budgeting.
DEFAULT_PRICES = {
    # Embeddings
    "text-embedding-3-large": ModelPrice(input_per_1m=0.13, output_per_1m=0.0),
    "text-embedding-3-small": ModelPrice(input_per_1m=0.02, output_per_1m=0.0),
    # Chat / reasoning models (placeholder defaults for budget guard)
    # NOTE: For gpt-5.2 this matches datasources/k8s/runs/full_20251225_093621/cost.txt
    "gpt-5.2": ModelPrice(input_per_1m=1.75, output_per_1m=14.0),
}


def estimate_cost_usd(
    *,
    model: str,
    prompt_tokens: int = 0,
    completion_tokens: int = 0,
    prices: Optional[dict[str, ModelPrice]] = None,
) -> float:
    """
    Estimate USD cost from token usage.

    Unknown models default to 0.0 (so we never *over*-estimate unexpectedly).
    If you want strictness, set RAPTOR_BUDGET_STRICT_MODELS=1 and handle upstream.
    """
    prices = prices or DEFAULT_PRICES
    mp = prices.get(str(model))
    if mp is None:
        return 0.0
    pt = max(0, int(prompt_tokens or 0))
    ct = max(0, int(completion_tokens or 0))
    return (pt / 1_000_000.0) * float(mp.input_per_1m) + (ct / 1_000_000.0) * float(
        mp.output_per_1m
    )
