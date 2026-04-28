import json
from typing import Any

import pandas as pd

from broker.iiflcapital.baseurl import BASE_URL
from database.token_db import get_brexchange, get_token
from utils.httpx_client import get_httpx_client
from utils.logging import get_logger

logger = get_logger(__name__)


def _try_json(value: Any) -> Any:
    if not isinstance(value, str):
        return value

    text = value.strip()
    if not text:
        return value

    if text[0] not in "{[":
        return value

    try:
        return json.loads(text)
    except Exception:
        return value


def _to_float(value: Any, default: float = 0.0) -> float:
    try:
        if value in (None, "", "-"):
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _to_int(value: Any, default: int = 0) -> int:
    try:
        if value in (None, "", "-"):
            return default
        return int(float(value))
    except (TypeError, ValueError):
        return default


def _safe_dict(value: Any) -> dict:
    return value if isinstance(value, dict) else {}


def _short_text(value: str, limit: int = 300) -> str:
    text = " ".join((value or "").split())
    if len(text) <= limit:
        return text
    return f"{text[:limit]}..."


def _first(value: dict, keys: tuple[str, ...], default=None):
    for key in keys:
        if key in value and value[key] not in (None, ""):
            return value[key]
    return default


def _is_success(status_code: int, payload: Any) -> bool:
    if isinstance(payload, dict):
        status = str(payload.get("status", "")).lower()
        if status in ("error", "failed", "failure", "false", "ko"):
            return False
        if status in ("ok", "success", "true", "200"):
            return True

        result = payload.get("result")
        if isinstance(result, dict):
            nested = str(result.get("status", "")).lower()
            if nested in ("error", "failed", "failure", "false", "ko"):
                return False
            if nested in ("ok", "success", "true", "200"):
                return True
        elif isinstance(result, list) and result and isinstance(result[0], dict):
            nested = str(result[0].get("status", "")).lower()
            if nested in ("error", "failed", "failure", "false", "ko"):
                return False
            if nested in ("ok", "success", "true", "200"):
                return True

    if status_code == 200:
        return True

    return False


def _looks_like_market_row(value: Any) -> bool:
    if not isinstance(value, dict):
        return False

    if any(
        key in value
        for key in (
            "ltp",
            "lastTradedPrice",
            "lastPrice",
            "open",
            "high",
            "low",
            "close",
            "tradedVolume",
            "volume",
            "bestBidPrice",
            "bestAskPrice",
            "besAskPrice",
            "marketDepth",
            "depth",
            "instrumentId",
        )
    ):
        return True

    touchline = value.get("touchline") or value.get("Touchline")
    if isinstance(touchline, dict):
        return True

    return False


def _extract_row_error(row: dict) -> str | None:
    status = str(_first(row, ("status", "Status"), "")).lower()
    if status in ("error", "failed", "failure", "false", "ko"):
        return str(
            _first(row, ("message", "error", "description", "emsg"), "Request failed")
        )
    return None


def _extract_rows(payload: Any) -> list:
    payload = _try_json(payload)

    if isinstance(payload, list):
        return payload

    if not isinstance(payload, dict):
        return []

    # Common response containers.
    for key in ("result", "data", "quotes", "candles", "historicalData", "marketDepth"):
        value = _try_json(payload.get(key))
        if isinstance(value, list):
            return value
        if isinstance(value, dict):
            for sub_key in (
                "data",
                "rows",
                "quotes",
                "candles",
                "historicalData",
                "marketDepth",
                "listQuotes",
            ):
                sub_value = _try_json(value.get(sub_key))
                if isinstance(sub_value, list):
                    return sub_value
                if isinstance(sub_value, dict) and _looks_like_market_row(sub_value):
                    return [sub_value]
                if isinstance(sub_value, str) and "|" in sub_value:
                    return [sub_value]
        if isinstance(value, dict) and _looks_like_market_row(value):
            return [value]

    if _looks_like_market_row(payload):
        # Some APIs may return a single quote/depth object directly.
        return [payload]

    return []


def _normalize_exchange(exchange: str) -> str:
    exchange = (exchange or "").upper()
    mapping = {
        "NSE": "NSEEQ",
        "BSE": "BSEEQ",
        "NFO": "NSEFO",
        "BFO": "BSEFO",
        "CDS": "NSECURR",
        "BCD": "BSECURR",
        "MCX": "MCXCOMM",
        "NSE_INDEX": "NSEEQ",
        "BSE_INDEX": "BSEEQ",
        "MCX_INDEX": "MCXCOMM",
    }
    return mapping.get(exchange, exchange)


def _parse_quote_row(row: dict) -> dict:
    row = _safe_dict(row)

    # Handle nested touchline/depth styles if broker returns XTS-like payload.
    touchline = _safe_dict(_first(row, ("touchline", "Touchline", "quote", "Quote"), {}))
    depth = _safe_dict(_first(row, ("depth", "marketDepth", "Depth"), {}))

    bid_levels = _first(depth, ("buy", "bids", "Buy"), []) or []
    ask_levels = _first(depth, ("sell", "asks", "Sell"), []) or []
    bid_level_1 = bid_levels[0] if isinstance(bid_levels, list) and bid_levels else {}
    ask_level_1 = ask_levels[0] if isinstance(ask_levels, list) and ask_levels else {}

    bid_info = _safe_dict(_first(touchline, ("BidInfo", "bidInfo"), {}))
    ask_info = _safe_dict(_first(touchline, ("AskInfo", "askInfo"), {}))

    ltp = _to_float(
        _first(
            row,
            ("ltp", "LTP", "lastTradedPrice", "lastPrice", "last_price"),
            _first(touchline, ("LastTradedPrice", "lastTradedPrice"), 0),
        )
    )

    return {
        "ask": _to_float(
            _first(
                row,
                ("ask", "askPrice", "bestAsk", "bestAskPrice", "besAskPrice"),
                _first(ask_info, ("Price", "price"), _first(ask_level_1, ("price", "Price"), 0)),
            )
        ),
        "bid": _to_float(
            _first(
                row,
                ("bid", "bidPrice", "bestBid", "bestBidPrice"),
                _first(bid_info, ("Price", "price"), _first(bid_level_1, ("price", "Price"), 0)),
            )
        ),
        "open": _to_float(
            _first(
                row,
                ("open", "openPrice", "dayOpen", "Open"),
                _first(touchline, ("Open", "open"), 0),
            )
        ),
        "high": _to_float(
            _first(
                row,
                ("high", "highPrice", "dayHigh", "High"),
                _first(touchline, ("High", "high"), 0),
            )
        ),
        "low": _to_float(
            _first(
                row,
                ("low", "lowPrice", "dayLow", "Low"),
                _first(touchline, ("Low", "low"), 0),
            )
        ),
        "ltp": ltp,
        "prev_close": _to_float(
            _first(
                row,
                (
                    "close",
                    "closePrice",
                    "previousClose",
                    "previousClosePrice",
                    "prevClose",
                    "prev_close",
                    "Close",
                ),
                _first(touchline, ("Close", "close"), 0),
            )
        ),
        "volume": _to_int(
            _first(
                row,
                ("volume", "tradedVolume", "totalTradedVolume", "totalTradedQuantity"),
                _first(touchline, ("TotalTradedQuantity", "totalTradedQuantity"), 0),
            )
        ),
        "oi": _to_int(_first(row, ("oi", "openInterest", "OpenInterest", "OI"), 0)),
    }


def _parse_depth_levels(levels: Any) -> list[dict]:
    if not isinstance(levels, list):
        return []

    normalized = []
    for level in levels[:20]:
        if isinstance(level, dict):
            normalized.append(
                {
                    "price": _to_float(_first(level, ("price", "Price"), 0)),
                    "quantity": _to_int(_first(level, ("quantity", "qty", "Quantity"), 0)),
                    "orders": _to_int(_first(level, ("orders", "numOrders", "Orders"), 0)),
                }
            )
        elif isinstance(level, (list, tuple)) and len(level) >= 2:
            normalized.append(
                {
                    "price": _to_float(level[0]),
                    "quantity": _to_int(level[1]),
                    "orders": _to_int(level[2]) if len(level) > 2 else 0,
                }
            )
    return normalized


def _top_five_depth_levels(levels: Any) -> list[dict]:
    normalized = _parse_depth_levels(levels)[:5]
    while len(normalized) < 5:
        normalized.append({"price": 0.0, "quantity": 0, "orders": 0})
    return normalized


def _parse_candle_sequence(row: Any) -> dict | None:
    if not isinstance(row, (list, tuple)) or len(row) < 6:
        return None

    timestamp = row[0]
    if isinstance(timestamp, str) and not timestamp.isdigit():
        parsed = pd.to_datetime(timestamp, errors="coerce")
        timestamp = int(parsed.timestamp()) if not pd.isna(parsed) else 0
    else:
        timestamp = _to_int(timestamp)
        if timestamp > 10**12:
            timestamp = timestamp // 1000

    return {
        "timestamp": timestamp,
        "open": _to_float(row[1]),
        "high": _to_float(row[2]),
        "low": _to_float(row[3]),
        "close": _to_float(row[4]),
        "volume": _to_int(row[5]),
        "oi": _to_int(row[6]) if len(row) > 6 else 0,
    }


def _parse_history_rows(rows: list) -> pd.DataFrame:
    candles = []

    for row in rows:
        row = _try_json(row)

        if isinstance(row, dict):
            nested_candles = _try_json(_first(row, ("candles", "Candles"), []))
            if isinstance(nested_candles, list):
                for candle_row in nested_candles:
                    candle = _parse_candle_sequence(candle_row)
                    if candle:
                        candles.append(candle)
                continue

        candle = _parse_candle_sequence(row)
        if candle:
            candles.append(candle)
            continue

        # Pipe-delimited fallback: timestamp|open|high|low|close|volume|oi
        if isinstance(row, str) and "|" in row:
            for candle_str in row.split(","):
                parts = candle_str.split("|")
                if len(parts) < 6:
                    continue
                candles.append(
                    {
                        "timestamp": _to_int(parts[0]),
                        "open": _to_float(parts[1]),
                        "high": _to_float(parts[2]),
                        "low": _to_float(parts[3]),
                        "close": _to_float(parts[4]),
                        "volume": _to_int(parts[5]),
                        "oi": _to_int(parts[6]) if len(parts) > 6 else 0,
                    }
                )
            continue

        row = _safe_dict(row)
        timestamp = _first(
            row,
            ("timestamp", "time", "dateTime", "datetime", "epoch", "candleTime"),
            0,
        )

        if isinstance(timestamp, str) and not timestamp.isdigit():
            parsed = pd.to_datetime(timestamp, errors="coerce")
            timestamp = int(parsed.timestamp()) if not pd.isna(parsed) else 0
        else:
            timestamp = _to_int(timestamp)
            if timestamp > 10**12:  # Milliseconds to seconds.
                timestamp = timestamp // 1000

        candles.append(
            {
                "timestamp": timestamp,
                "open": _to_float(_first(row, ("open", "o"), 0)),
                "high": _to_float(_first(row, ("high", "h"), 0)),
                "low": _to_float(_first(row, ("low", "l"), 0)),
                "close": _to_float(_first(row, ("close", "c"), 0)),
                "volume": _to_int(_first(row, ("volume", "v"), 0)),
                "oi": _to_int(_first(row, ("oi", "openInterest"), 0)),
            }
        )

    if not candles:
        return pd.DataFrame(columns=["timestamp", "open", "high", "low", "close", "volume", "oi"])

    df = pd.DataFrame(candles)
    df = df.replace([float("inf"), float("-inf")], 0).fillna(0)
    df = df.sort_values("timestamp").drop_duplicates("timestamp").reset_index(drop=True)
    return df[["timestamp", "open", "high", "low", "close", "volume", "oi"]]


def _format_iifl_date(value: str) -> str:
    parsed = pd.to_datetime(value, errors="coerce")
    if pd.isna(parsed):
        return value
    return parsed.strftime("%d-%b-%Y")


class BrokerData:
    def __init__(self, auth_token, feed_token=None, user_id=None):
        self.auth_token = auth_token
        self.feed_token = feed_token
        self.user_id = user_id
        self.timeframe_map = {
            "1m": "1 minute",
            "5m": "5 minutes",
            "10m": "10 minutes",
            "15m": "15 minutes",
            "30m": "30 minutes",
            "60m": "60 minutes",
            "1h": "60 minutes",
            "D": "1 day",
            "W": "weekly",
            "M": "monthly",
        }

    def _post(self, endpoint: str, payload: Any) -> Any:
        client = get_httpx_client()
        headers = {
            "Authorization": f"Bearer {self.auth_token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

        response = client.post(f"{BASE_URL}{endpoint}", headers=headers, json=payload)
        try:
            data = response.json()
        except Exception as exc:
            body = _short_text(response.text)
            message = f"Invalid broker response: HTTP {response.status_code}"
            if body:
                message = f"{message}: {body}"
            raise Exception(message) from exc

        if not _is_success(response.status_code, data):
            message = (
                data.get("message")
                if isinstance(data, dict)
                else None
            ) or (
                data.get("error") if isinstance(data, dict) else None
            ) or f"Request failed with HTTP {response.status_code}"
            raise Exception(message)

        return data

    def _fetch_marketquote_rows(self, instruments: list[dict]) -> list:
        response = self._post("/marketdata/marketquotes", instruments)
        rows = _extract_rows(response)
        if rows:
            return rows

        raise Exception("No quote rows in broker response")

    def _resolve_token(self, symbol: str, exchange: str) -> str:
        token = get_token(symbol, exchange)
        if token is None:
            raise Exception(f"Could not find instrument token for {exchange}:{symbol}")
        return str(token)

    def _instrument(self, symbol: str, exchange: str) -> dict:
        broker_exchange = (get_brexchange(symbol, exchange) or "").upper()
        if not broker_exchange or broker_exchange == "INDICES":
            broker_exchange = _normalize_exchange(exchange)

        return {
            "exchange": broker_exchange,
            "instrumentId": self._resolve_token(symbol, exchange),
        }

    def get_quotes(self, symbol: str, exchange: str) -> dict:
        rows = self._fetch_marketquote_rows([self._instrument(symbol, exchange)])
        if not rows:
            raise Exception("No quote data received from broker")

        row = _try_json(rows[0])
        if isinstance(row, str):
            raise Exception("Invalid quote row format received from broker")

        row = _safe_dict(row)
        row_error = _extract_row_error(row)
        if row_error:
            raise Exception(row_error)
        if not _looks_like_market_row(row):
            raise Exception("No quote data received from broker")

        return _parse_quote_row(row)

    def get_multiquotes(self, symbols: list) -> list:
        instruments = []
        valid_symbols = []
        skipped = []

        for item in symbols:
            symbol = item.get("symbol")
            exchange = item.get("exchange")
            if not symbol or not exchange:
                skipped.append(
                    {
                        "symbol": symbol,
                        "exchange": exchange,
                        "data": None,
                        "error": "Missing required symbol or exchange",
                    }
                )
                continue

            try:
                instrument = self._instrument(symbol, exchange)
                instruments.append(instrument)
                valid_symbols.append(
                    {
                        "symbol": symbol,
                        "exchange": exchange,
                        "instrument": instrument,
                    }
                )
            except Exception as exc:
                skipped.append(
                    {
                        "symbol": symbol,
                        "exchange": exchange,
                        "data": None,
                        "error": str(exc),
                    }
                )

        if not instruments:
            return skipped

        rows = self._fetch_marketquote_rows(instruments)

        parsed_rows = []
        rows_by_identity: dict[str, dict] = {}

        for row in rows:
            row = _try_json(row)
            if isinstance(row, str):
                continue
            row = _safe_dict(row)
            parsed_rows.append(row)

            row_exchange = str(_first(row, ("exchange", "exchangeSegment"), "")).upper()
            row_token = str(_first(row, ("instrumentId", "token", "exchangeInstrumentID"), ""))
            if row_exchange and row_token:
                rows_by_identity[f"{row_exchange}:{row_token}"] = row

        use_identity_lookup = bool(rows_by_identity)
        results = []

        for idx, original in enumerate(valid_symbols):
            instrument = original["instrument"]
            identity_key = f"{instrument['exchange']}:{instrument['instrumentId']}"
            original_exchange_key = f"{original['exchange'].upper()}:{instrument['instrumentId']}"

            if use_identity_lookup:
                row = rows_by_identity.get(identity_key) or rows_by_identity.get(original_exchange_key)
            else:
                row = parsed_rows[idx] if idx < len(parsed_rows) else None

            if not row:
                results.append(
                    {
                        "symbol": original["symbol"],
                        "exchange": original["exchange"],
                        "data": None,
                        "error": "No quote data available",
                    }
                )
                continue

            row_error = _extract_row_error(row)
            if row_error:
                results.append(
                    {
                        "symbol": original["symbol"],
                        "exchange": original["exchange"],
                        "data": None,
                        "error": row_error,
                    }
                )
                continue

            results.append(
                {
                    "symbol": original["symbol"],
                    "exchange": original["exchange"],
                    "data": _parse_quote_row(row),
                }
            )

        return skipped + results

    def get_depth(self, symbol: str, exchange: str) -> dict:
        payload = self._instrument(symbol, exchange)
        response = self._post("/marketdata/marketdepth", payload)

        rows = _extract_rows(response)
        if not rows:
            raise Exception("No depth data received from broker")

        row = rows[0]
        row = _try_json(row)
        if isinstance(row, str):
            raise Exception("Invalid depth row format received from broker")
        row = _safe_dict(row)

        depth = _safe_dict(_first(row, ("depth", "marketDepth", "Depth"), {}))
        buy = _top_five_depth_levels(_first(depth, ("buy", "bids", "Buy"), []))
        sell = _top_five_depth_levels(_first(depth, ("sell", "asks", "Sell"), []))

        ltp = _to_float(_first(row, ("ltp", "lastTradedPrice"), 0))
        ltq = _to_int(_first(row, ("ltq", "lastTradedQuantity", "lastTradeQty"), 0))
        open_price = _to_float(_first(row, ("open", "openPrice"), 0))
        high_price = _to_float(_first(row, ("high", "highPrice"), 0))
        low_price = _to_float(_first(row, ("low", "lowPrice"), 0))
        prev_close = _to_float(_first(row, ("close", "previousClose"), 0))
        volume = _to_int(_first(row, ("volume", "tradedVolume"), 0))
        oi = _to_int(_first(row, ("oi", "openInterest"), 0))
        total_buy_qty = _to_int(
            _first(
                row,
                ("totalBidQuantity", "totalBuyQuantity", "totBuyQuan", "totalbuyqty"),
                sum(level.get("quantity", 0) for level in buy),
            )
        )
        total_sell_qty = _to_int(
            _first(
                row,
                ("totalAskQuantity", "totalSellQuantity", "totSellQuan", "totalsellqty"),
                sum(level.get("quantity", 0) for level in sell),
            )
        )

        return {
            "bids": buy,
            "asks": sell,
            "buy": buy,
            "sell": sell,
            "depth": {"buy": buy, "sell": sell},
            "ltp": ltp,
            "open": open_price,
            "high": high_price,
            "low": low_price,
            "prev_close": prev_close,
            "ltq": ltq,
            "volume": volume,
            "oi": oi,
            "totalbuyqty": total_buy_qty,
            "totalsellqty": total_sell_qty,
        }

    def get_history(self, symbol: str, exchange: str, interval: str, start_date: str, end_date: str):
        broker_interval = self.timeframe_map.get(interval)
        if not broker_interval:
            raise Exception(f"Unsupported timeframe: {interval}")

        instrument = self._instrument(symbol, exchange)
        payload = {
            "exchange": instrument["exchange"],
            "instrumentId": instrument["instrumentId"],
            "interval": broker_interval,
            "fromDate": _format_iifl_date(start_date),
            "toDate": _format_iifl_date(end_date),
        }

        response = self._post("/marketdata/historicaldata", payload)
        rows = _extract_rows(response)
        df = _parse_history_rows(rows)

        if df.empty:
            # Return empty, typed frame for consistency with other brokers.
            return pd.DataFrame(
                columns=["timestamp", "open", "high", "low", "close", "volume", "oi"]
            )

        return df

    def get_history_oi(
        self,
        symbol: str,
        exchange: str,
        interval: str,
        start_date: str,
        end_date: str,
    ):
        df = self.get_history(symbol, exchange, interval, start_date, end_date)
        if "oi" not in df.columns:
            df["oi"] = 0
        return df
