# NStrategy

ZigZag N-pattern strategy research for CSI300 stocks.

## Strategy

The reference signal logic comes from `strategyZigZag.py`:

- Positive N pattern: buy or keep holding.
- Reverse N pattern: sell.
- Universe: dynamic CSI300 constituents from local qlib data.
- Backtest frequency: daily.
- Portfolio construction: long-only, equal-weight active holdings.
- Return timing: signals are calculated with same-day OHLC data and applied to next-day close-to-close returns.
- Costs: no fees or slippage.

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

Run the script directly:

```bash
python3 backtest_zigzag_csi300.py \
  --qlib-dir /Users/renxg/.qlib/qlib_data/cn_data \
  --instruments /Users/renxg/.qlib/qlib_data/cn_data/instruments/csi300.txt \
  --output-dir outputs \
  --years 10 \
  --window 60 \
  --threshold 0.001 \
  --benchmark sh000300
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

| Metric | ZigZag Strategy | CSI300 |
| --- | ---: | ---: |
| Final NAV | 1.4563 | 1.5238 |
| Total return | 45.63% | 52.38% |
| Annualized return | 3.98% | 4.47% |
| Max drawdown | -45.46% | -45.60% |
| Annualized volatility | 18.85% | 18.21% |
| Sharpe, rf=0 | 0.30 | 0.33 |

Other run stats:

- Trading days: 2,428
- Loaded symbols: 627
- Average held count: 142.5
- Max held count: 242
- Buy signals: 4,149
- Sell signals: 3,861
- Forced membership exits: 177

Generated files:

- `outputs/zigzag_csi300_nav.csv`
- `outputs/zigzag_csi300_summary.json`
- `outputs/zigzag_csi300_nav.png`
