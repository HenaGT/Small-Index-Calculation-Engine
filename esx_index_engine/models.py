"""Data models used throughout the ESX Index Engine."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Optional


@dataclass
class Constituent:
    """A single index constituent.

    Attributes:
        ticker: Exchange ticker / symbol, e.g. "DASH".
        name: Full issuer name, e.g. "Dashen Bank S.C.".
        price: Latest traded price (ETB).
        shares_outstanding: Total issued ordinary shares.
        free_float_pct: Free-float factor as a decimal (0.15 = 15%).
        sector: Sector classification (used for reporting/limits, optional).
        adtv: Average daily traded value, used for liquidity screening (optional).
        is_active: Whether this constituent currently sits in the index.
    """

    ticker: str
    name: str
    price: float
    shares_outstanding: float
    free_float_pct: float
    sector: str = "Unclassified"
    adtv: Optional[float] = None
    is_active: bool = True

    def __post_init__(self) -> None:
        if self.price < 0:
            raise ValueError(f"{self.ticker}: price cannot be negative")
        if self.shares_outstanding < 0:
            raise ValueError(f"{self.ticker}: shares_outstanding cannot be negative")
        if not (0.0 <= self.free_float_pct <= 1.0):
            raise ValueError(
                f"{self.ticker}: free_float_pct must be a decimal between 0 and 1 "
                f"(got {self.free_float_pct})"
            )

    @property
    def free_float_market_cap(self) -> float:
        """Free-Float Market Capitalization = Price * Shares * Free-Float %."""
        return self.price * self.shares_outstanding * self.free_float_pct

    @property
    def full_market_cap(self) -> float:
        return self.price * self.shares_outstanding


@dataclass
class CorporateAction:
    """A corporate action event to be processed against the index.

    action_type: one of "split", "rights_issue", "merger", "delisting",
                 "addition", "deletion", "cash_dividend", "free_float_update"
    """

    ticker: str
    action_type: str
    effective_date: date
    details: dict = field(default_factory=dict)
    notes: str = ""


@dataclass
class DailyRecord:
    """A single day's calculated index snapshot, retained for history/export."""

    calc_date: date
    index_value: float
    divisor: float
    total_free_float_market_cap: float
    weights: dict  # ticker -> capped weight (decimal)
    raw_weights: dict  # ticker -> pre-cap weight (decimal)
    prices: dict  # ticker -> price used
    constituents_count: int
    events: list = field(default_factory=list)  # human-readable log entries for the day

    def to_dict(self) -> dict:
        return {
            "date": self.calc_date.isoformat(),
            "index_value": round(self.index_value, 4),
            "divisor": self.divisor,
            "total_free_float_market_cap": round(self.total_free_float_market_cap, 2),
            "constituents_count": self.constituents_count,
            "weights": {k: round(v, 6) for k, v in self.weights.items()},
            "raw_weights": {k: round(v, 6) for k, v in self.raw_weights.items()},
            "prices": {k: round(v, 4) for k, v in self.prices.items()},
            "events": self.events,
        }
