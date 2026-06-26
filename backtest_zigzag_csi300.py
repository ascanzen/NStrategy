#!/usr/bin/env python3
# encoding: UTF-8
"""Backtest the ZigZag N-pattern strategy on local qlib CSI300 data."""

from __future__ import annotations

import argparse
import json
import math
from dataclasses import dataclass
from pathlib import Path
from xml.sax.saxutils import escape

import numpy as np
import pandas as pd

try:
    from thiszigzag import peak_valley_pivots as compiled_peak_valley_pivots
except Exception:
    compiled_peak_valley_pivots = None


PEAK = 1
VALLEY = -1
MIN_CIRCLE = 3


@dataclass(frozen=True)
class BacktestConfig:
    qlib_dir: Path
    instruments: Path
    start: pd.Timestamp | None
    end: pd.Timestamp | None
    years: int
    window: int
    threshold: float
    benchmark: str
    output_dir: Path
    liquidity_filter_pct: float
    amount_field: str


def identify_initial_pivot(values: np.ndarray, up_thresh: float, down_thresh: float) -> int:
    x_0 = values[0]
    max_x = x_0
    min_x = x_0
    max_t = 0
    min_t = 0
    up_thresh += 1
    down_thresh += 1

    for t in range(1, len(values)):
        x_t = values[t]
        if x_t / min_x >= up_thresh and t > MIN_CIRCLE:
            return VALLEY if min_t == 0 else PEAK
        if x_t / max_x <= down_thresh and t > MIN_CIRCLE:
            return PEAK if max_t == 0 else VALLEY
        if x_t > max_x:
            max_x = x_t
            max_t = t
        if x_t < min_x:
            min_x = x_t
            min_t = t

    return VALLEY if x_0 < values[-1] else PEAK


def peak_valley_pivots(low: np.ndarray, high: np.ndarray, up_thresh: float, down_thresh: float) -> np.ndarray:
    """Pure NumPy/Python port of thiszigzag.core.peak_valley_pivots."""
    if down_thresh > 0:
        raise ValueError("down_thresh must be negative")

    low = np.asarray(low)
    high = np.asarray(high)
    initial_pivot = identify_initial_pivot(low, up_thresh, down_thresh)
    pivots = np.zeros(len(low), dtype=np.int8)
    trend = -initial_pivot
    last_pivot_t = 0
    last_pivot_x = low[0]
    pivots[0] = initial_pivot

    up_thresh += 1
    down_thresh += 1
    for raw_t in range(1, len(low) + 1):
        t = raw_t if raw_t < len(low) else len(low) - 1
        if trend == -1:
            r = high[t] / (last_pivot_x + 0.0001)
            if low[t] < last_pivot_x:
                last_pivot_x = low[t]
                last_pivot_t = t
            elif r >= up_thresh and (t - last_pivot_t > MIN_CIRCLE):
                validate = True
                for c in range(last_pivot_t + 1, t):
                    if high[c] > high[t]:
                        validate = False
                        break
                if validate:
                    pivots[last_pivot_t] = trend
                    trend = PEAK
                    last_pivot_x = high[t]
                    last_pivot_t = t
        else:
            r = low[t] / (last_pivot_x + 0.0001)
            if high[t] > last_pivot_x:
                last_pivot_x = high[t]
                last_pivot_t = t
            elif r <= down_thresh and (t - last_pivot_t > MIN_CIRCLE):
                validate = True
                for c in range(last_pivot_t + 1, t):
                    if low[c] < low[t]:
                        validate = False
                        break
                if validate:
                    pivots[last_pivot_t] = trend
                    trend = VALLEY
                    last_pivot_x = low[t]
                    last_pivot_t = t

    pivots[last_pivot_t] = trend
    return pivots


def n_pattern_signal(low_window: np.ndarray, high_window: np.ndarray, threshold: float) -> int:
    """Return 1 for positive N, -1 for reverse N, 0 for no fresh signal."""
    if compiled_peak_valley_pivots is not None:
        pivots = compiled_peak_valley_pivots(low_window, high_window, threshold, -threshold)
        pivot_idx = np.nonzero(pivots)[0]
        if len(pivot_idx) <= 3:
            return 0

        idx0, idx1, idx2, idx3 = pivot_idx[-4:]
        if pivots[-1] == PEAK:
            if high_window[idx3] > high_window[idx1] and low_window[idx2] > low_window[idx0]:
                return 1
        elif pivots[-1] == VALLEY:
            if low_window[idx3] < low_window[idx1] and high_window[idx2] < high_window[idx0]:
                return -1
        return 0

    low = np.asarray(low_window)
    high = np.asarray(high_window)
    initial_pivot = identify_initial_pivot(low, threshold, -threshold)
    trend = -initial_pivot
    last_pivot_t = 0
    last_pivot_x = low[0]
    pivots: list[tuple[int, int]] = [(0, initial_pivot)]

    def set_pivot(idx: int, pivot_type: int) -> None:
        if pivots and pivots[-1][0] == idx:
            pivots[-1] = (idx, pivot_type)
        else:
            pivots.append((idx, pivot_type))

    up_thresh = threshold + 1
    down_thresh = 1 - threshold
    for raw_t in range(1, len(low) + 1):
        t = raw_t if raw_t < len(low) else len(low) - 1
        if trend == -1:
            r = high[t] / (last_pivot_x + 0.0001)
            if low[t] < last_pivot_x:
                last_pivot_x = low[t]
                last_pivot_t = t
            elif r >= up_thresh and (t - last_pivot_t > MIN_CIRCLE):
                validate = True
                for c in range(last_pivot_t + 1, t):
                    if high[c] > high[t]:
                        validate = False
                        break
                if validate:
                    set_pivot(last_pivot_t, trend)
                    trend = PEAK
                    last_pivot_x = high[t]
                    last_pivot_t = t
        else:
            r = low[t] / (last_pivot_x + 0.0001)
            if high[t] > last_pivot_x:
                last_pivot_x = high[t]
                last_pivot_t = t
            elif r <= down_thresh and (t - last_pivot_t > MIN_CIRCLE):
                validate = True
                for c in range(last_pivot_t + 1, t):
                    if low[c] < low[t]:
                        validate = False
                        break
                if validate:
                    set_pivot(last_pivot_t, trend)
                    trend = VALLEY
                    last_pivot_x = low[t]
                    last_pivot_t = t

    set_pivot(last_pivot_t, trend)
    if len(pivots) <= 3:
        return 0

    (idx0, _), (idx1, _), (idx2, _), (idx3, pivot3) = pivots[-4:]
    if idx3 != len(low) - 1:
        return 0
    if pivot3 == PEAK:
        if high_window[idx3] > high_window[idx1] and low_window[idx2] > low_window[idx0]:
            return 1
    if pivot3 == VALLEY:
        if low_window[idx3] < low_window[idx1] and high_window[idx2] < high_window[idx0]:
            return -1
    return 0


def read_calendar(qlib_dir: Path) -> pd.DatetimeIndex:
    path = qlib_dir / "calendars" / "day.txt"
    dates = pd.read_csv(path, header=None, names=["date"])["date"]
    return pd.DatetimeIndex(pd.to_datetime(dates))


def read_feature(qlib_dir: Path, symbol: str, field: str, calendar_len: int) -> np.ndarray | None:
    path = qlib_dir / "features" / symbol.lower() / f"{field}.day.bin"
    if not path.exists():
        return None
    raw = np.fromfile(path, dtype="<f4")
    if len(raw) < 2:
        return None
    start_idx = int(round(float(raw[0])))
    values = np.full(calendar_len, np.nan, dtype=np.float64)
    data = raw[1:]
    end_idx = min(start_idx + len(data), calendar_len)
    if end_idx > start_idx:
        values[start_idx:end_idx] = data[: end_idx - start_idx]
    return values


def read_memberships(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path, sep="\t", header=None, names=["symbol", "start", "end"])
    df["symbol"] = df["symbol"].str.lower()
    df["start"] = pd.to_datetime(df["start"])
    df["end"] = pd.to_datetime(df["end"])
    return df


def build_active_sets(
    memberships: pd.DataFrame, calendar: pd.DatetimeIndex, start_idx: int, end_idx: int
) -> list[set[str]]:
    active_sets = [set() for _ in range(end_idx - start_idx + 1)]
    for row in memberships.itertuples(index=False):
        lo = max(calendar.searchsorted(row.start, side="left"), start_idx)
        hi = min(calendar.searchsorted(row.end, side="right") - 1, end_idx)
        if lo > hi:
            continue
        for i in range(lo, hi + 1):
            active_sets[i - start_idx].add(row.symbol)
    return active_sets


def load_stock_data(
    qlib_dir: Path, symbols: list[str], calendar_len: int, extra_fields: list[str] | None = None
) -> dict[str, dict[str, np.ndarray]]:
    data: dict[str, dict[str, np.ndarray]] = {}
    extra_fields = extra_fields or []
    for symbol in symbols:
        close = read_feature(qlib_dir, symbol, "close", calendar_len)
        high = read_feature(qlib_dir, symbol, "high", calendar_len)
        low = read_feature(qlib_dir, symbol, "low", calendar_len)
        if close is None or high is None or low is None:
            continue
        series = {"close": close, "high": high, "low": low}
        missing_extra = False
        for field in extra_fields:
            values = read_feature(qlib_dir, symbol, field, calendar_len)
            if values is None:
                missing_extra = True
                break
            series[field] = values
        if missing_extra:
            continue
        data[symbol] = series
    return data


def build_liquidity_filtered_sets(
    active_sets: list[set[str]],
    stocks: dict[str, dict[str, np.ndarray]],
    start_idx: int,
    amount_field: str,
    top_pct: float,
) -> tuple[list[set[str]], np.ndarray]:
    """Filter each day's universe by daily amount ranking.

    Rank rule:
    - Higher amount is better.
    - Keep the top `top_pct` symbols for that trading day.
    """
    if not 0 < top_pct <= 1:
        raise ValueError("liquidity_filter_pct must be in (0, 1]")
    if top_pct >= 1:
        return [set(symbols) for symbols in active_sets], np.array([len(s) for s in active_sets], dtype=np.int32)

    filtered_sets: list[set[str]] = []
    tradable_counts = np.zeros(len(active_sets), dtype=np.int32)
    for local_i, active in enumerate(active_sets):
        global_i = start_idx + local_i
        rows: list[tuple[str, float]] = []
        for symbol in active:
            series = stocks.get(symbol)
            if series is None:
                continue
            amount = series[amount_field][global_i]
            if np.isfinite(amount) and amount > 0:
                rows.append((symbol, float(amount)))

        if not rows:
            filtered_sets.append(set())
            continue

        keep_n = max(1, int(np.ceil(len(rows) * top_pct)))
        selected = sorted(rows, key=lambda row: (-row[1], row[0]))[:keep_n]
        selected_set = {symbol for symbol, _ in selected}
        filtered_sets.append(selected_set)
        tradable_counts[local_i] = len(selected_set)

    return filtered_sets, tradable_counts


def max_drawdown(nav: np.ndarray) -> float:
    peak = np.maximum.accumulate(nav)
    drawdown = nav / peak - 1
    return float(drawdown.min())


def annualized_return(nav: np.ndarray, trading_days: int = 252) -> float:
    periods = max(len(nav) - 1, 1)
    return float(nav[-1] ** (trading_days / periods) - 1)


def annualized_volatility(returns: np.ndarray, trading_days: int = 252) -> float:
    if len(returns) < 2:
        return 0.0
    return float(np.nanstd(returns, ddof=1) * math.sqrt(trading_days))


def run_backtest(config: BacktestConfig) -> tuple[pd.DataFrame, dict[str, float | int | str]]:
    calendar = read_calendar(config.qlib_dir)
    data_end = calendar[-1]
    end = min(config.end or data_end, data_end)
    if config.start is None:
        start = end - pd.DateOffset(years=config.years)
    else:
        start = config.start

    start_idx = int(calendar.searchsorted(start, side="left"))
    end_idx = int(calendar.searchsorted(end, side="right") - 1)
    if start_idx >= end_idx:
        raise ValueError("Backtest date range is empty")
    start = calendar[start_idx]
    end = calendar[end_idx]

    memberships = read_memberships(config.instruments)
    memberships = memberships[(memberships["end"] >= start) & (memberships["start"] <= end)]
    symbols = sorted(memberships["symbol"].unique())
    extra_fields = [config.amount_field]
    stocks = load_stock_data(config.qlib_dir, symbols, len(calendar), extra_fields=extra_fields)
    symbols = sorted(stocks)
    memberships = memberships[memberships["symbol"].isin(symbols)]

    active_sets = build_active_sets(memberships, calendar, start_idx, end_idx)
    tradable_sets, tradable_counts = build_liquidity_filtered_sets(
        active_sets,
        stocks,
        start_idx,
        config.amount_field,
        config.liquidity_filter_pct,
    )
    benchmark_close = read_feature(config.qlib_dir, config.benchmark, "close", len(calendar))
    if benchmark_close is None:
        raise ValueError(f"Benchmark {config.benchmark} close data was not found")

    dates = calendar[start_idx : end_idx + 1]
    nav = np.ones(len(dates), dtype=np.float64)
    strategy_returns = np.zeros(len(dates), dtype=np.float64)
    held_counts = np.zeros(len(dates), dtype=np.int32)
    active_counts = np.array([len(s) for s in active_sets], dtype=np.int32)
    buy_signals = 0
    sell_signals = 0
    forced_exits = 0
    holdings: set[str] = set()

    for local_i, global_i in enumerate(range(start_idx, end_idx)):
        active_today = tradable_sets[local_i]
        active_next = active_sets[local_i + 1]

        dropped = holdings - active_today
        forced_exits += len(dropped)
        holdings.intersection_update(active_today)

        if global_i >= config.window - 1:
            window_slice = slice(global_i - config.window + 1, global_i + 1)
            for symbol in active_today:
                series = stocks.get(symbol)
                if series is None:
                    continue
                low_window = series["low"][window_slice]
                high_window = series["high"][window_slice]
                if not (np.isfinite(low_window).all() and np.isfinite(high_window).all()):
                    continue
                if np.any(low_window <= 0) or np.any(high_window <= 0):
                    continue

                signal = n_pattern_signal(low_window, high_window, config.threshold)
                if signal == 1:
                    if symbol not in holdings:
                        buy_signals += 1
                    holdings.add(symbol)
                elif signal == -1 and symbol in holdings:
                    holdings.remove(symbol)
                    sell_signals += 1

        overnight = []
        for symbol in holdings & active_today & active_next:
            close = stocks[symbol]["close"]
            c0 = close[global_i]
            c1 = close[global_i + 1]
            if np.isfinite(c0) and np.isfinite(c1) and c0 > 0:
                overnight.append(float(c1 / c0 - 1))

        held_counts[local_i] = len(overnight)
        day_return = float(np.mean(overnight)) if overnight else 0.0
        strategy_returns[local_i + 1] = day_return
        nav[local_i + 1] = nav[local_i] * (1 + day_return)

    held_counts[-1] = len(holdings & tradable_sets[-1])
    bench = benchmark_close[start_idx : end_idx + 1].astype(np.float64)
    first_valid = np.flatnonzero(np.isfinite(bench) & (bench > 0))
    if len(first_valid) == 0:
        raise ValueError("Benchmark has no valid values in the selected date range")
    base = bench[first_valid[0]]
    benchmark_nav = bench / base
    benchmark_returns = np.zeros_like(benchmark_nav)
    benchmark_returns[1:] = benchmark_nav[1:] / benchmark_nav[:-1] - 1

    result = pd.DataFrame(
        {
            "date": dates,
            "strategy_nav": nav,
            "csi300_nav": benchmark_nav,
            "strategy_return": strategy_returns,
            "csi300_return": benchmark_returns,
            "held_count": held_counts,
            "active_csi300_count": active_counts,
            "tradable_count": tradable_counts,
        }
    )

    ret = result["strategy_return"].to_numpy()[1:]
    bench_ret = result["csi300_return"].to_numpy()[1:]
    summary: dict[str, float | int | str] = {
        "data_source": str(config.qlib_dir),
        "universe_file": str(config.instruments),
        "benchmark": config.benchmark,
        "start": str(start.date()),
        "end": str(end.date()),
        "trading_days": int(len(result)),
        "loaded_symbols": int(len(stocks)),
        "threshold": float(config.threshold),
        "window": int(config.window),
        "liquidity_filter_pct": float(config.liquidity_filter_pct),
        "amount_field": config.amount_field,
        "liquidity_filter_rule": "amount_desc_top_pct",
        "strategy_final_nav": float(nav[-1]),
        "csi300_final_nav": float(benchmark_nav[-1]),
        "strategy_total_return": float(nav[-1] - 1),
        "csi300_total_return": float(benchmark_nav[-1] - 1),
        "strategy_annualized_return": annualized_return(nav),
        "csi300_annualized_return": annualized_return(benchmark_nav),
        "strategy_max_drawdown": max_drawdown(nav),
        "csi300_max_drawdown": max_drawdown(benchmark_nav),
        "strategy_annualized_volatility": annualized_volatility(ret),
        "csi300_annualized_volatility": annualized_volatility(bench_ret),
        "strategy_sharpe_0rf": float(np.nanmean(ret) / np.nanstd(ret, ddof=1) * math.sqrt(252))
        if np.nanstd(ret, ddof=1) > 0
        else 0.0,
        "csi300_sharpe_0rf": float(np.nanmean(bench_ret) / np.nanstd(bench_ret, ddof=1) * math.sqrt(252))
        if np.nanstd(bench_ret, ddof=1) > 0
        else 0.0,
        "average_held_count": float(np.mean(held_counts)),
        "max_held_count": int(np.max(held_counts)),
        "average_tradable_count": float(np.mean(tradable_counts)),
        "max_tradable_count": int(np.max(tradable_counts)),
        "buy_signals": int(buy_signals),
        "sell_signals": int(sell_signals),
        "forced_universe_exits": int(forced_exits),
        "assumption": "Long-only, equal-weight CSI300 constituents after daily amount filtering. Each day keeps the top liquidity_filter_pct symbols by amount_field descending. Positive N buys/holds; reverse N sells. Signals use same-day OHLC and earn next-day close-to-close returns. No fees/slippage.",
    }
    return result, summary


def nice_ticks(vmin: float, vmax: float, count: int = 6) -> list[float]:
    if vmin == vmax:
        return [vmin]
    span = vmax - vmin
    raw = span / max(count - 1, 1)
    power = 10 ** math.floor(math.log10(raw))
    step = min([1, 2, 2.5, 5, 10], key=lambda x: abs(x * power - raw)) * power
    lo = math.floor(vmin / step) * step
    hi = math.ceil(vmax / step) * step
    ticks = []
    value = lo
    while value <= hi + step * 0.5:
        ticks.append(round(value, 6))
        value += step
    return ticks


def svg_points(points: list[tuple[float, float]]) -> str:
    return " ".join(f"{x:.2f},{y:.2f}" for x, y in points)


def draw_nav_chart(df: pd.DataFrame, summary: dict[str, float | int | str], output_path: Path) -> None:
    width, height = 1600, 900
    margin_left, margin_right, margin_top, margin_bottom = 110, 70, 125, 120
    plot_w = width - margin_left - margin_right
    plot_h = height - margin_top - margin_bottom

    dates = pd.to_datetime(df["date"])
    x_values = np.arange(len(df), dtype=np.float64)
    strategy = df["strategy_nav"].to_numpy(dtype=np.float64)
    benchmark = df["csi300_nav"].to_numpy(dtype=np.float64)
    y_min = max(0, min(np.nanmin(strategy), np.nanmin(benchmark)) * 0.92)
    y_max = max(np.nanmax(strategy), np.nanmax(benchmark)) * 1.08
    y_ticks = nice_ticks(y_min, y_max)
    y_min = min(y_ticks)
    y_max = max(y_ticks)

    def map_x(x: float) -> float:
        return margin_left + x / max(len(df) - 1, 1) * plot_w

    def map_y(y: float) -> float:
        return margin_top + (y_max - y) / (y_max - y_min) * plot_h

    title = "ZigZag N Strategy vs CSI300"
    subtitle = (
        f"{summary['start']} to {summary['end']} | "
        f"Positive N hold, reverse N sell | "
        f"Top {summary['liquidity_filter_pct']:.0%} by {summary['amount_field']}"
    )
    footnote = (
        f"No fees/slippage. Avg holdings: {summary['average_held_count']:.1f}; "
        f"Max drawdown: strategy {summary['strategy_max_drawdown']:.1%}, CSI300 {summary['csi300_max_drawdown']:.1%}."
    )
    lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}" role="img" aria-labelledby="title desc">',
        f'<title id="title">{escape(title)}</title>',
        f'<desc id="desc">{escape(subtitle)}</desc>',
        "<style>",
        "text{font-family:Arial,Helvetica,sans-serif}.title{font-size:34px;font-weight:600;fill:#1f2933}.subtitle{font-size:20px;fill:#52616b}.axis-label{font-size:18px;fill:#52616b}.small{font-size:16px;fill:#52616b}.legend{font-size:20px;fill:#1f2933}.grid{stroke:#e2e5e8;stroke-width:1}.axis{stroke:#2f3a45;stroke-width:2}.series{fill:none;stroke-linejoin:round;stroke-linecap:round}",
        "</style>",
        f'<rect x="0" y="0" width="{width}" height="{height}" fill="#fbfbf8"/>',
        f'<text class="title" x="{margin_left}" y="73">{escape(title)}</text>',
        f'<text class="subtitle" x="{margin_left}" y="106">{escape(subtitle)}</text>',
    ]

    for tick in y_ticks:
        y = map_y(tick)
        label = f"{tick:.1f}x" if tick >= 1 else f"{tick:.2f}x"
        lines.append(f'<line class="grid" x1="{margin_left}" y1="{y:.2f}" x2="{margin_left + plot_w}" y2="{y:.2f}"/>')
        lines.append(f'<text class="axis-label" x="{margin_left - 15}" y="{y + 6:.2f}" text-anchor="end">{escape(label)}</text>')

    lines.append(f'<line class="axis" x1="{margin_left}" y1="{margin_top}" x2="{margin_left}" y2="{margin_top + plot_h}"/>')
    lines.append(f'<line class="axis" x1="{margin_left}" y1="{margin_top + plot_h}" x2="{margin_left + plot_w}" y2="{margin_top + plot_h}"/>')

    year_starts = []
    seen_years = set()
    for i, date in enumerate(dates):
        if date.year not in seen_years and (date.month == 1 or i == 0):
            seen_years.add(date.year)
            year_starts.append((i, date.year))
    if len(year_starts) > 12:
        year_starts = [item for idx, item in enumerate(year_starts) if idx % 2 == 0]
    for i, year in year_starts:
        x = map_x(i)
        lines.append(f'<line x1="{x:.2f}" y1="{margin_top}" x2="{x:.2f}" y2="{margin_top + plot_h}" stroke="#eef0f2" stroke-width="1"/>')
        lines.append(f'<text class="axis-label" x="{x:.2f}" y="{margin_top + plot_h + 36}" text-anchor="middle">{year}</text>')

    def line_points(series: np.ndarray) -> list[tuple[float, float]]:
        points = [(map_x(x), map_y(y)) for x, y in zip(x_values, series) if np.isfinite(y)]
        return points

    benchmark_points = line_points(benchmark)
    strategy_points = line_points(strategy)
    if len(benchmark_points) >= 2:
        lines.append(f'<polyline class="series" points="{svg_points(benchmark_points)}" stroke="#b8871a" stroke-width="4"/>')
    if len(strategy_points) >= 2:
        lines.append(f'<polyline class="series" points="{svg_points(strategy_points)}" stroke="#1f6f8b" stroke-width="5"/>')

    legend_x = margin_left + plot_w - 430
    legend_y = 44
    lines.extend(
        [
            f'<rect x="{legend_x - 18}" y="{legend_y - 14}" width="423" height="96" rx="8" fill="#ffffff" stroke="#e1e5e8"/>',
            f'<line x1="{legend_x}" y1="{legend_y + 9}" x2="{legend_x + 48}" y2="{legend_y + 9}" stroke="#1f6f8b" stroke-width="5"/>',
            f'<text class="legend" x="{legend_x + 62}" y="{legend_y + 15}">Strategy  {strategy[-1]:.2f}x</text>',
            f'<line x1="{legend_x}" y1="{legend_y + 52}" x2="{legend_x + 48}" y2="{legend_y + 52}" stroke="#b8871a" stroke-width="4"/>',
            f'<text class="legend" x="{legend_x + 62}" y="{legend_y + 58}">CSI300  {benchmark[-1]:.2f}x</text>',
            f'<text class="small" x="{margin_left}" y="{height - 40}">{escape(footnote)}</text>',
            "</svg>",
        ]
    )
    output_path.write_text("\n".join(lines), encoding="utf-8")


def parse_args() -> BacktestConfig:
    parser = argparse.ArgumentParser(description="Backtest ZigZag N-pattern strategy on CSI300 qlib data.")
    parser.add_argument("--qlib-dir", default="/Users/renxg/.qlib/qlib_data/cn_data")
    parser.add_argument("--instruments", default=None)
    parser.add_argument("--start", default=None)
    parser.add_argument("--end", default=None)
    parser.add_argument("--years", type=int, default=10)
    parser.add_argument("--window", type=int, default=60)
    parser.add_argument("--threshold", type=float, default=0.001)
    parser.add_argument("--benchmark", default="sh000300")
    parser.add_argument("--output-dir", default="outputs")
    parser.add_argument(
        "--liquidity-filter-pct",
        type=float,
        default=0.1,
        help="Daily tradable universe ratio after amount ranking. Use 1.0 to disable.",
    )
    parser.add_argument("--amount-field", default="amount", help="qlib field used for amount ranking.")
    args = parser.parse_args()

    qlib_dir = Path(args.qlib_dir).expanduser()
    instruments = Path(args.instruments).expanduser() if args.instruments else qlib_dir / "instruments" / "csi300.txt"
    return BacktestConfig(
        qlib_dir=qlib_dir,
        instruments=instruments,
        start=pd.Timestamp(args.start) if args.start else None,
        end=pd.Timestamp(args.end) if args.end else None,
        years=args.years,
        window=args.window,
        threshold=args.threshold,
        benchmark=args.benchmark.lower(),
        output_dir=Path(args.output_dir),
        liquidity_filter_pct=args.liquidity_filter_pct,
        amount_field=args.amount_field.lower(),
    )


def main() -> None:
    config = parse_args()
    config.output_dir.mkdir(parents=True, exist_ok=True)
    df, summary = run_backtest(config)

    nav_path = config.output_dir / "zigzag_csi300_nav.csv"
    summary_path = config.output_dir / "zigzag_csi300_summary.json"
    chart_path = config.output_dir / "zigzag_csi300_nav.svg"

    df.to_csv(nav_path, index=False)
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    draw_nav_chart(df, summary, chart_path)

    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print(f"NAV CSV: {nav_path}")
    print(f"Chart: {chart_path}")


if __name__ == "__main__":
    main()
