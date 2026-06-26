#!/usr/bin/env python3
# encoding: UTF-8
"""Examples for loading ZigZag positive-N / reverse-N signal files.

Run signal generation first:

    make zigzag-signals

This example shows two common ways to use the generated files:

1. Load `zigzag_n_daily_index.json` for fast date -> stock-list filtering.
2. Load `zigzag_n_events.csv` when you need a tabular event history.
"""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd


SIGNAL_DIR = Path("outputs/zigzag_signals_all")
DAILY_INDEX_FILE = SIGNAL_DIR / "zigzag_n_daily_index.json"
EVENTS_FILE = SIGNAL_DIR / "zigzag_n_events.csv"


def load_daily_index(path: Path = DAILY_INDEX_FILE) -> dict[str, dict[str, list[str]]]:
    """Load the strategy-friendly daily index.

    Return shape:

        {
          "2026-04-29": {
            "positive_n": ["SH600000", "SZ000001"],
            "reverse_n": ["SH600519"]
          }
        }

    `positive_n` is suitable as a stock inclusion list.
    `reverse_n` is suitable as an exclusion or sell list.
    """
    payload = json.loads(path.read_text(encoding="utf-8"))
    return payload["signals"]


def get_positive_n_symbols(trade_date: str, path: Path = DAILY_INDEX_FILE) -> list[str]:
    """Return stocks that have a fresh positive-N signal on `trade_date`."""
    signals_by_date = load_daily_index(path)
    return signals_by_date.get(trade_date, {}).get("positive_n", [])


def filter_candidates_by_positive_n(candidates: list[str], trade_date: str) -> list[str]:
    """Example: only keep candidates that are positive-N stocks on a date."""
    positive_n = set(get_positive_n_symbols(trade_date))
    return [symbol for symbol in candidates if symbol.upper() in positive_n]


def load_event_table(path: Path = EVENTS_FILE) -> pd.DataFrame:
    """Load the compact event table.

    Important fields:

    - `date`: trading day of the fresh signal.
    - `symbol`: stock code, uppercase qlib style such as `SH600000`.
    - `signal`: `1` for positive N, `-1` for reverse N.
    - `signal_name`: `positive_n` or `reverse_n`.
    - `lookback_start` / `lookback_end`: the OHLC window used by the signal.
    """
    return pd.read_csv(path, dtype={"symbol": str})


if __name__ == "__main__":
    trade_date = "2026-04-29"
    candidates = ["SH600000", "SH600519", "SZ000001", "SZ300750"]

    print("Positive-N symbols:", get_positive_n_symbols(trade_date)[:20])
    print("Filtered candidates:", filter_candidates_by_positive_n(candidates, trade_date))

    events = load_event_table()
    positive_events = events[(events["date"] == trade_date) & (events["signal"] == 1)]
    print(positive_events[["date", "symbol", "signal_name", "close"]].head(20).to_string(index=False))
