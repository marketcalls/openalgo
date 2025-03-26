import json
import os
import urllib.parse
from database.token_db import get_br_symbol, get_oa_symbol, get_brexchange
from broker.compositedge.database.master_contract_db import SymToken, db_session
from flask import session  
import logging
import pandas as pd
from datetime import datetime, timedelta
from utils.httpx_client import get_httpx_client
from database.auth_db import get_feed_token
from .XTSSocketIOMarketdata import CompositEdgeWebSocket
import socketio
import threading

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def get_api_response(endpoint, auth, method="GET", payload='', feed_token=None, params=None):
    AUTH_TOKEN = auth
    if feed_token:
        FEED_TOKEN = feed_token
    print(f"Feed Token: {FEED_TOKEN}")
    
    # Get the shared httpx client with connection pooling
    client = get_httpx_client()
    
    headers = {
        'authorization': FEED_TOKEN if feed_token else AUTH_TOKEN,
        'Content-Type': 'application/json'
    }

    url = f"https://xts.compositedge.com{endpoint}"

    try:
        # Log request details
        logger.info("=== API Request Details ===")
        logger.info(f"URL: {url}")
        logger.info(f"Method: {method}")
        logger.info(f"Headers: {json.dumps(headers, indent=2)}")
        if params:
            logger.info(f"Query Params: {json.dumps(params, indent=2)}")
        if payload and payload != '':
            if isinstance(payload, str):
                try:
                    payload = json.loads(payload)
                except json.JSONDecodeError:
                    logger.error("Failed to parse payload as JSON")
                    raise Exception("Invalid payload format")
            logger.info(f"Payload: {json.dumps(payload, indent=2)}")

        # Perform the request
        if method.upper() == "GET":
            response = client.get(url, headers=headers, params=params)
        elif method.upper() == "POST":
            response = client.post(url, headers=headers, json=payload)
        else:
            response = client.request(method, url, headers=headers, json=payload)

        # Log response details
        logger.info("=== API Response Details ===")
        logger.info(f"Status Code: {response.status_code}")
        logger.info(f"Response Headers: {dict(response.headers)}")
        logger.info(f"Response Body: {response.text}")

        # Add status attribute for compatibility
        response.status = response.status_code
        return response.json()

    except Exception as e:
        logger.error(f"API request failed: {str(e)}")
        raise

class BrokerData:
    def __init__(self, auth_token, feed_token=None):
        """Initialize CompositEdge data handler with authentication token"""
        self.auth_token = auth_token
        self.feed_token = feed_token
        self.ws = None
        
        # Map common timeframe format to CompositEdge intervals
        self.timeframe_map = {
            # Minutes
            '1m': '1',
            '3m': '3',
            '5m': '5',
            '10m': '10',
            '15m': '15',
            '30m': '30',
            '60m': '60',
            # Daily
            'D': 'D'
        }
        
        # Market timing configuration for different exchanges
        self.market_timings = {
            'NSE': {
                'start': '09:15:00',
                'end': '15:30:00'
            },
            'BSE': {
                'start': '09:15:00',
                'end': '15:30:00'
            },
            'NFO': {
                'start': '09:15:00',
                'end': '15:30:00'
            },
            'CDS': {
                'start': '09:00:00',
                'end': '17:00:00'
            },
            'BCD': {
                'start': '09:00:00',
                'end': '17:00:00'
            },
            'MCX': {
                'start': '09:00:00',
                'end': '23:30:00'
            }
        }
        
        # Default market timings if exchange not found
        self.default_market_timings = {
            'start': '00:00:00',
            'end': '23:59:59'
        }

    def get_market_timings(self, exchange: str) -> dict:
        """Get market start and end times for given exchange"""
        return self.market_timings.get(exchange, self.default_market_timings)

    def get_quotes(self, symbol: str, exchange: str) -> dict:
        """
        Get real-time quotes for given symbol
        Args:
            symbol: Trading symbol
            exchange: Exchange (e.g., NSE, BSE)
        Returns:
            dict: Quote data with required fields
        """
        try:
            # Exchange segment mapping
            exchange_segment_map = {
                "NSE": 1,
                "NFO": 2,
                "CDS": 3,
                "BSE": 11,
                "BFO": 12,
                "MCX": 51
            }
            
            # Convert symbol to broker format
            br_symbol = get_br_symbol(symbol, exchange)
            
            #brexchange = get_brexchange(symbol, exchange)
            #logger.info(f"Fetching quotes for {brexchange}, {br_symbol}")
            
            brexchange = exchange_segment_map.get(exchange)
            if brexchange is None:
                raise Exception(f"Unknown exchange segment: {brexchange}")
            # Get exchange_token from database
            with db_session() as session:
                symbol_info = session.query(SymToken).filter(
                    SymToken.exchange == exchange,
                    SymToken.brsymbol == br_symbol
                ).first()
                
                if not symbol_info:
                    raise Exception(f"Could not find exchange token for {exchange}:{br_symbol}")
                
                # Get the token for quotes
                token = {
                "exchangeSegment": brexchange,  
                "exchangeInstrumentID": symbol_info.token  # token = instrument ID
            }
            
            # Prepare payload for CompositEdge quotes API
            payload = {
                "instruments": [token],
                "xtsMessageCode": 1502,  # Market data request code for CompositEdge
                "publishFormat": "JSON"
            }
            
            response = get_api_response("/apimarketdata/instruments/quotes",self.auth_token, method="POST", payload=payload, feed_token=self.feed_token)
            
            if not response or response.get('type') != 'success':
                raise Exception(f"Error from CompositEdge API: {response.get('description', 'Unknown error')}")
            
            # Parse stringified JSON quote
            raw_quote_str = response.get('result', {}).get('listQuotes', [None])[0]
            if not raw_quote_str:
                raise Exception("No quote data found in listQuotes")
            
            # Get quote data from response
            quote = json.loads(raw_quote_str)
            #print(f"Quote: {quote}")
            touchline = quote.get('Touchline', {})
            #print(f"Touchline: {touchline}")
            return {
                'ask': touchline.get('AskInfo', {}).get('Price', 0),
                'bid': touchline.get('BidInfo', {}).get('Price', 0),
                'high': touchline.get('High', 0),
                'low': touchline.get('Low', 0),
                'ltp': touchline.get('LastTradedPrice', 0),
            'open': touchline.get('Open', 0),
            'prev_close': touchline.get('Close', 0),
            'volume': touchline.get('TotalTradedQuantity', 0)
        }
            
        except Exception as e:
            logger.error(f"Error fetching quotes: {str(e)}")
            raise Exception(f"Error fetching quotes: {str(e)}")

    def get_history(self, symbol, exchange, timeframe, from_date, to_date):
        """Get historical data for a symbol"""
        try:
            # Map timeframe to compression value
            compression_map = {
                "1m": "60", "2m": "120", "3m": "180", "5m": "300",
                "10m": "600", "15m": "900", "30m": "1800", "60m": "3600",
                "D": "D"
            }
            compression_value = compression_map.get(timeframe)
            if not compression_value:
                raise Exception(f"Unsupported timeframe: {timeframe}")

            # Convert symbol to broker format and get token
            br_symbol = get_br_symbol(symbol, exchange)
            #token = get_token(symbol, exchange)
            #if not token:
             #   raise Exception(f"Could not find instrument token for {exchange}:{symbol}")

            # Map exchange segment
            segment_map = {
                "NSE": "NSECM",
                "BSE": "BSECM",
                "NFO": "NSEFO",
                "BFO": "BSEFO",
                "CDS": "NSECD"
            }
            exchange_segment = segment_map.get(exchange)
            if not exchange_segment:
                raise Exception(f"Unsupported exchange: {exchange}")
             # Get exchange_token from database
            with db_session() as session:
                symbol_info = session.query(SymToken).filter(
                    SymToken.exchange == exchange,
                    SymToken.brsymbol == br_symbol
                ).first()
                
                if not symbol_info:
                    raise Exception(f"Could not find exchange token for {exchange}:{br_symbol}")
                
                # Get the token for quotes
                token = symbol_info.token  # token = instrument ID

            # Convert from/to dates
            start_date = pd.to_datetime(from_date)
            end_date = pd.to_datetime(to_date)

            dfs = []
            current_start = start_date

            while current_start <= end_date:
                current_end = min(current_start + timedelta(days=6), end_date)

                # CompositEdge expects MMM DD YYYY HHMMSS
                from_str = current_start.strftime('%b %d %Y 090000')
                to_str = current_end.strftime('%b %d %Y 153000')

                logger.info(f"Fetching {timeframe} data for {exchange}:{symbol} from {from_str} to {to_str}")

                params = {
                    "exchangeSegment": exchange_segment,
                    "exchangeInstrumentID": token,
                    "startTime": from_str,
                    "endTime": to_str,
                    "compressionValue": compression_value
                }

                response = get_api_response("/apibinarymarketdata/instruments/ohlc", self.auth_token, method="GET", feed_token=self.feed_token, params=params)

                if not response or response.get('type') != 'success':
                    logger.error(f"API Response: {response}")
                    raise Exception(f"Error from CompositEdge API: {response.get('description', 'Unknown error')}")

                # Parse dataResponse (pipe-delimited string)
                raw_data = response.get('result', {}).get('dataReponse', '')
                if not raw_data:
                    logger.warning(f"No data returned for period {from_str} to {to_str}")
                    current_start = current_end + timedelta(days=1)
                    continue

                rows = raw_data.strip().split(',')
                data = []
                for row in rows:
                    fields = row.split('|')
                    if len(fields) < 6:
                        continue
                    try:
                        data.append({
                            "timestamp": int(fields[0]),
                            "open": float(fields[1]),
                            "high": float(fields[2]),
                            "low": float(fields[3]),
                            "close": float(fields[4]),
                            "volume": int(fields[5])
                        })
                    except (ValueError, IndexError) as e:
                        logger.warning(f"Error parsing row {row}: {e}")
                        continue

                if data:
                    df = pd.DataFrame(data)
                    dfs.append(df)

                current_start = current_end + timedelta(days=1)
            
            if not dfs:
                return pd.DataFrame(columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])

            final_df = pd.concat(dfs, ignore_index=True)
            final_df = final_df.sort_values('timestamp').drop_duplicates('timestamp').reset_index(drop=True)

            return final_df

        except Exception as e:
            logger.error(f"Error fetching historical data: {str(e)}")
            raise Exception(f"Error fetching historical data: {str(e)}")

    def get_market_depth(self, exchange, symbol):
        """
        Get market depth for given symbol once and cleanup the connection
        
        Args:
            exchange (str): Exchange name (e.g. NSE, BSE)
            symbol (str): Trading symbol (e.g. RELIANCE, YESBANK)
            
        Returns:
            dict: Market depth data containing bid/ask quotes
        """
        logger.info(f"Fetching market depth for {symbol}:{exchange}")
        ws = None
        try:
            # Exchange segment mapping
            exchange_segment_map = {
                "NSE": 1,
                "NFO": 2,
                "CDS": 3,
                "BSE": 11,
                "BFO": 12,
                "MCX": 51
            }
            
            # Convert symbol to broker format
            br_symbol = get_br_symbol(symbol, exchange)
            
            brexchange = exchange_segment_map.get(exchange)
            if brexchange is None:
                raise Exception(f"Unknown exchange segment: {exchange}")
            
            # Get the exchange segment and instrument ID from the database
            with db_session() as session:
                symbol_info = session.query(SymToken).filter(
                    SymToken.exchange == exchange,
                    SymToken.brsymbol == br_symbol
                ).first()
                
                if not symbol_info:
                    raise Exception(f"Could not find exchange token for {exchange}:{br_symbol}")
                
                instrument_id = symbol_info.token

            # Create new websocket instance for this request
            ws = CompositEdgeWebSocket()
            depth_data = {}
            depth_received = threading.Event()
            
            def on_connect():
                logger.info("WebSocket connected, subscribing to market depth")
                ws.subscribe_market_depth(brexchange, instrument_id)
            
            def on_market_depth(data):
                nonlocal depth_data
                if isinstance(data, str):
                    data = json.loads(data)
                depth_data = data
                depth_received.set()
                
            def on_error(error):
                logger.error(f"WebSocket error: {error}")
                depth_received.set()
                
            # Set callbacks
            ws.on('connect', on_connect)
            ws.on('marketDepthEvent', on_market_depth)
            ws.on('error', on_error)
            
            # Connect and wait for data
            ws.connect(
                auth_token=self.auth_token,
                feed_token=self.feed_token,
                user_id=None
            )
                
            # Wait for depth data with timeout
            if depth_received.wait(timeout=5.0):
                if not depth_data:
                    raise Exception("No market depth data received")
                    
                # Format the response
                formatted_data = self._format_market_depth(depth_data)
                return formatted_data
            else:
                raise Exception("Timeout waiting for market depth data")

        except Exception as e:
            logger.error(f"Error fetching market depth: {str(e)}")
            raise Exception(f"Error fetching market depth: {str(e)}")
            
        finally:
            # Always cleanup the websocket
            if ws:
                try:
                    ws.cleanup()
                except Exception as e:
                    logger.error(f"Error during websocket cleanup: {str(e)}")

    def _format_market_depth(self, depth_data):
        """Format the raw market depth data into standard structure"""
        try:
            asks = []
            bids = []
            
            # Process sell orders (asks)
            sell_orders = depth_data.get('Asks', [])
            for i in range(5):
                if i < len(sell_orders):
                    asks.append({
                        'price': float(sell_orders[i].get('Price', 0)),
                        'quantity': int(sell_orders[i].get('Quantity', 0))
                    })
                else:
                    asks.append({'price': 0, 'quantity': 0})
                    
            # Process buy orders (bids)
            buy_orders = depth_data.get('Bids', [])
            for i in range(5):
                if i < len(buy_orders):
                    bids.append({
                        'price': float(buy_orders[i].get('Price', 0)),
                        'quantity': int(buy_orders[i].get('Quantity', 0))
                    })
                else:
                    bids.append({'price': 0, 'quantity': 0})
            
            return {
                'asks': asks,
                'bids': bids,
                'high': float(depth_data.get('High', 0)),
                'low': float(depth_data.get('Low', 0)),
                'ltp': float(depth_data.get('LastTradedPrice', 0)),
                'ltq': int(depth_data.get('LastTradedQuantity', 0)),
                'oi': int(depth_data.get('OpenInterest', 0)),
                'open': float(depth_data.get('Open', 0)),
                'prev_close': float(depth_data.get('PreviousClose', 0)),
                'totalbuyqty': sum(int(order.get('Quantity', 0)) for order in buy_orders),
                'totalsellqty': sum(int(order.get('Quantity', 0)) for order in sell_orders),
                'volume': int(depth_data.get('TotalTradedQuantity', 0))
            }
        except Exception as e:
            logger.error(f"Error formatting market depth data: {str(e)}")
            return depth_data  # Return raw data if formatting fails

    def get_depth(self, symbol: str, exchange: str) -> dict:
        """Alias for get_market_depth to maintain compatibility with common API"""
        return self.get_market_depth(exchange, symbol)

    def __del__(self):
        """Cleanup websocket connection when object is destroyed"""
        if self.ws:
            self.ws.close()
