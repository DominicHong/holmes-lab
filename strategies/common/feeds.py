"""公用数据源。"""

from __future__ import annotations

import backtrader as bt


class IntradaySnapshotData(bt.feeds.PandasData):
    """s1c 盘中策略专用的日频快照数据源（由 strategies.common.data_loader.load_minute_snapshots 生成）。

    每根“日 K 线”对应一个交易日：

    - open  = 信号时点后 2 分钟的成交参考价（14:47），回测中按 open ± 滑点成交；
    - high/low = 9:30 ~ 14:47 的高低点（供撮合滑点边界使用）；
    - close = 15:00 收盘价（净值估值口径）；
    - signal_close / sig_high / sig_low = 14:45 信号快照；
    - sma_fast / sma_slow / atr / cross_down = 预计算指标。
    """

    lines = ("signal_close", "sig_high", "sig_low", "sma_fast", "sma_slow", "atr", "cross_down")
    params = (
        ("signal_close", -1),
        ("sig_high", -1),
        ("sig_low", -1),
        ("sma_fast", -1),
        ("sma_slow", -1),
        ("atr", -1),
        ("cross_down", -1),
    )
