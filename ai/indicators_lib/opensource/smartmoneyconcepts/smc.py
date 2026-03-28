from functools import wraps
import pandas as pd
import numpy as np
from pandas import DataFrame, Series
from datetime import datetime

def inputvalidator(input_="ohlc"):
    def dfcheck(func):
        @wraps(func)
        def wrap(*args, **kwargs):
            args = list(args)
            i = 0 if isinstance(args[0], pd.DataFrame) else 1

            args[i] = args[i].rename(columns={c: c.lower() for c in args[i].columns})

            inputs = {
                "o": "open",
                "h": "high",
                "l": "low",
                "c": kwargs.get("column", "close").lower(),
                "v": "volume",
            }

            if inputs["c"] != "close":
                kwargs["column"] = inputs["c"]

            for l in input_:
                if inputs[l] not in args[i].columns:
                    raise LookupError(
                        'Must have a dataframe column named "{0}"'.format(inputs[l])
                    )

            return func(*args, **kwargs)

        return wrap

    return dfcheck


def apply(decorator):
    def decorate(cls):
        for attr in cls.__dict__:
            if callable(getattr(cls, attr)):
                setattr(cls, attr, decorator(getattr(cls, attr)))

        return cls

    return decorate


@apply(inputvalidator(input_="ohlc"))
class smc:
    __version__ = "0.0.26"

    @classmethod
    def fvg(cls, ohlc: DataFrame, join_consecutive=False) -> Series:
        """
        FVG - Fair Value Gap
        A fair value gap is when the previous high is lower than the next low if the current candle is bullish.
        Or when the previous low is higher than the next high if the current candle is bearish.

        parameters:
        join_consecutive: bool - if there are multiple FVG in a row then they will be merged into one using the highest top and the lowest bottom

        returns:
        FVG = 1 if bullish fair value gap, -1 if bearish fair value gap
        Top = the top of the fair value gap
        Bottom = the bottom of the fair value gap
        MitigatedIndex = the index of the candle that mitigated the fair value gap
        """

        fvg = np.where(
            (
                (ohlc["high"].shift(1) < ohlc["low"].shift(-1))
                & (ohlc["close"] > ohlc["open"])
            )
            | (
                (ohlc["low"].shift(1) > ohlc["high"].shift(-1))
                & (ohlc["close"] < ohlc["open"])
            ),
            np.where(ohlc["close"] > ohlc["open"], 1, -1),
            np.nan,
        )

        top = np.where(
            ~np.isnan(fvg),
            np.where(
                ohlc["close"] > ohlc["open"],
                ohlc["low"].shift(-1),
                ohlc["low"].shift(1),
            ),
            np.nan,
        )

        bottom = np.where(
            ~np.isnan(fvg),
            np.where(
                ohlc["close"] > ohlc["open"],
                ohlc["high"].shift(1),
                ohlc["high"].shift(-1),
            ),
            np.nan,
        )

        # if there are multiple consecutive fvg then join them together using the highest top and lowest bottom and the last index
        if join_consecutive:
            for i in range(len(fvg) - 1):
                if fvg[i] == fvg[i + 1]:
                    top[i + 1] = max(top[i], top[i + 1])
                    bottom[i + 1] = min(bottom[i], bottom[i + 1])
                    fvg[i] = top[i] = bottom[i] = np.nan

        mitigated_index = np.zeros(len(ohlc), dtype=np.int32)
        for i in np.where(~np.isnan(fvg))[0]:
            mask = np.zeros(len(ohlc), dtype=np.bool_)
            if fvg[i] == 1:
                mask = ohlc["low"][i + 2 :] <= top[i]
            elif fvg[i] == -1:
                mask = ohlc["high"][i + 2 :] >= bottom[i]
            if np.any(mask):
                j = np.argmax(mask) + i + 2
                mitigated_index[i] = j

        mitigated_index = np.where(np.isnan(fvg), np.nan, mitigated_index)

        return pd.concat(
            [
                pd.Series(fvg, name="FVG"),
                pd.Series(top, name="Top"),
                pd.Series(bottom, name="Bottom"),
                pd.Series(mitigated_index, name="MitigatedIndex"),
            ],
            axis=1,
        )

    @classmethod
    def swing_highs_lows(cls, ohlc: DataFrame, swing_length: int = 50) -> Series:
        """
        Swing Highs and Lows
        A swing high is when the current high is the highest high out of the swing_length amount of candles before and after.
        A swing low is when the current low is the lowest low out of the swing_length amount of candles before and after.

        parameters:
        swing_length: int - the amount of candles to look back and forward to determine the swing high or low

        returns:
        HighLow = 1 if swing high, -1 if swing low
        Level = the level of the swing high or low
        """

        swing_length *= 2
        # set the highs to 1 if the current high is the highest high in the last 5 candles and next 5 candles
        swing_highs_lows = np.where(
            ohlc["high"]
            == ohlc["high"].shift(-(swing_length // 2)).rolling(swing_length).max(),
            1,
            np.where(
                ohlc["low"]
                == ohlc["low"].shift(-(swing_length // 2)).rolling(swing_length).min(),
                -1,
                np.nan,
            ),
        )

        while True:
            positions = np.where(~np.isnan(swing_highs_lows))[0]

            if len(positions) < 2:
                break

            current = swing_highs_lows[positions[:-1]]
            next = swing_highs_lows[positions[1:]]

            highs = ohlc["high"].iloc[positions[:-1]].values
            lows = ohlc["low"].iloc[positions[:-1]].values

            next_highs = ohlc["high"].iloc[positions[1:]].values
            next_lows = ohlc["low"].iloc[positions[1:]].values

            index_to_remove = np.zeros(len(positions), dtype=bool)

            consecutive_highs = (current == 1) & (next == 1)
            index_to_remove[:-1] |= consecutive_highs & (highs < next_highs)
            index_to_remove[1:] |= consecutive_highs & (highs >= next_highs)

            consecutive_lows = (current == -1) & (next == -1)
            index_to_remove[:-1] |= consecutive_lows & (lows > next_lows)
            index_to_remove[1:] |= consecutive_lows & (lows <= next_lows)

            if not index_to_remove.any():
                break

            swing_highs_lows[positions[index_to_remove]] = np.nan

        positions = np.where(~np.isnan(swing_highs_lows))[0]

        if len(positions) > 0:
            if swing_highs_lows[positions[0]] == 1:
                swing_highs_lows[0] = -1
            if swing_highs_lows[positions[0]] == -1:
                swing_highs_lows[0] = 1
            if swing_highs_lows[positions[-1]] == -1:
                swing_highs_lows[-1] = 1
            if swing_highs_lows[positions[-1]] == 1:
                swing_highs_lows[-1] = -1

        level = np.where(
            ~np.isnan(swing_highs_lows),
            np.where(swing_highs_lows == 1, ohlc["high"], ohlc["low"]),
            np.nan,
        )

        return pd.concat(
            [
                pd.Series(swing_highs_lows, name="HighLow"),
                pd.Series(level, name="Level"),
            ],
            axis=1,
        )

    @classmethod
    def bos_choch(
        cls, ohlc: DataFrame, swing_highs_lows: DataFrame, close_break: bool = True
    ) -> Series:
        """
        BOS - Break of Structure
        CHoCH - Change of Character
        these are both indications of market structure changing

        parameters:
        swing_highs_lows: DataFrame - provide the dataframe from the swing_highs_lows function
        close_break: bool - if True then the break of structure will be mitigated based on the close of the candle otherwise it will be the high/low.

        returns:
        BOS = 1 if bullish break of structure, -1 if bearish break of structure
        CHOCH = 1 if bullish change of character, -1 if bearish change of character
        Level = the level of the break of structure or change of character
        BrokenIndex = the index of the candle that broke the level
        """

        swing_highs_lows = swing_highs_lows.copy()

        level_order = []
        highs_lows_order = []

        bos = np.zeros(len(ohlc), dtype=np.int32)
        choch = np.zeros(len(ohlc), dtype=np.int32)
        level = np.zeros(len(ohlc), dtype=np.float32)

        last_positions = []

        for i in range(len(swing_highs_lows["HighLow"])):
            if not np.isnan(swing_highs_lows["HighLow"][i]):
                level_order.append(swing_highs_lows["Level"][i])
                highs_lows_order.append(swing_highs_lows["HighLow"][i])
                if len(level_order) >= 4:
                    # bullish bos
                    bos[last_positions[-2]] = (
                        1
                        if (
                            np.all(highs_lows_order[-4:] == [-1, 1, -1, 1])
                            and np.all(
                                level_order[-4]
                                < level_order[-2]
                                < level_order[-3]
                                < level_order[-1]
                            )
                        )
                        else 0
                    )
                    level[last_positions[-2]] = (
                        level_order[-3] if bos[last_positions[-2]] != 0 else 0
                    )

                    # bearish bos
                    bos[last_positions[-2]] = (
                        -1
                        if (
                            np.all(highs_lows_order[-4:] == [1, -1, 1, -1])
                            and np.all(
                                level_order[-4]
                                > level_order[-2]
                                > level_order[-3]
                                > level_order[-1]
                            )
                        )
                        else bos[last_positions[-2]]
                    )
                    level[last_positions[-2]] = (
                        level_order[-3] if bos[last_positions[-2]] != 0 else 0
                    )

                    # bullish choch
                    choch[last_positions[-2]] = (
                        1
                        if (
                            np.all(highs_lows_order[-4:] == [-1, 1, -1, 1])
                            and np.all(
                                level_order[-1]
                                > level_order[-3]
                                > level_order[-4]
                                > level_order[-2]
                            )
                        )
                        else 0
                    )
                    level[last_positions[-2]] = (
                        level_order[-3]
                        if choch[last_positions[-2]] != 0
                        else level[last_positions[-2]]
                    )

                    # bearish choch
                    choch[last_positions[-2]] = (
                        -1
                        if (
                            np.all(highs_lows_order[-4:] == [1, -1, 1, -1])
                            and np.all(
                                level_order[-1]
                                < level_order[-3]
                                < level_order[-4]
                                < level_order[-2]
                            )
                        )
                        else choch[last_positions[-2]]
                    )
                    level[last_positions[-2]] = (
                        level_order[-3]
                        if choch[last_positions[-2]] != 0
                        else level[last_positions[-2]]
                    )

                last_positions.append(i)

        broken = np.zeros(len(ohlc), dtype=np.int32)
        for i in np.where(np.logical_or(bos != 0, choch != 0))[0]:
            mask = np.zeros(len(ohlc), dtype=np.bool_)
            # if the bos is 1 then check if the candles high has gone above the level
            if bos[i] == 1 or choch[i] == 1:
                mask = ohlc["close" if close_break else "high"][i + 2 :] > level[i]
            # if the bos is -1 then check if the candles low has gone below the level
            elif bos[i] == -1 or choch[i] == -1:
                mask = ohlc["close" if close_break else "low"][i + 2 :] < level[i]
            if np.any(mask):
                j = np.argmax(mask) + i + 2
                broken[i] = j
                # if there are any unbroken bos or choch that started before this one and ended after this one then remove them
                for k in np.where(np.logical_or(bos != 0, choch != 0))[0]:
                    if k < i and broken[k] >= j:
                        bos[k] = 0
                        choch[k] = 0
                        level[k] = 0

        # remove the ones that aren't broken
        for i in np.where(
            np.logical_and(np.logical_or(bos != 0, choch != 0), broken == 0)
        )[0]:
            bos[i] = 0
            choch[i] = 0
            level[i] = 0

        # replace all the 0s with np.nan
        bos = np.where(bos != 0, bos, np.nan)
        choch = np.where(choch != 0, choch, np.nan)
        level = np.where(level != 0, level, np.nan)
        broken = np.where(broken != 0, broken, np.nan)

        bos = pd.Series(bos, name="BOS")
        choch = pd.Series(choch, name="CHOCH")
        level = pd.Series(level, name="Level")
        broken = pd.Series(broken, name="BrokenIndex")

        return pd.concat([bos, choch, level, broken], axis=1)

    @classmethod
    def ob(
        cls,
        ohlc: DataFrame,
        swing_highs_lows: DataFrame,
        close_mitigation: bool = False,
    ) -> Series:
        """
        OB - Order Blocks
        This method detects order blocks when there is a high amount of market orders exist on a price range.

        parameters:
        swing_highs_lows: DataFrame - provide the dataframe from the swing_highs_lows function
        close_mitigation: bool - if True then the order block will be mitigated based on the close of the candle otherwise it will be the high/low.

        returns:
        OB = 1 if bullish order block, -1 if bearish order block
        Top = top of the order block
        Bottom = bottom of the order block
        OBVolume = volume + 2 last volumes amounts
        Percentage = strength of order block (min(highVolume, lowVolume)/max(highVolume, lowVolume))
        """

        ohlc_len = len(ohlc)
        _open = ohlc["open"].values
        _high = ohlc["high"].values
        _low = ohlc["low"].values
        _close = ohlc["close"].values
        _volume = ohlc["volume"].values
        swing_hl = swing_highs_lows["HighLow"].values

        # Pre-allocate arrays
        crossed = np.full(ohlc_len, False, dtype=bool)
        ob = np.zeros(ohlc_len, dtype=np.int32)
        top_arr = np.zeros(ohlc_len, dtype=np.float32)
        bottom_arr = np.zeros(ohlc_len, dtype=np.float32)
        obVolume = np.zeros(ohlc_len, dtype=np.float32)
        lowVolume = np.zeros(ohlc_len, dtype=np.float32)
        highVolume = np.zeros(ohlc_len, dtype=np.float32)
        percentage = np.zeros(ohlc_len, dtype=np.float32)
        mitigated_index = np.zeros(ohlc_len, dtype=np.int32)
        breaker = np.full(ohlc_len, False, dtype=bool)

        # Precompute swing indices (assumed sorted)
        swing_high_indices = np.flatnonzero(swing_hl == 1)
        swing_low_indices = np.flatnonzero(swing_hl == -1)

        # List to track active bullish order blocks
        active_bullish = []
        for i in range(ohlc_len):
            close_index = i
            # Update existing bullish OB
            for idx in active_bullish.copy():
                if breaker[idx]:
                    if _high[close_index] > top_arr[idx]:
                        # Reset this OB
                        ob[idx] = 0
                        top_arr[idx] = 0.0
                        bottom_arr[idx] = 0.0
                        obVolume[idx] = 0.0
                        lowVolume[idx] = 0.0
                        highVolume[idx] = 0.0
                        mitigated_index[idx] = 0
                        percentage[idx] = 0.0
                        active_bullish.remove(idx)
                else:
                    if ((not close_mitigation and _low[close_index] < bottom_arr[idx])
                        or (close_mitigation and min(_open[close_index], _close[close_index]) < bottom_arr[idx])):
                        breaker[idx] = True
                        mitigated_index[idx] = close_index - 1

            # Find last swing high index less than current candle (using binary search)
            pos = np.searchsorted(swing_high_indices, close_index)
            last_top_index = swing_high_indices[pos - 1] if pos > 0 else None

            if last_top_index is not None:
                if _close[close_index] > _high[last_top_index] and not crossed[last_top_index]:
                    crossed[last_top_index] = True
                    # Initialise with default values from previous candle
                    default_index = close_index - 1
                    obBtm = _high[default_index]
                    obTop = _low[default_index]
                    obIndex = default_index
                    # Look for a lower low between last_top_index and current candle
                    if close_index - last_top_index > 1:
                        start = last_top_index + 1
                        end = close_index  # up to but not including close_index
                        if end > start:
                            segment = _low[start:end]
                            min_val = segment.min()
                            # In case of ties, take the last occurrence
                            candidates = np.nonzero(segment == min_val)[0]
                            if candidates.size:
                                candidate_index = start + candidates[-1]
                                obBtm = _low[candidate_index]
                                obTop = _high[candidate_index]
                                obIndex = candidate_index
                    # Set bullish OB values
                    ob[obIndex] = 1
                    top_arr[obIndex] = obTop
                    bottom_arr[obIndex] = obBtm
                    vol_cur = _volume[close_index]
                    vol_prev1 = _volume[close_index - 1] if close_index >= 1 else 0.0
                    vol_prev2 = _volume[close_index - 2] if close_index >= 2 else 0.0
                    obVolume[obIndex] = vol_cur + vol_prev1 + vol_prev2
                    lowVolume[obIndex] = vol_prev2
                    highVolume[obIndex] = vol_cur + vol_prev1
                    max_vol = max(highVolume[obIndex], lowVolume[obIndex])
                    percentage[obIndex] = (min(highVolume[obIndex], lowVolume[obIndex]) / max_vol * 100.0) if max_vol != 0 else 100.0
                    active_bullish.append(obIndex)

        # List to track active bearish order blocks
        active_bearish = []
        for i in range(ohlc_len):
            close_index = i
            # Update existing bearish OB
            for idx in active_bearish.copy():
                if breaker[idx]:
                    if _low[close_index] < bottom_arr[idx]:
                        ob[idx] = 0
                        top_arr[idx] = 0.0
                        bottom_arr[idx] = 0.0
                        obVolume[idx] = 0.0
                        lowVolume[idx] = 0.0
                        highVolume[idx] = 0.0
                        mitigated_index[idx] = 0
                        percentage[idx] = 0.0
                        active_bearish.remove(idx)
                else:
                    if ((not close_mitigation and _high[close_index] > top_arr[idx])
                        or (close_mitigation and max(_open[close_index], _close[close_index]) > top_arr[idx])):
                        breaker[idx] = True
                        mitigated_index[idx] = close_index

            # Find last swing low index less than current candle
            pos = np.searchsorted(swing_low_indices, close_index)
            last_btm_index = swing_low_indices[pos - 1] if pos > 0 else None

            if last_btm_index is not None:
                if _close[close_index] < _low[last_btm_index] and not crossed[last_btm_index]:
                    crossed[last_btm_index] = True
                    default_index = close_index - 1
                    obTop = _high[default_index]
                    obBtm = _low[default_index]
                    obIndex = default_index
                    if close_index - last_btm_index > 1:
                        start = last_btm_index + 1
                        end = close_index
                        if end > start:
                            segment = _high[start:end]
                            max_val = segment.max()
                            candidates = np.nonzero(segment == max_val)[0]
                            if candidates.size:
                                candidate_index = start + candidates[-1]
                                obTop = _high[candidate_index]
                                obBtm = _low[candidate_index]
                                obIndex = candidate_index
                    ob[obIndex] = -1
                    top_arr[obIndex] = obTop
                    bottom_arr[obIndex] = obBtm
                    vol_cur = _volume[close_index]
                    vol_prev1 = _volume[close_index - 1] if close_index >= 1 else 0.0
                    vol_prev2 = _volume[close_index - 2] if close_index >= 2 else 0.0
                    obVolume[obIndex] = vol_cur + vol_prev1 + vol_prev2
                    lowVolume[obIndex] = vol_cur + vol_prev1
                    highVolume[obIndex] = vol_prev2
                    max_vol = max(highVolume[obIndex], lowVolume[obIndex])
                    percentage[obIndex] = (min(highVolume[obIndex], lowVolume[obIndex]) / max_vol * 100.0) if max_vol != 0 else 100.0
                    active_bearish.append(obIndex)

        # Convert zeros to NaN where OB was not set
        ob = np.where(ob != 0, ob, np.nan)
        top_arr = np.where(~np.isnan(ob), top_arr, np.nan)
        bottom_arr = np.where(~np.isnan(ob), bottom_arr, np.nan)
        obVolume = np.where(~np.isnan(ob), obVolume, np.nan)
        mitigated_index = np.where(~np.isnan(ob), mitigated_index, np.nan)
        percentage = np.where(~np.isnan(ob), percentage, np.nan)

        ob_series = pd.Series(ob, name="OB")
        top_series = pd.Series(top_arr, name="Top")
        bottom_series = pd.Series(bottom_arr, name="Bottom")
        obVolume_series = pd.Series(obVolume, name="OBVolume")
        mitigated_index_series = pd.Series(mitigated_index, name="MitigatedIndex")
        percentage_series = pd.Series(percentage, name="Percentage")

        return pd.concat(
            [
                ob_series,
                top_series,
                bottom_series,
                obVolume_series,
                mitigated_index_series,
                percentage_series,
            ],
            axis=1,
        )

    @classmethod
    def liquidity(cls, ohlc: DataFrame, swing_highs_lows: DataFrame, range_percent: float = 0.01) -> Series:
        """
        Liquidity
        Liquidity is when there are multiple highs within a small range of each other,
        or multiple lows within a small range of each other.

        parameters:
        swing_highs_lows: DataFrame - provide the dataframe from the swing_highs_lows function
        range_percent: float - the percentage of the range to determine liquidity

        returns:
        Liquidity = 1 if bullish liquidity, -1 if bearish liquidity
        Level = the level of the liquidity
        End = the index of the last liquidity level
        Swept = the index of the candle that swept the liquidity
        """

        # Work on a copy so the original is not modified.
        shl = swing_highs_lows.copy()
        n = len(ohlc)
        
        # Calculate the pip range based on the overall high-low range.
        pip_range = (ohlc["high"].max() - ohlc["low"].min()) * range_percent

        # Preconvert required columns to numpy arrays.
        ohlc_high = ohlc["high"].values
        ohlc_low = ohlc["low"].values
        # Make a copy to allow in-place marking of used candidates.
        shl_HL = shl["HighLow"].values.copy()
        shl_Level = shl["Level"].values.copy()

        # Initialise output arrays with NaN (to match later replacement of zeros).
        liquidity = np.full(n, np.nan, dtype=np.float32)
        liquidity_level = np.full(n, np.nan, dtype=np.float32)
        liquidity_end = np.full(n, np.nan, dtype=np.float32)
        liquidity_swept = np.full(n, np.nan, dtype=np.float32)

        # Process bullish liquidity (HighLow == 1)
        bull_indices = np.nonzero(shl_HL == 1)[0]
        for i in bull_indices:
            # Skip if this candidate has already been used.
            if shl_HL[i] != 1:
                continue
            high_level = shl_Level[i]
            range_low = high_level - pip_range
            range_high = high_level + pip_range
            group_levels = [high_level]
            group_end = i

            # Determine the swept index:
            # Find the first candle after i where the high reaches or exceeds range_high.
            c_start = i + 1
            if c_start < n:
                cond = ohlc_high[c_start:] >= range_high
                if np.any(cond):
                    swept = c_start + int(np.argmax(cond))
                else:
                    swept = 0
            else:
                swept = 0

            # Iterate only over candidate indices greater than i.
            for j in bull_indices:
                if j <= i:
                    continue
                # Emulate the inner loop break: if we've reached or passed the swept index, stop.
                if swept and j >= swept:
                    break
                # If candidate j is within the liquidity range, add it and mark it as used.
                if shl_HL[j] == 1 and (range_low <= shl_Level[j] <= range_high):
                    group_levels.append(shl_Level[j])
                    group_end = j
                    shl_HL[j] = 0  # mark candidate as used
            # Only record liquidity if more than one candidate is grouped.
            if len(group_levels) > 1:
                avg_level = sum(group_levels) / len(group_levels)
                liquidity[i] = 1
                liquidity_level[i] = avg_level
                liquidity_end[i] = group_end
                liquidity_swept[i] = swept

        # Process bearish liquidity (HighLow == -1)
        bear_indices = np.nonzero(shl_HL == -1)[0]
        for i in bear_indices:
            if shl_HL[i] != -1:
                continue
            low_level = shl_Level[i]
            range_low = low_level - pip_range
            range_high = low_level + pip_range
            group_levels = [low_level]
            group_end = i

            # Find the first candle after i where the low reaches or goes below range_low.
            c_start = i + 1
            if c_start < n:
                cond = ohlc_low[c_start:] <= range_low
                if np.any(cond):
                    swept = c_start + int(np.argmax(cond))
                else:
                    swept = 0
            else:
                swept = 0

            for j in bear_indices:
                if j <= i:
                    continue
                if swept and j >= swept:
                    break
                if shl_HL[j] == -1 and (range_low <= shl_Level[j] <= range_high):
                    group_levels.append(shl_Level[j])
                    group_end = j
                    shl_HL[j] = 0
            if len(group_levels) > 1:
                avg_level = sum(group_levels) / len(group_levels)
                liquidity[i] = -1
                liquidity_level[i] = avg_level
                liquidity_end[i] = group_end
                liquidity_swept[i] = swept

        # Convert arrays to Series with the proper names.
        liq_series = pd.Series(liquidity, name="Liquidity")
        level_series = pd.Series(liquidity_level, name="Level")
        end_series = pd.Series(liquidity_end, name="End")
        swept_series = pd.Series(liquidity_swept, name="Swept")

        return pd.concat([liq_series, level_series, end_series, swept_series], axis=1)

    @classmethod
    def previous_high_low(cls, ohlc: DataFrame, time_frame: str = "1D") -> DataFrame:
        """
        Previous High Low
        This method returns the previous high and low of the given time frame.

        parameters:
        time_frame: str - the time frame to get the previous high and low 15m, 1H, 4H, 1D, 1W, 1M

        returns:
        PreviousHigh = the previous high
        PreviousLow = the previous low
        BrokenHigh = 1 once price has broken the previous high of the timeframe, 0 otherwise
        BrokenLow = 1 once price has broken the previous low of the timeframe, 0 otherwise
        """
        ohlc = ohlc.copy()
        ohlc.index = pd.to_datetime(ohlc.index)
        n = len(ohlc)

        # Resample to target timeframe
        resampled = ohlc.resample(time_frame).agg({
            "open": "first",
            "high": "max",
            "low": "min",
            "close": "last",
            "volume": "sum"
        }).dropna()

        # Edge case: not enough resampled periods
        if len(resampled) < 2:
            return pd.concat([
                pd.Series(np.full(n, np.nan, dtype=np.float32), name="PreviousHigh"),
                pd.Series(np.full(n, np.nan, dtype=np.float32), name="PreviousLow"),
                pd.Series(np.zeros(n, dtype=np.int32), name="BrokenHigh"),
                pd.Series(np.zeros(n, dtype=np.int32), name="BrokenLow"),
            ], axis=1)

        resampled_times = resampled.index.values
        resampled_highs = resampled["high"].values
        resampled_lows = resampled["low"].values
        candle_times = ohlc.index.values

        # For each candle, find how many resampled periods have start time < candle time
        # This is equivalent to: len(np.where(resampled_times < candle_time)[0])
        periods_before = np.searchsorted(resampled_times, candle_times, side='left')

        # Original takes second-to-last: indices[-2] = periods_before - 2
        prev_period_idx = periods_before - 2

        # Valid only if more than 1 period before (original: len > 1, i.e., >= 2 periods)
        valid_mask = periods_before > 1

        # Initialize output arrays
        previous_high = np.full(n, np.nan, dtype=np.float32)
        previous_low = np.full(n, np.nan, dtype=np.float32)

        # Fill valid entries
        valid_indices = np.where(valid_mask)[0]
        if len(valid_indices) > 0:
            lookup_indices = prev_period_idx[valid_indices]
            previous_high[valid_indices] = resampled_highs[lookup_indices]
            previous_low[valid_indices] = resampled_lows[lookup_indices]

        # Group candles by their reference period for cumulative broken tracking
        # Original resets broken flags when the reference period changes
        group_changes = np.concatenate([[True], prev_period_idx[1:] != prev_period_idx[:-1]])
        group_id = np.cumsum(group_changes)

        ohlc_high = ohlc["high"].values
        ohlc_low = ohlc["low"].values

        # Compute cumulative max/min within each group
        df_temp = pd.DataFrame({
            'group': group_id,
            'high': ohlc_high,
            'low': ohlc_low,
        })

        cummax_high = df_temp.groupby('group')['high'].cummax().values
        cummin_low = df_temp.groupby('group')['low'].cummin().values

        # Broken = 1 if cumulative high > previous_high (or cummin < previous_low)
        broken_high = np.where(valid_mask & (cummax_high > previous_high), 1, 0).astype(np.int32)
        broken_low = np.where(valid_mask & (cummin_low < previous_low), 1, 0).astype(np.int32)

        return pd.concat([
            pd.Series(previous_high, name="PreviousHigh"),
            pd.Series(previous_low, name="PreviousLow"),
            pd.Series(broken_high, name="BrokenHigh"),
            pd.Series(broken_low, name="BrokenLow"),
        ], axis=1)
    
    @classmethod
    def sessions(
        cls,
        ohlc: DataFrame,
        session: str,
        start_time: str = "",
        end_time: str = "",
        time_zone: str = "UTC",
    ) -> Series:
        """
        Sessions
        This method returns wwhich candles are within the session specified

        parameters:
        session: str - the session you want to check (Sydney, Tokyo, London, New York, Asian kill zone, London open kill zone, New York kill zone, london close kill zone, Custom)
        start_time: str - the start time of the session in the format "HH:MM" only required for custom session.
        end_time: str - the end time of the session in the format "HH:MM" only required for custom session.
        time_zone: str - the time zone of the candles can be in the format "UTC+0" or "GMT+0"

        returns:
        Active = 1 if the candle is within the session, 0 if not
        High = the highest point of the session
        Low = the lowest point of the session
        """

        if session == "Custom" and (start_time == "" or end_time == ""):
            raise ValueError("Custom session requires a start and end time")

        default_sessions = {
            "Sydney": {
                "start": "21:00",
                "end": "06:00",
            },
            "Tokyo": {
                "start": "00:00",
                "end": "09:00",
            },
            "London": {
                "start": "07:00",
                "end": "16:00",
            },
            "New York": {
                "start": "13:00",
                "end": "22:00",
            },
            "Asian kill zone": {
                "start": "00:00",
                "end": "04:00",
            },
            "London open kill zone": {
                "start": "6:00",
                "end": "9:00",
            },
            "New York kill zone": {
                "start": "11:00",
                "end": "14:00",
            },
            "london close kill zone": {
                "start": "14:00",
                "end": "16:00",
            },
            "Custom": {
                "start": start_time,
                "end": end_time,
            },
        }

        ohlc.index = pd.to_datetime(ohlc.index)
        if time_zone != "UTC":
            time_zone = time_zone.replace("GMT", "Etc/GMT")
            time_zone = time_zone.replace("UTC", "Etc/GMT")
            ohlc.index = ohlc.index.tz_localize(time_zone).tz_convert("UTC")

        start_time = datetime.strptime(
            default_sessions[session]["start"], "%H:%M"
        ).strftime("%H:%M")
        start_time = datetime.strptime(start_time, "%H:%M")
        end_time = datetime.strptime(
            default_sessions[session]["end"], "%H:%M"
        ).strftime("%H:%M")
        end_time = datetime.strptime(end_time, "%H:%M")

        # if the candles are between the start and end time then it is an active session
        active = np.zeros(len(ohlc), dtype=np.int32)
        high = np.zeros(len(ohlc), dtype=np.float32)
        low = np.zeros(len(ohlc), dtype=np.float32)

        for i in range(len(ohlc)):
            current_time = ohlc.index[i].strftime("%H:%M")
            # convert current time to the second of the day
            current_time = datetime.strptime(current_time, "%H:%M")
            if (start_time < end_time and start_time <= current_time <= end_time) or (
                start_time >= end_time
                and (start_time <= current_time or current_time <= end_time)
            ):
                active[i] = 1
                high[i] = max(ohlc["high"].iloc[i], high[i - 1] if i > 0 else 0)
                low[i] = min(
                    ohlc["low"].iloc[i],
                    low[i - 1] if i > 0 and low[i - 1] != 0 else float("inf"),
                )

        active = pd.Series(active, name="Active")
        high = pd.Series(high, name="High")
        low = pd.Series(low, name="Low")

        return pd.concat([active, high, low], axis=1)

    @classmethod
    def retracements(cls, ohlc: DataFrame, swing_highs_lows: DataFrame) -> Series:
        """
        Retracement
        This method returns the percentage of a retracement from the swing high or low

        parameters:
        swing_highs_lows: DataFrame - provide the dataframe from the swing_highs_lows function

        returns:
        Direction = 1 if bullish retracement, -1 if bearish retracement
        CurrentRetracement% = the current retracement percentage from the swing high or low
        DeepestRetracement% = the deepest retracement percentage from the swing high or low
        """

        swing_highs_lows = swing_highs_lows.copy()

        direction = np.zeros(len(ohlc), dtype=np.int32)
        current_retracement = np.zeros(len(ohlc), dtype=np.float64)
        deepest_retracement = np.zeros(len(ohlc), dtype=np.float64)

        top = 0
        bottom = 0
        for i in range(len(ohlc)):
            if swing_highs_lows["HighLow"][i] == 1:
                direction[i] = 1
                top = swing_highs_lows["Level"][i]
                # deepest_retracement[i] = 0
            elif swing_highs_lows["HighLow"][i] == -1:
                direction[i] = -1
                bottom = swing_highs_lows["Level"][i]
                # deepest_retracement[i] = 0
            else:
                direction[i] = direction[i - 1] if i > 0 else 0

            if direction[i - 1] == 1:
                current_retracement[i] = round(
                    100 - (((ohlc["low"].iloc[i] - bottom) / (top - bottom)) * 100), 1
                )
                deepest_retracement[i] = max(
                    (
                        deepest_retracement[i - 1]
                        if i > 0 and direction[i - 1] == 1
                        else 0
                    ),
                    current_retracement[i],
                )
            if direction[i] == -1:
                current_retracement[i] = round(
                    100 - ((ohlc["high"].iloc[i] - top) / (bottom - top)) * 100, 1
                )
                deepest_retracement[i] = max(
                    (
                        deepest_retracement[i - 1]
                        if i > 0 and direction[i - 1] == -1
                        else 0
                    ),
                    current_retracement[i],
                )

        # shift the arrays by 1
        current_retracement = np.roll(current_retracement, 1)
        deepest_retracement = np.roll(deepest_retracement, 1)
        direction = np.roll(direction, 1)

        # remove the first 3 retracements as they get calculated incorrectly due to not enough data
        remove_first_count = 0
        for i in range(len(direction)):
            if i + 1 == len(direction):
                break
            if direction[i] != direction[i + 1]:
                remove_first_count += 1
            direction[i] = 0
            current_retracement[i] = 0
            deepest_retracement[i] = 0
            if remove_first_count == 3:
                direction[i + 1] = 0
                current_retracement[i + 1] = 0
                deepest_retracement[i + 1] = 0
                break

        direction = pd.Series(direction, name="Direction")
        current_retracement = pd.Series(current_retracement, name="CurrentRetracement%")
        deepest_retracement = pd.Series(deepest_retracement, name="DeepestRetracement%")

        return pd.concat([direction, current_retracement, deepest_retracement], axis=1)
