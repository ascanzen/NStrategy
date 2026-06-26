#!/usr/bin/env python3
# encoding: UTF-8
"""Generate daily ZigZag N-pattern signals for a qlib stock universe.

The output is designed as a reusable signal library for other strategies:

- `events.csv`: compact event table. It only contains dates where a stock has
  a fresh positive-N or reverse-N signal.
- `daily_lists.csv`: one row per trading day with pipe-separated symbol lists.
- `daily_index.json`: strategy-friendly date index with positive/reverse lists.
- `summary.json`: run metadata and signal counts.

Signal convention:

- `signal = 1`, `signal_name = positive_n`: positive N pattern. A long-only
  strategy can use this as an inclusion/keep-holding filter.
- `signal = -1`, `signal_name = reverse_n`: reverse N pattern. A long-only
  strategy can use this as an exclusion/sell filter.
- No row means no fresh N-pattern signal for that stock on that date.
"""

from __future__ import annotations

import argparse
import csv
import json
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

from backtest_zigzag_csi300 import (
    PEAK,
    VALLEY,
    compiled_peak_valley_pivots,
    n_pattern_signal,
    peak_valley_pivots,
    read_calendar,
    read_feature,
    read_memberships,
)


@dataclass(frozen=True)
class SignalConfig:
    qlib_dir: Path
    instruments: Path
    output_dir: Path
    start: pd.Timestamp | None
    end: pd.Timestamp | None
    years: int | None
    window: int
    threshold: float
    exclude_indexes: bool


def is_index_symbol(symbol: str) -> bool:
    """Return True for common A-share index symbols, not ordinary stocks."""
    symbol = symbol.lower()
    return symbol.startswith("sh000") or symbol.startswith("sz399")


def resolve_date_range(
    calendar: pd.DatetimeIndex, start: pd.Timestamp | None, end: pd.Timestamp | None, years: int | None
) -> tuple[int, int]:
    data_end = calendar[-1]
    selected_end = min(end or data_end, data_end)
    selected_start = start
    if selected_start is None:
        if years is None:
            selected_start = calendar[0]
        else:
            selected_start = selected_end - pd.DateOffset(years=years)

    start_idx = int(calendar.searchsorted(selected_start, side="left"))
    end_idx = int(calendar.searchsorted(selected_end, side="right") - 1)
    if start_idx >= end_idx:
        raise ValueError("Signal date range is empty")
    return start_idx, end_idx


def rolling_window_valid_mask(low: np.ndarray, high: np.ndarray, window: int) -> np.ndarray:
    """Mark dates where the trailing `window` bars are usable for signal calculation."""
    valid = np.isfinite(low) & np.isfinite(high) & (low > 0) & (high > 0)
    counts = np.concatenate([[0], np.cumsum(valid.astype(np.int32))])
    out = np.zeros(len(valid), dtype=bool)
    if len(valid) >= window:
        trailing_counts = counts[window:] - counts[:-window]
        out[window - 1 :] = trailing_counts == window
    return out


def signal_with_details(low_window: np.ndarray, high_window: np.ndarray, threshold: float) -> tuple[int, int]:
    """Return `(signal, pivot_count)` for one trailing OHLC window.

    This follows the same N-pattern decision used by `strategyZigZag.py`:

    - The last pivot must be the last bar in the window.
    - Last pivot is PEAK and higher-high/higher-low structure means positive N.
    - Last pivot is VALLEY and lower-low/lower-high structure means reverse N.
    """
    pivot_func = compiled_peak_valley_pivots or peak_valley_pivots
    pivots = pivot_func(low_window, high_window, threshold, -threshold)
    pivot_idx = np.nonzero(pivots)[0]
    if len(pivot_idx) <= 3:
        return 0, int(len(pivot_idx))

    idx0, idx1, idx2, idx3 = pivot_idx[-4:]
    if idx3 != len(low_window) - 1:
        return 0, int(len(pivot_idx))

    if pivots[-1] == PEAK:
        if high_window[idx3] > high_window[idx1] and low_window[idx2] > low_window[idx0]:
            return 1, int(len(pivot_idx))
    elif pivots[-1] == VALLEY:
        if low_window[idx3] < low_window[idx1] and high_window[idx2] < high_window[idx0]:
            return -1, int(len(pivot_idx))
    return 0, int(len(pivot_idx))


def iter_symbol_intervals(
    memberships: pd.DataFrame, symbol: str, calendar: pd.DatetimeIndex, start_idx: int, end_idx: int
) -> list[tuple[int, int]]:
    """Convert instrument active date ranges to calendar index ranges."""
    rows = memberships[memberships["symbol"] == symbol]
    intervals: list[tuple[int, int]] = []
    for row in rows.itertuples(index=False):
        lo = max(int(calendar.searchsorted(row.start, side="left")), start_idx)
        hi = min(int(calendar.searchsorted(row.end, side="right") - 1), end_idx)
        if lo <= hi:
            intervals.append((lo, hi))
    return intervals


def collect_signals(config: SignalConfig) -> tuple[list[dict[str, object]], dict[str, dict[str, list[str]]], dict[str, object]]:
    calendar = read_calendar(config.qlib_dir)
    start_idx, end_idx = resolve_date_range(calendar, config.start, config.end, config.years)
    memberships = read_memberships(config.instruments)
    memberships = memberships[(memberships["end"] >= calendar[start_idx]) & (memberships["start"] <= calendar[end_idx])]
    if config.exclude_indexes:
        memberships = memberships[~memberships["symbol"].map(is_index_symbol)]

    symbols = sorted(memberships["symbol"].unique())
    daily_index: dict[str, dict[str, list[str]]] = {
        str(date.date()): {"positive_n": [], "reverse_n": []} for date in calendar[start_idx : end_idx + 1]
    }
    events: list[dict[str, object]] = []
    loaded_symbols = 0
    skipped_symbols = 0

    for position, symbol in enumerate(symbols, start=1):
        low = read_feature(config.qlib_dir, symbol, "low", len(calendar))
        high = read_feature(config.qlib_dir, symbol, "high", len(calendar))
        close = read_feature(config.qlib_dir, symbol, "close", len(calendar))
        if low is None or high is None or close is None:
            skipped_symbols += 1
            continue

        intervals = iter_symbol_intervals(memberships, symbol, calendar, start_idx, end_idx)
        if not intervals:
            skipped_symbols += 1
            continue

        valid_window = rolling_window_valid_mask(low, high, config.window)
        loaded_symbols += 1
        symbol_upper = symbol.upper()
        for lo, hi in intervals:
            signal_start = max(lo, config.window - 1)
            for idx in range(signal_start, hi + 1):
                if not valid_window[idx]:
                    continue
                low_window = low[idx - config.window + 1 : idx + 1]
                high_window = high[idx - config.window + 1 : idx + 1]
                signal, pivot_count = signal_with_details(low_window, high_window, config.threshold)
                if signal == 0:
                    continue

                date = str(calendar[idx].date())
                signal_name = "positive_n" if signal == 1 else "reverse_n"
                event = {
                    "date": date,
                    "symbol": symbol_upper,
                    "signal": signal,
                    "signal_name": signal_name,
                    "close": float(close[idx]) if np.isfinite(close[idx]) else "",
                    "low": float(low[idx]),
                    "high": float(high[idx]),
                    "pivot_count": pivot_count,
                    "window": config.window,
                    "threshold": config.threshold,
                    "lookback_start": str(calendar[idx - config.window + 1].date()),
                    "lookback_end": date,
                }
                events.append(event)
                daily_index[date][signal_name].append(symbol_upper)

        if position % 500 == 0:
            print(f"Processed {position}/{len(symbols)} symbols; events={len(events)}")

    for date_signals in daily_index.values():
        date_signals["positive_n"].sort()
        date_signals["reverse_n"].sort()

    summary = {
        "data_source": str(config.qlib_dir),
        "universe_file": str(config.instruments),
        "start": str(calendar[start_idx].date()),
        "end": str(calendar[end_idx].date()),
        "trading_days": int(end_idx - start_idx + 1),
        "symbols_in_universe": int(len(symbols)),
        "loaded_symbols": int(loaded_symbols),
        "skipped_symbols": int(skipped_symbols),
        "window": int(config.window),
        "threshold": float(config.threshold),
        "exclude_indexes": bool(config.exclude_indexes),
        "event_rows": int(len(events)),
        "positive_n_events": int(sum(1 for row in events if row["signal"] == 1)),
        "reverse_n_events": int(sum(1 for row in events if row["signal"] == -1)),
        "signal_convention": {
            "1": "positive_n: positive N pattern; can be used as an inclusion/keep-holding filter",
            "-1": "reverse_n: reverse N pattern; can be used as an exclusion/sell filter",
            "missing_row": "no fresh N-pattern signal for that symbol/date",
        },
    }
    return events, daily_index, summary


def write_outputs(
    output_dir: Path, events: list[dict[str, object]], daily_index: dict[str, dict[str, list[str]]], summary: dict[str, object]
) -> dict[str, str]:
    output_dir.mkdir(parents=True, exist_ok=True)
    events_path = output_dir / "zigzag_n_events.csv"
    daily_lists_path = output_dir / "zigzag_n_daily_lists.csv"
    daily_index_path = output_dir / "zigzag_n_daily_index.json"
    summary_path = output_dir / "zigzag_n_summary.json"

    fieldnames = [
        "date",
        "symbol",
        "signal",
        "signal_name",
        "close",
        "low",
        "high",
        "pivot_count",
        "window",
        "threshold",
        "lookback_start",
        "lookback_end",
    ]
    with events_path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(events)

    with daily_lists_path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=["date", "positive_n", "reverse_n", "positive_n_count", "reverse_n_count"])
        writer.writeheader()
        for date, signals in daily_index.items():
            writer.writerow(
                {
                    "date": date,
                    "positive_n": "|".join(signals["positive_n"]),
                    "reverse_n": "|".join(signals["reverse_n"]),
                    "positive_n_count": len(signals["positive_n"]),
                    "reverse_n_count": len(signals["reverse_n"]),
                }
            )

    daily_index_path.write_text(
        json.dumps({"metadata": summary, "signals": daily_index}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    return {
        "events": str(events_path),
        "daily_lists": str(daily_lists_path),
        "daily_index": str(daily_index_path),
        "summary": str(summary_path),
    }


def parse_args() -> SignalConfig:
    parser = argparse.ArgumentParser(description="Generate daily positive/reverse N signals for qlib stocks.")
    parser.add_argument("--qlib-dir", default="/Users/renxg/.qlib/qlib_data/cn_data")
    parser.add_argument("--instruments", default=None, help="Default: <qlib-dir>/instruments/all.txt")
    parser.add_argument("--output-dir", default="outputs/zigzag_signals_all")
    parser.add_argument("--start", default=None, help="Inclusive start date, e.g. 2024-01-01")
    parser.add_argument("--end", default=None, help="Inclusive end date. Default: latest qlib calendar date")
    parser.add_argument("--years", type=int, default=2, help="Used only when --start is omitted. Set 0 for full history.")
    parser.add_argument("--window", type=int, default=60)
    parser.add_argument("--threshold", type=float, default=0.001)
    parser.add_argument("--include-indexes", action="store_true", help="Include index symbols such as SH000300/SZ399300.")
    args = parser.parse_args()

    qlib_dir = Path(args.qlib_dir).expanduser()
    years = None if args.years == 0 else args.years
    instruments = Path(args.instruments).expanduser() if args.instruments else qlib_dir / "instruments" / "all.txt"
    return SignalConfig(
        qlib_dir=qlib_dir,
        instruments=instruments,
        output_dir=Path(args.output_dir),
        start=pd.Timestamp(args.start) if args.start else None,
        end=pd.Timestamp(args.end) if args.end else None,
        years=years,
        window=args.window,
        threshold=args.threshold,
        exclude_indexes=not args.include_indexes,
    )


def main() -> None:
    config = parse_args()
    events, daily_index, summary = collect_signals(config)
    paths = write_outputs(config.output_dir, events, daily_index, summary)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    for label, path in paths.items():
        print(f"{label}: {path}")


if __name__ == "__main__":
    main()
