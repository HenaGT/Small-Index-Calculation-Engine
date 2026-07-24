"""
Single-constituent weight capping.

Implements the iterative proportional redistribution method used by
frontier-market benchmarks such as the EGX 30 (and recommended in the
ESX Index Methodology, Section: "Capping Rules to Manage Concentration
Risk"): any constituent whose free-float weight exceeds the cap is set
to exactly the cap, and the excess is redistributed proportionally
across the remaining (uncapped) constituents. Because redistribution
can itself push another constituent over the cap, the process repeats
until every weight is at or below the cap (or, in the degenerate case
where cap * N < 1, until all constituents sit at the cap).
"""

from __future__ import annotations

from .exceptions import InvalidCapError


def apply_cap(raw_weights: dict, cap_pct: float, tolerance: float = 1e-9) -> dict:
    """Apply a single-constituent weight cap with proportional redistribution.

    Args:
        raw_weights: mapping of ticker -> uncapped weight (decimals summing to ~1.0).
        cap_pct: maximum allowed weight for any single constituent, as a decimal
                 (e.g. 0.15 for a 15% cap).
        tolerance: numerical convergence tolerance.

    Returns:
        mapping of ticker -> capped weight (decimals summing to ~1.0).
    """
    if not (0 < cap_pct <= 1.0):
        raise InvalidCapError(f"cap_pct must be a decimal in (0, 1], got {cap_pct}")

    if not raw_weights:
        return {}

    weights = dict(raw_weights)
    n = len(weights)

    # Degenerate case: even an equal split would breach the cap.
    if cap_pct * n < 1.0 - tolerance:
        equal = 1.0 / n
        return {t: equal for t in weights}

    locked = set()  # tickers permanently fixed at the cap

    for _ in range(len(weights) + 1):  # guaranteed to converge within N passes
        over = {t: w for t, w in weights.items() if t not in locked and w > cap_pct + tolerance}
        if not over:
            break

        excess = sum(w - cap_pct for w in over.values())
        for t in over:
            weights[t] = cap_pct
            locked.add(t)

        free_tickers = [t for t in weights if t not in locked]
        free_total = sum(weights[t] for t in free_tickers)
        if free_total <= tolerance:
            # Everything is capped; any remaining excess can't be placed anywhere.
            break

        for t in free_tickers:
            share_of_excess = (weights[t] / free_total) * excess
            weights[t] += share_of_excess

    # Normalize to correct floating point drift so weights sum to exactly 1.0.
    total = sum(weights.values())
    if total > 0:
        weights = {t: w / total for t, w in weights.items()}

    return weights
