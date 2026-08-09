"""SMIFS God Quant market data for OpenAlgo.

SMIFS currently exposes snapshot LTP/quote. Depth and history raise
NotImplementedError until the corresponding SMIFS endpoints ship; the
OpenAlgo services catch and surface a clean message.
"""
from utils.httpx_client import get_httpx_client

from broker.smifs.api.baseurl import get_url
from broker.smifs.mapping.transform_data import map_exchange_type
from database.token_db import get_token


class BrokerData:
    def __init__(self, auth_token):
        self.auth_token = auth_token
        self.timeframe_map = {"1m": "1", "5m": "5", "15m": "15", "1h": "60", "D": "D"}

    def _headers(self):
        return {"access-token": self.auth_token, "Content-Type": "application/json"}

    def get_quotes(self, symbol, exchange):
        token = get_token(symbol, exchange)
        seg = map_exchange_type(exchange)
        body = {seg: [str(token)]}
        client = get_httpx_client()
        r = client.post(get_url("/v1/marketfeed/quote"), headers=self._headers(), json=body)
        rec = {}
        if r.status_code == 200:
            payload = r.json().get("data", r.json())
            rec = payload.get(seg, {}).get(str(token), {})
        return {
            "ltp": rec.get("last_price", 0),
            "open": rec.get("ohlc", {}).get("open", 0) if isinstance(rec.get("ohlc"), dict) else 0,
            "high": rec.get("ohlc", {}).get("high", 0) if isinstance(rec.get("ohlc"), dict) else 0,
            "low": rec.get("ohlc", {}).get("low", 0) if isinstance(rec.get("ohlc"), dict) else 0,
            "close": rec.get("ohlc", {}).get("close", 0) if isinstance(rec.get("ohlc"), dict) else 0,
            "volume": rec.get("volume", 0),
            "bid": 0, "ask": 0,
        }

    def get_depth(self, symbol, exchange):
        raise NotImplementedError("SMIFS God Quant does not yet expose market depth over REST")

    def get_history(self, symbol, exchange, interval, start_date, end_date):
        raise NotImplementedError("SMIFS God Quant history endpoint is not wired in this plugin yet")
