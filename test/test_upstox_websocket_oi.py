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

    def test_extract_quote_data_vtt_volume(self):
        feed_data = {
            "fullFeed": {
                "marketFF": {
                    "ltpc": {"ltp": 123.45, "ltq": 65, "ltt": 1786941986428, "cp": 120.0},
                    "vtt": 6538415,
                    "oi": 6538415.0,
                    "atp": 123.5,
                    "tbq": 4500,
                    "tsq": 5000,
                }
            }
        }
        extracted = self.adapter._extract_market_data(feed_data, self.sub_info, 1786941986428)
        self.assertEqual(extracted["volume"], 6538415)
        self.assertEqual(extracted["oi"], 6538415)
        self.assertEqual(extracted["ltp"], 123.45)
        self.assertEqual(extracted["average_price"], 123.5)
        self.assertEqual(self.adapter._last_volume.get("NSE_FO|54321"), 6538415)

    def test_extract_quote_data_first_level_with_greeks_volume(self):
        feed_data = {
            "firstLevelWithGreeks": {
                "ltpc": {"ltp": 500.0, "ltq": 50, "ltt": 1723600000, "cp": 480.0},
                "vtt": 5000,
                "oi": 85000.0,
            }
        }
        vol_extracted = self.adapter._extract_tick_volume(feed_data)
        self.assertEqual(vol_extracted, 5000)

    def test_extract_depth_mode_includes_full_quote_and_volume(self):
        depth_sub_info = {
            "symbol": "NIFTY18AUG2624200CE",
            "exchange": "NFO",
            "token": "NSE_FO|45098",
            "mode": 3,
            "instrument_key": "NSE_FO|45098",
        }
        feed_data = {
            "fullFeed": {
                "marketFF": {
                    "ltpc": {"ltp": 123.45, "ltq": 65, "ltt": 1786941986428, "cp": 120.0},
                    "marketLevel": {
                        "bidAskQuote": [
                            {"bidP": 123.3, "bidQ": 195, "askP": 123.6, "askQ": 195},
                            {"bidP": 123.25, "bidQ": 520, "askP": 123.65, "askQ": 1170},
                        ]
                    },
                    "marketOHLC": {
                        "ohlc": [
                            {
                                "interval": "1d",
                                "open": 100.0,
                                "high": 130.0,
                                "low": 90.0,
                                "close": 123.45,
                                "vol": 6538415,
                                "ts": 1786941986428,
                            }
                        ]
                    },
                    "atp": 123.5,
                    "vtt": 6538415,
                    "oi": 6538415.0,
                    "tbq": 4500,
                    "tsq": 5000,
                }
            }
        }
        extracted = self.adapter._extract_market_data(feed_data, depth_sub_info, 1786941986428)
        self.assertEqual(extracted["volume"], 6538415)
        self.assertEqual(extracted["ltp"], 123.45)
        self.assertEqual(extracted["open"], 100.0)
        self.assertEqual(extracted["high"], 130.0)
        self.assertEqual(extracted["low"], 90.0)
        self.assertEqual(extracted["close"], 123.45)
        self.assertEqual(extracted["average_price"], 123.5)
        self.assertEqual(extracted["total_buy_quantity"], 4500)
        self.assertEqual(extracted["total_sell_quantity"], 5000)
        self.assertEqual(extracted["oi"], 6538415)
        self.assertEqual(len(extracted["buy"]), 5)
        self.assertEqual(extracted["buy"][0]["price"], 123.3)
        self.assertEqual(extracted["buy"][0]["quantity"], 195)
        self.assertEqual(len(extracted["sell"]), 5)
        self.assertEqual(extracted["sell"][0]["price"], 123.6)
        self.assertEqual(extracted["sell"][0]["quantity"], 195)

    def test_carry_forward_volume_and_ohlc_on_incremental_depth_tick(self):
        depth_sub_info = {
            "symbol": "NIFTY18AUG2624200CE",
            "exchange": "NFO",
            "token": "NSE_FO|45098",
            "mode": 3,
            "instrument_key": "NSE_FO|45098",
        }
        # 1. Seed caches with initial full feed
        feed_data_1 = {
            "fullFeed": {
                "marketFF": {
                    "ltpc": {"ltp": 123.45, "ltq": 65, "ltt": 1786941986428, "cp": 120.0},
                    "marketOHLC": {
                        "ohlc": [
                            {
                                "interval": "1d",
                                "open": 100.0,
                                "high": 130.0,
                                "low": 90.0,
                                "close": 123.45,
                                "vol": 6538415,
                                "ts": 1786941986428,
                            }
                        ]
                    },
                    "atp": 123.5,
                    "vtt": 6538415,
                    "oi": 6538415.0,
                }
            }
        }
        self.adapter._extract_market_data(feed_data_1, depth_sub_info, 1786941986428)

        # 2. Incremental tick with ONLY marketLevel updates
        feed_data_2 = {
            "fullFeed": {
                "marketFF": {
                    "marketLevel": {
                        "bidAskQuote": [
                            {"bidP": 123.5, "bidQ": 300, "askP": 123.8, "askQ": 400},
                        ]
                    }
                }
            }
        }
        extracted_2 = self.adapter._extract_market_data(feed_data_2, depth_sub_info, 1786941986430)
        self.assertEqual(extracted_2["volume"], 6538415)
        self.assertEqual(extracted_2["ltp"], 123.45)
        self.assertEqual(extracted_2["open"], 100.0)
        self.assertEqual(extracted_2["high"], 130.0)
        self.assertEqual(extracted_2["oi"], 6538415)
        self.assertEqual(extracted_2["buy"][0]["price"], 123.5)

    def test_cleanup_clears_cached_oi(self):
        self.adapter._last_oi["NSE_FO|54321"] = 150250
        self.adapter._last_ltpc["NSE_FO|54321"] = {"ltp": 50000.0}
        self.adapter._last_volume["NSE_FO|54321"] = 125000
        self.adapter._last_ohlc["NSE_FO|54321"] = {"open": 49900.0}
        self.adapter.cleanup()
        self.assertEqual(len(self.adapter._last_oi), 0)
        self.assertEqual(len(self.adapter._last_ltpc), 0)
        self.assertEqual(len(self.adapter._last_volume), 0)
        self.assertEqual(len(self.adapter._last_ohlc), 0)

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
        self.adapter._last_volume[instrument_key] = 125000

        resp = self.adapter.unsubscribe("BANKNIFTY26AUGFUT", "NFO", 2)
        self.assertEqual(resp["status"], "success")
        self.assertNotIn(instrument_key, self.adapter._last_oi)
        self.assertNotIn(instrument_key, self.adapter._last_ltpc)
        self.assertNotIn(instrument_key, self.adapter._last_volume)

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
        self.adapter._last_volume[instrument_key] = 125000

        # Unsubscribe mode 2 only; mode 3 remains
        resp = self.adapter.unsubscribe("BANKNIFTY26AUGFUT", "NFO", 2)
        self.assertEqual(resp["status"], "success")
        self.assertEqual(self.adapter._last_oi.get(instrument_key), 150250)
        self.assertEqual(self.adapter._last_ltpc.get(instrument_key), {"ltp": 50000.0})
        self.assertEqual(self.adapter._last_volume.get(instrument_key), 125000)


if __name__ == "__main__":
    unittest.main()
