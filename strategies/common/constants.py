"""全局常量与默认配置。

所有策略共用的路径、账户参数、交易成本、仓位规则集中在本模块，
新增策略时只允许覆盖策略自身参数（策略类 params），不要另行硬编码全局常量。
"""

from pathlib import Path

# ---------- 路径 ----------
PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = PROJECT_ROOT / "data"

AU9999_DAILY_CSV = DATA_DIR / "AU9999_Daily.csv"

# ---------- 账户 ----------
INITIAL_CASH = 1_000_000.0

# ---------- 交易成本（单边） ----------
COMMISSION_RATE = 0.0002  # 手续费率，按成交金额计
SLIPPAGE_RATE = 0.0002    # 滑点率，按成交价计

# ---------- 资金模式 ----------
# fund mode 下 backtrader 以“基金净值”口径跟踪收益：
# 净值起点为 FUND_START_VALUE，入金/出金自动折算成份额，不受资金申赎干扰。
FUND_MODE = True
FUND_START_VALUE = 100.0

# ---------- 仓位规则 ----------
# "fixed_grams"   : 每次固定买入 FIXED_GRAMS 克
# "percent_equity": 每次按总资金 POSITION_PERCENT 折算克数
# "risk_budget"   : 每次按 RISK_PER_TRADE 风险预算 / 每克止损距离 折算克数
POSITION_MODE = "percent_equity"
FIXED_GRAMS = 100.0
POSITION_PERCENT = 0.95
RISK_PER_TRADE = 0.02
MIN_TRADE_GRAMS = 1.0       # 最小交易克数（按此取整）
SIZE_CASH_BUFFER = 0.02     # 按比例开仓时为次日跳空预留的现金缓冲

# ---------- 回测区间（None 表示使用数据文件全部区间） ----------
BACKTEST_START = None
BACKTEST_END = None

# ---------- 绩效口径 ----------
TRADING_DAYS_PER_YEAR = 252
RISK_FREE_RATE = 0.0
