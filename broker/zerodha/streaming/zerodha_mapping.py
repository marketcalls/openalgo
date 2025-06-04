"""
Zerodha WebSocket data mapping utilities.

This module provides utilities for mapping between Zerodha's WebSocket data format
and OpenAlgo's standard format.
"""
from typing import Dict, List, Any, Optional, Tuple
import logging
from datetime import datetime, timezone

class ZerodhaExchangeMapper:
    """Maps exchange codes between Zerodha and OpenAlgo formats"""
    
    # Map OpenAlgo exchange codes to Zerodha exchange codes
    _OA_TO_ZERODHA = {
        'NSE': 'NSE',
        'NFO': 'NFO',
        'CDS': 'CDS',
        'BSE': 'BSE',
        'BFO': 'BFO',
        'MCX': 'MCX',
        'NSE_INDEX': 'NSE_INDEX',
        'BSE_INDEX': 'BSE_INDEX',
    }
    
    # Map Zerodha exchange codes to OpenAlgo exchange codes
    _ZERODHA_TO_OA = {v: k for k, v in _OA_TO_ZERODHA.items()}
    
    @classmethod
    def to_zerodha_exchange(cls, oa_exchange: str) -> str:
        """
        Convert OpenAlgo exchange code to Zerodha exchange code.
        
        Args:
            oa_exchange: OpenAlgo exchange code (e.g., 'NSE', 'NFO')
            
        Returns:
            Zerodha exchange code
        """
        return cls._OA_TO_ZERODHA.get(oa_exchange.upper(), oa_exchange.upper())
    
    @classmethod
    def to_oa_exchange(cls, zerodha_exchange: str) -> str:
        """
        Convert Zerodha exchange code to OpenAlgo exchange code.
        
        Args:
            zerodha_exchange: Zerodha exchange code
            
        Returns:
            OpenAlgo exchange code
        """
        return cls._ZERODHA_TO_OA.get(zerodha_exchange.upper(), zerodha_exchange.upper())


class ZerodhaCapabilityRegistry:
    """Registry for Zerodha WebSocket capabilities"""
    
    # Map OpenAlgo capability flags to Zerodha subscription modes
    CAPABILITY_MAP = {
        'LTP': 'ltp',
        'QUOTE': 'quote',
        'DEPTH': 'full',
    }
    
    # Supported capabilities for Zerodha
    SUPPORTED_CAPABILITIES = set(CAPABILITY_MAP.keys())
    
    @classmethod
    def get_zerodha_mode(cls, capability: str) -> str:
        """
        Get Zerodha subscription mode for a capability.
        
        Args:
            capability: OpenAlgo capability (LTP, QUOTE, DEPTH)
            
        Returns:
            Zerodha subscription mode
        """
        return cls.CAPABILITY_MAP.get(capability.upper(), 'quote')
    
    @classmethod
    def is_supported(cls, capability: str) -> bool:
        """
        Check if a capability is supported by Zerodha.
        
        Args:
            capability: Capability to check
            
        Returns:
            bool: True if supported, False otherwise
        """
        return capability.upper() in cls.SUPPORTED_CAPABILITIES


class ZerodhaDataTransformer:
    """Transforms data between Zerodha and OpenAlgo formats"""
    
    def __init__(self):
        self.logger = logging.getLogger(__name__)
    
    def transform_tick(self, tick_data: Dict, symbol: str, exchange: str) -> Dict:
        """
        Transform Zerodha tick data to OpenAlgo format.
        
        Args:
            tick_data: Raw tick data from Zerodha WebSocket
            symbol: Trading symbol
            exchange: Exchange code
            
        Returns:
            Transformed tick data in OpenAlgo format
        """
        try:
            if not tick_data:
                return {}
                
            # Get the mode to determine what data is available
            mode = tick_data.get('mode', 'quote')
            
            # Base tick data
            transformed = {
                'symbol': symbol,
                'exchange': exchange,
                'token': str(tick_data.get('instrument_token', '')),
                'last_price': tick_data.get('last_price', 0),
                'volume': tick_data.get('volume', 0),
                'total_buy_quantity': tick_data.get('total_buy_quantity', 0),
                'total_sell_quantity': tick_data.get('total_sell_quantity', 0),
                'average_price': tick_data.get('average_price', 0),
                'mode': mode,
                'timestamp': tick_data.get('timestamp', int(datetime.now(timezone.utc).timestamp() * 1000))
            }
            
            # Add OHLC data if available
            ohlc = tick_data.get('ohlc', {})
            if ohlc:
                transformed.update({
                    'open': ohlc.get('open', 0),
                    'high': ohlc.get('high', 0),
                    'low': ohlc.get('low', 0),
                    'close': ohlc.get('close', 0),
                })
            
            # Add depth data if available and in full mode
            if mode == 'full' and 'depth' in tick_data:
                depth = tick_data['depth']
                transformed_depth = {'buy': [], 'sell': []}
                
                # Process buy side
                for i, level in enumerate(depth.get('buy', [])):
                    transformed_depth['buy'].append({
                        'price': level.get('price', 0),
                        'quantity': level.get('quantity', 0),
                        'orders': level.get('orders', 0),
                        'position': i + 1
                    })
                
                # Process sell side
                for i, level in enumerate(depth.get('sell', [])):
                    transformed_depth['sell'].append({
                        'price': level.get('price', 0),
                        'quantity': level.get('quantity', 0),
                        'orders': level.get('orders', 0),
                        'position': i + 1
                    })
                
                transformed['depth'] = transformed_depth
            
            # Add additional fields for full mode
            if mode == 'full':
                transformed.update({
                    'last_trade_time': tick_data.get('last_trade_time'),
                    'oi': tick_data.get('oi'),
                    'oi_day_high': tick_data.get('oi_day_high'),
                    'oi_day_low': tick_data.get('oi_day_low'),
                    'exchange_timestamp': tick_data.get('exchange_timestamp')
                })
            
            return transformed
            
        except Exception as e:
            self.logger.error(f"Error transforming tick data: {e}")
            return {}
    
    def transform_order_update(self, order_data: Dict) -> Dict:
        """
        Transform Zerodha order update to OpenAlgo format.
        
        Args:
            order_data: Raw order data from Zerodha WebSocket
            
        Returns:
            Transformed order data in OpenAlgo format
        """
        try:
            if not order_data or 'data' not in order_data:
                return {}
                
            data = order_data['data']
            
            # Map Zerodha status to OpenAlgo status
            status_map = {
                'OPEN': 'open',
                'COMPLETE': 'complete',
                'CANCELLED': 'cancelled',
                'REJECTED': 'rejected',
                'TRIGGER PENDING': 'trigger_pending',
                'MODIFIED': 'modified'
            }
            
            transformed = {
                'order_id': data.get('order_id', ''),
                'exchange_order_id': data.get('exchange_order_id', ''),
                'tradingsymbol': data.get('tradingsymbol', ''),
                'exchange': ZerodhaExchangeMapper.to_oa_exchange(data.get('exchange', '')),
                'transaction_type': data.get('transaction_type', '').lower(),
                'order_type': data.get('order_type', '').lower(),
                'product': data.get('product', '').lower(),
                'status': status_map.get(data.get('status', '').upper(), data.get('status', '').lower()),
                'price': float(data.get('price', 0)),
                'trigger_price': float(data.get('trigger_price', 0)),
                'quantity': int(data.get('quantity', 0)),
                'filled_quantity': int(data.get('filled_quantity', 0)),
                'pending_quantity': int(data.get('pending_quantity', 0)),
                'average_price': float(data.get('average_price', 0)),
                'order_timestamp': data.get('order_timestamp', ''),
                'exchange_timestamp': data.get('exchange_timestamp', ''),
                'status_message': data.get('status_message', '')
            }
            
            return transformed
            
        except Exception as e:
            self.logger.error(f"Error transforming order update: {e}")
            return {}
    
    def transform_position(self, position_data: Dict) -> Dict:
        """
        Transform Zerodha position data to OpenAlgo format.
        
        Args:
            position_data: Raw position data from Zerodha
            
        Returns:
            Transformed position data in OpenAlgo format
        """
        try:
            if not position_data:
                return {}
                
            transformed = {
                'tradingsymbol': position_data.get('tradingsymbol', ''),
                'exchange': ZerodhaExchangeMapper.to_oa_exchange(position_data.get('exchange', '')),
                'product': position_data.get('product', '').lower(),
                'quantity': int(position_data.get('quantity', 0)),
                'average_price': float(position_data.get('average_price', 0)),
                'last_price': float(position_data.get('last_price', 0)),
                'unrealized_pnl': float(position_data.get('unrealized', 0)),
                'realized_pnl': float(position_data.get('realized', 0)),
                'm2m': float(position_data.get('m2m', 0)),
                'buy_quantity': int(position_data.get('buy_quantity', 0)),
                'buy_price': float(position_data.get('buy_price', 0)),
                'buy_value': float(position_data.get('buy_value', 0)),
                'sell_quantity': int(position_data.get('sell_quantity', 0)),
                'sell_price': float(position_data.get('sell_price', 0)),
                'sell_value': float(position_data.get('sell_value', 0)),
                'day_buy_quantity': int(position_data.get('day_buy_quantity', 0)),
                'day_sell_quantity': int(position_data.get('day_sell_quantity', 0)),
                'day_buy_price': float(position_data.get('day_buy_price', 0)),
                'day_sell_price': float(position_data.get('day_sell_price', 0)),
                'day_buy_value': float(position_data.get('day_buy_value', 0)),
                'day_sell_value': float(position_data.get('day_sell_value', 0))
            }
            
            return transformed
            
        except Exception as e:
            self.logger.error(f"Error transforming position data: {e}")
            return {}


# Singleton instances for convenience
exchange_mapper = ZerodhaExchangeMapper()
capability_registry = ZerodhaCapabilityRegistry()
data_transformer = ZerodhaDataTransformer()
