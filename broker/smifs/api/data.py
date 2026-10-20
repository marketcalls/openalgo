"""SMIFS God Quant market data for OpenAlgo.

Quotes and five-level depth come from POST /v1/marketfeed/quote, and history
from POST /v1/charts/intraday (1, 5, 15 and 60 minute candles) and
POST /v1/charts/historical (daily candles).
"""

import time
from datetime import date, datetime, timedelta

import pandas as pd

from broker.smifs.api.baseurl import get_url
from broker.smifs.mapping.transform_data import map_exchange_type
from database.token_db import get_token
from utils.httpx_client import get_httpx_client

_COLUMNS = ["timestamp", "open", "high", "low", "close", "volume", "oi"]


class BrokerData:
    def __init__(self, auth_token):
        self.auth_token = auth_token
        # OpenAlgo interval -> SMIFS candle size. SMIFS serves 1, 5, 15, 25 and
        # 60 minute candles plus daily; 25 has no OpenAlgo interval name.
        self.timeframe_map = {"1m": "1", "5m": "5", "15m": "15", "1h": "60", "D": "D"}

    def _headers(self):
        return {"access-token": self.auth_token, "Content-Type": "application/json"}

    def _post(self, path, body):
        client = get_httpx_client()
        # Data calls are limited to 5 a second. A 429 is answered before the
        # call is processed, so waiting and retrying is always safe; this
        # matters when a long history range is fetched in several windows.
        for attempt in range(4):
            r = client.post(get_url(path), headers=self._headers(), json=body)
            if r.status_code != 429 or attempt == 3:
                break
            try:
                wait = float(r.headers.get("Retry-After", "1"))
            except ValueError:
                wait = 1.0
            time.sleep(min(max(wait, 0.2), 2.0))
        try:
            payload = r.json()
        except Exception:  # noqa: BLE001
            payload = {}
        if r.status_code != 200:
            message = payload.get("errorMessage") if isinstance(payload, dict) else None
            raise Exception(f"SMIFS {path} failed: {message or f'HTTP {r.status_code}'}")
        return payload

    def _instrument(self, symbol, exchange):
        token = get_token(symbol, exchange)
        if token is None:
            raise Exception(f"{symbol} is not in the SMIFS master contract for {exchange}")
        return str(token), map_exchange_type(exchange)

    def _quote(self, symbol, exchange):
        token, seg = self._instrument(symbol, exchange)
        payload = self._post("/v1/marketfeed/quote", {seg: [token]})
        rec = payload.get("data", {}).get(seg, {}).get(token)
        if rec is None:
            # SMIFS leaves out instruments it has no data for rather than erroring.
            raise Exception(f"SMIFS has no market data for {symbol} on {exchange}")
        return rec

    def get_quotes(self, symbol, exchange):
        rec = self._quote(symbol, exchange)
        ohlc = rec.get("ohlc") or {}
        depth = rec.get("depth") or {}
        bids, asks = depth.get("buy") or [], depth.get("sell") or []
        return {
            "ltp": rec.get("last_price", 0),
            "open": ohlc.get("open", 0),
            "high": ohlc.get("high", 0),
            "low": ohlc.get("low", 0),
            # SMIFS ohlc.close is the previous session's close.
            "prev_close": ohlc.get("close", 0),
            "volume": rec.get("volume", 0),
            "oi": rec.get("oi", 0),
            "bid": bids[0]["price"] if bids else 0,
            "ask": asks[0]["price"] if asks else 0,
        }

    def get_depth(self, symbol, exchange):
        rec = self._quote(symbol, exchange)
        ohlc = rec.get("ohlc") or {}
        depth = rec.get("depth") or {}

        def levels(side):
            rows = [
                {"price": lv.get("price", 0), "quantity": lv.get("quantity", 0)}
                for lv in (depth.get(side) or [])[:5]
            ]
            return rows + [{"price": 0, "quantity": 0}] * (5 - len(rows))

        return {
            "bids": levels("buy"),
            "asks": levels("sell"),
            "ltp": rec.get("last_price", 0),
            "ltq": 0,  # SMIFS snapshots do not carry the last traded quantity
            "volume": rec.get("volume", 0),
            "open": ohlc.get("open", 0),
            "high": ohlc.get("high", 0),
            "low": ohlc.get("low", 0),
            "prev_close": ohlc.get("close", 0),
            "oi": rec.get("oi", 0),
            "totalbuyqty": rec.get("total_buy_quantity", 0),
            "totalsellqty": rec.get("total_sell_quantity", 0),
        }

    def get_history(self, symbol, exchange, interval, start_date, end_date):
        if interval not in self.timeframe_map:
            raise Exception(
                f"interval {interval} is not supported; use one of {list(self.timeframe_map)}"
            )
        token, seg = self._instrument(symbol, exchange)
        daily = interval == "D"
        path = "/v1/charts/historical" if daily else "/v1/charts/intraday"
        span = _MAX_DAILY_SPAN if daily else _MAX_INTRADAY_SPAN
        frames = []
        for start, end in _windows(_as_date(start_date), _as_date(end_date), span):
            body = {
                "securityId": token,
                "exchangeSegment": seg,
                "fromDate": start.isoformat(),
                "toDate": end.isoformat(),
            }
            if not daily:
                body["interval"] = int(self.timeframe_map[interval])
            payload = self._post(path, body)
            frames.append(
                pd.DataFrame(
                    {
                        "timestamp": payload.get("timestamp", []),
                        "open": payload.get("open", []),
                        "high": payload.get("high", []),
                        "low": payload.get("low", []),
                        "close": payload.get("close", []),
                        "volume": payload.get("volume", []),
                        "oi": payload.get("openInterest", []),
                    },
                    columns=_COLUMNS,
                )
            )
        df = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame(columns=_COLUMNS)
        df = df.drop_duplicates(subset="timestamp")
        return df.sort_values("timestamp").reset_index(drop=True)


# SMIFS caps one request at 90 days of intraday candles and 7,305 days of
# daily candles (DT-2004); longer ranges are fetched in windows and joined.
_MAX_INTRADAY_SPAN = 90
_MAX_DAILY_SPAN = 7305


def _as_date(value):
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value)[:10])


def _windows(start, end, span_days):
    """Inclusive date windows of at most span_days days covering start..end."""
    windows = []
    while start <= end:
        stop = min(end, start + timedelta(days=span_days - 1))
        windows.append((start, stop))
        start = stop + timedelta(days=1)
    return windows


def _day(value):
    """OpenAlgo passes dates as yyyy-mm-dd strings or date objects; SMIFS wants yyyy-MM-dd."""
    if isinstance(value, (date, datetime)):
        return value.strftime("%Y-%m-%d")
    return str(value)[:10]
