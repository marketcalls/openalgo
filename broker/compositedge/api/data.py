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
    def __init__(self, auth_token, feed_token=None, user_id=None):
        """Initialize CompositEdge data handler with authentication token"""
        self.auth_token = auth_token
        self.feed_token = feed_token
        self.user_id = user_id
        
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
            touchline = quote.get('Touchline', {})
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
                "1s": "1", "1m": "60", "2m": "120", "3m": "180", "5m": "300",
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
                "CDS": "NSECD",
                "MCX": "MCXFO",
                "NSE_INDEX": "NSECM",
                "BSE_INDEX": "BSECM"
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

    def get_intervals(self) -> list:
        """Get available intervals/timeframes for historical data
        
        Returns:
            list: List of available intervals
        """
        return ["1s", "1m", "2m", "3m", "5m", "10m", "15m", "30m", "60m", "D"]

    def get_market_depth(self, symbol: str, exchange: str) -> dict:
        """
        Get market depth for given symbol via REST API
        Args:
            symbol: Trading symbol
            exchange: Exchange (e.g., NSE, BSE)
        Returns:
            dict: Market depth data
        """
        try:
            logger.info(f"=== Starting Market Depth Request ===")
            logger.info(f"Symbol: {symbol}, Exchange: {exchange}")
            
            # Get feed token and user ID for request
            user_id = None
            feed_token = None
            
            # First check if we have user ID in the instance
            if hasattr(self, 'user_id') and self.user_id:
                user_id = self.user_id
                logger.debug(f"Using instance user_id: {user_id}")
            
            # Try to get from session if not found in instance
            if not user_id and hasattr(session, 'marketdata_userid') and session.get('marketdata_userid'):
                user_id = session.get('marketdata_userid')
                logger.debug(f"Using session user_id: {user_id}")
            
            # If no user ID is available, use the one from feed token authentication
            if not user_id and self.user_id:
                user_id = self.user_id
                logger.debug(f"Using feed token auth user_id: {user_id}")
            
            if not user_id:
                logger.error("No user ID available for market depth request")
                return None
            
            # Get feed token from instance
            if hasattr(self, 'feed_token') and self.feed_token:
                feed_token = self.feed_token
                logger.debug("Using instance feed_token")
            
            # Try to get from session if not found in instance
            if not feed_token and hasattr(session, 'marketdata_token') and session.get('marketdata_token'):
                feed_token = session.get('marketdata_token')
                logger.debug("Using session feed_token")
            
            # If still no feed token, try to get a new one
            if not feed_token:
                logger.info("No feed token available, attempting to get one")
                from database.auth_db import get_feed_token
                feed_token, new_user_id, error = get_feed_token()
                if error:
                    logger.error(f"Failed to get feed token: {error}")
                    raise Exception(f"Failed to get feed token: {error}")
                if not user_id and new_user_id:
                    user_id = new_user_id
                    logger.info(f"Got new user_id from feed token: {user_id}")
            
            # Log the user ID and feed token we're using
            logger.info(f"Using user ID: {user_id}")
            logger.info(f"Using feed token: {feed_token[:20]}..." if feed_token else "No feed token available")
            
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
            logger.info(f"Converted symbol {symbol} to broker format: {br_symbol}")
            
            brexchange = exchange_segment_map.get(exchange)
            logger.info(f"Mapped exchange {exchange} to segment: {brexchange}")
            
            if brexchange is None:
                logger.error(f"Unknown exchange segment: {exchange}")
                raise Exception(f"Unknown exchange segment: {exchange}")
                
            # Get exchange_token from database
            logger.info("Querying database for symbol token...")
            with db_session() as session:
                symbol_info = session.query(SymToken).filter(
                    SymToken.exchange == exchange,
                    SymToken.brsymbol == br_symbol
                ).first()
                
                if not symbol_info:
                    logger.error(f"Could not find exchange token for {exchange}:{br_symbol}")
                    raise Exception(f"Could not find exchange token for {exchange}:{br_symbol}")
                logger.info(f"Found token {symbol_info.token} for {exchange}:{br_symbol}")

            # Get market depth via REST API
            logger.info("Getting market depth via REST API...")
            payload = {
                'instruments': [{
                    'exchangeSegment': brexchange,  
                    'exchangeInstrumentID': symbol_info.token
                }],
                'xtsMessageCode': 1502,
                'publishFormat': 'JSON'
            }
            logger.info(f"REST API payload: {json.dumps(payload, indent=2)}")
            
            response = get_api_response("/apimarketdata/instruments/quotes",
                                     self.auth_token, 
                                     method="POST", 
                                     payload=payload, 
                                     feed_token=feed_token)
            
            if response and response.get('type') == 'success':
                raw_quote = response.get('result', {}).get('listQuotes', [None])[0]
                if raw_quote:
                    quote = json.loads(raw_quote) if isinstance(raw_quote, str) else raw_quote
                    touchline = quote.get("Touchline", {})

                    # Extracting top 5 bids and asks
                    bids = [
                        {"price": b.get("Price", 0), "quantity": b.get("Size", 0)}
                        for b in quote.get("Bids", [])[:5]
                        ]
                    asks = [
                        {"price": a.get("Price", 0), "quantity": a.get("Size", 0)}
                        for a in quote.get("Asks", [])[:5]
                        ]

                    # Return structured response
                    return {
                        'bids': bids,
                        'asks': asks,
                        'high': touchline.get('High', 0),
                        'low': touchline.get('Low', 0),
                        'ltp': touchline.get('LastTradedPrice', 0),
                        'ltq': touchline.get('LastTradedQunatity', 0),
                        'open': touchline.get('Open', 0),
                        'prev_close': touchline.get('Close', 0),
                        'volume': touchline.get('TotalTradedQuantity', 0),
                        'oi': quote.get('OpenInterest', 0),  # optional: not always present
                        'totalbuyqty': touchline.get('TotalBuyQuantity', 0),
                        'totalsellqty': touchline.get('TotalSellQuantity', 0)
                    }
                else:
                    logger.warning("No quote data in response")
            else:
                logger.error(f"Error in API response: {response}")
                
            # Return empty structure if no data
            empty_depth = {
                'bids': [{'price': 0, 'quantity': 0} for _ in range(5)],
                'asks': [{'price': 0, 'quantity': 0} for _ in range(5)],
                'totalbuyqty': 0,
                'totalsellqty': 0,
                'ltp': 0,
                'ltq': 0,
                'volume': 0,
                'open': 0,
                'high': 0,
                'low': 0,
                'prev_close': 0,
                'oi': 0
            }
            logger.info("Returning empty market depth structure")
            return empty_depth
            
        except Exception as e:
            logger.error(f"Error in get_market_depth: {str(e)}", exc_info=True)
            # Return empty structure on error
            empty_depth = {
                'bids': [{'price': 0, 'quantity': 0} for _ in range(5)],
                'asks': [{'price': 0, 'quantity': 0} for _ in range(5)],
                'totalbuyqty': 0,
                'totalsellqty': 0,
                'ltp': 0,
                'ltq': 0,
                'volume': 0,
                'open': 0,
                'high': 0,
                'low': 0,
                'prev_close': 0,
                'oi': 0
            }
            logger.info("Returning empty market depth structure due to error")
            return empty_depth

    def get_depth(self, symbol: str, exchange: str) -> dict:
        """Alias for get_market_depth to maintain compatibility with common API"""
        return self.get_market_depth(symbol, exchange)
