from .HSWebSocketLib import HSWebSocket
import json
import time
import threading
import pandas as pd
from database.token_db import get_token
from utils.logging import get_logger

logger = get_logger(__name__)


logger = get_logger(__name__)

class KotakWebSocket:
    def __init__(self):
        self.ws = HSWebSocket()
        self.last_quote = None
        self.last_depth = None  # Add depth data storage

    def _send_messages(self, token, sid, exchange, scrip, message_type):
        try:
            # Send connection request
            self.ws.hs_send(json.dumps({
                "type": "cn",
                "Authorization": token,
                "Sid": sid
            }))
            logger.info("Sent connection request")

            # Send depth subscription request
            self.ws.hs_send(json.dumps({
                "type": message_type,  # Use message_type for flexibility
                "scrips": f"{exchange}|{scrip}",
                "channelnum": "1"
            }))
            logger.info(f"Sent {message_type} subscription request")
        except Exception as e:
            logger.error(f"Error in _send_messages: {e}")

    def on_message(self, message):
        try:
            data = json.loads(message) if isinstance(message, str) else message
            if data and isinstance(data, list) and len(data) > 0:
                msg = data[0]
                if isinstance(msg, dict):
                    if 'name' in msg and msg['name'] == 'dp':  # Check for depth data
                        # Process depth data
                        bids = []
                        asks = []

                        # Process best 5 bids
                        for i in range(5):
                            price_key = f'bp{i}' if i > 0 else 'bp'
                            qty_key = f'bq{i}' if i > 0 else 'bq'
                            
                            price = float(msg.get(price_key, 0))
                            bids.append({
                                'price': price,
                                'quantity': int(msg.get(qty_key, 0))
                            })

                        # Process best 5 asks
                        for i in range(5):
                            price_key = f'sp{i}' if i > 0 else 'sp'
                            qty_key = f'bs{i}' if i > 0 else 'bs'
                            
                            price = float(msg.get(price_key, 0))
                            asks.append({
                                'price': price,
                                'quantity': int(msg.get(qty_key, 0))
                            })

                        self.last_depth = {
                            'bids': bids,
                            'asks': asks,
                            'totalbuyqty': sum(bid['quantity'] for bid in bids),
                            'totalsellqty': sum(ask['quantity'] for ask in asks)
                        }
                        self.ws.close()
                    elif 'ltp' in msg:
                        self.last_quote = {
                            'bid': float(msg.get('bp', 0)),
                            'ask': float(msg.get('sp', 0)),
                            'open': float(msg.get('op', 0)),
                            'high': float(msg.get('h', 0)),
                            'low': float(msg.get('lo', 0)),
                            'ltp': float(msg.get('ltp', 0)),
                            'prev_close': float(msg.get('c', 0)),
                            'volume': float(msg.get('v', 0)),
                            'oi': int(msg.get('oi', 0))
                        }
                        self.ws.close()
        except Exception as e:
            logger.error(f"Error processing message: {e}")
            self.ws.close()

    def on_open(self, token, sid, exchange, scrip, message_type):  # Add message_type parameter
        threading.Thread(target=self._send_messages, 
                       args=(token, sid, exchange, scrip, message_type)).start()

    def connect(self, url, token, sid, exchange, scrip, message_type):  # Add message_type parameter
        self.ws.open_connection(
            url=url,
            token=token,
            sid=sid,
            on_open=lambda: self.on_open(token, sid, exchange, scrip, message_type),
            on_message=self.on_message,
            on_error=lambda error: logger.error(f"WebSocket error: {error}"),
            on_close=lambda: logger.info("WebSocket connection closed")
        )

class BrokerData:
    def __init__(self, auth_token):
        self.auth_token, self.sid, _, _ = auth_token.split(":::")
        self.ws_url = "wss://mlhsm.kotaksecurities.com"
        # Define empty timeframe map since Kotak Neo doesn't support historical data
        self.timeframe_map = {
            # Empty mapping to maintain compatibility
        }
        logger.warning("Kotak Neo does not support historical data intervals")

    def get_quotes(self, symbol, exchange):
        try:
            token = get_token(symbol, exchange)
            if not token:
                raise ValueError(f"Token not found for {symbol} on {exchange}")

            exchange_map = {'NSE': 'nse_cm', 'BSE': 'bse_cm', 'NFO': 'nse_fo',
                            "BFO": "bse_fo", "CDS": "cde_fo", "MCX": "mcx_fo", 
                            "NSE_INDEX": "nse_cm", "BSE_INDEX": "bse_cm"
                            }
            kotak_exchange = exchange_map.get(exchange)
            if not kotak_exchange:
                raise ValueError(f"Unsupported exchange: {exchange}")

            ws = KotakWebSocket()
            ws.connect(self.ws_url, self.auth_token, self.sid, kotak_exchange, token, "mws")  # Changed to "mws"
            time.sleep(0.2)

            return ws.last_quote or {
                'bid': 0, 'ask': 0, 'open': 0,
                'high': 0, 'low': 0, 'ltp': 0,
                'prev_close': 0, 'volume': 0, 'oi': 0
            }
        except Exception as e:
            logger.error(f"Error in get_quotes: {e}")
            return {
                'bid': 0, 'ask': 0, 'open': 0,
                'high': 0, 'low': 0, 'ltp': 0,
                'prev_close': 0, 'volume': 0, 'oi': 0
            }

    def get_depth(self, symbol: str, exchange: str) -> dict:
        """Get market depth for given symbol"""
        try:
            token = get_token(symbol, exchange)
            if not token:
                raise ValueError(f"Token not found for {symbol} on {exchange}")

            exchange_map = {'NSE': 'nse_cm', 'BSE': 'bse_cm', 'NFO': 'nse_fo'}
            kotak_exchange = exchange_map.get(exchange)
            if not kotak_exchange:
                raise ValueError(f"Unsupported exchange: {exchange}")

            ws = KotakWebSocket()
            ws.connect(self.ws_url, self.auth_token, self.sid, kotak_exchange, token, "dpsp")
            time.sleep(0.2)

            # Return depth data or default structure
            default_depth = {
                'bids': [{'price': 0, 'quantity': 0} for _ in range(5)],
                'asks': [{'price': 0, 'quantity': 0} for _ in range(5)],
                'totalbuyqty': 0,
                'totalsellqty': 0
            }

            return ws.last_depth or default_depth

        except Exception as e:
            logger.error(f"Error in get_depth: {e}")
            return {
                'bids': [{'price': 0, 'quantity': 0} for _ in range(5)],
                'asks': [{'price': 0, 'quantity': 0} for _ in range(5)],
                'totalbuyqty': 0,
                'totalsellqty': 0
            }

    def get_history(self, symbol: str, exchange: str, interval: str, start_date: str, end_date: str) -> pd.DataFrame:
        """Placeholder for historical data - not supported by Kotak Neo"""
        # Return empty DataFrame with required columns to match the API's expected format
        empty_df = pd.DataFrame(columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
        # Add an error message that will be logged but won't affect the DataFrame format
        logger.warning("Kotak Neo does not support historical data")
        return empty_df

    def get_supported_intervals(self) -> dict:
        """Return supported intervals matching the format expected by intervals.py"""
        intervals = {
            'seconds': sorted([k for k in self.timeframe_map.keys() if k.endswith('s')]),
            'minutes': sorted([k for k in self.timeframe_map.keys() if k.endswith('m')]),
            'hours': sorted([k for k in self.timeframe_map.keys() if k.endswith('h')]),
            'days': sorted([k for k in self.timeframe_map.keys() if k == 'D']),
            'weeks': sorted([k for k in self.timeframe_map.keys() if k == 'W']),
            'months': sorted([k for k in self.timeframe_map.keys() if k == 'M'])
        }
        logger.warning("Kotak Neo does not support historical data intervals")
        return intervals
