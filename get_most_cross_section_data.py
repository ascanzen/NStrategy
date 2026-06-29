# pyright: reportMissingImports=false, reportUndefinedVariable=false
"""
get_alpha158_csv.py
====================
1. 读取 Tushare 60 天日线数据 + akshare 当天截面数据
2. 合并为统一时间序列（akshare 最新数据作为最后一个交易日）
3. 对每个股票，用 alpha158_engine 计算 158 个截面因子
4. 输出结果 CSV

依赖: tushare, akshare, pandas, numpy
用法:
    export TUSHARE_TOKEN=your_token
    python get_alpha158_csv.py
"""

import argparse
import json
import logging
import multiprocessing
import os
import re
import sys
import time
import warnings
from collections import defaultdict
from datetime import datetime, timedelta
from functools import partial
from logging.handlers import RotatingFileHandler
from pathlib import Path
from xml.sax.saxutils import escape
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

from backtest_zigzag_csi300 import PEAK, VALLEY, peak_valley_pivots

warnings.filterwarnings("ignore")

# ============================================================
# 配置
# ============================================================
BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
RAW_DIR = DATA_DIR / "raw"
CACHE_DIR = DATA_DIR / "cache"
FEATURE_DIR = DATA_DIR / "features"
OUTPUT_DIR = BASE_DIR / "outputs"
LOG_DIR = BASE_DIR / "logs"
for _p in (DATA_DIR, RAW_DIR, CACHE_DIR, FEATURE_DIR):
    _p.mkdir(parents=True, exist_ok=True)
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
LOG_DIR.mkdir(parents=True, exist_ok=True)

TUSHARE_CSV = RAW_DIR / "tushare_daily_60d.csv"
AKSHARE_CSV = RAW_DIR / "akshare_daily_latest.csv"
OUTPUT_CSV = FEATURE_DIR / "alpha158_cross_section.csv"
OUTPUT_TRANSFORMED_CSV = FEATURE_DIR / "alpha158_cross_section_transformed.csv"
OUTPUT_NEXT_VOL_CSV = FEATURE_DIR / "next_volatility.csv"
TUSHARE_DAILY_CACHE_DIR = CACHE_DIR / "tushare_daily_cache"
TUSHARE_DAILY_CACHE_DIR.mkdir(exist_ok=True)
TUSHARE_ADJ_CACHE_DIR = CACHE_DIR / "tushare_adj_factor_cache"
TUSHARE_ADJ_CACHE_DIR.mkdir(exist_ok=True)
TUSHARE_TRADE_CAL_CACHE = CACHE_DIR / "tushare_trade_cal_sse_open.csv"
QLIB_INSTRUMENTS_DIR = DATA_DIR / "instruments"
N_PATTERN_OUTPUT_DIR = OUTPUT_DIR / "n_pattern"
N_PATTERN_SVG_DIR = N_PATTERN_OUTPUT_DIR / "svg"
DEFAULT_N_WINDOW = 60
DEFAULT_N_THRESHOLD = 0.001
DEFAULT_DAEMON_INTERVAL_MINUTES = 15
SHANGHAI_TZ = ZoneInfo("Asia/Shanghai")
TUSHARE_LOCAL_CACHE_TTL_HOURS = 8

# Tushare token（仅通过环境变量传入）
TUSHARE_TOKEN = os.environ.get("TUSHARE_TOKEN", "")
if not TUSHARE_TOKEN:
    TUSHARE_TOKEN = os.environ.get("TUSHARE", "")


LOGGER = logging.getLogger("cross_section_service")


def setup_logging() -> None:
    """Configure console and rotating file logging once."""
    if LOGGER.handlers:
        return

    LOGGER.setLevel(logging.INFO)
    formatter = logging.Formatter("%(asctime)s | %(levelname)s | %(message)s")

    file_handler = RotatingFileHandler(
        LOG_DIR / "cross_section_service.log",
        maxBytes=10 * 1024 * 1024,
        backupCount=5,
        encoding="utf-8",
    )
    file_handler.setFormatter(formatter)

    stream_handler = logging.StreamHandler(sys.stdout)
    stream_handler.setFormatter(formatter)

    LOGGER.addHandler(file_handler)
    LOGGER.addHandler(stream_handler)
    LOGGER.propagate = False


def print(*args, **kwargs):
    """Route legacy print calls into structured logs."""
    sep = kwargs.get("sep", " ")
    end = kwargs.get("end", "")
    message = sep.join(str(arg) for arg in args)
    if end and end != "\n":
        message = f"{message}{end}"
    LOGGER.info(message)


TRANSFORMED_FACTOR_ORDER = [
    "KMID", "KLEN", "KMID2", "KUP", "KUP2", "KLOW", "KLOW2", "KSFT", "KSFT2",
    "OPEN0", "HIGH0", "LOW0", "VWAP0",
    "ROC5", "ROC10", "ROC20", "ROC30", "ROC60",
    "MA5", "MA10", "MA20", "MA30", "MA60",
    "STD5", "STD10", "STD20", "STD30", "STD60",
    "BETA5", "BETA10", "BETA20", "BETA30", "BETA60",
    "RSQR5", "RSQR10", "RSQR20", "RSQR30", "RSQR60",
    "RESI5", "RESI10", "RESI20", "RESI30", "RESI60",
    "MAX5", "MAX10", "MAX20", "MAX30", "MAX60",
    "MIN5", "MIN10", "MIN20", "MIN30", "MIN60",
    "QTLU5", "QTLU10", "QTLU20", "QTLU30", "QTLU60",
    "QTLD5", "QTLD10", "QTLD20", "QTLD30", "QTLD60",
    "RANK5", "RANK10", "RANK20", "RANK30", "RANK60",
    "RSV5", "RSV10", "RSV20", "RSV30", "RSV60",
    "IMAX5", "IMAX10", "IMAX20", "IMAX30", "IMAX60",
    "IMIN5", "IMIN10", "IMIN20", "IMIN30", "IMIN60",
    "IMXD5", "IMXD10", "IMXD20", "IMXD30", "IMXD60",
    "CORR5", "CORR10", "CORR20", "CORR30", "CORR60",
    "CORD5", "CORD10", "CORD20", "CORD30", "CORD60",
    "CNTP5", "CNTP10", "CNTP20", "CNTP30", "CNTP60",
    "CNTN5", "CNTN10", "CNTN20", "CNTN30", "CNTN60",
    "CNTD5", "CNTD10", "CNTD20", "CNTD30", "CNTD60",
    "SUMP5", "SUMP10", "SUMP20", "SUMP30", "SUMP60",
    "SUMN5", "SUMN10", "SUMN20", "SUMN30", "SUMN60",
    "SUMD5", "SUMD10", "SUMD20", "SUMD30", "SUMD60",
    "VMA5", "VMA10", "VMA20", "VMA30", "VMA60",
    "VSTD5", "VSTD10", "VSTD20", "VSTD30", "VSTD60",
    "WVMA5", "WVMA10", "WVMA20", "WVMA30", "WVMA60",
    "VSUMP5", "VSUMP10", "VSUMP20", "VSUMP30", "VSUMP60",
    "VSUMN5", "VSUMN10", "VSUMN20", "VSUMN30", "VSUMN60",
    "VSUMD5", "VSUMD10", "VSUMD20", "VSUMD30", "VSUMD60",
]


def normalize_ts_code(code: str) -> str:
    """统一股票代码到 Tushare 口径: XXXXXX.SZ/SH/BJ。"""
    raw = str(code).strip().upper()
    if not raw or raw == "NAN":
        return ""

    raw = raw.replace("_", ".")
    m = re.match(r"^(SH|SZ|BJ)(\d{6})$", raw)
    if m:
        return f"{m.group(2)}.{m.group(1)}"

    m = re.match(r"^(\d{6})\.(SH|SZ|BJ)$", raw)
    if m:
        return f"{m.group(1)}.{m.group(2)}"

    m = re.match(r"^(\d{6})(SH|SZ|BJ)$", raw)
    if m:
        return f"{m.group(1)}.{m.group(2)}"

    m = re.match(r"^(SH|SZ|BJ)(\d{6})$", raw.replace(".", ""))
    if m:
        return f"{m.group(2)}.{m.group(1)}"

    m = re.match(r"^(\d{6})$", raw)
    if m:
        num = m.group(1)
        if num.startswith("6"):
            exch = "SH"
        elif num.startswith(("4", "8", "9")):
            exch = "BJ"
        else:
            exch = "SZ"
        return f"{num}.{exch}"

    return raw


def to_prefixed_instrument(ts_code: str) -> str:
    """300476.SZ -> SZ300476，兼容异常输入。"""
    norm = normalize_ts_code(ts_code)
    m = re.match(r"^(\d{6})\.(SH|SZ|BJ)$", norm)
    if not m:
        return str(ts_code).strip().upper().replace(".", "")
    return f"{m.group(2)}{m.group(1)}"


def rolling_window_valid_mask(low: np.ndarray, high: np.ndarray, window: int) -> np.ndarray:
    """标记可用于 N 型判定的滚动窗口位置。"""
    valid = np.isfinite(low) & np.isfinite(high) & (low > 0) & (high > 0)
    counts = np.concatenate([[0], np.cumsum(valid.astype(np.int32))])
    out = np.zeros(len(valid), dtype=bool)
    if len(valid) >= window:
        trailing_counts = counts[window:] - counts[:-window]
        out[window - 1 :] = trailing_counts == window
    return out


def n_pattern_signal_with_details(low_window: np.ndarray, high_window: np.ndarray, threshold: float) -> tuple[int, int]:
    """返回 `(signal, pivot_count)`，signal=1 正N，-1 反N，0 无新信号。"""
    pivots = peak_valley_pivots(low_window, high_window, threshold, -threshold)
    pivot_idx = np.nonzero(pivots)[0]
    if len(pivot_idx) < 4:
        return 0, int(len(pivot_idx))

    pivot_values = pivots[pivot_idx]
    idx0, idx1, idx2, idx3 = pivot_idx[-4:]
    direction = 0
    if pivot_values[-1] == 1:
        if high_window[idx3] > high_window[idx1] and low_window[idx2] > low_window[idx0]:
            direction = 1
    elif pivot_values[-1] == -1:
        if low_window[idx3] < low_window[idx1] and high_window[idx2] < high_window[idx0]:
            direction = -1
    return int(direction), int(len(pivot_idx))


def _n_transition_name(prev_signal: int, signal: int) -> str:
    """返回 N 型方向切换名称，仅支持正N<->反N互切。"""
    if prev_signal == 1 and signal == -1:
        return "positive_to_reverse"
    if prev_signal == -1 and signal == 1:
        return "reverse_to_positive"
    return "none"


def _svg_points(points: list[tuple[float, float]]) -> str:
    return " ".join(f"{x:.2f},{y:.2f}" for x, y in points)


def _load_stock_name_map_from_akshare() -> dict[str, str]:
    """从 akshare 原始文件读取 ts_code -> 中文名 映射。"""
    if not AKSHARE_CSV.exists():
        return {}

    try:
        ak_df = pd.read_csv(AKSHARE_CSV)
    except Exception:
        return {}

    if "代码" not in ak_df.columns or "名称" not in ak_df.columns:
        return {}

    out: dict[str, str] = {}
    for _, row in ak_df[["代码", "名称"]].dropna(subset=["代码"]).iterrows():
        code = normalize_ts_code(row["代码"])
        if not code:
            continue
        name_zh = str(row.get("名称", "")).strip()
        if name_zh and name_zh.upper() != "NAN":
            out[code] = name_zh
    return out


def _render_n_svg(
    window_df: pd.DataFrame,
    signal_name: str,
    threshold: float,
    output_path: Path,
    stock_code: str,
    stock_name_zh: str,
) -> None:
    """把最近窗口的 N 型走势渲染成一个轻量 SVG 文件。"""
    data = window_df.reset_index(drop=True).copy()
    open_ = pd.to_numeric(data["open"], errors="coerce").to_numpy(dtype=float)
    close = pd.to_numeric(data["close"], errors="coerce").to_numpy(dtype=float)
    high = pd.to_numeric(data["high"], errors="coerce").to_numpy(dtype=float)
    low = pd.to_numeric(data["low"], errors="coerce").to_numpy(dtype=float)
    pivots = peak_valley_pivots(low, high, threshold, -threshold)
    pivot_idx = np.nonzero(pivots)[0]

    width = 1280
    height = 720
    pad_x = 80
    pad_y = 80

    price_max = float(np.nanmax(high)) if np.isfinite(high).any() else 1.0
    price_min = float(np.nanmin(low)) if np.isfinite(low).any() else 0.0
    if price_max <= price_min:
        price_max = price_min + 1.0
    price_pad = (price_max - price_min) * 0.08
    price_max += price_pad
    price_min -= price_pad

    x_step = (width - 2 * pad_x) / max(len(data) - 1, 1)

    def x_at(idx: int) -> float:
        return pad_x + idx * x_step

    def y_at(price: float) -> float:
        return height - pad_y - (price - price_min) / (price_max - price_min) * (height - 2 * pad_y)

    candle_width = max(3.0, x_step * 0.65)
    half_w = candle_width / 2.0
    candle_elements = []
    for i in range(len(data)):
        if not (np.isfinite(open_[i]) and np.isfinite(close[i]) and np.isfinite(high[i]) and np.isfinite(low[i])):
            continue

        x = x_at(i)
        y_high = y_at(float(high[i]))
        y_low = y_at(float(low[i]))
        y_open = y_at(float(open_[i]))
        y_close = y_at(float(close[i]))
        is_up = close[i] >= open_[i]
        color = "#ef4444" if is_up else "#10b981"
        body_top = min(y_open, y_close)
        body_height = max(abs(y_open - y_close), 1.2)

        candle_elements.append(
            f'<line x1="{x:.2f}" y1="{y_high:.2f}" x2="{x:.2f}" y2="{y_low:.2f}" stroke="{color}" stroke-width="1.8" />'
        )
        candle_elements.append(
            f'<rect x="{x - half_w:.2f}" y="{body_top:.2f}" width="{candle_width:.2f}" height="{body_height:.2f}" fill="{color}" stroke="{color}" stroke-width="1.2" rx="0.8" />'
        )

    zigzag_points = []
    for idx in pivot_idx:
        pivot_price = float(high[idx] if pivots[idx] == PEAK else low[idx])
        zigzag_points.append((x_at(int(idx)), y_at(pivot_price)))

    display_name = str(stock_name_zh).strip()
    title = f"{stock_code} {display_name}" if display_name else str(stock_code)
    subtitle = f"window={len(data)} threshold={threshold:.4f} pivots={len(pivot_idx)}"
    if not data.empty:
        subtitle = f"{data['trade_date'].iloc[0].strftime('%Y-%m-%d')} ~ {data['trade_date'].iloc[-1].strftime('%Y-%m-%d')} | {subtitle}"

    grid_lines = []
    for i in range(5):
        y = pad_y + i * (height - 2 * pad_y) / 4
        grid_lines.append(f'<line x1="{pad_x}" y1="{y:.2f}" x2="{width - pad_x}" y2="{y:.2f}" class="grid" />')

    pivot_marks = []
    for idx in pivot_idx:
        pivot_price = float(high[idx] if pivots[idx] == PEAK else low[idx])
        pivot_marks.append(
            f'<circle cx="{x_at(int(idx)):.2f}" cy="{y_at(pivot_price):.2f}" r="5" fill="#fbbf24" stroke="#1f2937" stroke-width="2" />'
        )

    lines = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}" role="img" aria-labelledby="title desc">',
        "<title id='title'>" + escape(title) + "</title>",
        "<desc id='desc'>" + escape(subtitle) + "</desc>",
        "<style>",
        "  .bg{fill:#081120} .panel{fill:#0f172a;stroke:#243244;stroke-width:2} .grid{stroke:#243244;stroke-width:1;opacity:.55}",
        "  .title{font:700 34px Arial,Helvetica,sans-serif;fill:#f8fafc} .sub{font:400 18px Arial,Helvetica,sans-serif;fill:#94a3b8}",
        "  .axis{font:400 16px Arial,Helvetica,sans-serif;fill:#94a3b8}",
        "  .zigzag{fill:none;stroke:#f8fafc;stroke-width:4;stroke-linejoin:round;stroke-linecap:round}",
        "</style>",
        '<rect class="bg" x="0" y="0" width="100%" height="100%" />',
        f'<rect class="panel" x="40" y="40" width="{width - 80}" height="{height - 80}" rx="20" />',
        f'<text x="80" y="95" class="title">{escape(title)}</text>',
        f'<text x="80" y="130" class="sub">{escape(subtitle)}</text>',
        *grid_lines,
        *candle_elements,
    ]
    if len(zigzag_points) >= 2:
        lines.append(f'<polyline class="zigzag" points="{_svg_points(zigzag_points)}" />')
    lines.extend(pivot_marks)
    if np.isfinite(close[-1]) and np.isfinite(high[-1]) and np.isfinite(low[-1]) and np.isfinite(open_[-1]):
        lines.append(
            f'<text x="80" y="{height - 55}" class="axis">open={open_[-1]:.2f} close={close[-1]:.2f} high={high[-1]:.2f} low={low[-1]:.2f}</text>'
        )
    lines.append("</svg>")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text("\n".join(lines), encoding="utf-8")


def build_n_pattern_outputs(
    merged_df: pd.DataFrame,
    window: int = DEFAULT_N_WINDOW,
    threshold: float = DEFAULT_N_THRESHOLD,
    output_dir: Path = N_PATTERN_OUTPUT_DIR,
    fast_reverse_today: bool = False,
    fast_reverse_days: int = 3,
) -> pd.DataFrame:
    """计算日频 N 型信号并落盘全量日表、事件表、索引和 SVG。"""
    fast_reverse_days = max(1, int(fast_reverse_days))
    if fast_reverse_today:
        print(
            f"\n[4-fast] 极速模式：仅输出最近 {fast_reverse_days} 个交易日内相对前一日发生方向切换的 N 型信号（正N<->反N）..."
        )
    else:
        print("\n[4] 计算 N 型指标并输出...")

    required = {"ts_code", "trade_date", "open", "high", "low", "close", "vol"}
    missing = required - set(merged_df.columns)
    if missing:
        raise ValueError(f"无法计算 N 型指标，merged_df 缺少列: {sorted(missing)}")

    base = merged_df.copy()
    base["trade_date"] = pd.to_datetime(base["trade_date"], errors="coerce")
    for col in ["open", "high", "low", "close", "vol"]:
        base[col] = pd.to_numeric(base[col], errors="coerce")
    base = base.dropna(subset=["ts_code", "trade_date", "open", "high", "low", "close", "vol"]).copy()
    base = base.sort_values(["ts_code", "trade_date"]).reset_index(drop=True)
    latest_trade_ts = base["trade_date"].max() if not base.empty else None
    latest_trade_date = latest_trade_ts.strftime("%Y-%m-%d") if pd.notna(latest_trade_ts) else None
    recent_trade_dates = pd.DatetimeIndex([])
    recent_trade_dates_set: set[pd.Timestamp] = set()
    if fast_reverse_today and not base.empty:
        unique_trade_dates = pd.DatetimeIndex(sorted(base["trade_date"].dropna().unique()))
        recent_trade_dates = unique_trade_dates[-fast_reverse_days:]
        recent_trade_dates_set = set(recent_trade_dates.to_pydatetime())

    daily_rows: list[dict[str, object]] = []
    event_rows: list[dict[str, object]] = []
    daily_index: dict[str, dict[str, list[str]]] = defaultdict(lambda: {"positive_n": [], "reverse_n": []})

    groups = [(code, sub) for code, sub in base.groupby("ts_code", sort=False)]
    stock_name_map = _load_stock_name_map_from_akshare()
    print(f"    共 {len(groups)} 只股票，window={window} threshold={threshold:.4f}")

    for stock_code, sub_df in groups:
        stock_df = (
            sub_df.sort_values("trade_date")
            .drop_duplicates(subset=["trade_date"], keep="last")
            .reset_index(drop=True)
        )
        if len(stock_df) < window:
            continue

        valid_mask = rolling_window_valid_mask(stock_df["low"].to_numpy(dtype=float), stock_df["high"].to_numpy(dtype=float), window)
        instrument = to_prefixed_instrument(stock_code)
        stock_name_zh = stock_name_map.get(stock_code, "")

        if fast_reverse_today:
            idx_candidates = range(window - 1, len(stock_df))
        else:
            idx_candidates = range(window - 1, len(stock_df))

        prev_effective_state = 0
        prev_effective_trade_date = ""

        for idx in idx_candidates:
            if not valid_mask[idx]:
                continue

            window_df = stock_df.iloc[idx - window + 1 : idx + 1].copy()
            low_window = window_df["low"].to_numpy(dtype=float)
            high_window = window_df["high"].to_numpy(dtype=float)
            signal, pivot_count = n_pattern_signal_with_details(low_window, high_window, threshold)

            trade_date = window_df["trade_date"].iloc[-1]
            trade_date_str = trade_date.strftime("%Y-%m-%d")

            current_effective_state = signal if signal != 0 else prev_effective_state
            effective_signal_name = (
                "positive_n" if current_effective_state == 1 else "reverse_n" if current_effective_state == -1 else "none"
            )
            transition_name = _n_transition_name(prev_effective_state, current_effective_state)
            svg_path = ""

            if fast_reverse_today:
                if trade_date.to_pydatetime() not in recent_trade_dates_set or transition_name == "none":
                    prev_effective_state = current_effective_state
                    prev_effective_trade_date = trade_date_str
                    continue

                svg_dir = output_dir / "svg" / trade_date_str
                svg_path_obj = svg_dir / f"{instrument}_{transition_name}_{effective_signal_name}.svg"
                _render_n_svg(
                    window_df,
                    effective_signal_name,
                    threshold,
                    svg_path_obj,
                    stock_code=stock_code,
                    stock_name_zh=stock_name_zh,
                )
                svg_path = str(svg_path_obj.relative_to(output_dir))
            elif signal != 0:
                svg_dir = output_dir / "svg" / trade_date_str
                svg_path_obj = svg_dir / f"{instrument}_{effective_signal_name}.svg"
                _render_n_svg(
                    window_df,
                    effective_signal_name,
                    threshold,
                    svg_path_obj,
                    stock_code=stock_code,
                    stock_name_zh=stock_name_zh,
                )
                svg_path = str(svg_path_obj.relative_to(output_dir))

            row = {
                "trade_date": trade_date_str,
                "datetime": trade_date_str,
                "ts_code": stock_code,
                "instrument": instrument,
                "open": float(window_df["open"].iloc[-1]),
                "high": float(window_df["high"].iloc[-1]),
                "low": float(window_df["low"].iloc[-1]),
                "close": float(window_df["close"].iloc[-1]),
                "vol": float(window_df["vol"].iloc[-1]),
                "n_signal": int(current_effective_state if fast_reverse_today else signal),
                "n_signal_name": effective_signal_name if fast_reverse_today else ("positive_n" if signal == 1 else "reverse_n" if signal == -1 else "none"),
                "n_is_reversal": bool((current_effective_state if fast_reverse_today else signal) == -1),
                "n_prev_signal": int(prev_effective_state),
                "n_prev_signal_name": "positive_n" if prev_effective_state == 1 else "reverse_n" if prev_effective_state == -1 else "none",
                "n_prev_trade_date": prev_effective_trade_date,
                "n_transition": transition_name,
                "n_pivot_count": int(pivot_count),
                "n_window": int(window),
                "n_threshold": float(threshold),
                "n_lookback_start": window_df["trade_date"].iloc[0].strftime("%Y-%m-%d"),
                "n_lookback_end": trade_date_str,
                "n_svg_path": svg_path,
            }
            daily_rows.append(row)

            if fast_reverse_today:
                event_rows.append(row.copy())
                daily_index[trade_date_str][effective_signal_name].append(instrument)
            elif signal != 0:
                event_rows.append(row.copy())
                daily_index[trade_date_str][effective_signal_name].append(instrument)

            prev_effective_state = current_effective_state
            prev_effective_trade_date = trade_date_str

    if fast_reverse_today:
        output_dir.mkdir(parents=True, exist_ok=True)
        reverse_today_df = pd.DataFrame(event_rows)
        reverse_today_path = output_dir / "n_transition_recent.csv"
        reverse_today_legacy_path = output_dir / "n_reverse_today.csv"
        summary_path = output_dir / "n_transition_recent_summary.json"
        summary_legacy_path = output_dir / "n_reverse_today_summary.json"

        reverse_today_df.to_csv(reverse_today_path, index=False)
        reverse_today_df.to_csv(reverse_today_legacy_path, index=False)
        positive_to_reverse_count = 0
        reverse_to_positive_count = 0
        svg_rows = 0
        if not reverse_today_df.empty:
            positive_to_reverse_count = int((reverse_today_df["n_transition"] == "positive_to_reverse").sum())
            reverse_to_positive_count = int((reverse_today_df["n_transition"] == "reverse_to_positive").sum())
            svg_rows = int(reverse_today_df["n_svg_path"].astype(str).ne("").sum())
        summary = {
            "generated_at": datetime.now(SHANGHAI_TZ).strftime("%Y-%m-%d %H:%M:%S"),
            "mode": "fast_reverse_today",
            "fast_reverse_days": int(fast_reverse_days),
            "trade_date": latest_trade_date,
            "recent_trade_dates": [ts.strftime("%Y-%m-%d") for ts in recent_trade_dates],
            "rows": int(len(reverse_today_df)),
            "positive_to_reverse_rows": positive_to_reverse_count,
            "reverse_to_positive_rows": reverse_to_positive_count,
            "svg_rows": svg_rows,
            "window": int(window),
            "threshold": float(threshold),
            "output_files": {
                "transition_today": str(reverse_today_path),
                "reverse_today_legacy": str(reverse_today_legacy_path),
                "summary": str(summary_path),
                "summary_legacy": str(summary_legacy_path),
                "svg_dir": str(output_dir / "svg"),
            },
            "signal_convention": {
                "n_transition": ["positive_to_reverse", "reverse_to_positive"],
                "n_prev_trade_date": "previous trade day",
                "n_prev_signal": "previous trade-day N signal",
                "n_signal": "latest trade-day N signal",
            },
        }
        summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
        summary_legacy_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"    极速翻转表: {reverse_today_path} (rows={len(reverse_today_df)})")
        print(f"    极速翻转表(兼容): {reverse_today_legacy_path} (rows={len(reverse_today_df)})")
        print(f"    极速摘要: {summary_path}")
        print(f"    极速摘要(兼容): {summary_legacy_path}")
        return reverse_today_df

    for signals in daily_index.values():
        signals["positive_n"].sort()
        signals["reverse_n"].sort()

    output_dir.mkdir(parents=True, exist_ok=True)
    daily_df = pd.DataFrame(daily_rows)
    event_df = pd.DataFrame(event_rows)

    daily_path = output_dir / "n_daily_signals.csv"
    events_path = output_dir / "n_events.csv"
    latest_path = output_dir / "n_latest_signals.csv"
    daily_index_path = output_dir / "n_daily_index.json"
    summary_path = output_dir / "n_summary.json"

    daily_df.to_csv(daily_path, index=False)
    event_df.to_csv(events_path, index=False)

    latest_date = None
    latest_df = pd.DataFrame()
    if not daily_df.empty:
        latest_date = str(daily_df["trade_date"].max())
        latest_df = daily_df[daily_df["trade_date"] == latest_date].copy()
        latest_df.to_csv(latest_path, index=False)
    else:
        latest_path.write_text("", encoding="utf-8")

    summary = {
        "generated_at": datetime.now(SHANGHAI_TZ).strftime("%Y-%m-%d %H:%M:%S"),
        "rows": int(len(daily_df)),
        "event_rows": int(len(event_df)),
        "positive_n_events": int((event_df["n_signal"] == 1).sum()) if not event_df.empty else 0,
        "reverse_n_events": int((event_df["n_signal"] == -1).sum()) if not event_df.empty else 0,
        "symbols": int(daily_df["ts_code"].nunique()) if not daily_df.empty else 0,
        "trading_days": int(daily_df["trade_date"].nunique()) if not daily_df.empty else 0,
        "latest_trade_date": latest_date,
        "window": int(window),
        "threshold": float(threshold),
        "output_files": {
            "daily_signals": str(daily_path),
            "events": str(events_path),
            "latest_signals": str(latest_path),
            "daily_index": str(daily_index_path),
            "summary": str(summary_path),
            "svg_dir": str(output_dir / "svg"),
        },
        "signal_convention": {
            "1": "positive_n",
            "-1": "reverse_n",
            "0": "none",
            "n_is_reversal": "true when n_signal == -1",
        },
    }

    daily_index_path.write_text(
        json.dumps({"metadata": summary, "signals": daily_index}, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"    N 型日表: {daily_path} (rows={len(daily_df)})")
    print(f"    N 型事件表: {events_path} (rows={len(event_df)})")
    print(f"    N 型最新快照: {latest_path}")
    print(f"    N 型索引: {daily_index_path}")
    print(f"    N 型摘要: {summary_path}")
    print(f"    SVG 输出目录: {output_dir / 'svg'}")

    return daily_df


def transform_alpha158_for_export(alpha158_df: pd.DataFrame) -> pd.DataFrame:
    """将 ts_code/trade_date 口径转换为 datetime/instrument 口径并按目标列序输出。"""
    out = alpha158_df.copy()
    out["datetime"] = pd.to_datetime(out["trade_date"], errors="coerce").dt.strftime("%Y-%m-%d")
    out["instrument"] = out["ts_code"].map(to_prefixed_instrument)

    ordered = [col for col in TRANSFORMED_FACTOR_ORDER if col in out.columns]
    missing = [col for col in TRANSFORMED_FACTOR_ORDER if col not in out.columns]
    if missing:
        print(f"[提示] 以下目标列在当前结果中不存在，已跳过: {missing}")

    extra = [
        col for col in out.columns
        if col not in {"ts_code", "trade_date", "datetime", "instrument"}
        and col not in ordered
    ]
    if extra:
        print(f"[提示] 存在未在目标排序中的额外列，将追加到末尾: {extra}")

    return out[["datetime", "instrument"] + ordered + extra]


def _load_index_constituents(index_names):
    """读取并合并指数成分（qlib instruments 格式），返回 instrument/start/end。"""
    parts = []
    for name in index_names:
        file_path = QLIB_INSTRUMENTS_DIR / f"{name}.txt"
        if not file_path.exists():
            print(f"    [警告] 成分文件不存在，跳过: {file_path}")
            continue

        rows = pd.read_csv(
            file_path,
            sep="\t",
            header=None,
            names=["instrument", "start", "end"],
            dtype={"instrument": str},
        )
        if rows.empty:
            continue

        rows["instrument"] = rows["instrument"].map(normalize_ts_code)
        rows["start"] = pd.to_datetime(rows["start"], errors="coerce")
        rows["end"] = pd.to_datetime(rows["end"], errors="coerce")
        rows = rows.dropna(subset=["instrument", "start", "end"])
        if not rows.empty:
            parts.append(rows)

    if not parts:
        return pd.DataFrame(columns=["instrument", "start", "end"])

    out = pd.concat(parts, ignore_index=True)
    out = out.drop_duplicates(subset=["instrument", "start", "end"])
    return out


def maybe_filter_index_constituents(merged_df, market: str = "all"):
    """可选：按指数成分生效日期过滤样本。"""
    # print("\n[3-1] 可选过滤指数成分（按生效日期）")
    # print("    可选: none / csi300 / csi500 / csi1000 / csi300+csi500")
    # print("    兼容输入: 300, 500, 1000, 300/500, 3000/500")
    # choice = input("    请选择过滤范围（直接回车为 none）: ").strip().lower()

    # if choice in ("", "none", "n", "no"):
    #     print("    跳过指数成分过滤")
    #     return merged_df

    choice = str(market).strip().lower() or "all"
    if choice in ("all", "a"):
        print("    跳过指数成分过滤（market=all）")
        return merged_df

    alias = {
        "300": ["csi300"],
        "500": ["csi500"],
        "1000": ["csi1000"],
        "300/500": ["csi300", "csi500"],
        "3000/500": ["csi300", "csi500"],  # 与现有脚本口径保持兼容
        "csi300+csi500": ["csi300", "csi500"],
    }

    if choice in alias:
        index_names = alias[choice]
    else:
        tokens = re.split(r"[+,/\\s]+", choice)
        index_names = [t for t in tokens if t]

    index_names = [n if n.startswith("csi") else f"csi{n}" for n in index_names]
    index_names = list(dict.fromkeys(index_names))

    constituents = _load_index_constituents(index_names)
    if constituents.empty:
        print("    [警告] 未加载到有效成分数据，跳过过滤")
        return merged_df

    tolerance_days = 100

    base = merged_df.copy().reset_index(names="row_id")
    base["trade_date"] = pd.to_datetime(base["trade_date"], errors="coerce")

    matched = base.merge(
        constituents,
        left_on="ts_code",
        right_on="instrument",
        how="left",
    )
    keep_mask = (
        matched["start"].notna()
        & (matched["trade_date"] >= matched["start"])
        & (matched["trade_date"] <= (matched["end"] + pd.to_timedelta(tolerance_days, unit="D")))
    )
    keep_ids = matched.loc[keep_mask, "row_id"].drop_duplicates()

    filtered = base[base["row_id"].isin(keep_ids)].drop(columns=["row_id"])
    filtered = filtered.sort_values(["ts_code", "trade_date"]).reset_index(drop=True)

    print(
        f"    已按 {index_names} 过滤 (容忍N={tolerance_days}天): "
        f"{len(merged_df)} -> {len(filtered)} 行, "
        f"{merged_df['ts_code'].nunique()} -> {filtered['ts_code'].nunique()} 只股票"
    )
    print(f"    日期范围: {filtered['trade_date'].min().date()} ~ {filtered['trade_date'].max().date()}")
    return filtered


# ============================================================
# 1. 下载 / 读取 Tushare 日线
# ============================================================
def fetch_tushare_daily():
    """
    如果本地已存在 tushare_daily_60d.csv 则直接读取；
    否则通过 tushare pro_api 下载最近 60 个交易日数据。
    """
    import tushare as ts

    if TUSHARE_CSV.exists() :
        local_df = pd.read_csv(TUSHARE_CSV)
        cache_age = datetime.now() - datetime.fromtimestamp(TUSHARE_CSV.stat().st_mtime)
        cache_expired = cache_age > timedelta(hours=TUSHARE_LOCAL_CACHE_TTL_HOURS)
        if not cache_expired:
            print(
                f"[1] 读取本地 Tushare 数据: {TUSHARE_CSV} "
                f"(缓存时长 {cache_age.total_seconds() / 3600:.2f} 小时)"
            )
        else:
            print(
                f"[1] 本地 Tushare 缓存已过期: {TUSHARE_CSV} "
                f"(缓存时长 {cache_age.total_seconds() / 3600:.2f} 小时 > {TUSHARE_LOCAL_CACHE_TTL_HOURS} 小时)"
            )

        if cache_expired and not TUSHARE_TOKEN:
            print("    [警告] 缓存已过期且未设置 TUSHARE_TOKEN，无法刷新，将返回本地缓存")
            return local_df

        if cache_expired and TUSHARE_TOKEN:
            print("    [提示] 缓存已过期，开始刷新最近交易日数据...")
        else:
        # 兼容旧缓存：若缺少 adj_factor，则补拉后覆盖本地缓存。
            if "adj_factor" in local_df.columns:
                return local_df
            print("    [提示] 本地缓存缺少 adj_factor，尝试补齐复权因子...")
            if not TUSHARE_TOKEN:
                print("    [警告] 未设置 TUSHARE_TOKEN，无法补齐 adj_factor，将返回原始数据")
                return local_df

            ts.set_token(TUSHARE_TOKEN)
            pro = ts.pro_api()
            backfill = local_df.copy()
            if "trade_date" not in backfill.columns:
                raise ValueError("本地 Tushare 数据缺少 trade_date，无法补齐 adj_factor")

            trade_date_dt = pd.to_datetime(backfill["trade_date"], errors="coerce")
            if trade_date_dt.isna().all():
                raise ValueError("本地 Tushare trade_date 无法解析，无法补齐 adj_factor")

            backfill_dates = sorted(trade_date_dt.dropna().dt.strftime("%Y%m%d").unique().tolist())
            adj_df = _fetch_tushare_adj_factor_for_dates(pro, backfill_dates)
            if not adj_df.empty:
                backfill["ts_code"] = backfill["ts_code"].map(normalize_ts_code)
                adj_df["ts_code"] = adj_df["ts_code"].map(normalize_ts_code)
                backfill["trade_date_str"] = trade_date_dt.dt.strftime("%Y%m%d")
                adj_df["trade_date_str"] = adj_df["trade_date"].astype(str)
                backfill = backfill.merge(
                    adj_df[["ts_code", "trade_date_str", "adj_factor"]],
                    on=["ts_code", "trade_date_str"],
                    how="left",
                )
                backfill = backfill.drop(columns=["trade_date_str"])
                backfill.to_csv(TUSHARE_CSV, index=False)
                print(f"    已补齐并覆盖保存: {TUSHARE_CSV}")
            return backfill

    if not TUSHARE_TOKEN:
        raise ValueError(
            "TUSHARE_TOKEN 未设置。请设置环境变量:\n"
            "    export TUSHARE_TOKEN=your_token_here\n"
            "或在脚本中直接修改 TUSHARE_TOKEN 变量。"
        )

    ts.set_token(TUSHARE_TOKEN)
    pro = ts.pro_api()

    time.sleep(1)  # 避免请求过快被限流
    # 取最近 100 个交易日
    today_str = datetime.now().strftime("%Y%m%d")
    trade_days = _get_trade_days_sse_open_cached(pro, today_str=today_str, lookback=100)

    # 若当天未收盘，则不请求当天的 daily/adj_factor，避免空重试与空缓存。
    now = datetime.now()
    market_close = now.replace(hour=15, minute=0, second=0, microsecond=0)
    if now < market_close and trade_days and trade_days[-1] == today_str:
        trade_days = trade_days[:-1]
        print(f"    [提示] 当前未收盘，已跳过当日 {today_str} 的 daily/adj_factor 拉取")

    if not trade_days:
        raise ValueError("可用交易日为空（可能因盘中剔除当日后无历史交易日）")

    print(f"[1] 下载 Tushare 日线: {trade_days[0]} ~ {trade_days[-1]} ({len(trade_days)} 天)")

    dfs = []
    adj_dfs = []
    for date in trade_days:
        cache_path = TUSHARE_DAILY_CACHE_DIR / f"daily_{date}.csv"
        if cache_path.exists():
            df = pd.read_csv(cache_path)
            if "trade_date" not in df.columns and not df.empty:
                df["trade_date"] = date
            # print(f"    {date}: 使用缓存 ({len(df)} 只股票)")
        else:
            df = pd.DataFrame()
            # 兼容 Tushare 偶发空返回：空表和异常都按失败处理，最多重试 3 次。
            for attempt in range(3):
                try:
                    fetched = pro.daily(trade_date=date)
                    if fetched is not None and not fetched.empty:
                        df = fetched
                        break
                    print(f"    {date}: daily 为空 (尝试 {attempt + 1}/3)")
                except Exception as e:
                    print(f"    {date}: daily 拉取失败 (尝试 {attempt + 1}/3)，错误: {e}")

                if attempt < 2:
                    time.sleep(5)  # 等待后重试

            if not df.empty:
                df["trade_date"] = date
                df.to_csv(cache_path, index=False)
                print(f"    {date}: 下载并缓存 ({len(df)} 只股票)")
            else:
                print(f"    {date}: 拉取失败，数据为空，将跳过该日期")
                continue

        if not df.empty:
            dfs.append(df)

    adj_dfs = _fetch_tushare_adj_factor_for_dates(pro, trade_days)

    if not dfs:
        raise ValueError("Tushare 未返回任何数据")

    all_df = pd.concat(dfs, ignore_index=True)
    if not adj_dfs.empty:
        all_df["ts_code"] = all_df["ts_code"].map(normalize_ts_code)
        all_df["trade_date"] = pd.to_numeric(all_df["trade_date"], errors="coerce").astype("Int64")
        all_df = all_df.dropna(subset=["trade_date"]).copy()
        all_df["trade_date"] = all_df["trade_date"].astype(str)

        adj_merge = adj_dfs.copy()
        adj_merge["ts_code"] = adj_merge["ts_code"].map(normalize_ts_code)
        adj_merge["trade_date"] = adj_merge["trade_date"].astype(str)

        all_df = all_df.merge(adj_merge, on=["ts_code", "trade_date"], how="left")
    all_df.to_csv(TUSHARE_CSV, index=False)
    print(f"    已保存: {TUSHARE_CSV} ({len(all_df)} 行)")
    return all_df


def _fetch_tushare_adj_factor_for_dates(pro, trade_days):
    """按交易日拉取复权因子并缓存，返回列: ts_code, trade_date, adj_factor。"""
    adj_list = []
    for date in trade_days:
        cache_path = TUSHARE_ADJ_CACHE_DIR / f"adj_factor_{date}.csv"
        if cache_path.exists() and cache_path.stat().st_size > 100:
            adj_df = pd.read_csv(cache_path)
            # print(f"    {date}: 使用 adj_factor 缓存 ({len(adj_df)} 只股票)")
        else:
            adj_df = pd.DataFrame(columns=["ts_code", "trade_date", "adj_factor"])
            # 兼容 Tushare 偶发空返回：空表和异常都按失败处理，最多重试 3 次。
            for attempt in range(3):
                try:
                    fetched = pro.adj_factor(trade_date=date)
                    if fetched is not None and not fetched.empty:
                        adj_df = fetched
                        break
                    print(f"    {date}: adj_factor 为空 (尝试 {attempt + 1}/3)")
                except Exception as e:
                    print(f"    {date}: adj_factor 拉取失败 (尝试 {attempt + 1}/3)，错误: {e}")

                if attempt < 2:
                    time.sleep(5)  # 等待后重试

            adj_df.to_csv(cache_path, index=False)
            print(f"    {date}: 下载并缓存 adj_factor ({len(adj_df)} 只股票)")

        if not adj_df.empty:
            adj_list.append(adj_df[["ts_code", "trade_date", "adj_factor"]].copy())

    if not adj_list:
        return pd.DataFrame(columns=["ts_code", "trade_date", "adj_factor"])

    adj_all = pd.concat(adj_list, ignore_index=True)
    adj_all["trade_date"] = pd.to_numeric(adj_all["trade_date"], errors="coerce").astype("Int64")
    adj_all = adj_all.dropna(subset=["trade_date"]).copy()
    adj_all["trade_date"] = adj_all["trade_date"].astype(str)
    adj_all["adj_factor"] = pd.to_numeric(adj_all["adj_factor"], errors="coerce")
    adj_all = adj_all.dropna(subset=["adj_factor"])
    adj_all = adj_all.drop_duplicates(subset=["ts_code", "trade_date"])
    return adj_all


def _get_trade_days_sse_open_cached(pro, today_str: str, lookback: int = 100):
    """优先使用本地缓存获取上交所开市日，缓存缺失时回源 Tushare。"""
    trade_cal = None
    if TUSHARE_TRADE_CAL_CACHE.exists():
        try:
            trade_cal = pd.read_csv(TUSHARE_TRADE_CAL_CACHE)
            if "cal_date" not in trade_cal.columns:
                trade_cal = None
            else:
                print(f"    使用 trade_cal 缓存: {TUSHARE_TRADE_CAL_CACHE}")
        except Exception:
            trade_cal = None

    if trade_cal is None:
        trade_cal = pro.trade_cal(exchange="SSE", is_open="1", fields="cal_date")
        if trade_cal is None or trade_cal.empty:
            raise ValueError("Tushare trade_cal 未返回有效交易日")
        trade_cal.to_csv(TUSHARE_TRADE_CAL_CACHE, index=False)
        print(f"    已缓存 trade_cal: {TUSHARE_TRADE_CAL_CACHE}")

    cal_dates = pd.to_numeric(trade_cal["cal_date"], errors="coerce").dropna().astype(int).astype(str)
    trade_days = sorted([d for d in cal_dates.tolist() if d <= today_str])[-lookback:]
    if not trade_days:
        raise ValueError("trade_cal 过滤后为空，请检查缓存或 Tushare 返回")
    return trade_days


# ============================================================
# 2. 读取 / 下载 akshare 当天截面
# ============================================================
def fetch_akshare_spot():
    """
    如果本地已存在 akshare_daily_latest.csv 则直接读取；
    否则通过 akshare stock_zh_a_spot 获取当天截面。
    """
    now = datetime.now()
    cooldown_seconds = 120
    market_open = now.replace(hour=9, minute=30, second=0, microsecond=0)
    market_close = now.replace(hour=15, minute=0, second=0, microsecond=0)
    is_trading_time = market_open <= now < market_close

    # 两分钟内不重复刷新，避免频繁请求 akshare。
    if AKSHARE_CSV.exists():
        mod_time = datetime.fromtimestamp(AKSHARE_CSV.stat().st_mtime)
        age_seconds = (now - mod_time).total_seconds()
        if 0 <= age_seconds < cooldown_seconds:
            print(
                f"[2] 本地 akshare 数据 {AKSHARE_CSV} 刚更新于 {mod_time:%H:%M:%S}，"
                f"{cooldown_seconds} 秒内复用缓存"
            )
            return pd.read_csv(AKSHARE_CSV)

    if is_trading_time:
        import akshare as ak

        print("[2] 交易时段内强制刷新 akshare 当天截面数据（不读缓存）...")
        df = ak.stock_zh_a_spot()
        df.to_csv(AKSHARE_CSV, index=False)
        print(f"    已保存: {AKSHARE_CSV} ({len(df)} 只股票)")
        return df

    # 提示csv是否更新，避免重复下载
    if AKSHARE_CSV.exists():
        # 通过文件修改时间判断是否为当天数据，若是则直接读取，否则提示更新。
        mod_time = datetime.fromtimestamp(AKSHARE_CSV.stat().st_mtime)
        if mod_time.date() < datetime.now().date():
            print(f"[提示] 本地 akshare 数据 {AKSHARE_CSV} 不是当天数据，建议删除后重新运行以获取最新数据")
        else:
            print(f"[2] 读取本地 akshare 数据: {AKSHARE_CSV}")
            return pd.read_csv(AKSHARE_CSV)

    import akshare as ak

    print("[2] 下载 akshare 当天截面数据...")
    df = ak.stock_zh_a_spot()
    df.to_csv(AKSHARE_CSV, index=False)
    print(f"    已保存: {AKSHARE_CSV} ({len(df)} 只股票)")
    return df


# ============================================================
# 3. 数据清洗与合并
# ============================================================
def clean_tushare(df):
    """
        清洗 Tushare 日线数据:
            - 统一列名: ts_code, trade_date, open, high, low, close, vol, adj_factor
            - trade_date 转为日期类型
            - 数值列转为数值类型
    """
    df = df.copy()
    # 确保关键列存在
    need_cols = {"ts_code", "trade_date", "open", "high", "low", "close", "vol", "adj_factor"}
    missing = need_cols - set(df.columns)
    if missing:
        raise ValueError(f"Tushare 数据缺少列: {missing}")

    df["ts_code"] = df["ts_code"].map(normalize_ts_code)
    df = df[df["ts_code"] != ""].copy()

    for col in ["open", "high", "low", "close", "vol", "adj_factor"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")

    # Tushare 的 vol 单位是"手"，统一转换为"股"。
    df["vol"] = df["vol"] * 100

    # 日期解析
    trade_date_raw = df["trade_date"].copy()
    df["trade_date"] = pd.to_datetime(trade_date_raw, format="%Y%m%d", errors="coerce")
    if df["trade_date"].isna().any():
        # 兼容历史缓存里可能出现的 YYYY-MM-DD 日期格式。
        date_fallback = pd.to_datetime(trade_date_raw, errors="coerce")
        df["trade_date"] = df["trade_date"].fillna(date_fallback)
    df = df.dropna(subset=["open", "high", "low", "close", "vol", "adj_factor"])
    df = df.dropna(subset=["trade_date"])

    # 去重
    df = df.drop_duplicates(subset=["ts_code", "trade_date"])
    df = df.sort_values(["ts_code", "trade_date"]).reset_index(drop=True)
    return df[["ts_code", "trade_date", "open", "high", "low", "close", "vol", "adj_factor"]]


def clean_akshare(df):
    """
    清洗 akshare 截面数据，转换为 Tushare 格式:
      - 提取: 代码, 今开, 最高, 最低, 最新价, 成交量
      - 代码格式统一为 XXXXXX.XX
    """
    df = df.copy()

    # 列名映射（兼容不同 akshare 版本）
    col_map = {
        "代码": "ts_code",
        "今开": "open",
        "最高": "high",
        "最低": "low",
        "最新价": "close",
        "成交量": "vol",
    }

    # 尝试多种可能的列名
    rename_map = {}
    for ak_col, std_col in col_map.items():
        if ak_col in df.columns:
            rename_map[ak_col] = std_col

    # 如果标准映射不够，尝试其他常见列名
    for col in df.columns:
        if col not in rename_map:
            if "开" in col and "open" not in rename_map.values():
                rename_map[col] = "open"
            elif "最高" in col and "high" not in rename_map.values():
                rename_map[col] = "high"
            elif "最低" in col and "low" not in rename_map.values():
                rename_map[col] = "low"
            elif col in ("最新价", "现价", "close", "收盘价") and "close" not in rename_map.values():
                rename_map[col] = "close"
            elif col in ("成交量", "vol", "volume") and "vol" not in rename_map.values():
                rename_map[col] = "vol"

    df = df.rename(columns=rename_map)

    # 统一代码格式，兼容 bj920679 / sz000001 / 000001 等输入。
    if "ts_code" in df.columns:
        df["ts_code"] = df["ts_code"].map(normalize_ts_code)
        df = df[df["ts_code"] != ""].copy()

    # 数值转换
    for col in ["open", "high", "low", "close", "vol"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    # 过滤掉无效数据
    df = df.dropna(subset=["open", "high", "low", "close", "vol"])
    df = df[df["close"] > 0]  # 去掉停牌/退市

    # 添加 trade_date（当天）
    df["trade_date"] = pd.Timestamp.now().normalize()

    df["adj_factor"] = np.nan
    return df[["ts_code", "trade_date", "open", "high", "low", "close", "vol", "adj_factor"]]


def apply_forward_adjustment(df):
    """
    对合并(并可选过滤)后的数据统一做前复权：
      - 价格乘以 adj_factor / latest_adj
      - 成交量除以 adj_factor / latest_adj
    """
    out = df.copy()
    if "adj_factor" not in out.columns:
        print("    [警告] 缺少 adj_factor 列，跳过复权")
        return out

    out["adj_factor"] = pd.to_numeric(out["adj_factor"], errors="coerce")
    latest_adj = out.groupby("ts_code")["adj_factor"].transform("max")
    latest_adj = latest_adj.fillna(1.0)
    effective_adj = out["adj_factor"].fillna(latest_adj)

    adj_ratio = (effective_adj / latest_adj).replace([np.inf, -np.inf], np.nan)
    valid = adj_ratio.notna() & (adj_ratio > 0)
    out = out[valid].copy()
    adj_ratio = adj_ratio[valid]

    out["open"] = out["open"] * adj_ratio
    out["high"] = out["high"] * adj_ratio
    out["low"] = out["low"] * adj_ratio
    out["close"] = out["close"] * adj_ratio
    out["vol"] = out["vol"] / adj_ratio

    out = out.sort_values(["ts_code", "trade_date"]).reset_index(drop=True)
    return out


def merge_data(tushare_df, akshare_df):
    """
    合并:
      1) Tushare 历史日线（除最后一天）
      2) akshare 当天截面（替换/补充最后一天）
    返回: 每个股票一个时间序列 DataFrame
    """
    print("\n[3] 数据合并...")

    tushare_clean = clean_tushare(tushare_df)
    akshare_clean = clean_akshare(akshare_df)

    print(f"    Tushare: last date {tushare_clean['trade_date'].max().date()}, {len(tushare_clean)} 行, {tushare_clean['ts_code'].nunique()} 只股票")

    print(f"    akshare: last date {akshare_clean['trade_date'].max().date()}, {len(akshare_clean)} 行, {akshare_clean['ts_code'].nunique()} 只股票")

    # 测试
    if False:
        # test,对比两者最后一天的重叠股票数量和价格差异，帮助用户判断是否合并。
        last_date = tushare_clean["trade_date"].max()
        tushare_last = tushare_clean[tushare_clean["trade_date"] == last_date]
        akshare_last = akshare_clean
        # 打印第一行数据
        print(f"    [对比] Tushare 最后一天样例: {tushare_last.iloc[0].to_dict() if not tushare_last.empty else '无数据'}") 
        print(f"    [对比] akshare 最后一天样例: {akshare_last.iloc[0].to_dict() if not akshare_last.empty else '无数据'}") 

        # 打印 300502.SZ 这只股票的最后一天价格对比，帮助用户判断是否合并。
        sample_code = "300502.SZ"
        tushare_sample = tushare_last[tushare_last["ts_code"] == sample_code]
        akshare_sample = akshare_last[akshare_last["ts_code"] == sample_code]
        if not tushare_sample.empty and not akshare_sample.empty:
            # 对比所有字段的差异
            compare_fields = ["open", "high", "low", "close", "vol"]
            print(f"    [对比] {sample_code} 最后一天价格对比:")
            for field in compare_fields:
                tushare_value = tushare_sample.iloc[0][field]
                akshare_value = akshare_sample.iloc[0][field]
                if pd.isna(tushare_value) or pd.isna(akshare_value):
                    print(f"        {field}: Tushare={tushare_value}, akshare={akshare_value} (缺失数据)")
                else:
                    diff = akshare_value - tushare_value
                    diff_pct = (diff / tushare_value) * 100 if tushare_value != 0 else np.nan
                    print(f"        {field}: Tushare={tushare_value}, akshare={akshare_value}, 差异={diff:.2f} ({diff_pct:.2f}%)")
        else:
            print(f"    [对比] {sample_code} 最后一天在 Tushare 或 akshare 中缺失，无法对比价格。")

    # Tushare 最后一天
    last_tushare_date = tushare_clean["trade_date"].max()
    print(f"    Tushare 最后交易日: {last_tushare_date.date()}")

    tushare_hist = tushare_clean

    # 判断当前时间是否已过收盘（15:00）
    now = datetime.now()
    market_open = now.replace(hour=9, minute=30, second=0, microsecond=0)
    market_close = now.replace(hour=15, minute=0, second=0, microsecond=0)
    is_trading_time = market_open <= now < market_close
    if is_trading_time:
        print("    [警告] 当前为盘中，akshare 数据可能不完整，仅供参考！")
        print("    [提示] 交易时段默认合并 Tushare 和 akshare 数据。")
    else:
        print("    [提示] 当前已过收盘，akshare 数据应为完整日线，自动合并。")
    
    merged = pd.concat(
        [tushare_hist, akshare_clean], ignore_index=True, sort=False
    )
    merged = merged.sort_values(["ts_code", "trade_date"]).reset_index(drop=True)


    print(f"    合并后: {len(merged)} 行, {merged['ts_code'].nunique()} 只股票")
    print(f"    日期范围: {merged['trade_date'].min().date()} ~ {merged['trade_date'].max().date()}")
    return merged


def _is_shanghai_trading_session(now: datetime) -> bool:
    market_open_morning = now.replace(hour=9, minute=30, second=0, microsecond=0)
    market_close_morning = now.replace(hour=11, minute=30, second=0, microsecond=0)
    market_open_afternoon = now.replace(hour=13, minute=0, second=0, microsecond=0)
    market_close = now.replace(hour=15, minute=0, second=0, microsecond=0)
    return (market_open_morning <= now < market_close_morning) or (market_open_afternoon <= now < market_close)


def _next_trading_sleep_seconds(now: datetime, interval_minutes: int) -> float:
    today = now.date()
    market_open_morning = now.replace(hour=9, minute=30, second=0, microsecond=0)
    market_close_morning = now.replace(hour=11, minute=30, second=0, microsecond=0)
    market_open_afternoon = now.replace(hour=13, minute=0, second=0, microsecond=0)
    market_close = now.replace(hour=15, minute=0, second=0, microsecond=0)
    interval = timedelta(minutes=interval_minutes)

    if now < market_open_morning:
        return max(1.0, (market_open_morning - now).total_seconds())
    if market_open_morning <= now < market_close_morning:
        next_run = now + interval
        if next_run >= market_close_morning:
            return max(1.0, (market_open_afternoon - now).total_seconds())
        return max(1.0, (next_run - now).total_seconds())
    if market_close_morning <= now < market_open_afternoon:
        return max(1.0, (market_open_afternoon - now).total_seconds())
    if market_open_afternoon <= now < market_close:
        next_run = now + interval
        if next_run >= market_close:
            next_day = datetime.combine(today + timedelta(days=1), datetime.min.time(), tzinfo=now.tzinfo)
            next_open = next_day.replace(hour=9, minute=30, second=0, microsecond=0)
            return max(1.0, (next_open - now).total_seconds())
        return max(1.0, (next_run - now).total_seconds())

    next_day = datetime.combine(today + timedelta(days=1), datetime.min.time(), tzinfo=now.tzinfo)
    next_open = next_day.replace(hour=9, minute=30, second=0, microsecond=0)
    return max(1.0, (next_open - now).total_seconds())


# ============================================================
# 4. 计算 Alpha158 截面因子
# ============================================================

def _calc_stock_alpha158(stock_code, sub_df):
    """
    对单只股票用 calculate_alpha158_lastday 极速计算最后一天的 158 个特征。
    供 groupby.apply 调用，直接返回 1 行 DataFrame。
    """
    sub_df = sub_df.sort_values("trade_date")
    df_input = pd.DataFrame(
        {
            "$open": sub_df["open"].values,
            "$high": sub_df["high"].values,
            "$low": sub_df["low"].values,
            "$close": sub_df["close"].values,
            "$volume": sub_df["vol"].values,
        },
        index=sub_df["trade_date"],
    )
    row = calculate_alpha158_lastday(df_input)
    row = row.reset_index().rename(columns={"index": "trade_date"})
    row.insert(0, "ts_code", stock_code)
    return row


def _calc_stock_alpha158_worker(args):
    """多进程 worker，接收 (stock_code, sub_df) 元组。"""
    stock_code, sub_df = args
    return _calc_stock_alpha158(stock_code, sub_df)


def _calc_next_vol_worker(args):
    """多进程 worker，接收 (stock_code, sub_df) 元组并返回次日波动率结果。"""
    stock_code, sub_df = args
    sub_df = sub_df.sort_values("trade_date")
    ohlc = (
        sub_df[["trade_date", "open", "high", "low", "close"]]
        .drop_duplicates(subset=["trade_date"], keep="last")
        .sort_values("trade_date")
        .set_index("trade_date")
    )
    if len(ohlc) < 20:
        return None

    try:
        next_vol = float(yz_ewma_next_vol(ohlc, lam=0.94, k=0.14, annualize=False))
    except Exception:
        return None

    close_last = float(ohlc["close"].iloc[-1])
    return {
        "trade_date": ohlc.index.max(),
        "ts_code": stock_code,
        "instrument": to_prefixed_instrument(stock_code),
        "close": close_last,
        "next_vol": next_vol,
    }


def calc_alpha158_cross_section(merged_df, n_jobs: int = None):
    """
    用多进程并行计算截面因子。
    每只股票只算最后 1 天，速度比全序列计算快 40x+。
    n_jobs: 进程数，默认使用 CPU 核数的一半（避免内存压力）。
    """
    print("\n[4] 计算 Alpha158 截面因子 (多进程版)...")

    counts = merged_df.groupby("ts_code").size()
    valid = counts[counts >= 60].index.tolist()
    merged_valid = merged_df[merged_df["ts_code"].isin(valid)].copy()

    skipped = counts[counts < 60]
    if len(skipped):
        print(f"    跳过 {len(skipped)} 只（数据不足 60 天）")

    if merged_valid.empty:
        raise ValueError("没有股票满足 60 天数据要求")

    # 按 ts_code 分组，生成 (code, sub_df) 列表
    groups = [(code, sub) for code, sub in merged_valid.groupby("ts_code", sort=False)]

    if n_jobs is None:
        n_jobs = max(1, multiprocessing.cpu_count() // 2)

    print(f"    共 {len(groups)} 只股票，使用 {n_jobs} 个进程并行计算...")

    with multiprocessing.Pool(processes=n_jobs) as pool:
        parts = pool.map(_calc_stock_alpha158_worker, groups, chunksize=max(1, len(groups) // (n_jobs * 4)))

    result = pd.concat(parts, ignore_index=True)

    feat_cols = [c for c in result.columns if c not in ("ts_code", "trade_date")]
    return result[["ts_code", "trade_date"] + sorted(feat_cols)]


def calc_and_save_next_volatility(merged_df: pd.DataFrame, output_csv: Path = OUTPUT_NEXT_VOL_CSV) -> pd.DataFrame:
    """基于复权后的 merged_df 计算每只股票的次日波动率并落盘。"""
    print("\n[3-3] 计算次日波动率并输出...")

    required = {"ts_code", "trade_date", "open", "high", "low", "close"}
    missing = required - set(merged_df.columns)
    if missing:
        raise ValueError(f"无法计算波动率，merged_df 缺少列: {sorted(missing)}")

    base = merged_df.copy()
    base["trade_date"] = pd.to_datetime(base["trade_date"], errors="coerce")
    for col in ["open", "high", "low", "close"]:
        base[col] = pd.to_numeric(base[col], errors="coerce")
    base = base.dropna(subset=["ts_code", "trade_date", "open", "high", "low", "close"]).copy()
    base = base.sort_values(["ts_code", "trade_date"]).reset_index(drop=True)

    groups = [(code, sub) for code, sub in base.groupby("ts_code", sort=False)]
    if not groups:
        out = pd.DataFrame(columns=["trade_date", "ts_code", "instrument", "close", "next_vol"])
    else:
        n_jobs = max(1, multiprocessing.cpu_count() // 2)
        n_jobs = min(n_jobs, len(groups))

        print(f"    共 {len(groups)} 只股票，使用 {n_jobs} 个进程并行计算...")

        if n_jobs == 1:
            rows = [_calc_next_vol_worker(item) for item in groups]
        else:
            with multiprocessing.Pool(processes=n_jobs) as pool:
                rows = pool.map(
                    _calc_next_vol_worker,
                    groups,
                    chunksize=max(1, len(groups) // (n_jobs * 4)),
                )

        rows = [row for row in rows if row is not None]
        out = pd.DataFrame(rows)

    if out.empty:
        print("    [警告] 次日波动率结果为空，未生成有效行")
    else:
        # 次日价格带（对数正态分布分位数参考）
        c = out["close"]
        s = out["next_vol"]
        out["high_ref"]      = c * np.exp( 0.80 * s)   # 高点参考  (~80% 单侧)
        out["low_ref"]       = c * np.exp(-0.80 * s)   # 低点参考
        out["strong_resist"] = c * np.exp( 1.28 * s)   # 强压力   (~90% 单侧)
        out["strong_support"] = c * np.exp(-1.28 * s)  # 强支撑
        out["risk_upper"]    = c * np.exp( 1.65 * s)   # 风险上沿  (~95% 单侧)
        out["risk_lower"]    = c * np.exp(-1.65 * s)   # 风险下沿
        out = out.sort_values("next_vol", ascending=False).reset_index(drop=True)
    output_csv.parent.mkdir(parents=True, exist_ok=True)
    out.to_csv(output_csv, index=False)
    print(f"    已保存: {output_csv} (rows={len(out)})")
    return out


# ============================================================
# 5. 主流程
# ============================================================
def run_once(
    market: str = "all",
    n_window: int = DEFAULT_N_WINDOW,
    n_threshold: float = DEFAULT_N_THRESHOLD,
    output_dir: Path = N_PATTERN_OUTPUT_DIR,
    fast_reverse_today: bool = False,
    fast_reverse_days: int = 3,
) -> pd.DataFrame:
    print("=" * 60)
    print("市场最新 100 日数据 + N 型指标")
    print("=" * 60)

    tushare_df = fetch_tushare_daily()
    akshare_df = fetch_akshare_spot()
    merged_df = merge_data(tushare_df, akshare_df)
    merged_df = maybe_filter_index_constituents(merged_df, market=market)
    merged_df = apply_forward_adjustment(merged_df)

    build_n_pattern_outputs(
        merged_df,
        window=n_window,
        threshold=n_threshold,
        output_dir=output_dir,
        fast_reverse_today=fast_reverse_today,
        fast_reverse_days=fast_reverse_days,
    )
    return merged_df


def run_daemon(
    market: str = "all",
    n_window: int = DEFAULT_N_WINDOW,
    n_threshold: float = DEFAULT_N_THRESHOLD,
    interval_minutes: int = DEFAULT_DAEMON_INTERVAL_MINUTES,
    output_dir: Path = N_PATTERN_OUTPUT_DIR,
    fast_reverse_today: bool = False,
    fast_reverse_days: int = 3,
) -> None:
    print(f"[daemon] 启动常驻任务，交易时段每 {interval_minutes} 分钟刷新一次")
    if not TUSHARE_TOKEN:
        raise ValueError("daemon 模式需要 TUSHARE_TOKEN 才能判定交易日")

    import tushare as ts

    ts.set_token(TUSHARE_TOKEN)
    pro = ts.pro_api()

    while True:
        now = datetime.now(SHANGHAI_TZ)
        today_str = now.strftime("%Y%m%d")
        trade_days = _get_trade_days_sse_open_cached(pro, today_str=today_str, lookback=10)
        is_trade_day = today_str in trade_days

        if now.weekday() >= 5 or not is_trade_day:
            sleep_seconds = _next_trading_sleep_seconds(now, interval_minutes)
            print(f"[daemon] 当前不是交易日，休眠 {int(sleep_seconds)} 秒")
            time.sleep(sleep_seconds)
            continue

        if not _is_shanghai_trading_session(now):
            sleep_seconds = _next_trading_sleep_seconds(now, interval_minutes)
            print(f"[daemon] 当前不在交易时段，休眠 {int(sleep_seconds)} 秒")
            time.sleep(sleep_seconds)
            continue

        try:
            run_once(
                market=market,
                n_window=n_window,
                n_threshold=n_threshold,
                output_dir=output_dir,
                fast_reverse_today=fast_reverse_today,
                fast_reverse_days=fast_reverse_days,
            )
        except Exception:
            LOGGER.exception("daemon 运行失败")

        now = datetime.now(SHANGHAI_TZ)
        sleep_seconds = _next_trading_sleep_seconds(now, interval_minutes)
        print(f"[daemon] 下一次刷新前休眠 {int(sleep_seconds)} 秒")
        time.sleep(sleep_seconds)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Fetch market data and generate daily N-pattern outputs.")
    parser.add_argument("--market", default="all", help="Index constituent filter: all / 300 / 500 / 1000 / csi300...")
    parser.add_argument("--n-window", type=int, default=DEFAULT_N_WINDOW, help="Trailing bars used for N-pattern detection")
    parser.add_argument("--n-threshold", type=float, default=DEFAULT_N_THRESHOLD, help="ZigZag threshold for N-pattern detection")
    parser.add_argument("--n-output-dir", default=str(N_PATTERN_OUTPUT_DIR), help="Directory for N-pattern outputs")
    parser.add_argument("--fast-reverse-today", action="store_true", help="Fast mode: only output latest trade-day N-signal flips (positive<->reverse)")
    parser.add_argument("--fast-reverse-days", type=int, default=3, help="Fast mode lookback trading days for transition scan")
    parser.add_argument("--daemon", action="store_true", help="Keep running and refresh during trading sessions")
    parser.add_argument("--interval-minutes", type=int, default=DEFAULT_DAEMON_INTERVAL_MINUTES, help="Refresh interval in daemon mode")
    return parser.parse_args()


if __name__ == "__main__":
    setup_logging()
    args = parse_args()
    try:
        output_dir = Path(args.n_output_dir).expanduser()
        if args.daemon:
            run_daemon(
                market=args.market,
                n_window=args.n_window,
                n_threshold=args.n_threshold,
                interval_minutes=args.interval_minutes,
                output_dir=output_dir,
                fast_reverse_today=args.fast_reverse_today,
                fast_reverse_days=args.fast_reverse_days,
            )
        else:
            run_once(
                market=args.market,
                n_window=args.n_window,
                n_threshold=args.n_threshold,
                output_dir=output_dir,
                fast_reverse_today=args.fast_reverse_today,
                fast_reverse_days=args.fast_reverse_days,
            )
    except Exception:
        LOGGER.exception("脚本执行失败")
        sys.exit(1)