"""
End-to-end demonstration of the ESX Index Engine.

Run with:  python examples/run_example.py
"""

import csv
import os
import random
from datetime import date, timedelta

import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from esx_index_engine import ESXIndexEngine, Constituent, CorporateAction


def load_constituents(csv_path):
    constituents = []
    with open(csv_path, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            constituents.append(
                Constituent(
                    ticker=row["ticker"],
                    name=row["name"],
                    price=float(row["price"]),
                    shares_outstanding=float(row["shares_outstanding"]),
                    free_float_pct=float(row["free_float_pct"]),
                    sector=row["sector"],
                )
            )
    return constituents


def main():
    data_path = os.path.join(os.path.dirname(__file__), "..", "sample_data", "constituents.csv")
    constituents = load_constituents(data_path)

    engine = ESXIndexEngine(name="ESX Flagship Index", cap_pct=0.15)

    base_date = date(2026, 1, 5)
    divisor = engine.set_base(constituents, base_date=base_date, base_value=1000.0)
    print(f"Base established on {base_date}: divisor = {divisor:,.6f}")
    print(f"Base weights (capped): {engine.history[0].weights}\n")

    # --- Day 2: ordinary price move ---------------------------------
    d2 = base_date + timedelta(days=1)
    record = engine.calculate(d2, market_data={"ETEL": 861.00, "CBE": 605.00})
    print(f"{d2}: index = {record.index_value:,.4f}  weights = "
          f"{ {k: round(v, 4) for k, v in record.weights.items()} }")

    # --- Corporate action: ETEL 2-for-1 stock split -------------------
    split_date = base_date + timedelta(days=2)
    action = CorporateAction(
        ticker="ETEL",
        action_type="split",
        effective_date=split_date,
        details={"ratio": 2},
    )
    record = engine.process_corporate_action(action)
    print(f"\n{split_date}: after 2-for-1 ETEL split -> index = {record.index_value:,.4f}")
    print(f"Events: {record.events}")

    # --- Corporate action: rights issue at BOA ------------------------
    rights_date = base_date + timedelta(days=3)
    action = CorporateAction(
        ticker="BOA",
        action_type="rights_issue",
        effective_date=rights_date,
        details={"subscription_ratio": 0.10},  # 1 new share per 10 held
    )
    record = engine.process_corporate_action(action)
    print(f"\n{rights_date}: after BOA rights issue -> index = {record.index_value:,.4f}")
    print(f"Events: {record.events}")

    # --- Simple synthetic historical backtest -------------------------
    print("\nRunning a 60-day synthetic backtest...")
    random.seed(42)
    price_history = {}
    tickers = list(engine.constituents.keys())
    last_prices = {t: engine.constituents[t].price for t in tickers}
    start = rights_date + timedelta(days=1)
    for i in range(60):
        d = start + timedelta(days=i)
        day_prices = {}
        for t in tickers:
            drift = random.gauss(0.0003, 0.012)
            last_prices[t] = max(0.01, last_prices[t] * (1 + drift))
            day_prices[t] = round(last_prices[t], 2)
        price_history[d] = day_prices

    quarterly_rebalance = {start + timedelta(days=30)}
    backtest_records = engine.backtest(price_history, rebalance_dates=quarterly_rebalance)

    print(f"Backtest complete: {len(backtest_records)} trading days simulated.")
    print(f"Start index value: {backtest_records[0].index_value:,.4f}")
    print(f"End index value:   {backtest_records[-1].index_value:,.4f}")

    # --- Export ---------------------------------------------------------
    out_dir = os.path.join(os.path.dirname(__file__), "..", "output")
    os.makedirs(out_dir, exist_ok=True)
    engine.export_csv(os.path.join(out_dir, "esx_index_history.csv"))
    engine.export_json(os.path.join(out_dir, "esx_index_history.json"))
    print(f"\nExported daily history to {out_dir}/esx_index_history.csv and .json")


if __name__ == "__main__":
    main()
