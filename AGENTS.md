# AGENTS.md

Quant research repo (docs/comments/output in Chinese). Two distinct areas:

- `strategies/` — backtrader backtest framework; currently one family, `au9999_cta` (AU9999 gold / 518880.SH ETF).
- `experiments/`, `tools/` — standalone bond/rates research scripts and utilities, not wired into the strategy framework.

No tests, CI, or packaging. Verification = run a backtest and compare numbers against the docs.

## Environment

- Python 3.12, conda env `fxincome` (`C:\Users\panda\miniforge3\envs\fxincome`). 
- No requirements file. Installed: backtrader, pandas, numpy, matplotlib, python-dotenv, iFinDAPI, financepy, scipy, openpyxl.
- Some `experiments/` scripts import packages that are NOT installed (plotly, statsmodels, seaborn, tqdm, WindPy) and fail as-is.
- `.env` (gitignored, local only) holds iFinD credentials; never commit or print them. Data-update commands fail on a fresh clone without it.

## Commands (run from repo root; `-m` is required — modules use package-relative imports)

- All strategies: `python -m strategies.au9999_cta.run`
- Selected strategy: `python -m strategies.au9999_cta.run --strategies s1a_ma_cross_trailing s1c_ma_cross_intraday` (names = keys of `STRATEGIES` in `strategies/au9999_cta/__init__.py`)
- Other symbol: add `--csv data/518880.SH.csv` (output goes to `results/518880.SH/`, not the default dir)
- Window comparison (bull/bear/sideways windows; default B&H/s1a/s1c, any strategy set via `--strategies`): `python -m strategies.au9999_cta.compare_windows`
- Update committed market data via iFinD: `python -m strategies.common.data_loader [au9999|518880] [--dry-run] [--source auto|sdk|http]`
- `.vscode/` pytest config points at a nonexistent `tests/` dir

## Architecture

- `strategies/common/` shared by all families: `constants.py` (all global params), `data_loader.py`, `engine.py` (Cerebro setup), `base.py` (`LongOnlyStrategyBase`), `indicators.py`, `performance.py`, `feeds.py`, `observers.py`.
- `strategies/au9999_cta/`: one file per strategy + `run.py` + `compare_windows.py`; registry/backtest window in `__init__.py`.
- New strategy family = new subpackage next to `au9999_cta` reusing `common/` (see `strategies/__init__.py`).
- `strategies/**/results/` and all `*.png` are gitignored; run outputs are local artifacts, not committed.
- `experiments/Callable_Bond_Valuation/` scripts import siblings by bare module name — run with that directory as cwd (`cd` there first), unlike `strategies/`.

## Strategy conventions

- Long-only: exits always `self.close()`; never open shorts even when the spec mentions bearish signals.
- Signal confirmed at bar close, fill next open. Engine uses `cheat_on_open=True`; size is computed in `next_open` from the real open price. In `next()` use `buy_next_open()` / `sell_next_open()`, not raw `buy()/close()`.
- Global parameters (costs, sizing, initial cash, fund mode) live in `common/constants.py`; do not hardcode them in strategy files.
- `s1c_ma_cross_intraday` (`data_kind = "minute_snapshot"`): SMA/ATR/cross indicators are precomputed in pandas in `load_minute_snapshots` because backtrader indicators are not updated inside `next_open`. Changing s1a periods (SMA 30/90, ATR 14) requires syncing that precompute.
- Keep module docstrings current: every strategy file header documents logic, usage, and the latest backtest figures (returns/Sharpe/trades), and `docs/trade_strat/au9999_cta.md` is the authoritative spec. Logic/param changes should update both, plus `compare_windows.py` expectations if the window metrics change.

## Data

- Committed CSVs: `data/AU9999_Daily.csv` (from 2002), `data/518880.SH.csv` (daily), `data/518880.sh.minutes.csv` (minute bars, s1c only). Format `date,open,high,low,close,volume,amt`; AU9999 OHLC in 元/克, amt in 亿元;518880 OHLC in 元/份, amt in 亿元; 518880.minutes OHLC in 元/份, `amt` in 元.
- `update_daily` appends only rows after the CSV's last date (market-close-aware; never writes an unclosed day). `--dry-run` prints rows without writing.
- Minute snapshots are built at 14:45 signal, 14:47 fill, 15:00 close by `build_minute_snapshots`; don't "fix" the odd `open` semantics there.

## Style

- Docstrings, comments, prints, and reports are Chinese; follow the existing module-docstring pattern (usage + backtest numbers).
- Commit style: conventional prefixes with scope, e.g. `feat:`, `refactor:`, `docs(au9999_cta):`.
