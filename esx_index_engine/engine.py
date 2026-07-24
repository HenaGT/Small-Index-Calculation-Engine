"""
ESXIndexEngine
==============

Implements the ESX Index Methodology:

    Index Value = Sum(Price_i * Shares_i * FreeFloat%_i * CapFactor_i) / Divisor

Design notes
------------
Rather than re-deriving a hard cap every single day (which would make the
index re-weight itself on every tick, contradicting the "cap enforced at
rebalance" principle in the methodology document), this engine follows
standard frontier-market practice:

    * A "capping factor" per constituent is fixed at each scheduled
      rebalance (or corporate-action event) so that capped weight =
      raw weight * capping factor at that moment.
    * Between rebalances, capping factors stay fixed and only prices
      move -- exactly like real free-float indices (S&P, FTSE, EGX 30).
      This means a constituent's *effective* weight can drift slightly
      above the cap between rebalances; the cap is restored at the
      next rebalance. This is intentional and realistic.
    * The divisor is adjusted at every event that is *not* a pure price
      move (rebalances, additions/deletions, free-float changes, rights
      issues, mergers) so the index level never jumps for a
      non-performance reason. Stock splits require no divisor
      adjustment because price * shares is unchanged.
"""

from __future__ import annotations

import csv
import json
from datetime import date
from typing import Dict, Iterable, List, Optional, Sequence

from .capping import apply_cap
from .exceptions import (
    ConstituentNotFoundError,
    InvalidCorporateActionError,
    NotInitializedError,
)
from .models import Constituent, CorporateAction, DailyRecord


class ESXIndexEngine:
    def __init__(self, name: str = "ESX Index", cap_pct: float = 0.15):
        self.name = name
        self.cap_pct = cap_pct

        self.constituents: Dict[str, Constituent] = {}
        self.capping_factors: Dict[str, float] = {}

        self.divisor: Optional[float] = None
        self.base_date: Optional[date] = None
        self.base_value: Optional[float] = None

        self.history: List[DailyRecord] = []
        self.action_log: List[dict] = []

    # ------------------------------------------------------------------
    # Setup
    # ------------------------------------------------------------------
    def set_base(
        self,
        constituents: Sequence[Constituent],
        base_date: date,
        base_value: float = 1000.0,
    ) -> float:
        """Establish the base date, base value, and initial divisor.

        The divisor is solved so that the (cap-adjusted) index opens at
        exactly `base_value` on `base_date`.
        """
        self.constituents = {c.ticker: c for c in constituents}
        self.base_date = base_date
        self.base_value = base_value

        raw_weights = self._raw_weights()
        capped_weights = apply_cap(raw_weights, self.cap_pct)
        self.capping_factors = self._factors_from_weights(raw_weights, capped_weights)

        capped_total = self._capped_total_ffmc()
        self.divisor = capped_total / base_value

        record = self._build_record(base_date, raw_weights, capped_weights)
        record.events.append(
            f"Base established: {len(self.constituents)} constituents, "
            f"base value {base_value:,.2f}, divisor {self.divisor:,.6f}"
        )
        self.history.append(record)
        return self.divisor

    # ------------------------------------------------------------------
    # Daily calculation
    # ------------------------------------------------------------------
    def calculate(
        self,
        calc_date: date,
        market_data: Optional[Dict[str, float]] = None,
    ) -> DailyRecord:
        """Calculate the index for a given date.

        Args:
            calc_date: the trading date being calculated.
            market_data: optional {ticker: latest_price} updates to apply
                         before calculating (i.e. today's closing prices).
        """
        self._require_initialized()

        if market_data:
            for ticker, price in market_data.items():
                self._require_ticker(ticker)
                self.constituents[ticker].price = price

        raw_weights = self._raw_weights()
        capped_weights = self._effective_weights()

        record = self._build_record(calc_date, raw_weights, capped_weights)
        self.history.append(record)
        return record

    # ------------------------------------------------------------------
    # Rebalancing (scheduled or event-driven)
    # ------------------------------------------------------------------
    def rebalance(
        self,
        effective_date: date,
        new_constituents: Optional[Sequence[Constituent]] = None,
        reason: str = "Scheduled rebalance",
        reference_value: Optional[float] = None,
    ) -> DailyRecord:
        """Recompute weights and capping factors, preserving index continuity.

        If `new_constituents` is provided, it fully replaces the current
        constituent set (additions, deletions, and free-float / share
        updates should all be reflected in it). The divisor is adjusted
        so the index value is unchanged at the moment of the rebalance.

        Args:
            reference_value: the index value to hold constant through this
                event. Defaults to the value computed from the CURRENT
                (not-yet-replaced) constituent set. Callers that mutate a
                constituent in place before invoking rebalance (corporate
                actions) MUST capture the value beforehand and pass it here
                -- otherwise the "before" snapshot would already include
                the very change being neutralized.
        """
        self._require_initialized()

        current_value = (
            reference_value if reference_value is not None else self._current_index_value()
        )

        if new_constituents is not None:
            self.constituents = {c.ticker: c for c in new_constituents}

        raw_weights = self._raw_weights()
        capped_weights = apply_cap(raw_weights, self.cap_pct)
        self.capping_factors = self._factors_from_weights(raw_weights, capped_weights)

        new_capped_total = self._capped_total_ffmc()
        self.divisor = new_capped_total / current_value if current_value else self.divisor

        record = self._build_record(effective_date, raw_weights, capped_weights)
        record.events.append(
            f"{reason}: divisor reset to {self.divisor:,.6f} "
            f"({len(self.constituents)} constituents), index continuity preserved "
            f"at {current_value:,.4f}"
        )
        self.history.append(record)
        self.action_log.append(
            {"date": effective_date.isoformat(), "type": "rebalance", "reason": reason}
        )
        return record

    # ------------------------------------------------------------------
    # Corporate actions
    # ------------------------------------------------------------------
    def process_corporate_action(self, action: CorporateAction) -> DailyRecord:
        """Apply a corporate action and return the resulting daily record.

        Supported action_type values:
            split            details: {"ratio": float}          e.g. 2-for-1 -> ratio=2
            rights_issue      details: {"subscription_ratio": float}
            free_float_update details: {"new_free_float_pct": float}
            addition          details: {"constituent": Constituent}
            deletion          details: {}
            delisting         details: {}
            merger            details: {"acquirer_ticker": str, "new_shares_for_acquirer": float}
            cash_dividend     details: {"amount_per_share": float}   (logged only; no
                              divisor change for a price-return index)
        """
        self._require_initialized()
        t = action.ticker
        kind = action.action_type

        if kind != "addition":
            self._require_ticker(t)

        # Snapshot the index value BEFORE any in-place mutation below, so
        # structural events (rights issues, free-float changes, additions,
        # deletions, mergers) can be neutralized against the true "before"
        # state rather than a state that already reflects the change.
        value_before = self._current_index_value()

        log_note = ""

        if kind == "split":
            ratio = self._require_detail(action, "ratio")
            c = self.constituents[t]
            c.shares_outstanding *= ratio
            c.price /= ratio
            log_note = f"{t}: {ratio}-for-1 split applied (no divisor change)."
            record = self.calculate(action.effective_date)
            record.events.append(log_note)
            self.action_log.append(self._log_entry(action, log_note))
            return record

        if kind == "cash_dividend":
            amount = self._require_detail(action, "amount_per_share")
            log_note = (
                f"{t}: cash dividend of {amount:,.4f}/share noted "
                f"(no adjustment - price-return index)."
            )
            record = self.calculate(action.effective_date)
            record.events.append(log_note)
            self.action_log.append(self._log_entry(action, log_note))
            return record

        if kind == "rights_issue":
            ratio = self._require_detail(action, "subscription_ratio")
            c = self.constituents[t]
            new_shares = c.shares_outstanding * ratio
            c.shares_outstanding += new_shares
            log_note = (
                f"{t}: rights issue at 1-for-{1/ratio:.2f} added "
                f"{new_shares:,.0f} shares; divisor adjusted for continuity."
            )

        elif kind == "free_float_update":
            new_ff = self._require_detail(action, "new_free_float_pct")
            c = self.constituents[t]
            old_ff = c.free_float_pct
            c.free_float_pct = new_ff
            log_note = (
                f"{t}: free-float updated {old_ff:.2%} -> {new_ff:.2%}; "
                f"divisor adjusted for continuity."
            )

        elif kind == "addition":
            new_c = action.details.get("constituent")
            if new_c is None:
                raise InvalidCorporateActionError("addition requires details['constituent']")
            self.constituents[new_c.ticker] = new_c
            log_note = f"{new_c.ticker}: added to index; divisor adjusted for continuity."

        elif kind in ("deletion", "delisting"):
            del self.constituents[t]
            log_note = f"{t}: removed from index ({kind}); divisor adjusted for continuity."

        elif kind == "merger":
            acquirer = self._require_detail(action, "acquirer_ticker")
            new_shares = action.details.get("new_shares_for_acquirer")
            del self.constituents[t]
            if acquirer in self.constituents and new_shares is not None:
                self.constituents[acquirer].shares_outstanding = new_shares
            log_note = (
                f"{t}: removed following merger into {acquirer}; "
                f"divisor adjusted for continuity."
            )

        else:
            raise InvalidCorporateActionError(f"Unknown action_type: {kind}")

        record = self.rebalance(
            action.effective_date,
            new_constituents=list(self.constituents.values()),
            reason=f"Corporate action ({kind})",
            reference_value=value_before,
        )
        record.events.append(log_note)
        self.action_log.append(self._log_entry(action, log_note))
        return record

    # ------------------------------------------------------------------
    # Backtesting
    # ------------------------------------------------------------------
    def backtest(
        self,
        price_history: Dict[date, Dict[str, float]],
        rebalance_dates: Optional[Iterable[date]] = None,
    ) -> List[DailyRecord]:
        """Replay a historical price series through the engine.

        Args:
            price_history: {date: {ticker: price}}, sorted internally by date.
            rebalance_dates: dates on which to re-run the capping/rebalance
                             logic (e.g. quarterly review dates). The
                             constituent list itself is not changed here --
                             only weights/capping factors are recalculated
                             against that day's prices.

        Returns:
            The list of DailyRecord snapshots produced, in date order.
        """
        self._require_initialized()
        rebalance_dates = set(rebalance_dates or [])
        results = []

        for d in sorted(price_history.keys()):
            prices = price_history[d]
            for ticker, price in prices.items():
                if ticker in self.constituents:
                    self.constituents[ticker].price = price

            if d in rebalance_dates:
                results.append(self.rebalance(d, reason="Scheduled backtest rebalance"))
            else:
                results.append(self.calculate(d))

        return results

    # ------------------------------------------------------------------
    # Export
    # ------------------------------------------------------------------
    def export_json(self, path: str) -> None:
        payload = {
            "index_name": self.name,
            "base_date": self.base_date.isoformat() if self.base_date else None,
            "base_value": self.base_value,
            "cap_pct": self.cap_pct,
            "divisor": self.divisor,
            "history": [r.to_dict() for r in self.history],
            "action_log": self.action_log,
        }
        with open(path, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2)

    def export_csv(self, path: str) -> None:
        if not self.history:
            raise NotInitializedError("No history to export yet.")

        tickers = sorted({t for r in self.history for t in r.weights})
        fieldnames = (
            ["date", "index_value", "divisor", "total_ffmc", "constituents_count"]
            + [f"weight_{t}" for t in tickers]
            + [f"price_{t}" for t in tickers]
        )

        with open(path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            for r in self.history:
                row = {
                    "date": r.calc_date.isoformat(),
                    "index_value": round(r.index_value, 4),
                    "divisor": r.divisor,
                    "total_ffmc": round(r.total_free_float_market_cap, 2),
                    "constituents_count": r.constituents_count,
                }
                for t in tickers:
                    row[f"weight_{t}"] = round(r.weights.get(t, 0.0), 6)
                    row[f"price_{t}"] = round(r.prices.get(t, 0.0), 4)
                writer.writerow(row)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------
    def _require_initialized(self) -> None:
        if self.divisor is None:
            raise NotInitializedError(
                "Call set_base(...) before calculating the index."
            )

    def _require_ticker(self, ticker: str) -> None:
        if ticker not in self.constituents:
            raise ConstituentNotFoundError(f"'{ticker}' is not a current constituent.")

    @staticmethod
    def _require_detail(action: CorporateAction, key: str):
        if key not in action.details:
            raise InvalidCorporateActionError(
                f"{action.action_type} action for {action.ticker} requires "
                f"details['{key}']"
            )
        return action.details[key]

    @staticmethod
    def _log_entry(action: CorporateAction, note: str) -> dict:
        return {
            "date": action.effective_date.isoformat(),
            "ticker": action.ticker,
            "type": action.action_type,
            "note": note,
        }

    def _active(self) -> List[Constituent]:
        return [c for c in self.constituents.values() if c.is_active]

    def _raw_weights(self) -> Dict[str, float]:
        active = self._active()
        total = sum(c.free_float_market_cap for c in active)
        if total <= 0:
            return {c.ticker: 0.0 for c in active}
        return {c.ticker: c.free_float_market_cap / total for c in active}

    @staticmethod
    def _factors_from_weights(raw: Dict[str, float], capped: Dict[str, float]) -> Dict[str, float]:
        factors = {}
        for t, rw in raw.items():
            cw = capped.get(t, rw)
            factors[t] = (cw / rw) if rw > 0 else 1.0
        return factors

    def _capped_total_ffmc(self) -> float:
        total = 0.0
        for c in self._active():
            factor = self.capping_factors.get(c.ticker, 1.0)
            total += c.free_float_market_cap * factor
        return total

    def _current_index_value(self) -> float:
        if self.divisor is None:
            return 0.0
        return self._capped_total_ffmc() / self.divisor

    def _effective_weights(self) -> Dict[str, float]:
        total = self._capped_total_ffmc()
        if total <= 0:
            return {c.ticker: 0.0 for c in self._active()}
        weights = {}
        for c in self._active():
            factor = self.capping_factors.get(c.ticker, 1.0)
            weights[c.ticker] = (c.free_float_market_cap * factor) / total
        return weights

    def _build_record(
        self,
        calc_date: date,
        raw_weights: Dict[str, float],
        capped_weights: Dict[str, float],
    ) -> DailyRecord:
        capped_total = self._capped_total_ffmc()
        index_value = capped_total / self.divisor if self.divisor else 0.0
        active = self._active()
        return DailyRecord(
            calc_date=calc_date,
            index_value=index_value,
            divisor=self.divisor,
            total_free_float_market_cap=capped_total,
            weights=capped_weights,
            raw_weights=raw_weights,
            prices={c.ticker: c.price for c in active},
            constituents_count=len(active),
        )
