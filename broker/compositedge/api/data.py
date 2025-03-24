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

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def get_api_response(endpoint, auth, method="GET", payload='',feed_token=None):
    
    AUTH_TOKEN = auth
    if feed_token:
        FEED_TOKEN = feed_token
    #print(f"Auth Token: {AUTH_TOKEN}")
    #print(f"Feed Token: {FEED_TOKEN}")
    
    # Get the shared httpx client with connection pooling
    client = get_httpx_client()
    
    headers = {
        'authorization': FEED_TOKEN,
        'Content-Type': 'application/json'
    }
    
    # Add feed token to payload for market data requests
     # If payload is a string, try to parse it into dict
    if isinstance(payload, str):
        try:
            payload = json.loads(payload)
        except json.JSONDecodeError:
            logger.error("Failed to parse payload as JSON")
            raise Exception("Invalid payload format")

    url = f"https://xts.compositedge.com{endpoint}"

    try:
        # Log request details
        logger.info("=== API Request Details ===")
        logger.info(f"URL: {url}")
        logger.info(f"Method: {method}")
        logger.info(f"Headers: {json.dumps(headers, indent=2)}")
        if payload:
            logger.info(f"Payload: {json.dumps(payload, indent=2)}")

        # Perform the request
        if method.upper() == "GET":
            response = client.get(url, headers=headers)
        elif method.upper() == "POST":
            response = client.post(url, headers=headers, json=payload)
        else:
            response = client.request(method, url, headers=headers, json=payload)

        #print(f"Response: {response}")

        # Log response details
        logger.info("=== API Response Details ===")
        logger.info(f"Status Code: {response.status_code}")
        logger.info(f"Response Headers: {dict(response.headers)}")
        logger.info(f"Response Body: {response.text}")

        return response.json()

    except Exception as e:
        logger.error(f"API request failed: {str(e)}")
        raise

class BrokerData:
    def __init__(self, auth_token, feed_token=None):
        """Initialize CompositEdge data handler with authentication token"""
        self.auth_token = auth_token
        self.feed_token = feed_token
        
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
            
            response = get_api_response("/apimarketdata/instruments/quotes",self.auth_token, method="POST", payload=payload,feed_token=self.feed_token)
            
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

    def get_history(self, symbol: str, exchange: str, timeframe: str, from_date: str, to_date: str) -> pd.DataFrame:
        """
        Get historical data for given symbol and timeframe
        Args:
            symbol: Trading symbol
            exchange: Exchange (e.g., NSE, BSE)
            timeframe: Timeframe (e.g., 1m, 5m, 15m, 60m, D)
            from_date: Start date in format YYYY-MM-DD
            to_date: End date in format YYYY-MM-DD
        Returns:
            pd.DataFrame: Historical data with OHLCV
        """
        try:
            # Convert timeframe to CompositEdge format
            resolution = self.timeframe_map.get(timeframe)
            if not resolution:
                raise Exception(f"Unsupported timeframe: {timeframe}")
            

            # Convert symbol to broker format
            br_symbol = get_br_symbol(symbol, exchange)

            # Get the token from database
            with db_session() as session:
                symbol_info = session.query(SymToken).filter(
                    SymToken.exchange == exchange,
                    SymToken.brsymbol == br_symbol
                ).first()
                
                if not symbol_info:
                    all_symbols = session.query(SymToken).filter(
                        SymToken.exchange == exchange
                    ).all()
                    logger.info(f"All matching symbols in DB: {[(s.symbol, s.brsymbol, s.exchange, s.brexchange, s.token) for s in all_symbols]}")
                    raise Exception(f"Could not find instrument token for {exchange}:{symbol}")
                
                # Get the token for historical data
                token = symbol_info.token

            # Convert dates to datetime objects
            start_date = pd.to_datetime(from_date)
            end_date = pd.to_datetime(to_date)
            
            # Initialize empty list to store DataFrames
            dfs = []
            
            # Process data in 60-day chunks
            current_start = start_date
            while current_start <= end_date:
                # Calculate chunk end date (60 days or remaining period)
                current_end = min(current_start + timedelta(days=59), end_date)
                
                # Format dates for API call
                from_str = current_start.strftime('%Y-%m-%d')
                to_str = current_end.strftime('%Y-%m-%d')
                
                # Log the request details
                logger.info(f"Fetching {resolution} data for {exchange}:{symbol} from {from_str} to {to_str}")
                
                # Prepare payload for CompositEdge historical data API
                payload = {
                    "instruments": [token],
                    "xtsMessageCode": 1101,  # Historical data request code for CompositEdge
                    "resolution": resolution,
                    "from": from_str,
                    "to": to_str,
                    "publishFormat": "JSON"
                }
                
                # Use get_api_response
                response = get_api_response("/apimarketdata/historical", self.auth_token, method="POST", payload=payload)
                
                if not response or response.get('type') != 'success':
                    logger.error(f"API Response: {response}")
                    raise Exception(f"Error from CompositEdge API: {response.get('description', 'Unknown error')}")
                
                # Convert to DataFrame
                candles = response.get('result', {}).get('listCandles', [])
                if candles:
                    df = pd.DataFrame(candles, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
                    dfs.append(df)
                
                # Move to next chunk
                current_start = current_end + timedelta(days=1)
                
            # If no data was found, return empty DataFrame
            if not dfs:
                return pd.DataFrame(columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
            
            # Combine all chunks
            final_df = pd.concat(dfs, ignore_index=True)
            
            # Convert timestamp to epoch properly using ISO format
            final_df['timestamp'] = pd.to_datetime(final_df['timestamp'], format='ISO8601')
            final_df['timestamp'] = final_df['timestamp'].astype('int64') // 10**9  # Convert nanoseconds to seconds
            
            # Sort by timestamp and remove duplicates
            final_df = final_df.sort_values('timestamp').drop_duplicates(subset=['timestamp']).reset_index(drop=True)
            
            # Ensure volume is integer
            final_df['volume'] = final_df['volume'].astype(int)
            
            return final_df
                
        except Exception as e:
            logger.error(f"Error fetching historical data: {str(e)}")
            raise Exception(f"Error fetching historical data: {str(e)}")

    def get_market_depth(self, symbol: str, exchange: str) -> dict:
        """
        Get market depth for given symbol
        Args:
            symbol: Trading symbol
            exchange: Exchange (e.g., NSE, BSE)
        Returns:
            dict: Market depth data
        """
        try:
            # Convert symbol to broker format
            br_symbol = get_br_symbol(symbol, exchange)
            logger.info(f"Fetching market depth for {exchange}:{br_symbol}")
            
            # Get exchange_token from database
            with db_session() as session:
                symbol_info = session.query(SymToken).filter(
                    SymToken.exchange == exchange,
                    SymToken.brsymbol == br_symbol
                ).first()
                
                if not symbol_info:
                    raise Exception(f"Could not find exchange token for {exchange}:{br_symbol}")
                
                # Get the token for quotes
                token = symbol_info.token
            
            # Prepare payload for CompositEdge market depth API
            payload = {
                "instruments": [token],
                "xtsMessageCode": 1503,  # Market depth request code for CompositEdge
                "publishFormat": "JSON"
            }
            
            response = get_api_response("/apimarketdata/instruments/depth", self.feed_token, method="POST", payload=payload)
            
            if not response or response.get('type') != 'success':
                raise Exception(f"Error from CompositEdge API: {response.get('description', 'Unknown error')}")
            
            # Get market depth data from response
            depth = response.get('result', {}).get('listDepth', [{}])[0]
            if not depth:
                raise Exception("No market depth data found")
            
            # Format asks and bids data
            asks = []
            bids = []
            
            # Process sell orders (asks)
            sell_orders = depth.get('sell', [])
            for i in range(5):
                if i < len(sell_orders):
                    asks.append({
                        'price': sell_orders[i].get('price', 0),
                        'quantity': sell_orders[i].get('quantity', 0)
                    })
                else:
                    asks.append({'price': 0, 'quantity': 0})
                    
            # Process buy orders (bids)
            buy_orders = depth.get('buy', [])
            for i in range(5):
                if i < len(buy_orders):
                    bids.append({
                        'price': buy_orders[i].get('price', 0),
                        'quantity': buy_orders[i].get('quantity', 0)
                    })
                else:
                    bids.append({'price': 0, 'quantity': 0})
            
            # Return market depth data
            return {
                'asks': asks,
                'bids': bids,
                'high': depth.get('high', 0),
                'low': depth.get('low', 0),
                'ltp': depth.get('last_traded_price', 0),
                'ltq': depth.get('last_traded_quantity', 0),
                'oi': depth.get('open_interest', 0),
                'open': depth.get('open', 0),
                'prev_close': depth.get('previous_close', 0),
                'totalbuyqty': sum(order.get('quantity', 0) for order in buy_orders),
                'totalsellqty': sum(order.get('quantity', 0) for order in sell_orders),
                'volume': depth.get('volume', 0)
            }
            
        except Exception as e:
            logger.error(f"Error fetching market depth: {str(e)}")
            raise Exception(f"Error fetching market depth: {str(e)}")

    def get_depth(self, symbol: str, exchange: str) -> dict:
        """Alias for get_market_depth to maintain compatibility with common API"""
        return self.get_market_depth(symbol, exchange)
