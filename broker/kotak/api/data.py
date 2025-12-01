import httpx
import json
import time
import pandas as pd
import urllib.parse
from database.token_db import get_token, get_br_symbol, get_brexchange
from utils.logging import get_logger
from utils.httpx_client import get_httpx_client

logger = get_logger(__name__)

class BrokerData:
    def __init__(self, auth_token):
        # Updated for Neo API v2: session_token:::session_sid:::base_url:::access_token
        self.session_token, self.session_sid, self.base_url, self.access_token = auth_token.split(":::")
        
        # Override baseUrl with the working quotes server
        self.quotes_base_url = "https://cis.kotaksecurities.com"
        logger.info(f"Using quotes baseUrl: {self.quotes_base_url}")
        
        # Define empty timeframe map since Kotak Neo doesn't support historical data
        self.timeframe_map = {}
        logger.warning("Kotak Neo does not support historical data intervals")

    def _get_kotak_exchange(self, exchange):
        """Map OpenAlgo exchange to Kotak exchange segment"""
        exchange_map = {
            'NSE': 'nse_cm', 
            'BSE': 'bse_cm', 
            'NFO': 'nse_fo',
            'BFO': 'bse_fo', 
            'CDS': 'cde_fo', 
            'MCX': 'mcx_fo', 
            'NSE_INDEX': 'nse_cm', 
            'BSE_INDEX': 'bse_cm'
        }
        return exchange_map.get(exchange)

    def _get_index_symbol(self, symbol):
        """Map OpenAlgo index symbols to Kotak Neo API format"""
        index_map = {
            'NIFTY': 'Nifty 50',
            'NIFTY50': 'Nifty 50',
            'BANKNIFTY': 'Nifty Bank',
            'SENSEX': 'SENSEX',
            'BANKEX': 'BANKEX',
            'FINNIFTY': 'Nifty Fin Service',
            'MIDCPNIFTY': 'NIFTY MIDCAP 100'
        }
        # Return mapped symbol or original symbol if not found
        return index_map.get(symbol.upper(), symbol)

    def _make_quotes_request(self, query, filter_name="all"):
        """Make HTTP request to Neo API v2 quotes endpoint using httpx connection pooling"""
        try:
            # Get the shared httpx client with connection pooling
            client = get_httpx_client()

            # URL encode only spaces, keep pipe character (|) as is
            # The query format is: exchange_segment|symbol (e.g., nse_cm|INFY-EQ)
            encoded_query = urllib.parse.quote(query, safe='|')
            endpoint = f"/script-details/1.0/quotes/neosymbol/{encoded_query}/{filter_name}"

            # Neo API v2 quotes headers - only Authorization (access token), no Auth/Sid
            headers = {
                'Authorization': self.access_token,
                'Content-Type': 'application/json'
            }

            # Construct full URL
            url = f"{self.quotes_base_url}{endpoint}"

            logger.info(f"QUOTES API - Making request to: {url}")
            logger.debug(f"QUOTES API - Using access_token: {self.access_token[:10]}...")

            # Make request using httpx
            response = client.get(url, headers=headers)

            logger.info(f"QUOTES API - Response status: {response.status_code}")

            if response.status_code == 200:
                response_data = json.loads(response.text)
                logger.debug(f"QUOTES API - Raw response: {response.text[:200]}...")  # Log first 200 chars
                
                # Log the complete structure for debugging (only for depth requests)
                if "depth" in endpoint and response_data and isinstance(response_data, list) and len(response_data) > 0:
                    logger.debug(f"DEPTH API - Complete raw response structure: {json.dumps(response_data[0], indent=2)}")
                
                return response_data
            else:
                logger.warning(f"QUOTES API - HTTP {response.status_code}: {response.text}")
                return None

        except httpx.HTTPError as e:
            logger.error(f"HTTP error in _make_quotes_request: {e}")
            return None
        except Exception as e:
            logger.error(f"Error in _make_quotes_request: {e}")
            return None

    def get_quotes(self, symbol, exchange):
        """Get live quotes using Neo API v2 quotes endpoint with pSymbol-based queries"""
        try:
            logger.info(f"QUOTES API - Symbol: {symbol}, Exchange: {exchange}")

            # Check if this is an index - use symbol name instead of pSymbol
            if 'INDEX' in exchange.upper():
                # For indices, map to correct Neo API format and use static exchange mapping
                kotak_exchange = self._get_kotak_exchange(exchange)
                neo_symbol = self._get_index_symbol(symbol)
                query = f"{kotak_exchange}|{neo_symbol}"
                logger.info(f"QUOTES API - Index query: {symbol} → {neo_symbol} → {query}")
            else:
                # For regular stocks/F&O, get both pSymbol and brexchange from database
                # In Kotak DB: token = pSymbol, brexchange = nse_cm/nse_fo/bse_cm etc.
                psymbol = get_token(symbol, exchange)
                brexchange = get_brexchange(symbol, exchange)
                logger.info(f"QUOTES API - pSymbol: {psymbol}, brexchange: {brexchange}")

                if not psymbol or not brexchange:
                    logger.error(f"pSymbol or brexchange not found for {symbol} on {exchange}")
                    return self._get_default_quote()

                # Map brexchange to correct Kotak format if needed
                if brexchange in ['NSE', 'BSE', 'NFO', 'BFO', 'CDS', 'MCX']:
                    kotak_exchange = self._get_kotak_exchange(brexchange)
                    logger.info(f"QUOTES API - Mapped {brexchange} to {kotak_exchange}")
                else:
                    kotak_exchange = brexchange  # Already in correct format
                
                # Build query using mapped exchange: kotak_exchange|pSymbol
                query = f"{kotak_exchange}|{psymbol}"
                logger.info(f"QUOTES API - Query: {query}")
            
            # Make API request
            response = self._make_quotes_request(query, "all")
            
            if response and isinstance(response, list) and len(response) > 0:
                quote_data = response[0]
                logger.info(f"QUOTES API - Query successful for: {quote_data.get('display_symbol')}")
            else:
                logger.error(f"QUOTES API - Query failed for {symbol}")
                return self._get_default_quote()
            
            if response and isinstance(response, list) and len(response) > 0:
                quote_data = response[0]
                
                # Parse Neo API v2 response format (based on actual API response)
                ohlc_data = quote_data.get('ohlc', {})
                ltp_parsed = float(quote_data.get('ltp', 0))
                
                # Get depth data for actual bid/ask prices
                depth_data = quote_data.get('depth', {})
                buy_orders = depth_data.get('buy', [])
                sell_orders = depth_data.get('sell', [])
                
                # Extract best bid and ask prices from depth
                bid_price = float(buy_orders[0].get('price', 0)) if buy_orders else ltp_parsed
                ask_price = float(sell_orders[0].get('price', 0)) if sell_orders else ltp_parsed
                
                # Get total quantities (for reference)
                total_buy_qty = quote_data.get('total_buy', 0)
                total_sell_qty = quote_data.get('total_sell', 0)
                
                logger.debug(f"QUOTES API - Parsing for {quote_data.get('display_symbol', 'unknown')}:")
                logger.debug(f"  - ltp: {ltp_parsed}")
                logger.debug(f"  - total_buy_qty: {total_buy_qty} (quantity, not price)")
                logger.debug(f"  - total_sell_qty: {total_sell_qty} (quantity, not price)")
                logger.debug(f"  - best_bid_price: {bid_price}")
                logger.debug(f"  - best_ask_price: {ask_price}")
                
                return {
                    'bid': bid_price,
                    'ask': ask_price,
                    'open': float(ohlc_data.get('open', 0)),
                    'high': float(ohlc_data.get('high', 0)),
                    'low': float(ohlc_data.get('low', 0)),
                    'ltp': ltp_parsed,
                    'prev_close': float(ohlc_data.get('close', 0)),
                    'volume': float(quote_data.get('last_volume', 0)),
                    'oi': int(quote_data.get('open_int', 0))  # Available in response
                }
            elif response is not None:
                # API returned 200 but empty response - this is normal for some symbols
                logger.info(f"Empty response received for {symbol} - API returned 200 but no data")
                return self._get_default_quote()
            else:
                logger.warning(f"No quote data received for {symbol}")
                return self._get_default_quote()
                
        except Exception as e:
            logger.error(f"Error in get_quotes: {e}")
            return self._get_default_quote()

    def get_depth(self, symbol: str, exchange: str) -> dict:
        """Get market depth using Neo API v2 quotes endpoint with depth filter"""
        try:
            logger.info(f"DEPTH API - Symbol: {symbol}, Exchange: {exchange}")

            # Check if this is an index - use symbol name instead of pSymbol
            if 'INDEX' in exchange.upper():
                # For indices, map to correct Neo API format and use static exchange mapping
                kotak_exchange = self._get_kotak_exchange(exchange)
                neo_symbol = self._get_index_symbol(symbol)
                query = f"{kotak_exchange}|{neo_symbol}"
                logger.debug(f"DEPTH API - Index query: {symbol} → {neo_symbol} → {query}")
            else:
                # For regular stocks/F&O, get both pSymbol and brexchange from database
                # In Kotak DB: token = pSymbol, brexchange = nse_cm/nse_fo/bse_cm etc.
                psymbol = get_token(symbol, exchange)
                brexchange = get_brexchange(symbol, exchange)
                logger.info(f"DEPTH API - pSymbol: {psymbol}, brexchange: {brexchange}")

                if not psymbol or brexchange is None:
                    logger.error(f"pSymbol or brexchange not found for {symbol} on {exchange}")
                    return self._get_default_depth()

                # Map brexchange to correct Kotak format if needed
                if brexchange in ['NSE', 'BSE', 'NFO', 'BFO', 'CDS', 'MCX']:
                    kotak_exchange = self._get_kotak_exchange(brexchange)
                    logger.info(f"DEPTH API - Mapped {brexchange} to {kotak_exchange}")
                else:
                    kotak_exchange = brexchange  # Already in correct format
                
                # Build query using mapped exchange: kotak_exchange|pSymbol
                query = f"{kotak_exchange}|{psymbol}"
                logger.debug(f"DEPTH API - Query: {query}")
            
            # Make API request with depth filter
            response = self._make_quotes_request(query, "depth")
            
            if response and isinstance(response, list) and len(response) > 0:
                target_quote = response[0]
                depth_data = target_quote.get('depth', {})
                
                logger.debug(f"DEPTH API - Raw depth data: {depth_data}")
                
                # Parse Neo API v2 depth format (based on actual API response)
                bids = []
                asks = []
                
                # Process buy orders (bids) - handle both array and object formats
                buy_data = depth_data.get('buy', [])
                logger.debug(f"DEPTH API - Buy data: {buy_data}")
                
                if isinstance(buy_data, list):
                    for i, bid in enumerate(buy_data[:5]):  # Top 5 bids
                        logger.debug(f"DEPTH API - Processing bid {i}: {bid}")
                        bids.append({
                            'price': float(bid.get('price', 0)),
                            'quantity': int(bid.get('quantity', 0))
                        })
                
                # Process sell orders (asks) - handle both array and object formats  
                sell_data = depth_data.get('sell', [])
                logger.debug(f"DEPTH API - Sell data: {sell_data}")
                
                if isinstance(sell_data, list):
                    for i, ask in enumerate(sell_data[:5]):  # Top 5 asks
                        logger.debug(f"DEPTH API - Processing ask {i}: {ask}")
                        asks.append({
                            'price': float(ask.get('price', 0)),
                            'quantity': int(ask.get('quantity', 0))
                        })
                
                logger.debug(f"DEPTH API - Parsed bids: {bids}")
                logger.debug(f"DEPTH API - Parsed asks: {asks}")
                
                # Ensure we have 5 levels
                while len(bids) < 5:
                    bids.append({'price': 0, 'quantity': 0})
                while len(asks) < 5:
                    asks.append({'price': 0, 'quantity': 0})
                
                total_buy_qty = sum(bid['quantity'] for bid in bids if bid['quantity'] > 0)
                total_sell_qty = sum(ask['quantity'] for ask in asks if ask['quantity'] > 0)
                
                result = {
                    'bids': bids,
                    'asks': asks,
                    'totalbuyqty': total_buy_qty,
                    'totalsellqty': total_sell_qty
                }
                
                logger.debug(f"DEPTH API - Final result: {result}")
                return result
            else:
                logger.warning(f"No depth data received for {symbol}")
                return self._get_default_depth()

        except Exception as e:
            logger.error(f"Error in get_depth: {e}")
            return self._get_default_depth()

    def get_multiquotes(self, symbols: list) -> list:
        """
        Get real-time quotes for multiple symbols with automatic batching
        Args:
            symbols: List of dicts with 'symbol' and 'exchange' keys
                     Example: [{'symbol': 'SBIN', 'exchange': 'NSE'}, ...]
        Returns:
            list: List of quote data for each symbol with format:
                  [{'symbol': 'SBIN', 'exchange': 'NSE', 'data': {...}}, ...]
        """
        try:
            BATCH_SIZE = 50  # Conservative limit for URL length (GET request)
            RATE_LIMIT_DELAY = 0.2  # 5 requests/sec = 250 symbols/sec (under 500 limit)

            # If symbols exceed batch size, process in batches
            if len(symbols) > BATCH_SIZE:
                logger.info(f"Processing {len(symbols)} symbols in batches of {BATCH_SIZE}")
                all_results = []

                # Split symbols into batches
                for i in range(0, len(symbols), BATCH_SIZE):
                    batch = symbols[i:i + BATCH_SIZE]
                    logger.debug(f"Processing batch {i//BATCH_SIZE + 1}: symbols {i+1} to {min(i+BATCH_SIZE, len(symbols))}")

                    # Process this batch
                    batch_results = self._process_quotes_batch(batch)
                    all_results.extend(batch_results)

                    # Rate limit delay between batches
                    if i + BATCH_SIZE < len(symbols):
                        time.sleep(RATE_LIMIT_DELAY)

                logger.info(f"Successfully processed {len(all_results)} quotes in {(len(symbols) + BATCH_SIZE - 1) // BATCH_SIZE} batches")
                return all_results
            else:
                # Single batch processing
                return self._process_quotes_batch(symbols)

        except Exception as e:
            logger.exception(f"Error fetching multiquotes")
            raise Exception(f"Error fetching multiquotes: {e}")

    def _process_quotes_batch(self, symbols: list) -> list:
        """
        Process a single batch of symbols (internal method)
        Args:
            symbols: List of dicts with 'symbol' and 'exchange' keys (max 50)
        Returns:
            list: List of quote data for the batch
        """
        # Build comma-separated queries and mapping
        queries = []
        query_map = {}  # {query -> {symbol, exchange}}
        skipped_symbols = []  # Track symbols that couldn't be resolved

        for item in symbols:
            symbol = item['symbol']
            exchange = item['exchange']

            try:
                # Check if this is an index
                if 'INDEX' in exchange.upper():
                    kotak_exchange = self._get_kotak_exchange(exchange)
                    neo_symbol = self._get_index_symbol(symbol)
                    query = f"{kotak_exchange}|{neo_symbol}"
                else:
                    # For regular stocks/F&O, get pSymbol and brexchange
                    psymbol = get_token(symbol, exchange)
                    brexchange = get_brexchange(symbol, exchange)

                    if not psymbol or not brexchange:
                        logger.warning(f"Skipping symbol {symbol} on {exchange}: could not resolve pSymbol or brexchange")
                        skipped_symbols.append({
                            'symbol': symbol,
                            'exchange': exchange,
                            'error': 'Could not resolve pSymbol or brexchange'
                        })
                        continue

                    # Map brexchange to Kotak format if needed
                    if brexchange in ['NSE', 'BSE', 'NFO', 'BFO', 'CDS', 'MCX']:
                        kotak_exchange = self._get_kotak_exchange(brexchange)
                    else:
                        kotak_exchange = brexchange

                    query = f"{kotak_exchange}|{psymbol}"

                queries.append(query)
                query_map[query] = {
                    'symbol': symbol,
                    'exchange': exchange
                }

            except Exception as e:
                logger.warning(f"Skipping symbol {symbol} on {exchange}: {str(e)}")
                skipped_symbols.append({
                    'symbol': symbol,
                    'exchange': exchange,
                    'error': str(e)
                })
                continue

        # Return skipped symbols if no valid queries
        if not queries:
            logger.warning("No valid queries to fetch quotes for")
            return skipped_symbols

        # Build comma-separated query string
        combined_query = ','.join(queries)

        logger.info(f"Requesting quotes for {len(queries)} instruments")
        logger.debug(f"Combined query: {combined_query[:200]}..." if len(combined_query) > 200 else f"Combined query: {combined_query}")

        # Make API request using existing method (handles URL encoding)
        try:
            # Get the shared httpx client
            client = get_httpx_client()

            # URL encode spaces but keep pipe and comma characters
            encoded_query = urllib.parse.quote(combined_query, safe='|,')
            endpoint = f"/script-details/1.0/quotes/neosymbol/{encoded_query}/all"

            headers = {
                'Authorization': self.access_token,
                'Content-Type': 'application/json'
            }

            url = f"{self.quotes_base_url}{endpoint}"
            logger.debug(f"MULTIQUOTES API - Making request to: {url[:200]}...")

            response = client.get(url, headers=headers)

            if response.status_code != 200:
                logger.error(f"MULTIQUOTES API - HTTP {response.status_code}: {response.text}")
                raise Exception(f"API Error: HTTP {response.status_code}")

            response_data = json.loads(response.text)

        except Exception as e:
            logger.error(f"API Error: {str(e)}")
            raise Exception(f"API Error: {str(e)}")

        # Parse response and build results
        results = []

        if not response_data or not isinstance(response_data, list):
            logger.warning("Empty or invalid response from API")
            return results

        # Build lookup by query for response matching
        # Response items have 'exchange' and 'exchange_token' or 'display_symbol'
        response_lookup = {}
        for quote in response_data:
            # Build possible keys to match
            exch = quote.get('exchange', '')
            token = quote.get('exchange_token', '')
            display = quote.get('display_symbol', '')

            # Try to match with original query format
            key1 = f"{exch}|{token}"
            key2 = f"{exch}|{display.replace('-EQ', '').replace('-IN', '')}" if display else None

            response_lookup[key1] = quote
            if key2:
                response_lookup[key2] = quote

        # Build results from query_map
        for query, original in query_map.items():
            # Try to find matching quote in response
            quote_data = response_lookup.get(query)

            # If not found, try variations
            if not quote_data:
                for resp_key, resp_quote in response_lookup.items():
                    if query.lower() == resp_key.lower():
                        quote_data = resp_quote
                        break

            if not quote_data:
                logger.warning(f"No quote data found for {original['symbol']} ({query})")
                results.append({
                    'symbol': original['symbol'],
                    'exchange': original['exchange'],
                    'error': 'No quote data available'
                })
                continue

            # Parse and format quote data
            ohlc_data = quote_data.get('ohlc', {})
            depth_data = quote_data.get('depth') or {}  # Guard against null depth
            buy_orders = depth_data.get('buy', [])
            sell_orders = depth_data.get('sell', [])

            ltp = float(quote_data.get('ltp', 0))
            bid_price = float(buy_orders[0].get('price', 0)) if buy_orders else ltp
            ask_price = float(sell_orders[0].get('price', 0)) if sell_orders else ltp

            result_item = {
                'symbol': original['symbol'],
                'exchange': original['exchange'],
                'data': {
                    'bid': bid_price,
                    'ask': ask_price,
                    'open': float(ohlc_data.get('open', 0)),
                    'high': float(ohlc_data.get('high', 0)),
                    'low': float(ohlc_data.get('low', 0)),
                    'ltp': ltp,
                    'prev_close': float(ohlc_data.get('close', 0)),
                    'volume': float(quote_data.get('last_volume', 0)),
                    'oi': int(quote_data.get('open_int', 0))
                }
            }
            results.append(result_item)

        # Include skipped symbols in results
        return skipped_symbols + results

    def _get_default_quote(self):
        """Return default quote structure"""
        return {
            'bid': 0, 'ask': 0, 'open': 0,
            'high': 0, 'low': 0, 'ltp': 0,
            'prev_close': 0, 'volume': 0, 'oi': 0
        }

    def _get_default_depth(self):
        """Return default depth structure"""
        return {
            'bids': [{'price': 0, 'quantity': 0} for _ in range(5)],
            'asks': [{'price': 0, 'quantity': 0} for _ in range(5)],
            'totalbuyqty': 0,
            'totalsellqty': 0
        }

    def get_history(self, symbol: str, exchange: str, interval: str, start_date: str, end_date: str) -> pd.DataFrame:
        """Placeholder for historical data - not supported by Kotak Neo"""
        empty_df = pd.DataFrame(columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
        logger.warning("Kotak Neo does not support historical data")
        return empty_df

    def get_supported_intervals(self) -> dict:
        """Return supported intervals matching the format expected by intervals.py"""
        intervals = {
            'seconds': [],
            'minutes': [],
            'hours': [],
            'days': [],
            'weeks': [],
            'months': []
        }
        logger.warning("Kotak Neo does not support historical data intervals")
        return intervals
