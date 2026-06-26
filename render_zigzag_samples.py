#!/usr/bin/env python3
# encoding: UTF-8
"""Render ZigZag candlestick samples from local qlib data."""

from __future__ import annotations

import argparse
import csv
from pathlib import Path
from xml.sax.saxutils import escape

import numpy as np
import pandas as pd
from PIL import Image, ImageDraw, ImageFont

from backtest_zigzag_csi300 import read_calendar, read_feature, read_memberships

try:
    from thiszigzag import peak_valley_pivots
except Exception as exc:  # pragma: no cover - this is a runtime guard.
    raise SystemExit(f"thiszigzag is not available. Run `make build-zigzag` first. {exc}")


def load_font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    candidates = [
        "/System/Library/Fonts/Supplemental/Arial Unicode.ttf",
        "/System/Library/Fonts/Supplemental/Arial.ttf",
        "/System/Library/Fonts/Helvetica.ttc",
    ]
    for candidate in candidates:
        if Path(candidate).exists():
            try:
                return ImageFont.truetype(candidate, size=size)
            except OSError:
                pass
    return ImageFont.load_default()


def active_symbols_at(memberships: pd.DataFrame, date: pd.Timestamp) -> list[str]:
    active = memberships[(memberships["start"] <= date) & (memberships["end"] >= date)]
    return sorted(active["symbol"].unique())


def load_ohlcv(qlib_dir: Path, symbol: str, calendar: pd.DatetimeIndex) -> pd.DataFrame | None:
    fields = {}
    for field in ["open", "high", "low", "close", "volume"]:
        values = read_feature(qlib_dir, symbol, field, len(calendar))
        if values is None:
            return None
        fields[field] = values
    df = pd.DataFrame(fields, index=calendar)
    df.index.name = "date"
    return df


def latest_two_year_window(calendar: pd.DatetimeIndex, years: int) -> tuple[int, int]:
    end = calendar[-1]
    start = end - pd.DateOffset(years=years)
    start_idx = int(calendar.searchsorted(start, side="left"))
    end_idx = len(calendar) - 1
    return start_idx, end_idx


def moving_average(values: np.ndarray, window: int) -> np.ndarray:
    return pd.Series(values).rolling(window, min_periods=window).mean().to_numpy(dtype=np.float64)


def draw_png_chart(df: pd.DataFrame, symbol: str, threshold: float, output_path: Path) -> dict[str, object]:
    width, height = 1500, 920
    left, right, top, bottom = 88, 42, 92, 62
    volume_h = 150
    gap = 22
    price_bottom = height - bottom - volume_h - gap
    price_h = price_bottom - top
    volume_top = price_bottom + gap
    plot_w = width - left - right

    open_v = df["open"].to_numpy(dtype=np.float64)
    high_v = df["high"].to_numpy(dtype=np.float64)
    low_v = df["low"].to_numpy(dtype=np.float64)
    close_v = df["close"].to_numpy(dtype=np.float64)
    volume_v = df["volume"].to_numpy(dtype=np.float64)

    pivots = peak_valley_pivots(low_v, high_v, threshold, -threshold)
    pivot_idx = np.nonzero(pivots)[0]

    img = Image.new("RGB", (width, height), "#111827")
    draw = ImageDraw.Draw(img)
    title_font = load_font(30)
    subtitle_font = load_font(18)
    axis_font = load_font(16)
    tiny_font = load_font(14)

    price_min = float(np.nanmin(low_v))
    price_max = float(np.nanmax(high_v))
    pad = (price_max - price_min) * 0.06
    price_min -= pad
    price_max += pad
    volume_max = float(np.nanmax(volume_v)) if np.nanmax(volume_v) > 0 else 1.0

    def x_at(i: int) -> float:
        return left + i / max(len(df) - 1, 1) * plot_w

    def y_price(v: float) -> float:
        return top + (price_max - v) / (price_max - price_min) * price_h

    def y_volume(v: float) -> float:
        return volume_top + (1 - v / volume_max) * volume_h

    draw.rectangle((0, 0, width, height), fill="#111827")
    title = f"{symbol.upper()} ZigZag"
    subtitle = f"{df.index[0].date()} to {df.index[-1].date()} | threshold={threshold:g} | pivots={len(pivot_idx)}"
    draw.text((left, 28), title, fill="#f8fafc", font=title_font)
    draw.text((left, 64), subtitle, fill="#94a3b8", font=subtitle_font)

    grid = "#263244"
    axis = "#64748b"
    for frac in np.linspace(0, 1, 6):
        y = top + frac * price_h
        price = price_max - frac * (price_max - price_min)
        draw.line((left, y, width - right, y), fill=grid, width=1)
        draw.text((16, y - 8), f"{price:.2f}", fill="#94a3b8", font=axis_font)
    draw.line((left, top, left, price_bottom), fill=axis, width=1)
    draw.line((left, price_bottom, width - right, price_bottom), fill=axis, width=1)
    draw.line((left, volume_top + volume_h, width - right, volume_top + volume_h), fill=axis, width=1)

    date_positions = np.linspace(0, len(df) - 1, 6, dtype=int)
    for i in date_positions:
        x = x_at(int(i))
        draw.line((x, top, x, price_bottom), fill="#1f2937", width=1)
        label = df.index[int(i)].strftime("%Y-%m")
        bbox = draw.textbbox((0, 0), label, font=axis_font)
        draw.text((x - (bbox[2] - bbox[0]) / 2, height - bottom + 18), label, fill="#94a3b8", font=axis_font)

    candle_step = plot_w / max(len(df), 1)
    candle_w = max(2, min(9, int(candle_step * 0.58)))
    up_color = "#ef4444"
    down_color = "#22c55e"
    flat_color = "#cbd5e1"

    for i, (o, h, l, c, vol) in enumerate(zip(open_v, high_v, low_v, close_v, volume_v)):
        x = x_at(i)
        color = up_color if c >= o else down_color
        if c == o:
            color = flat_color
        draw.line((x, y_price(l), x, y_price(h)), fill=color, width=1)
        y0 = y_price(max(o, c))
        y1 = y_price(min(o, c))
        if abs(y1 - y0) < 1:
            draw.line((x - candle_w / 2, y0, x + candle_w / 2, y0), fill=color, width=2)
        else:
            draw.rectangle((x - candle_w / 2, y0, x + candle_w / 2, y1), fill=color, outline=color)
        vy = y_volume(vol)
        draw.rectangle((x - candle_w / 2, vy, x + candle_w / 2, volume_top + volume_h), fill=color)

    ma_specs = [(5, "#60a5fa"), (10, "#fbbf24"), (20, "#c084fc")]
    for window, color in ma_specs:
        ma = moving_average(close_v, window)
        points = [(x_at(i), y_price(v)) for i, v in enumerate(ma) if np.isfinite(v)]
        if len(points) >= 2:
            draw.line(points, fill=color, width=2)
        draw.text((width - right - 235 + 70 * (window // 5 - 1), 35), f"MA{window}", fill=color, font=tiny_font)

    zigzag_points = []
    for i in pivot_idx:
        price = high_v[i] if pivots[i] == 1 else low_v[i]
        zigzag_points.append((x_at(int(i)), y_price(float(price))))
    if len(zigzag_points) >= 2:
        draw.line(zigzag_points, fill="#e0f2fe", width=3)
    for i in pivot_idx:
        price = high_v[i] if pivots[i] == 1 else low_v[i]
        x = x_at(int(i))
        y = y_price(float(price))
        fill = "#f97316" if pivots[i] == 1 else "#38bdf8"
        draw.ellipse((x - 4, y - 4, x + 4, y + 4), fill=fill)

    start_close = close_v[0]
    end_close = close_v[-1]
    ret = end_close / start_close - 1 if start_close > 0 else np.nan
    note = f"Close return: {ret:.2%} | Last close: {end_close:.2f} | Volume panel below"
    draw.text((left, height - 34), note, fill="#cbd5e1", font=subtitle_font)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    img.save(output_path)
    return {
        "symbol": symbol.upper(),
        "start": str(df.index[0].date()),
        "end": str(df.index[-1].date()),
        "bars": int(len(df)),
        "pivots": int(len(pivot_idx)),
        "return": float(ret),
        "file": str(output_path),
    }


def svg_points(points: list[tuple[float, float]]) -> str:
    return " ".join(f"{x:.2f},{y:.2f}" for x, y in points)


def draw_svg_chart(df: pd.DataFrame, symbol: str, threshold: float, output_path: Path) -> dict[str, object]:
    width, height = 1500, 920
    left, right, top, bottom = 88, 42, 92, 62
    volume_h = 150
    gap = 22
    price_bottom = height - bottom - volume_h - gap
    price_h = price_bottom - top
    volume_top = price_bottom + gap
    plot_w = width - left - right

    open_v = df["open"].to_numpy(dtype=np.float64)
    high_v = df["high"].to_numpy(dtype=np.float64)
    low_v = df["low"].to_numpy(dtype=np.float64)
    close_v = df["close"].to_numpy(dtype=np.float64)
    volume_v = df["volume"].to_numpy(dtype=np.float64)

    pivots = peak_valley_pivots(low_v, high_v, threshold, -threshold)
    pivot_idx = np.nonzero(pivots)[0]

    price_min = float(np.nanmin(low_v))
    price_max = float(np.nanmax(high_v))
    pad = (price_max - price_min) * 0.06
    price_min -= pad
    price_max += pad
    volume_max = float(np.nanmax(volume_v)) if np.nanmax(volume_v) > 0 else 1.0

    def x_at(i: int) -> float:
        return left + i / max(len(df) - 1, 1) * plot_w

    def y_price(v: float) -> float:
        return top + (price_max - v) / (price_max - price_min) * price_h

    def y_volume(v: float) -> float:
        return volume_top + (1 - v / volume_max) * volume_h

    candle_step = plot_w / max(len(df), 1)
    candle_w = max(2, min(9, int(candle_step * 0.58)))
    up_color = "#ef4444"
    down_color = "#22c55e"
    flat_color = "#cbd5e1"
    grid = "#263244"
    axis = "#64748b"

    title = f"{symbol.upper()} ZigZag"
    subtitle = f"{df.index[0].date()} to {df.index[-1].date()} | threshold={threshold:g} | pivots={len(pivot_idx)}"
    start_close = close_v[0]
    end_close = close_v[-1]
    ret = end_close / start_close - 1 if start_close > 0 else np.nan
    note = f"Close return: {ret:.2%} | Last close: {end_close:.2f} | Volume panel below"

    lines: list[str] = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}" role="img" aria-labelledby="title desc">',
        f"<title id=\"title\">{escape(title)}</title>",
        f"<desc id=\"desc\">{escape(subtitle)}</desc>",
        "<style>",
        "text{font-family:Arial,Helvetica,sans-serif}.title{font-size:30px;font-weight:600;fill:#f8fafc}.subtitle{font-size:18px;fill:#94a3b8}.axis-label{font-size:16px;fill:#94a3b8}.tiny{font-size:14px}.note{font-size:18px;fill:#cbd5e1}.grid{stroke:#263244;stroke-width:1}.axis{stroke:#64748b;stroke-width:1}.wick{stroke-width:1}.ma{fill:none;stroke-width:2;stroke-linejoin:round}.zigzag{fill:none;stroke:#e0f2fe;stroke-width:3;stroke-linejoin:round;stroke-linecap:round}",
        "</style>",
        f'<rect x="0" y="0" width="{width}" height="{height}" fill="#111827"/>',
        f'<text class="title" x="{left}" y="58">{escape(title)}</text>',
        f'<text class="subtitle" x="{left}" y="84">{escape(subtitle)}</text>',
    ]

    for frac in np.linspace(0, 1, 6):
        y = top + frac * price_h
        price = price_max - frac * (price_max - price_min)
        lines.append(f'<line class="grid" x1="{left}" y1="{y:.2f}" x2="{width - right}" y2="{y:.2f}"/>')
        lines.append(f'<text class="axis-label" x="16" y="{y + 5:.2f}">{price:.2f}</text>')

    lines.extend(
        [
            f'<line class="axis" x1="{left}" y1="{top}" x2="{left}" y2="{price_bottom}"/>',
            f'<line class="axis" x1="{left}" y1="{price_bottom}" x2="{width - right}" y2="{price_bottom}"/>',
            f'<line class="axis" x1="{left}" y1="{volume_top + volume_h}" x2="{width - right}" y2="{volume_top + volume_h}"/>',
        ]
    )

    for i in np.linspace(0, len(df) - 1, 6, dtype=int):
        x = x_at(int(i))
        label = df.index[int(i)].strftime("%Y-%m")
        lines.append(f'<line x1="{x:.2f}" y1="{top}" x2="{x:.2f}" y2="{price_bottom}" stroke="#1f2937" stroke-width="1"/>')
        lines.append(f'<text class="axis-label" x="{x:.2f}" y="{height - bottom + 34}" text-anchor="middle">{escape(label)}</text>')

    for i, (o, h, l, c, vol) in enumerate(zip(open_v, high_v, low_v, close_v, volume_v)):
        x = x_at(i)
        color = up_color if c >= o else down_color
        if c == o:
            color = flat_color
        x0 = x - candle_w / 2
        y0 = y_price(max(o, c))
        y1 = y_price(min(o, c))
        body_h = max(1, y1 - y0)
        vy = y_volume(vol)
        volume_rect_h = max(0, volume_top + volume_h - vy)
        lines.append(f'<line class="wick" x1="{x:.2f}" y1="{y_price(l):.2f}" x2="{x:.2f}" y2="{y_price(h):.2f}" stroke="{color}"/>')
        lines.append(f'<rect x="{x0:.2f}" y="{y0:.2f}" width="{candle_w}" height="{body_h:.2f}" fill="{color}" stroke="{color}"/>')
        lines.append(f'<rect x="{x0:.2f}" y="{vy:.2f}" width="{candle_w}" height="{volume_rect_h:.2f}" fill="{color}"/>')

    ma_specs = [(5, "#60a5fa"), (10, "#fbbf24"), (20, "#c084fc")]
    for idx, (window, color) in enumerate(ma_specs):
        ma = moving_average(close_v, window)
        points = [(x_at(i), y_price(v)) for i, v in enumerate(ma) if np.isfinite(v)]
        if len(points) >= 2:
            lines.append(f'<polyline class="ma" points="{svg_points(points)}" stroke="{color}"/>')
        lines.append(f'<text class="tiny" x="{width - right - 235 + 70 * idx}" y="50" fill="{color}">MA{window}</text>')

    zigzag_points = []
    for i in pivot_idx:
        price = high_v[i] if pivots[i] == 1 else low_v[i]
        zigzag_points.append((x_at(int(i)), y_price(float(price))))
    if len(zigzag_points) >= 2:
        lines.append(f'<polyline class="zigzag" points="{svg_points(zigzag_points)}"/>')
    for i in pivot_idx:
        price = high_v[i] if pivots[i] == 1 else low_v[i]
        fill = "#f97316" if pivots[i] == 1 else "#38bdf8"
        lines.append(f'<circle cx="{x_at(int(i)):.2f}" cy="{y_price(float(price)):.2f}" r="4" fill="{fill}"/>')

    lines.append(f'<text class="note" x="{left}" y="{height - 14}">{escape(note)}</text>')
    lines.append("</svg>")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text("\n".join(lines), encoding="utf-8")
    return {
        "symbol": symbol.upper(),
        "start": str(df.index[0].date()),
        "end": str(df.index[-1].date()),
        "bars": int(len(df)),
        "pivots": int(len(pivot_idx)),
        "return": float(ret),
        "file": str(output_path),
    }


def draw_chart(df: pd.DataFrame, symbol: str, threshold: float, output_path: Path, output_format: str) -> dict[str, object]:
    if output_format == "svg":
        return draw_svg_chart(df, symbol, threshold, output_path)
    return draw_png_chart(df, symbol, threshold, output_path)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Render 2-year ZigZag charts for CSI300 samples.")
    parser.add_argument("--qlib-dir", default="/Users/renxg/.qlib/qlib_data/cn_data")
    parser.add_argument("--instruments", default=None)
    parser.add_argument("--output-dir", default="outputs/zigzag_2y_samples_svg")
    parser.add_argument("--years", type=int, default=2)
    parser.add_argument("--count", type=int, default=100)
    parser.add_argument("--threshold", type=float, default=0.001)
    parser.add_argument("--format", choices=["svg", "png"], default="svg")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    qlib_dir = Path(args.qlib_dir).expanduser()
    instruments = Path(args.instruments).expanduser() if args.instruments else qlib_dir / "instruments" / "csi300.txt"
    output_dir = Path(args.output_dir)

    calendar = read_calendar(qlib_dir)
    memberships = read_memberships(instruments)
    start_idx, end_idx = latest_two_year_window(calendar, args.years)
    dates = calendar[start_idx : end_idx + 1]
    symbols = active_symbols_at(memberships, calendar[end_idx])

    output_dir.mkdir(parents=True, exist_ok=True)
    rows = []
    for symbol in symbols:
        if len(rows) >= args.count:
            break
        df = load_ohlcv(qlib_dir, symbol, calendar)
        if df is None:
            continue
        df = df.loc[dates].dropna()
        if len(df) < 120:
            continue
        if (df[["open", "high", "low", "close"]] <= 0).any().any():
            continue
        out = output_dir / f"{len(rows) + 1:03d}_{symbol.upper()}_zigzag.{args.format}"
        rows.append(draw_chart(df, symbol, args.threshold, out, args.format))

    manifest = output_dir / "manifest.csv"
    with manifest.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=["symbol", "start", "end", "bars", "pivots", "return", "file"])
        writer.writeheader()
        writer.writerows(rows)

    print(f"Rendered {len(rows)} charts to {output_dir}")
    print(f"Manifest: {manifest}")
    if len(rows) < args.count:
        print(f"Only {len(rows)} symbols had enough valid data for the requested window.")


if __name__ == "__main__":
    main()
