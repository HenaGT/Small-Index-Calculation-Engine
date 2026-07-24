"""
Automated tests for the ESX Index Engine.
Run with: python -m pytest tests/ -v   (or: python tests/test_engine.py)
"""

import os
import sys
from datetime import date

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from esx_index_engine import ESXIndexEngine, Constituent, CorporateAction
from esx_index_engine.capping import apply_cap

TOL = 1e-6


def make_constituents():
    return [
        Constituent("A", "Alpha Corp", 100.0, 1_000_000, 0.20),  # FFMC 20,000,000
        Constituent("B", "Beta Corp", 50.0, 2_000_000, 0.30),   # FFMC 30,000,000
        Constituent("C", "Gamma Corp", 20.0, 5_000_000, 0.10),  # FFMC 10,000,000
        Constituent("D", "Delta Corp", 10.0, 1_000_000, 0.50),  # FFMC 5,000,000
    ]


# ----------------------------------------------------------------------
# Capping algorithm
# ----------------------------------------------------------------------

def test_apply_cap_sums_to_one():
    raw = {"A": 0.5, "B": 0.3, "C": 0.15, "D": 0.05}
    capped = apply_cap(raw, 0.30)
    assert abs(sum(capped.values()) - 1.0) < TOL


def test_apply_cap_no_one_exceeds_cap():
    raw = {"A": 0.5, "B": 0.3, "C": 0.15, "D": 0.05}
    capped = apply_cap(raw, 0.30)
    assert all(w <= 0.30 + TOL for w in capped.values())


def test_apply_cap_no_change_when_under_cap():
    raw = {"A": 0.25, "B": 0.25, "C": 0.25, "D": 0.25}
    capped = apply_cap(raw, 0.30)
    for t in raw:
        assert abs(capped[t] - raw[t]) < TOL


def test_apply_cap_cascading_redistribution():
    # 4 constituents, 28% cap (feasible: 4 * 0.28 = 1.12 >= 1). Capping A's
    # 55% and redistributing its 27% excess proportionally to B/C/D pushes
    # B (30% -> 48%) over the cap too, forcing a second redistribution pass.
    raw = {"A": 0.55, "B": 0.30, "C": 0.10, "D": 0.05}
    capped = apply_cap(raw, 0.28)
    assert all(w <= 0.28 + TOL for w in capped.values())
    assert abs(sum(capped.values()) - 1.0) < TOL


def test_apply_cap_degenerate_equal_split():
    # cap * n < 1 -> everyone forced to equal weight
    raw = {"A": 0.7, "B": 0.1, "C": 0.1, "D": 0.1}
    capped = apply_cap(raw, 0.20)  # 0.20 * 4 = 0.80 < 1.0
    for w in capped.values():
        assert abs(w - 0.25) < TOL


# ----------------------------------------------------------------------
# Base setup & capping applied at base
# ----------------------------------------------------------------------

def test_set_base_applies_cap():
    engine = ESXIndexEngine(cap_pct=0.30)
    engine.set_base(make_constituents(), base_date=date(2026, 1, 1), base_value=1000.0)
    weights = engine.history[0].weights
    # Total FFMC = 65,000,000; B's raw weight = 30/65 = 46.2% > 30% cap
    assert weights["B"] <= 0.30 + TOL
    assert abs(sum(weights.values()) - 1.0) < TOL


def test_index_opens_at_base_value():
    engine = ESXIndexEngine(cap_pct=0.30)
    engine.set_base(make_constituents(), base_date=date(2026, 1, 1), base_value=1000.0)
    assert abs(engine.history[0].index_value - 1000.0) < TOL


# ----------------------------------------------------------------------
# Corporate action continuity: index value must not jump for
# non-performance reasons.
# ----------------------------------------------------------------------

def _fresh_engine():
    engine = ESXIndexEngine(cap_pct=0.30)
    engine.set_base(make_constituents(), base_date=date(2026, 1, 1), base_value=1000.0)
    return engine


def test_split_preserves_index_value_exactly():
    engine = _fresh_engine()
    before = engine._current_index_value()
    engine.process_corporate_action(
        CorporateAction("A", "split", date(2026, 1, 2), {"ratio": 2})
    )
    after = engine._current_index_value()
    assert abs(before - after) < TOL


def test_rights_issue_preserves_index_value():
    engine = _fresh_engine()
    before = engine._current_index_value()
    engine.process_corporate_action(
        CorporateAction("C", "rights_issue", date(2026, 1, 2), {"subscription_ratio": 0.2})
    )
    after = engine._current_index_value()
    assert abs(before - after) < TOL


def test_free_float_update_preserves_index_value():
    engine = _fresh_engine()
    before = engine._current_index_value()
    engine.process_corporate_action(
        CorporateAction("D", "free_float_update", date(2026, 1, 2), {"new_free_float_pct": 0.75})
    )
    after = engine._current_index_value()
    assert abs(before - after) < TOL


def test_addition_preserves_index_value():
    engine = _fresh_engine()
    before = engine._current_index_value()
    new_c = Constituent("E", "Epsilon Corp", 30.0, 500_000, 0.40)
    engine.process_corporate_action(
        CorporateAction("E", "addition", date(2026, 1, 2), {"constituent": new_c})
    )
    after = engine._current_index_value()
    assert abs(before - after) < TOL
    assert "E" in engine.constituents


def test_deletion_preserves_index_value():
    engine = _fresh_engine()
    before = engine._current_index_value()
    engine.process_corporate_action(
        CorporateAction("D", "deletion", date(2026, 1, 2), {})
    )
    after = engine._current_index_value()
    assert abs(before - after) < TOL
    assert "D" not in engine.constituents


def test_merger_preserves_index_value_and_updates_acquirer():
    engine = _fresh_engine()
    before = engine._current_index_value()
    engine.process_corporate_action(
        CorporateAction(
            "D", "merger", date(2026, 1, 2),
            {"acquirer_ticker": "C", "new_shares_for_acquirer": 6_000_000},
        )
    )
    after = engine._current_index_value()
    assert abs(before - after) < TOL
    assert "D" not in engine.constituents
    assert engine.constituents["C"].shares_outstanding == 6_000_000


def test_cash_dividend_no_change():
    engine = _fresh_engine()
    before = engine._current_index_value()
    engine.process_corporate_action(
        CorporateAction("A", "cash_dividend", date(2026, 1, 2), {"amount_per_share": 2.5})
    )
    after = engine._current_index_value()
    assert abs(before - after) < TOL


# ----------------------------------------------------------------------
# Backtest & export smoke tests
# ----------------------------------------------------------------------

def test_backtest_runs_and_reweights_on_rebalance_dates():
    engine = _fresh_engine()
    prices = {
        date(2026, 1, 2): {"A": 101.0, "B": 49.0, "C": 20.5, "D": 9.8},
        date(2026, 1, 3): {"A": 103.0, "B": 48.0, "C": 21.0, "D": 9.5},
    }
    records = engine.backtest(prices, rebalance_dates={date(2026, 1, 3)})
    assert len(records) == 2
    assert records[-1].calc_date == date(2026, 1, 3)


def test_export_csv_and_json(tmp_path=None):
    import tempfile
    engine = _fresh_engine()
    engine.calculate(date(2026, 1, 2))
    with tempfile.TemporaryDirectory() as d:
        csv_path = os.path.join(d, "out.csv")
        json_path = os.path.join(d, "out.json")
        engine.export_csv(csv_path)
        engine.export_json(json_path)
        assert os.path.getsize(csv_path) > 0
        assert os.path.getsize(json_path) > 0


if __name__ == "__main__":
    tests = [obj for name, obj in list(globals().items()) if name.startswith("test_")]
    passed, failed = 0, 0
    for t in tests:
        try:
            t()
            print(f"PASS  {t.__name__}")
            passed += 1
        except AssertionError as e:
            print(f"FAIL  {t.__name__}: {e}")
            failed += 1
    print(f"\n{passed} passed, {failed} failed")
    sys.exit(1 if failed else 0)
