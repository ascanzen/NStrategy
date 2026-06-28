# NStrategy

ZigZag N-pattern strategy research for CSI300 stocks.

## Strategy

The reference signal logic comes from `strategyZigZag.py`:

- Positive N pattern: buy or keep holding.
- Reverse N pattern: sell.
- Base universe: dynamic CSI300 constituents from local qlib data.
- Trading universe: each day rank CSI300 stocks by total amount, then trade the top 10%.
- Backtest frequency: daily.
- Portfolio construction: long-only, equal-weight active holdings.
- Return timing: signals are calculated with same-day OHLC data and applied to next-day close-to-close returns.
- Costs: no fees or slippage.

Liquidity filter:

- `amount_field = amount`
- Ranking rule: amount descending.
- `LIQUIDITY_FILTER_PCT=0.1` keeps the best 10%; set it to `1.0` to disable the filter.

## Common Commands

Compile `thiszigzag` for the active Python:

```bash
make build-zigzag
```

Run the CSI300 backtest:

```bash
make backtest
```

Run with custom parameters:

```bash
make backtest YEARS=5 THRESHOLD=0.002 OUTPUT_DIR=outputs_5y
```

Run without the liquidity filter:

```bash
make backtest LIQUIDITY_FILTER_PCT=1.0
```

Generate daily positive-N / reverse-N signal files for all stocks:

```bash
make zigzag-signals
```

Generate signals for a custom stock universe or date range:

```bash
make zigzag-signals \
  SIGNAL_INSTRUMENTS=/Users/renxg/.qlib/qlib_data/cn_data/instruments/csi300.txt \
  SIGNAL_YEARS=5 \
  SIGNAL_OUTPUT_DIR=outputs/zigzag_signals_csi300_5y
```

Run the script directly:

```bash
python3 backtest_zigzag_csi300.py \
  --qlib-dir /Users/renxg/.qlib/qlib_data/cn_data \
  --instruments /Users/renxg/.qlib/qlib_data/cn_data/instruments/csi300.txt \
  --output-dir outputs \
  --years 10 \
  --window 60 \
  --threshold 0.001 \
  --benchmark sh000300 \
  --liquidity-filter-pct 0.1 \
  --amount-field amount
```

Clean generated extension build files:

```bash
make clean-zigzag
```

Clean backtest outputs:

```bash
make clean-outputs
```

## Backtest Result

Data source: `/Users/renxg/.qlib/qlib_data/cn_data`

Date range: `2016-04-29` to `2026-04-29`

Filter: CSI300 daily constituents, top 10% by `amount`.

| Metric | ZigZag Strategy | CSI300 |
| --- | ---: | ---: |
| Final NAV | 1.8834 | 1.5238 |
| Total return | 88.34% | 52.38% |
| Annualized return | 6.79% | 4.47% |
| Max drawdown | -69.07% | -45.60% |
| Annualized volatility | 30.41% | 18.21% |
| Sharpe, rf=0 | 0.37 | 0.33 |

Other run stats:

- Trading days: 2,428
- Loaded symbols: 627
- Average tradable count after filter: 29.8
- Average held count: 10.6
- Max held count: 25
- Buy signals: 3,660
- Sell signals: 114
- Forced universe/filter exits: 3,536

Generated files:

- `outputs/zigzag_csi300_nav.csv`
- `outputs/zigzag_csi300_summary.json`
- `outputs/zigzag_csi300_nav.svg`

## Daily N-Pattern Signal Files

Command:

```bash
make zigzag-signals
```

Default output directory: `outputs/zigzag_signals_all`

Default universe: `/Users/renxg/.qlib/qlib_data/cn_data/instruments/all.txt`

Default window: latest 2 years, using `WINDOW=60` and `THRESHOLD=0.001`.

Generated files:

- `zigzag_n_events.csv`: compact event table. It only contains fresh positive-N or reverse-N signals.
- `zigzag_n_daily_lists.csv`: one row per trading day with pipe-separated positive-N and reverse-N stock lists.
- `zigzag_n_daily_index.json`: strategy-friendly date index for quick filtering.
- `zigzag_n_summary.json`: run metadata and event counts.

Signal convention:

| Field value | Meaning | Typical strategy use |
| --- | --- | --- |
| `signal = 1` / `signal_name = positive_n` | Positive N pattern | Inclusion list, keep-holding filter, or candidate whitelist |
| `signal = -1` / `signal_name = reverse_n` | Reverse N pattern | Exclusion list, sell filter, or candidate blacklist |
| Missing row in `events.csv` | No fresh signal for that stock/date | Do not change filter state from this file alone |

`zigzag_n_events.csv` fields:

| Column | Description |
| --- | --- |
| `date` | Trading day when the fresh signal appears |
| `symbol` | Uppercase qlib symbol, such as `SH600000` |
| `signal` | `1` for positive N, `-1` for reverse N |
| `signal_name` | `positive_n` or `reverse_n` |
| `close`, `low`, `high` | Signal-day adjusted qlib prices |
| `pivot_count` | Number of ZigZag pivots found in the trailing window |
| `window` | Number of trailing bars used by the signal, default `60` |
| `threshold` | ZigZag threshold, default `0.001` |
| `lookback_start`, `lookback_end` | Date range used to calculate the signal |

Load only positive-N stocks for another strategy:

```python
import json
from pathlib import Path

payload = json.loads(Path("outputs/zigzag_signals_all/zigzag_n_daily_index.json").read_text())
signals = payload["signals"]

trade_date = "2026-04-29"
positive_n = set(signals[trade_date]["positive_n"])

candidate_symbols = ["SH600000", "SH600519", "SZ000001", "SZ300750"]
filtered = [symbol for symbol in candidate_symbols if symbol in positive_n]
print(filtered)
```

Load the compact event table:

```python
import pandas as pd

events = pd.read_csv("outputs/zigzag_signals_all/zigzag_n_events.csv")
positive_today = events[(events["date"] == "2026-04-29") & (events["signal"] == 1)]
print(positive_today[["date", "symbol", "signal_name", "close"]].head())
```

A fuller annotated example is available at `examples/load_zigzag_signals.py`.

## N Pattern Service

This repository now includes a containerized service for the market cross-section fetch + N-pattern refresh workflow.

Outputs are written to `outputs/n_pattern/`:

- `n_daily_signals.csv`: one row per stock per trading day, including `n_signal`, `n_signal_name`, and `n_is_reversal`.
- `n_events.csv`: only rows where a fresh positive-N or reverse-N signal appears.
- `n_latest_signals.csv`: the latest trading-day snapshot for downstream consumers.
- `n_daily_index.json`: date-indexed positive-N / reverse-N symbol lists.
- `n_summary.json`: run metadata, counts, and file locations.
- `svg/<trade_date>/`: per-signal SVG charts.

Fast transition mode (only direction flips on latest trade day):

- Condition: previous trade day is `positive_n` and latest is `reverse_n`, or previous is `reverse_n` and latest is `positive_n`.
- Range: recent 3 trading days by default, can be adjusted by `--fast-reverse-days`.
- Command: `python3 get_most_cross_section_data.py --market all --fast-reverse-today --fast-reverse-days 3`
- Outputs:
  - `n_transition_recent.csv` (primary)
  - `n_transition_recent_summary.json` (primary)
  - `n_reverse_today.csv` (legacy-compatible alias)
  - `n_reverse_today_summary.json` (legacy-compatible alias)
  - `svg/<trade_date>/` only for changed symbols in this mode

Local run:

```bash
export TUSHARE_TOKEN=your_token_here
python3 get_most_cross_section_data.py --market all --n-window 60 --n-threshold 0.001
```

Daemon mode inside Docker:

```bash
export TUSHARE_TOKEN=your_token_here
docker compose up -d --build
```

The service runs only during Shanghai trading sessions and refreshes every 15 minutes. Logs are written to `logs/cross_section_service.log` and also streamed to the container console.

## N Pattern Browser

The repository includes a FastAPI + Vue browser for `outputs/n_pattern/`.

Local backend:

```bash
pip install -r requirements.txt
make n-pattern-api
```

Local frontend:

```bash
cd frontend
npm install
cd ..
make n-pattern-web
```

Open `http://localhost:5173`.

Container deployment:

```bash
cp .env.example .env
# edit .env and set TUSHARE_TOKEN
make n-pattern-compose
```

Open `http://localhost:8080`. API is also exposed at `http://localhost:8000`.

Production deployment:

```bash
cp .env.example .env
# edit .env:
#   TUSHARE_TOKEN=...
#   API_BIND=127.0.0.1
#   WEB_HTTP_PORT=8080
#   API_PORT=8000
make prod-deploy
```

Production operations:

```bash
make prod-status
make prod-health
make prod-logs
make prod-restart
make prod-down
```

The production deploy script is `scripts/deploy_prod.sh`. It checks Docker, validates `.env`, creates `data/`, `outputs/`, and `logs/`, builds the containers, starts the refresh daemon + API + web services, then checks `http://127.0.0.1:${API_PORT}/api/health`.

Browser features:

- Recent 3-day or 10-day N-pattern switch list.
- Date and switch-type filters: `positive_to_reverse`, `reverse_to_positive`.
- Stock search by code. Pinyin search is supported when an alias file is available.
- SVG chart preview from `outputs/n_pattern/svg/`.
- XLSX export with the same filters as the current view.

Optional pinyin alias file:

```csv
ts_code,instrument,name,pinyin,abbr
000001.SZ,SZ000001,平安银行,ping an yin hang,payh
```

Save it as `data/stock_aliases.csv`, or set `STOCK_ALIAS_FILE=/path/to/stock_aliases.csv` for the API service.

Useful API paths:

- `GET /api/health`
- `GET /api/summary`
- `GET /api/transitions?days=3&transition=all&q=000001`
- `GET /api/export.xlsx?days=10&transition=positive_to_reverse`
- `GET /api/svg/<relative-svg-path>`
