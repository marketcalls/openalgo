"""
Fyers Symbol to HSM Token Converter
Converts OpenAlgo symbols to Fyers HSM format for WebSocket streaming
Uses database lookup for brsymbol mapping
"""

import requests
import json
import logging
from typing import Dict, List, Tuple, Optional

# Import database functions
try:
    from database.token_db import get_br_symbol
    DATABASE_AVAILABLE = True
except ImportError:
    DATABASE_AVAILABLE = False
    get_br_symbol = None
    logging.warning("Database not available - falling back to manual conversion")

class FyersTokenConverter:
    """
    Converts symbols to Fyers HSM tokens for WebSocket subscription
    """
    
    # Exchange segment codes (first 4 digits of fytoken)
    EXCHANGE_SEGMENTS = {
        "1010": "nse_cm",    # NSE Cash Market
        "1011": "nse_fo",    # NSE F&O
        "1120": "mcx_fo",    # MCX F&O
        "1210": "bse_cm",    # BSE Cash Market
        "1211": "bse_fo",    # BSE F&O (BFO)
        "1212": "bcs_fo",    # BSE Currency
        "1012": "cde_fo",    # CDE F&O
        "1020": "nse_com"    # NSE Commodity
    }
    
    # Known index mappings (from official library)
    INDEX_MAPPINGS = {
        "NSE:NIFTY50-INDEX": "Nifty 50",
        "NSE:NIFTYBANK-INDEX": "Nifty Bank", 
        "NSE:FINNIFTY-INDEX": "Nifty Fin Service",
        "NSE:INDIAVIX-INDEX": "India VIX",
        "NSE:NIFTY100-INDEX": "Nifty 100",
        "NSE:NIFTYNEXT50-INDEX": "Nifty Next 50",
        "NSE:NIFTYMIDCAP50-INDEX": "Nifty Midcap 50",
        "NSE:NIFTYSMLCAP50-INDEX": "NIFTY SMLCAP 50",
        "BSE:SENSEX-INDEX": "SENSEX",
        "BSE:BANKEX-INDEX": "BANKEX",
        "BSE:BSE500-INDEX": "BSE500",
        "BSE:BSE100-INDEX": "BSE100",
        "BSE:BSE200-INDEX": "BSE200"
    }
    
    def __init__(self, access_token: str):
        """
        Initialize the token converter
        
        Args:
            access_token: Fyers access token (can be in format "appid:token")
        """
        self.logger = logging.getLogger("fyers_token_converter")
        
        # Store full access token for API calls
        self.access_token = access_token
            
        self.symbols_token_api = "https://api-t1.fyers.in/data/symbol-token"
        self.database_available = DATABASE_AVAILABLE
    
    def get_brsymbols_from_database(self, symbol_exchange_pairs: List[Tuple[str, str]]) -> Dict[Tuple[str, str], str]:
        """
        Lookup brsymbols from database using OpenAlgo symbol and exchange
        Uses the existing get_br_symbol function from database.token_db
        
        Args:
            symbol_exchange_pairs: List of (symbol, exchange) tuples
            
        Returns:
            Dict mapping (symbol, exchange) to brsymbol
        """
        brsymbol_map = {}
        
        if not self.database_available or get_br_symbol is None:
            self.logger.error("Database not available - brsymbol lookup required")
            return brsymbol_map
        
        try:
            for symbol, exchange in symbol_exchange_pairs:
                #self.logger.info(f"Looking up brsymbol for {symbol} on {exchange}")
                
                # Use the existing get_br_symbol function
                brsymbol = get_br_symbol(symbol, exchange)
                
                if brsymbol:
                    brsymbol_map[(symbol, exchange)] = brsymbol
                    #self.logger.info(f"Found brsymbol: {symbol}@{exchange} -> {brsymbol}")
                else:
                    self.logger.error(f"No brsymbol found in database for {symbol}@{exchange}")
                    
        except Exception as e:
            self.logger.error(f"Database lookup error: {e}")
            
        return brsymbol_map
    
    def convert_openalgo_symbols_to_hsm(self, symbol_info_list: List[Dict], data_type: str = "SymbolUpdate") -> Tuple[List[str], Dict[str, str], List[str]]:
        """
        Convert OpenAlgo symbols to HSM tokens using database lookup for brsymbols
        
        Args:
            symbol_info_list: List of dicts with 'symbol' and 'exchange' keys
            data_type: Type of data subscription ("SymbolUpdate" or "DepthUpdate")
            
        Returns:
            Tuple of (hsm_tokens, token_to_symbol_mapping, invalid_symbols)
        """
        try:
            # Extract symbol and exchange pairs  
            symbol_exchange_pairs = [(info['symbol'], info['exchange']) for info in symbol_info_list]
            #self.logger.info(f"Converting OpenAlgo symbols: {symbol_exchange_pairs}")
            
            # Get brsymbols from database using get_br_symbol
            brsymbol_map = self.get_brsymbols_from_database(symbol_exchange_pairs)
            
            # Convert only symbols found in database
            brsymbols = []
            invalid_symbols = []
            
            for (symbol, exchange) in symbol_exchange_pairs:
                if (symbol, exchange) in brsymbol_map:
                    brsymbol = brsymbol_map[(symbol, exchange)]
                    brsymbols.append(brsymbol)
                    #self.logger.info(f"Using database brsymbol: {symbol}@{exchange} -> {brsymbol}")
                else:
                    # No fallback - symbol must be in database
                    invalid_symbols.append(f"{symbol}@{exchange}")
                    self.logger.error(f"Symbol not found in database: {symbol}@{exchange}")
            
            if invalid_symbols:
                self.logger.error(f"Symbols not found in database: {invalid_symbols}")
            
            # Convert brsymbols to HSM format
            if brsymbols:
                return self.convert_symbols_to_hsm(brsymbols, data_type)
            else:
                return [], {}, invalid_symbols
            
        except Exception as e:
            self.logger.error(f"OpenAlgo symbol conversion error: {e}")
            return [], {}, [f"{info['symbol']}@{info['exchange']}" for info in symbol_info_list]
        
    def convert_symbols_to_hsm(self, brsymbols: List[str], data_type: str = "SymbolUpdate") -> Tuple[List[str], Dict[str, str], List[str]]:
        """
        Convert brsymbols to HSM tokens for WebSocket subscription
        
        Args:
            brsymbols: List of broker symbols from database (e.g., ["NSE:RELIANCE-EQ", "BSE:TCS-A"])
            data_type: Type of data subscription ("SymbolUpdate" or "DepthUpdate")
            
        Returns:
            Tuple of (hsm_tokens, token_to_symbol_mapping, invalid_symbols)
        """
        try:
            #self.logger.info(f"Converting {len(brsymbols)} brsymbols to HSM tokens")
            #self.logger.info(f"Brsymbols to convert: {brsymbols}")
            #self.logger.info(f"Data type: {data_type}")
            
            hsm_tokens = []
            token_mappings = {}
            invalid_symbols = []
            
            # Process ALL symbols with API conversion to get proper fytokens for live data
            # This ensures both NSE and non-NSE symbols get live data feeds
            if brsymbols:
                self.logger.debug(f"Processing all {len(brsymbols)} symbols with Fyers API conversion")
                try:
                    # Call Fyers API to get fytokens for all symbols
                    data = {"symbols": brsymbols}
                    response = requests.post(
                        url=self.symbols_token_api,
                        headers={
                            "Authorization": self.access_token,
                            "Content-Type": "application/json",
                        },
                        json=data,
                        timeout=10
                    )
                    
                    response_data = response.json()
                    self.logger.debug(f"Fyers API response for all symbols: {response_data}")
                    
                    if response_data.get('s') == "ok":
                        valid_symbols = response_data.get("validSymbol", {})
                        api_invalid = response_data.get("invalidSymbol", [])
                        
                        self.logger.debug(f"API returned {len(valid_symbols)} valid symbols, {len(api_invalid)} invalid symbols")
                        
                        # Process valid symbols with API tokens
                        for symbol, fytoken in valid_symbols.items():
                            hsm_token = self._convert_to_hsm_token(symbol, fytoken, data_type)
                            if hsm_token:
                                hsm_tokens.append(hsm_token)
                                token_mappings[hsm_token] = symbol
                                #self.logger.info(f"✅ Converted: {symbol} -> {hsm_token} (fytoken: {fytoken})")
                            else:
                                invalid_symbols.append(symbol)
                                self.logger.warning(f"❌ Failed to convert: {symbol} with fytoken: {fytoken}")
                        
                        # Add API invalid symbols
                        if api_invalid:
                            invalid_symbols.extend(api_invalid)
                            self.logger.warning(f"API invalid symbols: {api_invalid}")
                    else:
                        error_msg = response_data.get('message', 'Unknown API error')
                        self.logger.error(f"Fyers API error: {error_msg}")
                        invalid_symbols.extend(brsymbols)
                        
                except requests.exceptions.RequestException as e:
                    self.logger.error(f"API request failed: {e}")
                    invalid_symbols.extend(brsymbols)
            
            # If API conversion failed for all symbols, fall back to manual conversion
            # But exclude symbols that were already processed and marked invalid (like depth+index)
            remaining_symbols = [sym for sym in brsymbols if sym not in invalid_symbols]
            if not hsm_tokens and remaining_symbols:
                self.logger.warning("API conversion failed for all symbols, using manual conversion as fallback")
                fallback_tokens, fallback_mappings, fallback_invalid = self._manual_conversion(remaining_symbols, data_type)
                hsm_tokens.extend(fallback_tokens)
                token_mappings.update(fallback_mappings)
                invalid_symbols.extend(fallback_invalid)
            
            #self.logger.info(f"Conversion complete: {len(hsm_tokens)} HSM tokens generated")
            self.logger.debug(f"HSM tokens: {hsm_tokens}")
            
            return hsm_tokens, token_mappings, invalid_symbols
                
        except Exception as e:
            self.logger.error(f"Brsymbol to HSM conversion error: {e}")
            return [], {}, brsymbols
    
    def _convert_to_hsm_token(self, symbol: str, fytoken: str, data_type: str) -> Optional[str]:
        """
        Convert a single symbol and fytoken to HSM token format
        
        Args:
            symbol: Original symbol (e.g., "BSE:TCS-A")
            fytoken: Fyers token from API
            data_type: Type of data subscription
            
        Returns:
            HSM token string or None if conversion fails
        """
        try:
            # Extract exchange segment (first 4 digits)
            if len(fytoken) < 10:
                self.logger.warning(f"Invalid fytoken length for {symbol}: {fytoken}")
                return None
                
            ex_sg = fytoken[:4]
            
            if ex_sg not in self.EXCHANGE_SEGMENTS:
                self.logger.warning(f"Unknown exchange segment {ex_sg} for {symbol}")
                return None
                
            segment = self.EXCHANGE_SEGMENTS[ex_sg]
            
            # Check if it's an index
            is_index = symbol.endswith("-INDEX")
            
            if is_index:
                # For indices, always use index feed (if) regardless of data_type
                # Depth requests for indices will be converted to quote data and then synthetic depth
                if symbol in self.INDEX_MAPPINGS:
                    token_name = self.INDEX_MAPPINGS[symbol]
                else:
                    # Extract index name from symbol
                    token_name = symbol.split(":")[1].replace("-INDEX", "")
                hsm_token = f"if|{segment}|{token_name}"
                
                if data_type == "DepthUpdate":
                    self.logger.debug(f"Index depth subscription: {symbol} -> using index feed for synthetic depth")
            elif data_type == "DepthUpdate":
                # Depth feed
                token_suffix = fytoken[10:]  # Extract token suffix
                hsm_token = f"dp|{segment}|{token_suffix}"
            else:
                # Symbol feed (regular quote/LTP)
                token_suffix = fytoken[10:]  # Extract token suffix
                hsm_token = f"sf|{segment}|{token_suffix}"
            
            return hsm_token
            
        except Exception as e:
            self.logger.error(f"Error converting {symbol} with fytoken {fytoken}: {e}")
            return None
    
    def _manual_conversion(self, symbols: List[str], data_type: str) -> Tuple[List[str], Dict[str, str], List[str]]:
        """
        Manual fallback conversion when API is not available
        This uses known patterns but may not work for all symbols
        For brsymbols (NSE:SYMBOL format), creates HSM tokens directly
        
        Args:
            symbols: List of symbols
            data_type: Type of data subscription
            
        Returns:
            Tuple of (hsm_tokens, token_mappings, invalid_symbols)
        """
        #self.logger.info("Using manual conversion for symbols")
        hsm_tokens = []
        token_mappings = {}
        invalid_symbols = []
        
        for symbol in symbols:
            try:
                # Parse exchange and symbol name
                if ":" not in symbol:
                    invalid_symbols.append(symbol)
                    continue
                    
                exchange, symbol_name = symbol.split(":", 1)
                
                # Determine segment based on exchange and symbol pattern
                segment = self._get_segment_from_exchange(exchange, symbol_name)
                if not segment:
                    invalid_symbols.append(symbol)
                    continue
                
                # Determine prefix and token
                prefix = "sf"  # Default to symbol feed
                
                if symbol.endswith("-INDEX"):
                    # For indices, always use index feed (if) regardless of data_type
                    prefix = "if"
                    if symbol in self.INDEX_MAPPINGS:
                        token = self.INDEX_MAPPINGS[symbol]
                    else:
                        token = symbol_name.replace("-INDEX", "")
                    
                    if data_type == "DepthUpdate":
                        self.logger.debug(f"Manual index depth subscription: {symbol} -> using index feed for synthetic depth")
                elif data_type == "DepthUpdate":
                    prefix = "dp"
                    # For brsymbols, use symbol name as token
                    token = symbol_name
                else:
                    # For brsymbols (NSE:SYMBOL with various suffixes), use the symbol name directly
                    # Examples: NSE:GOLDSTAR-SM, NSE:ABAN-EQ, NSE:ARE&M-EQ, NSE:RELIANCE
                    if exchange == "NSE":
                        # Use symbol name as token for all NSE brsymbols
                        token = symbol_name
                        #self.logger.info(f"Processing NSE brsymbol: {symbol} -> token: {token}")
                    else:
                        token = symbol_name
                
                hsm_token = f"{prefix}|{segment}|{token}"
                hsm_tokens.append(hsm_token)
                token_mappings[hsm_token] = symbol
                #self.logger.info(f"Manual conversion: {symbol} -> {hsm_token}")
                
            except Exception as e:
                self.logger.error(f"Manual conversion failed for {symbol}: {e}")
                invalid_symbols.append(symbol)
        
        return hsm_tokens, token_mappings, invalid_symbols
    
    def _get_segment_from_exchange(self, exchange: str, symbol_name: str) -> Optional[str]:
        """
        Get segment name from exchange and symbol
        
        Args:
            exchange: Exchange name (NSE, BSE, MCX, etc.)
            symbol_name: Symbol name
            
        Returns:
            Segment name or None
        """
        if exchange == "NSE":
            if symbol_name.endswith("-INDEX"):
                return "nse_cm"
            elif (symbol_name.endswith("FUT") or 
                  "OPT" in symbol_name or 
                  # Check for derivatives with specific patterns
                  # CE/PE only if they are clear option indicators (not part of company name)
                  (symbol_name.endswith("CE") and any(char.isdigit() for char in symbol_name)) or
                  (symbol_name.endswith("PE") and any(char.isdigit() for char in symbol_name)) or
                  # Future patterns with date indicators  
                  any(fut_pattern in symbol_name for fut_pattern in ["FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"])):
                return "nse_fo"
            else:
                return "nse_cm"
                
        elif exchange == "BSE":
            if symbol_name.endswith("-INDEX"):
                return "bse_cm"
            else:
                return "bse_cm"
                
        elif exchange == "BFO":
            return "bse_fo"
            
        elif exchange == "MCX":
            return "mcx_fo"
            
        elif exchange == "NFO":
            return "nse_fo"
            
        return None
    
    def get_exchange_from_token(self, fytoken: str) -> Optional[str]:
        """
        Get exchange segment from fytoken
        
        Args:
            fytoken: Fyers token
            
        Returns:
            Exchange segment string or None
        """
        if len(fytoken) >= 4:
            ex_sg = fytoken[:4]
            return self.EXCHANGE_SEGMENTS.get(ex_sg)
        return None
    
    def convert_openalgo_to_fyers_symbol(self, exchange: str, symbol: str) -> str:
        """
        Convert OpenAlgo format (exchange, symbol) to Fyers symbol format
        
        Args:
            exchange: Exchange name (NSE, BSE, MCX, etc.)
            symbol: Symbol name
            
        Returns:
            Fyers symbol format (e.g., "BSE:TCS-A", "NSE:RELIANCE-EQ")
        """
        # Handle different exchange formats
        if exchange == "BSE" and not symbol.endswith(("-A", "-B")):
            # BSE symbols typically end with -A
            symbol = f"{symbol}-A"
        elif exchange == "NSE":
            # For NSE, don't automatically add -EQ unless it's clearly needed
            # Most NSE symbols work without the -EQ suffix
            if not any(suffix in symbol for suffix in ["-INDEX", "FUT", "CE", "PE", "-EQ"]):
                # Try without -EQ first, fallback handled in API call
                pass
        
        return f"{exchange}:{symbol}"