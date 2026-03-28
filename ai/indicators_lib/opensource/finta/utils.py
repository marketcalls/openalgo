import pandas as pd


def to_dataframe(ticks: list) -> pd.DataFrame:
    """Convert list to Series compatible with the library."""

    df = pd.DataFrame(ticks)
    df["time"] = pd.to_datetime(df["time"], unit="s")
    df.set_index("time", inplace=True)

    return df


def resample(df: pd.DataFrame, interval: str) -> pd.DataFrame:
    """Resample DataFrame by <interval>."""

    d = {"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"}

    return df.resample(interval).agg(d)


def resample_calendar(df: pd.DataFrame, offset: str) -> pd.DataFrame:
    """Resample the DataFrame by calendar offset.
    See http://pandas.pydata.org/pandas-docs/stable/user_guide/timeseries.html#anchored-offsets for compatible offsets.
    :param df: data
    :param offset: calendar offset
    :return: result DataFrame
    """

    d = {"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"}

    return df.resample(offset).agg(d)


def trending_up(df: pd.Series, period: int) -> pd.Series:
    """returns boolean Series if the inputs Series is trending up over last n periods.
    :param df: data
    :param period: range
    :return: result Series
    """

    return pd.Series(df.diff(period) > 0, name="trending_up {}".format(period))


def trending_down(df: pd.Series, period: int) -> pd.Series:
    """returns boolean Series if the input Series is trending up over last n periods.
    :param df: data
    :param period: range
    :return: result Series
    """

    return pd.Series(df.diff(period) < 0, name="trending_down {}".format(period))
