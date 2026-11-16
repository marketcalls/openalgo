"""Nuvama market data: quotes, depth and history.

- Quote and depth: GET {content}quote/scrip/{symbol}/ with the streaming symbol
  (``2885_NSE``, or ``-29`` for an index). One answer carries both the quote
  (``data.qt``) and five levels each side (``data.mkd``). There is no batch
  route, so multi-quotes are single quotes paced under the published limit of
  3000 requests per 5 minutes per IP.
- History: POST {content}charts/v2/main/{interval}/{exc}/{aTyp}/{symbol}.
  Intervals M1, M3, M5, M15, M30, H1 (intraday) and D1, all paged backwards
  with ``ltt`` (see get_history). Candle times come as IST wall-clock text
  (``2024-01-05 09:15:00``).
"""

import threading
import time
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import pandas as pd

from broker.nuvama.api.baseurl import BASE_CONTENT, nuvama_request
from broker.nuvama.mapping.exchange import chart_asset_type, chart_exchange
from database.market_calendar_db import get_market_timings_for_date
from database.token_db import get_symbol_info, get_token
from utils.logging import get_logger

logger = get_logger(__name__)

IST = ZoneInfo("Asia/Kolkata")
_INTRADAY_MINUTES = {"M1": 1, "M3": 3, "M5": 5, "M15": 15, "M30": 30, "H1": 60}

HISTORY_COLUMNS = ["timestamp", "open", "high", "low", "close", "volume", "oi"]

# 3000 requests / 5 minutes / IP is 10 a second across every route, orders
# included; quotes keep to 8 a second so orders always have room.
_QUOTE_INTERVAL = 0.125
_pace_lock = threading.Lock()
_next_slot = 0.0


def _pace():
    """Wait for the next quote slot (shared by every quote and history call)."""
    global _next_slot
    with _pace_lock:
        now = time.monotonic()
        slot = max(now, _next_slot)
        _next_slot = slot + _QUOTE_INTERVAL
    wait = slot - time.monotonic()
    if wait > 0:
        time.sleep(wait)


def _f(value):
    if value in (None, "", "--"):
        return 0.0
    try:
        return float(str(value).replace(",", ""))
    except (TypeError, ValueError):
        return 0.0


def _i(value):
    return int(_f(value))


def _session_open_minute(day, exchange):
    """Minute of the IST day the exchange opens on `day`, from OpenAlgo's market calendar.

    None when the calendar has no session for it (a holiday, a year the
    calendar does not serve, an exchange it does not list).
    """
    try:
        rows = get_market_timings_for_date(day)
    except Exception:
        logger.exception(f"Market timings for {day} could not be read")
        return None
    for row in rows or []:
        if row.get("exchange") == exchange and row.get("start_time"):
            opened = datetime.fromtimestamp(int(row["start_time"]) / 1000, IST)
            return opened.hour * 60 + opened.minute
    return None


def _session_open_epoch(day, open_minute):
    midnight = datetime(day.year, day.month, day.day, tzinfo=IST)
    return int(midnight.timestamp()) + open_minute * 60


class NuvamaDataError(Exception):
    pass


class BrokerData:
    def __init__(self, auth_token):
        self.auth_token = auth_token
        self.timeframe_map = {
            "1m": "M1",
            "3m": "M3",
            "5m": "M5",
            "15m": "M15",
            "30m": "M30",
            "1h": "H1",
            "D": "D1",
        }

    # --- quotes and depth ---------------------------------------------------------

    def _stream_symbol(self, symbol, exchange):
        token = get_token(symbol, exchange)
        if not token:
            raise NuvamaDataError(f"{symbol} is not in the Nuvama master contract for {exchange}")
        return token

    def _snapshot(self, symbol, exchange):
        token = self._stream_symbol(symbol, exchange)
        _pace()
        response = nuvama_request("GET", f"{BASE_CONTENT}quote/scrip/{token}/", self.auth_token)
        if not response.ok:
            raise NuvamaDataError(
                f"No quote for {exchange}:{symbol}: {response.error_message('Nuvama sent no quote')}"
            )
        data = response.data.get("data") or {}
        return data.get("qt") or {}, data.get("mkd") or {}

    @staticmethod
    def _quote_from(qt, mkd):
        bids = mkd.get("bid") or []
        asks = mkd.get("ask") or []
        best_bid = bids[0] if bids else {}
        best_ask = asks[0] if asks else {}
        return {
            "ask": _f(qt.get("askPr") or best_ask.get("price")),
            "bid": _f(qt.get("bidPr") or best_bid.get("price")),
            "ask_qty": _i(qt.get("akSz") or best_ask.get("qty")),
            "bid_qty": _i(qt.get("bdSz") or best_bid.get("qty")),
            "high": _f(qt.get("h")),
            "low": _f(qt.get("l")),
            "ltp": _f(qt.get("ltp")),
            "open": _f(qt.get("o")),
            "prev_close": _f(qt.get("c")),
            "volume": _i(qt.get("vol")),
            "oi": _i(qt.get("opInt")),
        }

    def get_quotes(self, symbol: str, exchange: str) -> dict:
        try:
            qt, mkd = self._snapshot(symbol, exchange)
            return self._quote_from(qt, mkd)
        except NuvamaDataError:
            raise
        except Exception as e:
            logger.exception(f"Error fetching Nuvama quote for {exchange}:{symbol}")
            raise NuvamaDataError(f"Error fetching quotes: {e}") from e

    def get_multiquotes(self, symbols: list) -> list:
        results = []
        for item in symbols:
            symbol, exchange = item.get("symbol"), item.get("exchange")
            try:
                results.append(
                    {
                        "symbol": symbol,
                        "exchange": exchange,
                        "data": self.get_quotes(symbol, exchange),
                    }
                )
            except Exception as e:
                results.append({"symbol": symbol, "exchange": exchange, "error": str(e)})
        return results

    def get_depth(self, symbol: str, exchange: str) -> dict:
        try:
            qt, mkd = self._snapshot(symbol, exchange)
        except NuvamaDataError:
            raise
        except Exception as e:
            logger.exception(f"Error fetching Nuvama depth for {exchange}:{symbol}")
            raise NuvamaDataError(f"Error fetching market depth: {e}") from e

        def levels(rows):
            out = [{"price": _f(r.get("price")), "quantity": _i(r.get("qty"))} for r in rows[:5]]
            while len(out) < 5:
                out.append({"price": 0, "quantity": 0})
            return out

        bids = mkd.get("bid") or []
        asks = mkd.get("ask") or []
        return {
            "asks": levels(asks),
            "bids": levels(bids),
            "high": _f(qt.get("h")),
            "low": _f(qt.get("l")),
            "ltp": _f(qt.get("ltp")),
            "ltq": _i(qt.get("ltTQty")),
            "oi": _i(qt.get("opInt")),
            "open": _f(qt.get("o")),
            "prev_close": _f(qt.get("c")),
            "totalbuyqty": _i(mkd.get("buyQty")) or sum(_i(r.get("qty")) for r in bids),
            "totalsellqty": _i(mkd.get("sellQty")) or sum(_i(r.get("qty")) for r in asks),
            "volume": _i(qt.get("vol")),
        }

    def get_market_depth(self, symbol: str, exchange: str) -> dict:
        return self.get_depth(symbol, exchange)

    # --- history ------------------------------------------------------------------

    def _chart_route(self, symbol, exchange, interval):
        info = get_symbol_info(symbol, exchange)
        if not info or not info.token:
            raise NuvamaDataError(f"{symbol} is not in the Nuvama master contract for {exchange}")
        is_index_underlying = False
        if exchange in ("NFO", "BFO"):
            underlying = info.name or ""
            is_index_underlying = bool(
                get_token(underlying, "NSE_INDEX") or get_token(underlying, "BSE_INDEX")
            )
        asset = chart_asset_type(exchange, info.instrumenttype, is_index_underlying)
        return f"{BASE_CONTENT}charts/v2/main/{interval}/{chart_exchange(exchange)}/{asset}/{info.token}"

    def _fetch_candles(self, url, body):
        _pace()
        response = nuvama_request("POST", url, self.auth_token, payload=body, timeout=30.0)
        if not response.ok:
            code = response.error_code()
            if response.status_code == 222 or code:
                # Nuvama's "no data" answer.
                logger.debug(f"Nuvama chart answered no data: {response.error_message()}")
                return pd.DataFrame(columns=HISTORY_COLUMNS[:-1])
            raise NuvamaDataError(response.error_message("Nuvama sent no chart data"))
        points = (response.data.get("data") or {}).get("pltPnts") or {}
        frame = pd.DataFrame(
            {
                "timestamp": points.get("ltt") or [],
                "open": points.get("open") or [],
                "high": points.get("high") or [],
                "low": points.get("low") or [],
                "close": points.get("close") or [],
                "volume": points.get("vol") or [],
            }
        )
        return frame

    def get_history(
        self, symbol: str, exchange: str, interval: str, start_date: str, end_date: str
    ) -> pd.DataFrame:
        resolution = self.timeframe_map.get(interval)
        if not resolution:
            raise NuvamaDataError(
                f"Interval {interval} is not available from Nuvama. "
                f"Use one of: {', '.join(self.timeframe_map)}"
            )
        start = datetime.strptime(str(start_date)[:10], "%Y-%m-%d").date()
        end = datetime.strptime(str(end_date)[:10], "%Y-%m-%d").date()
        df = self._series(symbol, exchange, resolution, start, end)
        if resolution in _INTRADAY_MINUTES and not df.empty:
            df = self._session_align(df, symbol, exchange, resolution)
        return df

    def _series(self, symbol, exchange, resolution, start, end) -> pd.DataFrame:
        """Nuvama's own candles for a date range, each stamped with its open (epoch)."""
        url = self._chart_route(symbol, exchange, resolution)

        frames = []
        today = datetime.now(IST).date()
        # The chart route pages backwards with `ltt` (checked live):
        # - no ltt: the latest page, up to now (today's candle included)
        # - intraday, ltt=D: about 1500 candles up to the day before D
        # - daily, ltt=D: about six years up to the end of the year before D's
        # The custom-period body (prdTyp CUST) is not used: past about six
        # months it answers coarser candles than asked (monthly for a year).
        if resolution == "D1":
            till = None if end.year >= today.year else date(end.year + 1, 1, 1)
        else:
            till = None if end >= today else end + timedelta(days=1)
        for _ in range(200):
            frame = self._fetch_candles(
                url,
                {"chTyp": "Interval", "conti": False, "ltt": till.isoformat() if till else None},
            )
            if frame.empty:
                break
            frames.append(frame)
            earliest = pd.to_datetime(frame["timestamp"]).min().date()
            if earliest <= start:
                break
            if resolution == "D1":
                # Pages are whole years: the next one ends the year before.
                next_till = date(earliest.year, 1, 1)
            else:
                # A page can start partway through a day; ask through that
                # whole day again and let the duplicates drop.
                next_till = earliest + timedelta(days=1)
            if till is not None and next_till >= till:
                break
            till = next_till

        if not frames or all(f.empty for f in frames):
            return pd.DataFrame(columns=HISTORY_COLUMNS)

        df = pd.concat(frames, ignore_index=True)
        stamps = pd.to_datetime(df["timestamp"], format="%Y-%m-%d %H:%M:%S", errors="coerce")
        df = df[stamps.notna()].copy()
        stamps = stamps[stamps.notna()]
        df = df[(stamps.dt.date >= start) & (stamps.dt.date <= end)]
        stamps = stamps.loc[df.index]

        if resolution == "D1":
            # Daily candles at the date's midnight, as the other plugins report them.
            epoch = stamps.dt.normalize().astype("int64") // 10**9
        else:
            # Intraday: Nuvama's bars sit on a clock grid (30m bars end at :00
            # and :30, 1h bars on the hour) and are stamped with their close
            # (the first 1m bar is 09:16), the bar still forming with its last
            # tick. Floor each stamp, less a second, onto that grid to get the
            # bar's open. The IST wall-clock open as a true epoch.
            step = f"{_INTRADAY_MINUTES[resolution]}min"
            opens = (stamps - pd.Timedelta(seconds=1)).dt.floor(step)
            epoch = opens.dt.tz_localize("Asia/Kolkata").astype("int64") // 10**9

        out = pd.DataFrame(
            {
                "timestamp": epoch.astype("int64"),
                "open": pd.to_numeric(df["open"], errors="coerce"),
                "high": pd.to_numeric(df["high"], errors="coerce"),
                "low": pd.to_numeric(df["low"], errors="coerce"),
                "close": pd.to_numeric(df["close"], errors="coerce"),
                "volume": pd.to_numeric(df["volume"], errors="coerce").fillna(0).astype("int64"),
                "oi": 0,
            }
        )
        out = out.sort_values("timestamp").drop_duplicates(subset=["timestamp"], keep="first")
        return out.reset_index(drop=True)[HISTORY_COLUMNS]

    def _session_align(self, df, symbol, exchange, resolution) -> pd.DataFrame:
        """Put intraday bars on the exchange session grid, as Zerodha and Shoonya send them.

        Nuvama's bars are clock-aligned: its 1h bars start 09:00, 10:00, and
        its 15m bars on Muhurat day (session 14:20) start 14:00, 14:15. The
        /trading chart refuses a whole history request when one source bar is
        off its session grid ("Unknown source candle boundaries") while
        deriving 45m, 2h, 3h, 4h and the like, and shows only live bars.

        Each day whose session open (from OpenAlgo's market calendar, so no
        session time is assumed here) is not a multiple of the bar length is
        rebuilt from the coarsest Nuvama interval that fits both the bar length
        and the open (15m for 30m and 1h on a 09:15 open, 5m or 1m on a special
        session), in buckets counted from the open. Bars before the open (the
        pre-open match Nuvama reports on special sessions, 14:05 on Muhurat
        day) fold into the first bucket on every interval, 1m included: the
        chart refuses them too. Days already on the grid with nothing before
        the open, and days the calendar does not cover, keep Nuvama's bars.
        """
        step = _INTRADAY_MINUTES[resolution]
        calendar_exchange = {"NSE_INDEX": "NSE", "BSE_INDEX": "BSE"}.get(exchange, exchange)
        days = pd.to_datetime(df["timestamp"], unit="s", utc=True).dt.tz_convert(IST).dt.date

        rebuild: dict[int, list[tuple[date, int]]] = {}
        for day in sorted(set(days)):
            open_minute = _session_open_minute(day, calendar_exchange)
            if open_minute is None:
                continue
            if open_minute % step == 0:
                # On the grid already; fold any pre-open bars from the bars in hand.
                day_first = int(df["timestamp"][(days == day).values].min())
                if day_first < _session_open_epoch(day, open_minute):
                    rebuild.setdefault(0, []).append((day, open_minute))
                continue
            source = next(
                (m for m in (15, 5, 3, 1) if m < step and step % m == 0 and open_minute % m == 0),
                1,
            )
            rebuild.setdefault(source, []).append((day, open_minute))
        if not rebuild:
            return df

        rebuilt = []
        rebuilt_days = set()
        for source, day_opens in rebuild.items():
            first, last = day_opens[0][0], day_opens[-1][0]
            src = df if source == 0 else self._series(symbol, exchange, f"M{source}", first, last)
            if src.empty:
                continue
            src_days = (
                pd.to_datetime(src["timestamp"], unit="s", utc=True).dt.tz_convert(IST).dt.date
            )
            for day, open_minute in day_opens:
                bars = src[src_days == day]
                if bars.empty:
                    continue
                session_open = _session_open_epoch(day, open_minute)
                offset = (bars["timestamp"].clip(lower=session_open) - session_open) // (step * 60)
                bucket = (session_open + offset * step * 60).values
                grouped = bars.groupby(bucket)
                rebuilt.append(
                    pd.DataFrame(
                        {
                            "timestamp": grouped["open"].first().index.astype("int64"),
                            "open": grouped["open"].first().values,
                            "high": grouped["high"].max().values,
                            "low": grouped["low"].min().values,
                            "close": grouped["close"].last().values,
                            "volume": grouped["volume"].sum().values.astype("int64"),
                            "oi": 0,
                        }
                    )
                )
                rebuilt_days.add(day)
        if not rebuilt:
            return df
        kept = df[~days.isin(rebuilt_days).values]
        out = pd.concat([kept, *rebuilt], ignore_index=True)
        out = out.sort_values("timestamp").drop_duplicates(subset=["timestamp"], keep="first")
        return out.reset_index(drop=True)[HISTORY_COLUMNS]

    def get_intervals(self) -> list:
        return list(self.timeframe_map)
