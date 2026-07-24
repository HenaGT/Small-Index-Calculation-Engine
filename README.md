# ESX Index Engine

A production-grade Python engine for calculating, maintaining, and
backtesting a free-float market-capitalization-weighted equity index,
built to the ESX Index Methodology.

```
Index Value = Σ (Price_i × Shares_i × FreeFloat%_i × CapFactor_i) / Divisor
```

## Features

| # | Capability | Module |
|---|---|---|
| 1 | Daily index-level calculation from latest market data | `engine.py :: calculate()` |
| 2 | Automatic weight computation from free-float market cap | `engine.py :: _raw_weights()` |
| 3 | Corporate action processing (splits, rights issues, mergers, delistings, dividends) | `engine.py :: process_corporate_action()` |
| 4 | Free-float adjustment | `models.py :: Constituent.free_float_market_cap` |
| 5 | Divisor management for index continuity | `engine.py :: rebalance()` |
| 6 | Single-constituent capping with proportional redistribution | `capping.py :: apply_cap()` |
| 7 | Historical backtesting | `engine.py :: backtest()` |
| 8 | CSV / JSON export | `engine.py :: export_csv() / export_json()` |

## Design decisions worth knowing about

**Capping factors, not daily re-capping.** Real free-float indices (S&P,
FTSE, EGX 30) don't recompute the cap every tick — that would make the
index re-weight itself on every price move. Instead, a "capping factor"
per constituent is fixed at each rebalance / corporate-action event, and
only prices move between events. This means a constituent's *effective*
weight can drift slightly above the cap between rebalances — that's
realistic, not a bug, and is restored at the next scheduled rebalance.

**Divisor continuity.** Any change that isn't a pure price move (index
additions/deletions, free-float updates, rights issues, mergers) would
otherwise make the index level jump for a reason that has nothing to do
with performance. The engine neutralizes this by resetting the divisor
so the index value is unchanged at the instant of the event:

```
Divisor_new = CappedTotalFFMC_new / IndexValue_immediately_before_event
```

Stock splits and cash dividends (for a price-return index) require **no**
divisor change — a split leaves price × shares unchanged, and dividends
don't structurally alter the constituent's shares or price.

**A subtle correctness trap avoided:** if you mutate a constituent's
shares/free-float *before* asking "what was the index worth right
before this change", you'll capture a value that already includes the
change — silently breaking continuity. `process_corporate_action()`
snapshots the index value first, then mutates, then calls `rebalance()`
with that snapshot passed explicitly as `reference_value`.

## Quick start

```python
from datetime import date
from esx_index_engine import ESXIndexEngine, Constituent, CorporateAction

engine = ESXIndexEngine(name="ESX Flagship Index", cap_pct=0.15)

constituents = [
    Constituent("ETEL", "Ethio Telecom", 845.00, 120_000_000, 0.15, "Telecom"),
    Constituent("CBE",  "Commercial Bank of Ethiopia", 610.50, 85_000_000, 0.18, "Banking"),
    # ...
]

engine.set_base(constituents, base_date=date(2026, 1, 5), base_value=1000.0)

# Daily calculation
record = engine.calculate(date(2026, 1, 6), market_data={"ETEL": 861.00})
print(record.index_value, record.weights)

# Corporate action
engine.process_corporate_action(CorporateAction(
    ticker="ETEL", action_type="split",
    effective_date=date(2026, 1, 7), details={"ratio": 2},
))

# Export
engine.export_csv("output/esx_history.csv")
engine.export_json("output/esx_history.json")
```

See `examples/run_example.py` for a full walkthrough including a
60-day synthetic backtest, and `tests/test_engine.py` for correctness
tests (capping, continuity across every corporate action type).

## Running the example / tests

```bash
python examples/run_example.py
python tests/test_engine.py
```

## Project layout

```
esx_index_engine/
    __init__.py        Public API
    models.py           Constituent, CorporateAction, DailyRecord
    capping.py          apply_cap() - iterative proportional redistribution
    engine.py           ESXIndexEngine - the calculation engine itself
    exceptions.py       Typed exceptions
examples/
    run_example.py      End-to-end demonstration
sample_data/
    constituents.csv    Illustrative starter constituents
tests/
    test_engine.py      16 correctness tests
```

## Extending for production use

- **Live market data**: replace the `market_data` dict passed into
  `calculate()` with a feed adapter (exchange API, FIX, or a scheduled
  CSV drop) that produces the same `{ticker: price}` shape.
- **Persistence**: `DailyRecord.to_dict()` is already JSON-serializable;
  point it at a database instead of / in addition to file export.
- **Governance workflow**: the methodology document referenced for this
  engine requires Index Committee approval for base date/value and cap
  percentage changes — wire `set_base()` / `cap_pct` changes to your
  approval workflow rather than calling them ad hoc.
- **Total-return variant**: to build a total-return index, extend
  `cash_dividend` handling to reinvest the dividend by adjusting the
  divisor, instead of the current no-op (correct for a price-return
  index).
