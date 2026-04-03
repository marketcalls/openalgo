import json
from typing import Any

import pandas as pd

from broker.iiflcapital.baseurl import BASE_URL
from database.token_db import get_token
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
        "NSE_INDEX": "INDICES",
        "BSE_INDEX": "INDICES",
        "MCX_INDEX": "INDICES",
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
                ("ask", "askPrice", "bestAsk", "bestAskPrice"),
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


def _parse_history_rows(rows: list) -> pd.DataFrame:
    candles = []

    for row in rows:
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


class BrokerData:
    def __init__(self, auth_token, feed_token=None, user_id=None):
        self.auth_token = auth_token
        self.feed_token = feed_token
        self.user_id = user_id
        self.timeframe_map = {
            "1m": "ONE_MINUTE",
            "2m": "TWO_MINUTE",
            "3m": "THREE_MINUTE",
            "5m": "FIVE_MINUTE",
            "10m": "TEN_MINUTE",
            "15m": "FIFTEEN_MINUTE",
            "30m": "THIRTY_MINUTE",
            "60m": "SIXTY_MINUTE",
            "D": "ONE_DAY",
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
            raise Exception(f"Invalid broker response: HTTP {response.status_code}") from exc

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
        errors = []
        payload_variants = [
            instruments,
            {"instruments": instruments},
        ]

        for payload in payload_variants:
            try:
                response = self._post("/marketdata/marketquotes", payload)
            except Exception as exc:
                errors.append(str(exc))
                continue

            rows = _extract_rows(response)
            if rows:
                return rows

            errors.append("No quote rows in broker response")

        if errors:
            raise Exception(errors[-1])

        raise Exception("No quote data received from broker")

    def _resolve_token(self, symbol: str, exchange: str) -> str:
        token = get_token(symbol, exchange)
        if token is None:
            raise Exception(f"Could not find instrument token for {exchange}:{symbol}")
        return str(token)

    def _instrument(self, symbol: str, exchange: str) -> dict:
        return {
            "exchange": _normalize_exchange(exchange),
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
        identity_map: dict[str, dict] = {}
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
                valid_symbols.append({"symbol": symbol, "exchange": exchange})
                identity_map[f"{instrument['exchange']}:{instrument['instrumentId']}"] = {
                    "symbol": symbol,
                    "exchange": exchange,
                }
                identity_map[f"{exchange.upper()}:{instrument['instrumentId']}"] = {
                    "symbol": symbol,
                    "exchange": exchange,
                }
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

        results = []
        for idx, row in enumerate(rows):
            row = _try_json(row)
            if isinstance(row, str):
                continue
            row = _safe_dict(row)

            row_exchange = str(_first(row, ("exchange", "exchangeSegment"), "")).upper()
            row_token = str(_first(row, ("instrumentId", "token", "exchangeInstrumentID"), ""))
            original = identity_map.get(f"{row_exchange}:{row_token}")

            # Fallback to request order when identity is not present in response payload.
            if not original and idx < len(valid_symbols):
                original = {
                    "symbol": valid_symbols[idx]["symbol"],
                    "exchange": valid_symbols[idx]["exchange"],
                }

            if not original:
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
        payload = {"instruments": [self._instrument(symbol, exchange)], "depthLevel": 5}
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
        buy = _parse_depth_levels(_first(depth, ("buy", "bids", "Buy"), []))
        sell = _parse_depth_levels(_first(depth, ("sell", "asks", "Sell"), []))

        ltp = _to_float(_first(row, ("ltp", "lastTradedPrice"), 0))
        open_price = _to_float(_first(row, ("open", "openPrice"), 0))
        high_price = _to_float(_first(row, ("high", "highPrice"), 0))
        low_price = _to_float(_first(row, ("low", "lowPrice"), 0))
        prev_close = _to_float(_first(row, ("close", "previousClose"), 0))
        volume = _to_int(_first(row, ("volume", "tradedVolume"), 0))
        oi = _to_int(_first(row, ("oi", "openInterest"), 0))

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
            "volume": volume,
            "oi": oi,
            "totalbuyqty": sum(level.get("quantity", 0) for level in buy),
            "totalsellqty": sum(level.get("quantity", 0) for level in sell),
        }

    def get_history(self, symbol: str, exchange: str, interval: str, start_date: str, end_date: str):
        broker_interval = self.timeframe_map.get(interval)
        if not broker_interval:
            raise Exception(f"Unsupported timeframe: {interval}")

        start_ts = f"{start_date} 00:00:00"
        end_ts = f"{end_date} 23:59:59"
        payload = {
            "exchange": _normalize_exchange(exchange),
            "instrumentId": self._resolve_token(symbol, exchange),
            "interval": broker_interval,
            "fromDate": start_ts,
            "toDate": end_ts,
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
