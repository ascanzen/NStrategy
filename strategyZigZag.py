# encoding: UTF-8
"""
zigzag 交易策略
后续改用修改版本的zigzag
"""
from cta_strategy.ctaTemplatePatch.ctaTemplatePatternPatch import (
    CtaTemplatePatternPatch,
)
from vnpy.app.cta_strategy import (
    ArrayManager,
    BarData,
    BarGenerator,
    CtaTemplate,
    Direction,
    OrderData,
    StopOrder,
    TickData,
    TradeData,
)
from vnpy.trader.object import Interval

from thiszigzag import compute_segment_returns, peak_valley_pivots
import numpy as np
from loguru import logger
from datetime import timedelta, datetime
import pandas as pd
import mplfinance as mpf
from functools import reduce
import matplotlib

threshold = 0.001


def rend_signal(am: ArrayManager, title=""):
    """绘制zigzag信号"""
    df = pd.DataFrame(
        {
            "Date": am.datetime_array,
            "Open": am.open_array,
            "High": am.high_array,
            "Low": am.low_array,
            "Close": am.close_array,
            "Volume": am.volume_array,
        }
    )
    df.set_index(["Date"], inplace=True)  # 将日期列作为行索引
    df = (
        df.sort_index()
    )  # 倒序，因为Tushare的数据是最近的交易日数据显示在DataFrame上方，倒序后方能保证作图时X轴从左到右时间序列递增。

    # 提取收盘价，最高价，最低价数据
    Close = df.Close
    High = df.High
    Low = df.Low

    matplotlib.pyplot.switch_backend("Agg")

    s = mpf.make_mpf_style(
        base_mpf_style="nightclouds", rc={"font.family": "SimHei"}
    )  # 解决mplfinance绘制输出中文乱码

    X = Close
    pivots = peak_valley_pivots(Low, High, threshold, -threshold)

    # # use high and low to draw zigzag，merge high pivot ，low pivot
    # high_pivots = peak_valley_pivots(High, threshold, -threshold)
    # low_pivots = peak_valley_pivots(Low, threshold, -threshold)

    # pivots = np.where(high_pivots == 1, 1, 0) + np.where(
    #     low_pivots == -1, -1, 0
    # )

    points = np.nonzero(pivots)[0]

    # list(datetime,price)
    seq_of_points = []

    lines = []
    for p1, p2 in list(zip(iter(points[:-1]), iter(points[1:]))):
        # get the n-th index of the dataframe
        lines.append((df.index[p1], df.index[p2]))

    for p in points:
        seq_of_points.append(
            (df.index[p], High[p] if pivots[p] == 1 else Low[p])
        )

    mpf.plot(
        df,
        type="candle",
        style=s,
        title=title,
        # addplot=add_plot,
        mav=(5, 10, 20),
        volume=True,
        # tlines=lines,
        alines=seq_of_points,
        savefig=dict(fname=title, dpi=200, pad_inches=0.1),
    )


########################################################################
class ZigZagStrategy(CtaTemplatePatternPatch):
    class_name = "ZigZagStrategy"
    author = "Port"

    kLineCycle = 1
    arraySize = 60
    render_png = False
    
    # 参数列表，保存了参数的名称
    parameters = CtaTemplatePatternPatch.parameters + []

    # ----------------------------------------------------------------------
    def __init__(self, cta_engine, strategy_name, vt_symbol, setting):
        """"""
        super().__init__(cta_engine, strategy_name, vt_symbol, setting)
        self.trade_state = (False, 0, 0, None, None,0,0,0,0)

    # ----------------------------------------------------------------------
    def on_bar(self, bar: BarData):
        """K线更新"""
        super(ZigZagStrategy, self).on_bar(bar)

    # ----------------------------------------------------------------------
    def onXminBar(self, bar):
        """收到X分钟K线"""
        super(ZigZagStrategy, self).onXminBar(bar)

        if not self.trading:
            return
        if not self.am.inited:
            return
        
        if self.render_png:
            if self.lastDatetime > datetime.today() - timedelta(days=1) :
                rend_signal(
                    self.am,
                    f'./zigzag_{self.vt_symbol}_{self.lastDatetime.strftime("%Y%m%dT%H%M%S")}.png',
                )        

            
        # 清理状态
        if self.trade_state[0]:
            # 输出最后一根K线的交易信息
            if self.lastBar.interval == Interval.WEEKLY:
                windows = 7*4
            elif self.lastBar.interval == Interval.DAILY:
                windows = 7
            else:
                windows = 2
                        
            if self.trade_state[0] and (
                bar.datetime - self.trade_state[3]
            ) > timedelta(days=windows):
                self.trade_state = (False, 0, 0, None, None,0,0,0,0)

        # 发出状态更新事件
        if self.trading:
            # method one, use close
            close = self.am.close
            high = self.am.high
            low = self.am.low

            # check unexpected data
            if not np.any(high) or not np.any(low) or not np.any(close):
                return

            pivotV = peak_valley_pivots(
                self.am.low, self.am.high, threshold, -threshold
            )

            indexs = np.nonzero(pivotV)[0]

            direction = 0
            if len(indexs) > 3:
                # get last not zero value index
                idx0, idx1, idx2, idx3 = indexs[-4:]

                # 计算N型方向
                if pivotV[-1] == 1:
                    # 正N检测
                    if high[idx3] > high[idx1] and low[idx2] > low[idx0]:
                        # logger.info(pivotV)
                        # logger.info(
                        #     f"{self.lastDatetime} 检测到正N {idx0} {idx1} {idx2} {idx3} [ {close[idx0]}, {close[idx1]}, {close[idx2]}, {close[idx3]} ]"
                        # )
                        direction = 1
                elif pivotV[-1] == -1:
                    # 负N检测
                    if low[idx3] < low[idx1] and high[idx2] < high[idx0]:
                        # logger.info("检测到反N")
                        direction = -1

                if self.pos == 0:
                    # 空仓，开新仓
                    self.filterTrade(direction)
                elif self.direction == direction and pivotV[-1] != 0:
                    # 新的加仓信息
                    self.filterTrade(direction)
                else:
                    # 持仓相反，开仓
                    if self.direction * direction < 0:
                        self.clearOrder()
                    else:
                        if self.direction == 1:

                            # 如果不前高点是正N，那么c20是idx1，c100是idx2
                            # c20是部分平仓线，c100是清仓线
                            if pivotV[idx3] == 1:
                                c20 = high[idx1]
                                c100 = low[idx2]
                            else:
                                c20 = high[idx0]
                                c100 = low[idx1]
                            
                            # 如果当前价格低于c20，但是高于c100，那么卖出一半
                            if (
                                low[-1] < c20
                                and low[-1] > c100
                                and abs(self.pos) == self.fixed_size
                            ):
                                self.trade(-self.pos / 2)
                                self.output_signal("sale.part",-1)
                            elif low[-1] < c100:
                                self.clearOrder()
                            # if low[-1] < high[idx2]:
                            #     self.clearOrder()
                            #     self.output_signal("sale.clear")
                            else:
                                return

                        elif self.direction == -1:
                            if pivotV[idx3] == -1:
                                c20 = low[idx1]
                                c100 = high[idx2]
                            else:
                                c20 = low[idx0]
                                c100 = high[idx1]
                            if (
                                low[-1] > c20
                                and low[-1] < c100
                                and abs(self.pos) == self.fixed_size
                            ):
                                self.trade(-self.pos / 2)
                                self.output_signal("cover.part",1)
                            elif low[-1] > c100:
                                self.clearOrder()
                            else:
                                return
                            
    # ----------------------------------------------------------------------
    def filterTrade(self, direction):
        """对指定方向的交易进行过滤"""
        if direction == 0:
            return

        self.output_signal("buy" if direction == 1 else "short", direction)

        self.fixed_size = 100000 // self.lastPrice

        if direction == -1:
            # 空头无法做空，两股做标记
            self.trade(2 * direction)
        else:
            self.trade(self.fixed_size * direction)
        self.put_event()

        

    # ----------------------------------------------------------------------
    def output_signal(self, signal_type, direction):
        """输出信号"""
        close = self.am.close
        high = self.am.high
        low = self.am.low

        # check unexpected data
        if not np.any(high) or not np.any(low) or not np.any(close):
            return

        pivotV = peak_valley_pivots(
            self.am.low, self.am.high, threshold, -threshold
        )

        indexs = np.nonzero(pivotV)[0]

        if len(indexs) < 4:
            return
        
        # get last not zero value index
        idx0, idx1, idx2, idx3 = indexs[-4:]
        # 计算N型方向
        if pivotV[-1] == 1:    
            a,b,c = low[idx0], high[idx1], low[idx2]
        else:
            a,b,c = high[idx2], low[idx1], high[idx0]    

        
            
        # 记录交易信号描述信息
        self.trade_state = (
            True,
            signal_type,
            self.lastBar.close_price,
            self.lastBar.datetime,
            self.lastBar.vt_symbol,
            direction,
            a,b,c
        )
        
        if self.render_png:
            rend_signal(
                self.am,
                f'./zigzag_{self.vt_symbol}_{self.lastDatetime.strftime("%Y%m%dT%H%M%S")}.{signal_type}.png',
            )

    def clearOrder(self):
        """清仓"""
        self.output_signal("clear.all", -self.direction)
        return super().clearOrder()

    @property
    def extra(self):
        return {
            "strategy_name": self.strategy_name,
            "vt_symbol": self.vt_symbol,
            "trade_state": self.trade_state,
        }