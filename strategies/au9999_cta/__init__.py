"""AU9999 日频纯多头 CTA 策略集合（策略逻辑见 docs/trade_strat/au9999_cta.md）。"""

from pathlib import Path

from .buy_and_hold import BuyAndHold
from .s1a_ma_cross_trailing import MaCrossTrailingStop
from .s1b_vol_filtered_ma_cross import VolFilteredMaCross
from .s2_donchian_breakout import DonchianBreakout
from .s3_bollinger_squeeze import BollingerSqueeze
from .s4_keltner_breakout import KeltnerBreakout
from .s5_rsi_mean_reversion import RsiMeanReversion

PACKAGE_DIR = Path(__file__).resolve().parent
RESULTS_DIR = PACKAGE_DIR / "results"

# 本族默认回测区间（可用 run.py 的 --start/--end 覆盖）
BACKTEST_START = "2018-01-01"
BACKTEST_END = "2026-09-01"

STRATEGIES = {
    "buy_and_hold": BuyAndHold,
    "s1a_ma_cross_trailing": MaCrossTrailingStop,
    "s1b_vol_filtered_ma_cross": VolFilteredMaCross,
    "s2_donchian_breakout": DonchianBreakout,
    "s3_bollinger_squeeze": BollingerSqueeze,
    "s4_keltner_breakout": KeltnerBreakout,
    "s5_rsi_mean_reversion": RsiMeanReversion,
}

__all__ = [
    "BACKTEST_END",
    "BACKTEST_START",
    "BollingerSqueeze",
    "BuyAndHold",
    "DonchianBreakout",
    "KeltnerBreakout",
    "MaCrossTrailingStop",
    "RESULTS_DIR",
    "RsiMeanReversion",
    "STRATEGIES",
    "VolFilteredMaCross",
]
