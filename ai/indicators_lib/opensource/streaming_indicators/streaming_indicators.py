import numpy as np
import pandas as pd
from collections import deque

class RollingStat:
    '''Abstract Class - Used for functions which require computing stat on fixed window queue'''
    def __init__(self, period:int, func, points=None):
        assert period > 1, "Period needs to be greater than 1."
        self.period = period
        if(points is None): self.points = deque(maxlen=period)
        else: self.points = deque(points[-period:], maxlen=period)
        self.func = func
    def compute(self, point:float):
        points = (list(self.points) + [float(point)])[-self.period:]
        if(len(points) == self.period):
            return self.func(points)
        return None
    def update(self, point:float):
        self.points.append(float(point))
        return self.value
    @property
    def value(self):
        if(len(self.points) == self.period):
            return self.func(self.points)
        return None

class Max(RollingStat):
    '''Maximum in a rolling window'''
    def __init__(self, period:int, points=None):
        super().__init__(period=period, func=max, points=points)

class Min(RollingStat):
    '''Minimum in a rolling window'''
    def __init__(self, period:int, points=None):
        super().__init__(period=period, func=min, points=points)

class SMA(RollingStat):
    '''Simple Moving Average'''
    def __init__(self, period:int, points=None):
        super().__init__(period=period, func=np.mean, points=points)
        # TODO: Any efficient way rather than computing everytime?

class SD(RollingStat):
    '''Standard Deviation'''
    def __init__(self, period:int, points=None):
        super().__init__(period=period, func=np.std, points=points)
        # TODO: Any efficient way rather than computing everytime?

class EMA:
    '''Exponential Moving Average'''
    def __init__(self, period:int, smoothing_factor:int=2):
        self.period = period
        self.smoothing_factor = smoothing_factor
        self.mult = smoothing_factor / (1+period)
        self.points = deque(maxlen=period+1)
        self.value = None
    def compute(self, point:float):
        points = (list(self.points) + [float(point)])[-self.period:]
        if(len(points) == self.period):
            return np.mean(self.points) # Simple SMA
        elif(len(points) > self.period):
            return (point * self.mult) + (self.value * (1-self.mult))
        return None
    def update(self, point:float):
        self.points.append(point)
        if(len(self.points) == self.period):
            self.value = np.mean(self.points) # Simple SMA
        elif(len(self.points) > self.period):
            self.value = (point * self.mult) + (self.value * (1-self.mult))
        return self.value

class WMA:
    '''Weighted Moving Average'''
    def __init__(self, period:int):
        self.period = period
        self.points = deque(maxlen=period)
        self._den = (period*(period+1))//2
        self._weights = np.arange(1,period+1)
        self.value = None
    def compute(self, point:float):
        points = (list(self.points) + [float(point)])[-self.period:]
        if(len(points) == self.period):
            return sum(self._weights*points)/self._den
        return None
    def update(self, point:float):
        self.points.append(point)
        if(len(self.points) == self.period):
            self.value = sum(self._weights*self.points)/self._den
        return self.value

class SMMA:
    '''Smoothed Moving Average'''
    def __init__(self, period:int):
        assert period > 1, "Period needs to be greater than 1."
        self.period = period
        self.ema_period = period*2-1
        # https://stackoverflow.com/a/72533211/6430403
        self.ema = EMA(self.ema_period)
    def compute(self, point:float):
        return self.ema.compute(point)
    def update(self, point:float):
        self.value = self.ema.update(point)
        return self.value

class RMA:
    '''
        Moving average used in RSI.
        https://www.tradingview.com/pine-script-reference/v6/#fun_ta.rma
    '''
    def __init__(self, period:int):
        self._alpha = 1/period
        self._alpha_1 = 1-self._alpha
        self.points = deque(maxlen=period)
        self.rma = None
    @property
    def value(self):
        return self.rma
    def update(self, point:float):
        self.points.append(point)
        if(self.rma is None):
            self.rma = np.mean(self.points)
        else:
            self.rma = self._alpha * point + self._alpha_1 * self.rma
        self.rma = round(self.rma, 4)
        return self.rma

class VWAP:
    '''Volume Weighted Average Price'''
    def __init__(self, candles=None):
        '''
            tp = typical_price = (high+low+close)3
            tpv = tp * volume
            vwap = tpv.cumsum() / volume.cumsum()
            anchored from first candle.
        '''
        if(candles is not None):
            self.tpv_sum = ((candles['high']+candles['low']+candles['close'])/3 * candles['volume']).sum()
            self.vol_sum = candles['volume'].sum()
        else:
            self.tpv_sum = 0
            self.vol_sum = 0
    @staticmethod
    def _compute_vwap(tpv_sum, vol_sum):
        if(vol_sum > 0): return tpv_sum/vol_sum
        return None
    @property
    def vwap(self):
        return self._compute_vwap(self.tpv_sum, self.vol_sum)
    @property
    def value(self):
        return self.vwap
    def compute(self, candle):
        tpv_sum = self.tpv_sum + ((candle['high']+candle['low']+candle['close'])/3 * candle['volume'])
        vol_sum = self.vol_sum + candle['volume']
        return self._compute_vwap(tpv_sum, vol_sum)
    def update(self, candle):
        self.tpv_sum += ((candle['high']+candle['low']+candle['close'])/3 * candle['volume'])
        self.vol_sum += candle['volume']
        return self.vwap

class RSI:
    '''Relative Strength Index'''
    def __init__(self, period:int):
        self.period = period
        self._period_minus_1 = period-1
        self._period_plus_1 = period+1
        self.points = deque(maxlen=self._period_plus_1)
        self.losses = deque(maxlen=self._period_plus_1)
        self.gains = deque(maxlen=self._period_plus_1)
        self.avg_gain = None
        self.avg_loss = None
        self.rsi = None
        self.value = None
    def update(self, point:float):
        self.points.append(point)
        if(len(self.points) > 1):
            diff = self.points[-1] - self.points[-2]
            if(diff >= 0):
                self.gains.append(diff)
                self.losses.append(0)
            else:
                self.gains.append(0)
                self.losses.append(-diff)

            if(len(self.points) == self._period_plus_1):
                if(self.avg_gain is None):
                    self.avg_gain = np.mean(self.gains)
                    self.avg_loss = np.mean(self.losses)
                else:
                    self.avg_gain = ((self.avg_gain*(self._period_minus_1)) + self.gains[-1])/self.period
                    self.avg_loss = ((self.avg_loss*(self._period_minus_1)) + self.losses[-1])/self.period
                rs = self.avg_gain / self.avg_loss
                self.rsi = 100 - (100/(1+rs))
                self.value = self.rsi
        return self.value

class TRANGE:
    '''True Range'''
    def __init__(self):
        self.prev_close = None
        self.value = None
    def compute(self, candle):
        if(self.prev_close is None):
            return candle['high'] - candle['low']
        else:
            return max(
                candle['high'] - candle['low'],
                abs(candle['high'] - self.prev_close),
                abs(candle['low'] - self.prev_close)
            )
    def update(self, candle):
        self.value = self.compute(candle)
        self.prev_close = candle['close']
        return self.value


class CPR:
    '''Central Pivot Range'''
    '''Reference: https://medium.com/@anoobpaul/pivot-points-and-central-pivot-range-cpr-using-python-04c0a613738c'''
    def __init__(self):
        self.cpr = None
        self.bc = None
        self.tc = None
    def compute(self, candle):
        cpr = round((candle['high'] + candle['low'] + candle['close']) / 3.0, 2)
        bc = round (((candle['high'] + candle['low']) / 2.0),2)
        tc = round ((cpr + (cpr - bc)),2)
        return (cpr, bc, tc)
    @property
    def value(self):
        return self.cpr, self.bc, self.tc
    def update(self, candle):
        self.cpr, self.bc, self.tc = self.compute(candle)
        return self.value

class ATR:
    '''Average True Range'''
    def __init__(self, period, candles=None):
        self.period = period
        self.period_1 = period-1
        self.TR = TRANGE()
        if(candles is None):
            self.atr = 0 # initialised to 0, because values are added to it
            self.value = None
            self.count = 0
        else:
            from talib import ATR
            ta_atr = ATR(candles['high'],candles['low'],candles['close'],period)
            if(pd.notna(ta_atr.iloc[-1])):
                self.atr = ta_atr.iloc[-1]
                self.value = self.atr
            else:
                self.atr = 0
                self.value = None
            self.count = len(candles)
            self.TR.update(candles.iloc[-1])
    def compute(self, candle):
        tr = self.TR.compute(candle)
        if(self.count < self.period):
            return None
        elif(self.count == self.period):
            return (self.atr + tr)/self.period
        else:
            return (self.atr*self.period_1 + tr)/self.period
    def update(self, candle):
        self.count += 1
        tr = self.TR.update(candle)
        if(self.count < self.period):
            self.atr += tr
            return None
        if(self.count == self.period):
            self.atr += tr
            self.atr /= self.period
        else:
            self.atr = (self.atr*self.period_1 + tr)/self.period
        self.value = self.atr
        return self.value

class BBands:
    '''Bollinger Bands'''
    def __init__(self, period:int, stddev_mult:float, ma=SMA, points=None):
        self.period = period
        self.stddev_mult = stddev_mult
        if(isinstance(ma, type)): # if class
            self.MA = ma(self.period, points=points)
        else:
            self.MA = ma
        self.SD = SD(period, points=points)
    @property
    def middleband(self):
        return self.MA.value
    @property
    def upperband(self):
        if(self.SD.value is None): return None
        return self.MA.value + self.SD.value * self.stddev_mult
    @property
    def lowerband(self):
        if(self.SD.value is None): return None
        return self.MA.value - self.SD.value * self.stddev_mult
    @property
    def value(self):
        return (self.upperband, self.middleband, self.lowerband)
    def compute(self, point:float):
        ma = self.MA.compute(point)
        sd = self.SD.compute(point)
        if(ma is not None and sd is not None):
            middleband = ma
            upperband = ma + sd*self.stddev_mult
            lowerband = ma - sd*self.stddev_mult
            return (upperband, middleband, lowerband)
        return (None, None, None)
    def update(self, point:float):
        ma = self.MA.update(point)
        sd = self.SD.update(point)
        return self.value

class SuperTrend:
    def __init__(self, atr_length, factor, candles=None):
        self.factor = factor
        self.super_trend = 1
        if(candles is None):
            self.ATR = ATR(atr_length)
            self.lower_band = None
            self.upper_band = None
            self.final_band = None
        else:
            self.ATR = ATR(atr_length, candles=candles) # TODO: ATR is getting computed twice
            # Adapted from pandas_ta supertrend.py
            # https://github.com/twopirllc/pandas-ta/blob/main/pandas_ta/overlap/supertrend.py
            from talib import ATR as talib_ATR
            _open = candles['open']
            _high = candles['high']
            _low = candles['low']
            _close = candles['close']
            _median = 0.5 * (_high + _low) # hl2
            _fatr = factor * talib_ATR(_high, _low, _close, atr_length)
            _basic_upperband = _median + _fatr
            _basic_lowerband = _median - _fatr
            self.lower_band = _basic_lowerband.iloc[0]
            self.upper_band = _basic_upperband.iloc[0]
            for i in range(1,len(candles)):
                if self.super_trend == 1:
                    self.upper_band = _basic_upperband.iloc[i]
                    self.lower_band = max(_basic_lowerband.iloc[i], self.lower_band)
                    if _close.iloc[i] <= self.lower_band:
                        self.super_trend = -1
                else:
                    self.lower_band = _basic_lowerband.iloc[i]
                    self.upper_band = min(_basic_upperband.iloc[i], self.upper_band)
                    if _close.iloc[i] >= self.upper_band:
                        self.super_trend = 1
            if(self.super_trend == 1):
                self.final_band = self.lower_band
            else:
                self.final_band = self.upper_band
        self.value = (self.super_trend, self.final_band) # direction, value
                        
    def compute(self, candle):
        median = round((candle['high']+candle['low'])/2, 4)
        atr = self.ATR.compute(candle)
        if(atr is None):
            return None, None
        _fatr = self.factor * atr
        basic_upper_band = round(median + _fatr, 4)
        basic_lower_band = round(median - _fatr, 4)
        super_trend = self.super_trend
        if self.super_trend == 1:
            upper_band = basic_upper_band
            lower_band = max(basic_lower_band, self.lower_band) if self.lower_band is not None else basic_lower_band
            if candle['close'] <= self.lower_band: super_trend = -1
        else:
            lower_band = basic_lower_band
            upper_band = min(basic_upper_band, self.upper_band) if self.upper_band is not None else basic_upper_band
            if candle['close'] >= self.upper_band: super_trend = 1
        if(super_trend == 1):
            final_band = lower_band
        else:
            final_band = upper_band
        return (super_trend, final_band)
    def update(self, candle):
        median = round((candle['high']+candle['low'])/2, 4)
        atr = self.ATR.update(candle)
        if(atr is None):
            return None, None
        basic_upper_band = round(median + self.factor * atr, 4)
        basic_lower_band = round(median - self.factor * atr, 4)
        if self.super_trend == 1:
            self.upper_band = basic_upper_band
            self.lower_band = max(basic_lower_band, self.lower_band) if self.lower_band is not None else basic_lower_band
            if candle['close'] <= self.lower_band:
                self.super_trend = -1
        else:
            self.lower_band = basic_lower_band
            self.upper_band = min(basic_upper_band, self.upper_band) if self.upper_band is not None else basic_upper_band
            if candle['close'] >= self.upper_band:
                self.super_trend = 1

        if(self.super_trend == 1):
            self.final_band = self.lower_band
        else:
            self.final_band = self.upper_band
        
        self.value = (self.super_trend, self.final_band)
        return self.value

class HeikinAshi:
    def __init__(self):
        self.value = None

    def compute(self, candle):
        ha = {}
        ha['close'] = round((candle['open']+candle['high']+candle['low']+candle['close'])/4,4)
        if(self.value is None):
            # no previous candle
            ha['open'] = candle['open']
        else:
            ha['open'] = round((self.value['open']+self.value['close'])/2,4)
        ha['high'] = max(candle['high'], ha['open'], ha['close'])
        ha['low'] = min(candle['low'], ha['open'], ha['close'])
        return ha

    def update(self, candle):
        self.value = self.compute(candle)
        return self.value

class Renko:
    def __init__(self, start_price=None):
        self.bricks = []
        self.current_direction = 0
        self.brick_end_price = start_price
        self.pwick = 0   # positive wick
        self.nwick = 0   # negative wick
        self.brick_num = 0
        self.value = None
        
    def _create_brick(self, direction, brick_size, price):
        self.brick_end_price = round(self.brick_end_price + direction*brick_size,2)
        brick = {
            'direction': direction,
            'brick_num': self.brick_num,
            'wick_size': self.nwick if direction==1 else self.pwick,
            'brick_size': brick_size,
            'brick_end_price': self.brick_end_price,
            'price': price
        }
        self.bricks.append(brick)
        self.brick_num += 1
        self.current_direction = direction
        self.pwick = 0
        self.nwick = 0
        return brick        
        
    def update(self, price, brick_size):
        if(self.brick_end_price is None):
            self.brick_end_price = price
            #print("renko brick start price:", price)
            return None
        if(brick_size is None): return None
        bricks = None
        change = round(price - self.brick_end_price, 2)
        self.pwick = max(change, self.pwick)
        self.nwick = min(-change, self.nwick)
        if(self.current_direction == 0):
            direction = 0
            if(change >= brick_size): direction = 1
            elif(-change >= brick_size): direction = -1
            if(direction != 0):
                #print("firect brick direction:", str(direction))
                num_bricks = int(abs(change)//brick_size)
                bricks = [self._create_brick(direction, brick_size, price) for i in range(num_bricks)]
                
        elif(self.current_direction == 1):
            if(change >= brick_size):
                # more bricks in +1 direction
                num_bricks = int(abs(change)//brick_size)
                bricks = [self._create_brick(1, brick_size, price) for i in range(num_bricks)]
                
            elif(-change >= 2*brick_size):
                # reverse direction to -1
                num_bricks = int(abs(change)//brick_size)
                bricks = [self._create_brick(-1, brick_size, price) for i in range(num_bricks-1)]
                
        elif(self.current_direction == -1):
            if(-change >= brick_size):
                # more bricks in -1 direction
                num_bricks = int(abs(change)//brick_size)
                bricks = [self._create_brick(-1, brick_size, price) for i in range(num_bricks)]
                
            elif(change >= 2*brick_size):
                # reverse direction to +1
                num_bricks = int(abs(change)//brick_size)
                bricks = [self._create_brick(1, brick_size, price) for i in range(num_bricks-1)]

        self.value = bricks
        return bricks

import operator
COMPARATORS = {
    '>': operator.gt,
    '<': operator.lt,
    '>=': operator.ge,
    '<=': operator.le,
    '==': operator.eq    
}
class IsOrder:
    ''' 
        Checks if a given list of elements is in an order. eg. all increasing
        examples:
        - all_increasing = IsOrder('>', len)
        - all_decreasing = IsOrder('<=', len)
        - doubling = IsOrder(lambda a,b: a == 2*b, len)
    '''
    def __init__(self, comparator, length):
        self.comparator = COMPARATORS.get(comparator, comparator)
        self.length = length
        self.q = deque(length*[None], maxlen=length)
        self.fresh = True
        self.order_idx = 1
        self.is_ordered = False
        self.value = False

    def update(self, element):
        self.q.append(element)
        if(self.fresh): 
            self.fresh = False
            return False
        # comparator (new element, old element)
        if(self.comparator(element, self.q[-2])):
            self.order_idx += 1
        else:
            self.order_idx = 1
        self.is_ordered = self.order_idx >= self.length
        self.value = self.is_ordered
        return self.value
    
class HalfTrend:
    '''HalfTrend by Alex Orekhov (everget) in tradingview. Refered pinescript for source code'''
    def __init__(self, amplitude, channel_deviation, atr_period=100, candles=None):
        self.amplitude = amplitude
        self.channel_deviation = channel_deviation
        self.atr_period = atr_period
        self.channel_deviation_by_2 = channel_deviation/2
        self.ATR = ATR(atr_period)
        self.Max_high = Max(amplitude)
        self.Min_low = Min(amplitude)
        self.SMA_high = SMA(amplitude)
        self.SMA_low = SMA(amplitude)
        self.trend = 0  # 0 = uptrend, 1 = downtred
        self.next_trend = 0
        self.max_low_price = None
        self.min_high_price = None
        self.up = 0
        self.down = 0
        self.atr_high = 0
        self.atr_low = 0
    def update(self, candle):
        if(self.max_low_price is None):
            self.max_low_price = candle['low']
            self.min_high_price = candle['high']
        atr = self.ATR.update(candle)
        high_price = self.Max_high.update(candle['high'])
        low_price = self.Min_low.update(candle['low'])
        high_ma = self.SMA_high.update(candle['high'])
        low_ma = self.SMA_low.update(candle['low'])
        if(atr is None):
            return None, None, None, None, None, None
        dev = self.channel_deviation_by_2 * atr
        prev_trend = self.trend
        if self.next_trend == 1:
            self.max_low_price = max(low_price, self.max_low_price) if self.max_low_price else low_price
            if high_ma < self.max_low_price and candle['close'] < self.Min_low.points[-2]:
                self.trend = 1
                self.next_trend = 0
                self.min_high_price = high_price
        else:
            self.min_high_price = min(high_price, self.min_high_price) if self.min_high_price else high_price
            if low_ma > self.min_high_price and candle['close'] > self.Max_high.points[-2]:
                self.trend = 0
                self.next_trend = 1
                self.max_low_price = low_price

        if self.trend == 0:
            if prev_trend != 0:
                self.up = self.down if self.down is not None else candle['low']
            else:
                self.up = max(self.max_low_price, self.up) if self.up else self.max_low_price
            self.atr_high = self.up + dev
            self.atr_low = self.up - dev
        else:
            if prev_trend != 1:
                self.down = self.up if self.up is not None else candle['high']
            else:
                self.down = min(self.min_high_price, self.down) if self.down else self.min_high_price
            self.atr_high = self.down + dev
            self.atr_low = self.down - dev

        self.half_trend = self.up if self.trend == 0 else self.down
        return self.value
    
    @property
    def value(self):
        return self.trend, self.half_trend, self.up, self.down, self.atr_high, self.atr_low

class DI:
    ''' Directional Movement Index (abstract class to derive PLUS_DI and MINUS_DI)'''
    def __init__(self, period:int):
        self.prev_candle = None
        self.TRANGE = TRANGE()
        self.RMA_TR = RMA(period)
        self.RMA_DI = RMA(period)
    @property
    def value(self):
        return self.di
    @property
    def di(self):
        if(self.RMA_DI.value is not None):
            return (100 * self.RMA_DI.value)/self.RMA_TR.value
        return None
    def update(self, candle):
        if(self.prev_candle is not None):
            _up = candle['high'] - self.prev_candle['high']
            _down = self.prev_candle['low'] - candle['low']
            _dm = self._logic(_up, _down)
            self.RMA_DI.update(_dm)
            tr = self.TRANGE.update(candle)
            if(tr is not None): self.RMA_TR.update(tr)
        self.prev_candle = candle
        return self.di

class MINUS_DI(DI):
    def _logic(self, _up, _down):
        if(_down > _up and _down > 0): return _down
        else: return 0

class PLUS_DI(DI):
    def _logic(self, _up, _down):
        if(_up > _down and _up > 0): return _up
        else: return 0

class CWA2Sigma:
    '''As discussed by Mr Rakesh Pujara in his interview(https://www.youtube.com/watch?v=tSlfPgaWIu4)'''
    def __init__(self, bb_period:int=50, bb_width:float=2, ema_period:int=100, atr_period:int=14, atr_factor:float=1.8, sl_perc:float=20):
        self.BBands = BBands(bb_period, bb_width)
        self.EMA = EMA(ema_period)
        self.ATR = ATR(atr_period)
        self.atr_factor = atr_factor
        self.sl_perc = 100/sl_perc
        self.signal = 0
        self.entry_price = None
        self.sl_price = None
    @property
    def value(self):
        return self.signal, self.entry_price
    def _signal_change_logic(self, candle, bbands_upper, ema, atr):
        if(bbands_upper is not None and ema is not None and atr is not None):
            if(self.signal == 0 and candle['close'] > bbands_upper):
                signal = 1
                entry_price = candle['close']
                sl_price = entry_price * (1-self.sl_perc)
            elif(self.signal == 1 and candle['close'] <= max(self.sl_price, ema, candle['close']-(atr*self.atr_factor))):
                signal = 0
                entry_price = None
                sl_price = None
            else:
                signal = self.signal
                entry_price = self.entry_price
                sl_price = self.sl_price
            return signal, entry_price, sl_price
        else:
            return self.signal, self.entry_price, self.sl_price
    def compute(self, candle):
        bbands = self.BBands.compute(candle['close'])
        ema = self.EMA.compute(candle['close'])
        atr = self.ATR.compute(candle)
        signal, entry_price, sl_price = self._signal_change_logic(candle, bbands[0], ema, atr)
        return signal, entry_price
    def update(self, candle):
        bbands = self.BBands.update(candle['close'])
        ema = self.EMA.update(candle['close'])
        atr = self.ATR.update(candle)
        self.signal, self.entry_price, self.sl_price = self._signal_change_logic(candle, bbands[0], ema, atr)
        return self.value
