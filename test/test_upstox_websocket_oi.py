"""
Unit tests for Upstox WebSocket Open Interest (OI) extraction and caching.
"""

import unittest
from unittest.mock import MagicMock, patch

import websocket_proxy.base_adapter  # Initialize websocket_proxy package first
from broker.upstox.streaming.upstox_adapter import UpstoxWebSocketAdapter


class TestUpstoxWebSocketOI(unittest.TestCase):
    def setUp(self):
        self.adapter = UpstoxWebSocketAdapter()
        self.sub_info = {
            "symbol": "BANKNIFTY26AUGFUT",
            "exchange": "NFO",
            "token": "NSE_FO|54321",
            "mode": 2,
            "instrument_key": "NSE_FO|54321",
        }

    def test_extract_quote_data_market_full_feed_oi(self):
        feed_data = {
            "fullFeed": {
                "marketFF": {
                    "ltpc": {"ltp": 50000.0, "ltq": 15, "ltt": 1723600000, "cp": 49800.0},
                    "marketOHLC": {
                        "ohlc": [
                            {
                                "interval": "1d",
                                "open": 49900.0,
                                "high": 50200.0,
                                "low": 49800.0,
                                "close": 50000.0,
                                "vol": 125000,
                                "ts": 1723600000,
                            }
                        ]
                    },
                    "atp": 50050.0,
                    "vtt": 125000,
                    "oi": 150250.0,
                    "tbq": 3000,
                    "tsq": 2500,
                }
            }
        }
        extracted = self.adapter._extract_market_data(feed_data, self.sub_info, 1723600000)
        self.assertEqual(extracted["oi"], 150250)
        self.assertNotIn("open_interest", extracted)
        self.assertEqual(self.adapter._last_oi.get("NSE_FO|54321"), 150250)

    def test_extract_quote_data_first_level_with_greeks_oi(self):
        feed_data = {
            "firstLevelWithGreeks": {
                "ltpc": {"ltp": 500.0, "ltq": 50, "ltt": 1723600000, "cp": 480.0},
                "vtt": 5000,
                "oi": 85000.0,
            }
        }
        oi_extracted = self.adapter._extract_tick_oi(feed_data)
        self.assertEqual(oi_extracted, 85000)

    def test_carry_forward_oi_on_partial_market_ff_tick(self):
        # 1. First tick has full feed with OI
        feed_data_1 = {
            "fullFeed": {
                "marketFF": {
                    "ltpc": {"ltp": 50000.0, "ltq": 15, "ltt": 1723600000, "cp": 49800.0},
                    "marketOHLC": {
                        "ohlc": [
                            {
                                "interval": "1d",
                                "open": 49900.0,
                                "high": 50200.0,
                                "low": 49800.0,
                                "close": 50000.0,
                                "vol": 125000,
                                "ts": 1723600000,
                            }
                        ]
                    },
                    "atp": 50050.0,
                    "oi": 150250.0,
                }
            }
        }
        self.adapter._extract_market_data(feed_data_1, self.sub_info, 1723600000)

        # 2. Realistic partial marketFF tick with quote details but WITHOUT oi
        feed_data_2 = {
            "fullFeed": {
                "marketFF": {
                    "ltpc": {"ltp": 50020.0, "ltq": 30, "ltt": 1723600005, "cp": 49800.0},
                    "marketOHLC": {
                        "ohlc": [
                            {
                                "interval": "1d",
                                "open": 49900.0,
                                "high": 50250.0,
                                "low": 49800.0,
                                "close": 50020.0,
                                "vol": 125100,
                                "ts": 1723600005,
                            }
                        ]
                    },
                    "atp": 50055.0,
                    "tbq": 3200,
                    "tsq": 2300,
                }
            }
        }
        extracted_2 = self.adapter._extract_market_data(feed_data_2, self.sub_info, 1723600005)
        # Verify quote fields are extracted correctly
        self.assertEqual(extracted_2["ltp"], 50020.0)
        self.assertEqual(extracted_2["high"], 50250.0)
        self.assertEqual(extracted_2["volume"], 125100)
        self.assertEqual(extracted_2["average_price"], 50055.0)
        # Verify OI is carried forward from cached value
        self.assertEqual(extracted_2["oi"], 150250)

    def test_carry_forward_oi_on_bare_ltpc_tick(self):
        # 1. Seed the cache with a full feed tick
        feed_data_1 = {
            "fullFeed": {
                "marketFF": {
                    "ltpc": {"ltp": 50000.0, "ltq": 15, "ltt": 1723600000, "cp": 49800.0},
                    "oi": 150250.0,
                }
            }
        }
        self.adapter._extract_market_data(feed_data_1, self.sub_info, 1723600000)

        # 2. Incremental tick without fullFeed wrapper
        feed_data_2 = {"ltpc": {"ltp": 50010.0, "ltq": 25, "ltt": 1723600005, "cp": 49800.0}}
        extracted_2 = self.adapter._extract_market_data(feed_data_2, self.sub_info, 1723600005)
        self.assertEqual(extracted_2["ltp"], 50010.0)
        self.assertEqual(extracted_2["oi"], 150250)

    def test_cleanup_clears_cached_oi(self):
        self.adapter._last_oi["NSE_FO|54321"] = 150250
        self.adapter._last_ltpc["NSE_FO|54321"] = {"ltp": 50000.0}
        self.adapter.cleanup()
        self.assertEqual(len(self.adapter._last_oi), 0)
        self.assertEqual(len(self.adapter._last_ltpc), 0)

    @patch("broker.upstox.streaming.upstox_adapter.SymbolMapper.get_token_from_symbol")
    def test_unsubscribe_clears_cached_oi_and_ltpc_when_no_remaining_subscriptions(
        self, mock_get_token
    ):
        mock_get_token.return_value = {
            "symbol": "BANKNIFTY26AUGFUT",
            "exchange": "NFO",
            "brexchange": "NSE_FO",
            "token": "54321",
        }
        self.adapter.ws_client = MagicMock()
        self.adapter.ws_client.unsubscribe.return_value = True

        instrument_key = "NSE_FO|54321"
        correlation_id = "BANKNIFTY26AUGFUT_NFO_2"
        self.adapter.subscriptions[correlation_id] = {
            "symbol": "BANKNIFTY26AUGFUT",
            "exchange": "NFO",
            "mode": 2,
            "token": "NSE_FO|54321",
            "instrument_key": instrument_key,
        }
        self.adapter._last_oi[instrument_key] = 150250
        self.adapter._last_ltpc[instrument_key] = {"ltp": 50000.0}

        resp = self.adapter.unsubscribe("BANKNIFTY26AUGFUT", "NFO", 2)
        self.assertEqual(resp["status"], "success")
        self.assertNotIn(instrument_key, self.adapter._last_oi)
        self.assertNotIn(instrument_key, self.adapter._last_ltpc)

    @patch("broker.upstox.streaming.upstox_adapter.SymbolMapper.get_token_from_symbol")
    def test_unsubscribe_retains_cache_when_other_mode_remains(self, mock_get_token):
        mock_get_token.return_value = {
            "symbol": "BANKNIFTY26AUGFUT",
            "exchange": "NFO",
            "brexchange": "NSE_FO",
            "token": "54321",
        }
        self.adapter.ws_client = MagicMock()
        self.adapter.ws_client.unsubscribe.return_value = True

        instrument_key = "NSE_FO|54321"
        self.adapter.subscriptions["BANKNIFTY26AUGFUT_NFO_2"] = {
            "symbol": "BANKNIFTY26AUGFUT",
            "exchange": "NFO",
            "mode": 2,
            "token": "NSE_FO|54321",
            "instrument_key": instrument_key,
        }
        self.adapter.subscriptions["BANKNIFTY26AUGFUT_NFO_3"] = {
            "symbol": "BANKNIFTY26AUGFUT",
            "exchange": "NFO",
            "mode": 3,
            "token": "NSE_FO|54321",
            "instrument_key": instrument_key,
        }
        self.adapter._last_oi[instrument_key] = 150250
        self.adapter._last_ltpc[instrument_key] = {"ltp": 50000.0}

        # Unsubscribe mode 2 only; mode 3 remains
        resp = self.adapter.unsubscribe("BANKNIFTY26AUGFUT", "NFO", 2)
        self.assertEqual(resp["status"], "success")
        self.assertEqual(self.adapter._last_oi.get(instrument_key), 150250)
        self.assertEqual(self.adapter._last_ltpc.get(instrument_key), {"ltp": 50000.0})


if __name__ == "__main__":
    unittest.main()
