import json
import os
import time
import urllib.parse
import httpx
from database.token_db import get_br_symbol, get_token
from broker.paytm.database.master_contract_db import SymToken, db_session
import pandas as pd
from datetime import datetime, timedelta
from utils.httpx_client import get_httpx_client
from utils.logging import get_logger

logger = get_logger(__name__)

def get_api_response(endpoint, auth, method="GET", payload=''):
    AUTH_TOKEN = auth
    base_url = "https://developer.paytmmoney.com"
    headers = {
        'x-jwt-token': AUTH_TOKEN,
        'Content-Type': 'application/json',
        'Accept': 'application/json',
    }

    try:
        # Log the complete request details for Postman
        logger.debug("=== API Request Details ===")
        logger.debug(f"URL: {base_url}{endpoint}")
        logger.debug(f"Method: {method}")
        logger.debug(f"Headers: {json.dumps(headers, indent=2)}")
        if payload:
            logger.debug(f"Payload: {payload}")

        client = get_httpx_client()
        # Use a longer timeout for Paytm API requests
        timeout = httpx.Timeout(60.0, connect=30.0)
        if method == "GET":
            response = client.get(f"{base_url}{endpoint}", headers=headers, timeout=timeout)
        else:
            response = client.post(f"{base_url}{endpoint}", headers=headers, content=payload, timeout=timeout)

        # Log the complete response
        logger.debug("=== API Response Details ===")
        logger.debug(f"Status Code: {response.status_code}")
        logger.debug(f"Response Headers: {dict(response.headers)}")
        response_data = response.json()
        logger.debug(f"Response Body: {json.dumps(response_data, indent=2)}")

        return response_data
    except Exception as e:
        logger.exception(f"API request failed for endpoint {endpoint}: {e}")
        raise

class BrokerData:
    def __init__(self, auth_token):
        """Initialize Paytm data handler with authentication token"""
        self.auth_token = auth_token
        
        # PAYTM does not support historical data API
        # Empty timeframe map since historical data is not supported
        self.timeframe_map = {}
        
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
            }
        }
        
        # Default market timings if exchange not found
        self.default_market_timings = {
            'start': '09:15:00',
            'end': '15:29:59'
        }

    def get_market_timings(self, exchange: str) -> dict:
        """Get market start and end times for given exchange"""
        return self.market_timings.get(exchange, self.default_market_timings)

    def _prepare_symbol_for_api(self, symbol: str, exchange: str) -> dict:
        """
        Prepare symbol data for Paytm API calls.

        Args:
            symbol: Trading symbol
            exchange: Exchange (e.g., NSE, BSE, NFO)

        Returns:
            dict: Contains token, br_symbol, opt_type, request_exchange
        """
        token = get_token(symbol, exchange)
        br_symbol = get_br_symbol(symbol, exchange)

        # Determine opt_type based on exchange and symbol format
        if exchange in ['NSE_INDEX', 'BSE_INDEX']:
            opt_type = 'INDEX'
        else:
            parts = br_symbol.split('-') if br_symbol else []
            if len(parts) > 2:
                if parts[-1] in ['CE', 'PE']:
                    opt_type = 'OPTION'
                elif 'FUT' in parts[-1]:
                    opt_type = 'FUTURE'
                else:
                    opt_type = 'EQUITY'
            else:
                opt_type = 'EQUITY'

        # Map exchange for API
        if exchange in ['NFO', 'NSE_INDEX']:
            request_exchange = 'NSE'
        elif exchange in ['BFO', 'BSE_INDEX']:
            request_exchange = 'BSE'
        else:
            request_exchange = exchange

        return {
            'token': token,
            'br_symbol': br_symbol,
            'opt_type': opt_type,
            'request_exchange': request_exchange
        }

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
            # Prepare symbol for API
            sym_data = self._prepare_symbol_for_api(symbol, exchange)
            token = sym_data['token']
            request_exchange = sym_data['request_exchange']
            opt_type = sym_data['opt_type']

            logger.debug(f"Fetching quotes for {exchange}:{token}")

            # URL encode the symbol to handle special characters
            # Paytm expects the symbol to be in the format "exchange:token:opt_type" E.g: NSE:335:EQUITY
            encoded_symbol = urllib.parse.quote(f"{request_exchange}:{token}:{opt_type}")
            
            response = get_api_response(f"/data/v1/price/live?mode=QUOTE&pref={encoded_symbol}", self.auth_token)
            
            if not response or not response.get('data', []):
                error_msg = f"Error from Paytm API: {response.get('message', 'Unknown error')}"
                logger.error(error_msg)
                raise Exception(error_msg)
            
            
            # Return quote data
            quote = response.get('data', [])[0] if response.get('data') else {}
            if not quote:
                error_msg = f"No quote data found for {symbol}"
                logger.error(error_msg)
                raise Exception(error_msg)

            return {
                'ask': 0,  # Not available in new format
                'bid': 0,  # Not available in new format
                'high': quote.get('ohlc', {}).get('high', 0),
                'low': quote.get('ohlc', {}).get('low', 0),
                'ltp': quote.get('last_price', 0),
                'open': quote.get('ohlc', {}).get('open', 0),
                'prev_close': quote.get('ohlc', {}).get('close', 0),
                'volume': quote.get('volume_traded', 0)
            }
            
        except Exception as e:
            logger.exception(f"Error fetching quotes for {symbol}: {e}")
            raise

    def get_multiquotes(self, symbols: list) -> list:
        """
        Get real-time quotes for multiple symbols using REST API
        Paytm API supports multiple symbols in one request

        Args:
            symbols: List of dicts with 'symbol' and 'exchange' keys
                     Example: [{'symbol': 'SBIN', 'exchange': 'NSE'}, ...]
        Returns:
            list: List of quote data for each symbol with format:
                  [{'symbol': 'SBIN', 'exchange': 'NSE', 'data': {...}}, ...]
        """
        try:
            # Paytm API batch size - adjust based on API limits
            BATCH_SIZE = 100
            RATE_LIMIT_DELAY = 0.1  # Delay between batches in seconds

            if len(symbols) > BATCH_SIZE:
                logger.info(f"Processing {len(symbols)} symbols in batches of {BATCH_SIZE}")
                all_results = []

                for i in range(0, len(symbols), BATCH_SIZE):
                    batch = symbols[i:i + BATCH_SIZE]
                    logger.debug(f"Processing batch {i//BATCH_SIZE + 1}: symbols {i+1} to {min(i+BATCH_SIZE, len(symbols))}")

                    batch_results = self._process_multiquotes_batch(batch)
                    all_results.extend(batch_results)

                    # Rate limit delay between batches
                    if i + BATCH_SIZE < len(symbols):
                        time.sleep(RATE_LIMIT_DELAY)

                logger.info(f"Successfully processed {len(all_results)} quotes")
                return all_results
            else:
                return self._process_multiquotes_batch(symbols)

        except Exception as e:
            logger.exception(f"Error fetching multiquotes")
            raise Exception(f"Error fetching multiquotes: {e}")

    def _process_multiquotes_batch(self, symbols: list) -> list:
        """
        Process a batch of symbols using REST API
        Args:
            symbols: List of dicts with 'symbol' and 'exchange' keys
        Returns:
            list: List of quote data for the batch
        """
        results = []
        skipped_symbols = []
        pref_list = []
        symbol_list = []  # Keep ordered list of symbol info

        for item in symbols:
            symbol = item.get('symbol')
            exchange = item.get('exchange')

            if not symbol or not exchange:
                logger.warning(f"Skipping entry due to missing symbol/exchange: {item}")
                skipped_symbols.append({
                    'symbol': symbol,
                    'exchange': exchange,
                    'data': None,
                    'error': 'Missing required symbol or exchange'
                })
                continue

            try:
                # Use common helper for symbol preparation
                sym_data = self._prepare_symbol_for_api(symbol, exchange)
                token = sym_data['token']
                request_exchange = sym_data['request_exchange']
                opt_type = sym_data['opt_type']

                if not token:
                    logger.warning(f"Skipping symbol {symbol} on {exchange}: could not resolve token")
                    skipped_symbols.append({
                        'symbol': symbol,
                        'exchange': exchange,
                        'data': None,
                        'error': 'Could not resolve token'
                    })
                    continue

                pref_str = f"{request_exchange}:{token}:{opt_type}"
                pref_list.append(pref_str)

                # Store symbol info in ordered list
                symbol_list.append({
                    'symbol': symbol,
                    'exchange': exchange,
                    'token': str(token),
                    'request_exchange': request_exchange
                })

            except Exception as e:
                logger.warning(f"Error preparing {symbol} on {exchange}: {str(e)}")
                skipped_symbols.append({
                    'symbol': symbol,
                    'exchange': exchange,
                    'data': None,
                    'error': str(e)
                })

        if not pref_list:
            logger.warning("No valid symbols to fetch quotes for")
            return skipped_symbols

        # Call REST API with all symbols
        try:
            encoded_pref = urllib.parse.quote(','.join(pref_list))
            logger.info(f"Fetching {len(pref_list)} quotes via REST API")

            response = get_api_response(f"/data/v1/price/live?mode=QUOTE&pref={encoded_pref}", self.auth_token)

            if not response or not response.get('data', []):
                raise Exception(f"API error: {response.get('message', 'No data received')}")

            # Process response - build lookup by token
            quotes_data = response.get('data', [])
            logger.debug(f"API returned {len(quotes_data)} quotes")

            quotes_by_token = {}
            for quote in quotes_data:
                quote_token = str(quote.get('security_id', ''))
                if quote_token:
                    quotes_by_token[quote_token] = quote

            # Match quotes to symbols using ordered list
            for sym_info in symbol_list:
                token = sym_info['token']
                quote = quotes_by_token.get(token)

                if quote:
                    results.append({
                        'symbol': sym_info['symbol'],
                        'exchange': sym_info['exchange'],
                        'data': {
                            'bid': 0,
                            'ask': 0,
                            'open': quote.get('ohlc', {}).get('open', 0),
                            'high': quote.get('ohlc', {}).get('high', 0),
                            'low': quote.get('ohlc', {}).get('low', 0),
                            'ltp': quote.get('last_price', 0),
                            'prev_close': quote.get('ohlc', {}).get('close', 0),
                            'volume': quote.get('volume_traded', 0),
                            'oi': 0
                        }
                    })
                else:
                    results.append({
                        'symbol': sym_info['symbol'],
                        'exchange': sym_info['exchange'],
                        'error': 'No data received'
                    })

        except Exception as e:
            logger.error(f"Error calling quote API: {str(e)}")
            for sym_info in symbol_list:
                results.append({
                    'symbol': sym_info['symbol'],
                    'exchange': sym_info['exchange'],
                    'error': str(e)
                })

        logger.info(f"Retrieved quotes for {len([r for r in results if 'data' in r])}/{len(symbols)} symbols")
        return skipped_symbols + results

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
            # Prepare symbol for API
            sym_data = self._prepare_symbol_for_api(symbol, exchange)
            token = sym_data['token']
            request_exchange = sym_data['request_exchange']
            opt_type = sym_data['opt_type']

            logger.debug(f"Fetching market depth for {exchange}:{token}")

            # URL encode the symbol to handle special characters
            # Paytm expects the symbol to be in the format "exchange:token:opt_type" E.g: NSE:335:EQUITY
            encoded_symbol = urllib.parse.quote(f"{request_exchange}:{token}:{opt_type}")
            
            response = get_api_response(f"/data/v1/price/live?mode=FULL&pref={encoded_symbol}", self.auth_token)
            
            if not response or not response.get('data', []):
                error_msg = f"Error from Paytm API: {response.get('message', 'Unknown error')}"
                logger.error(error_msg)
                raise Exception(error_msg)
            
            
            # Return quote data
            quote = response.get('data', [])[0] if response.get('data') else {}
            if not quote:
                error_msg = f"No market depth data found for {symbol}"
                logger.error(error_msg)
                raise Exception(error_msg)
            
            depth = quote.get('depth', {})
            
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
                'high': quote.get('ohlc', {}).get('high', 0),
                'low': quote.get('ohlc', {}).get('low', 0),
                'ltp': quote.get('last_price', 0),
                'ltq': quote.get('last_quantity', 0),
                'oi': quote.get('oi', 0),
                'open': quote.get('ohlc', {}).get('open', 0),
                'prev_close': quote.get('ohlc', {}).get('close', 0),
                'totalbuyqty': sum(order.get('quantity', 0) for order in buy_orders),
                'totalsellqty': sum(order.get('quantity', 0) for order in sell_orders),
                'volume': quote.get('volume', 0)
            }
            
        except Exception as e:
            logger.exception(f"Error fetching market depth for {symbol}: {e}")
            raise

    def get_depth(self, symbol: str, exchange: str) -> dict:
        """Alias for get_market_depth to maintain compatibility with common API"""
        return self.get_market_depth(symbol, exchange)

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
        raise NotImplementedError("Paytm does not support historical data API")

    def get_intervals(self) -> list:
        """Get available intervals/timeframes for historical data
        
        Returns:
            list: List of available intervals
        """
        raise NotImplementedError("Paytm does not support historical data API")
