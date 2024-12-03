import logging
from datetime import datetime, timedelta
import pytz
from database.analyzer_db import AnalyzerLog, db_session, async_log_analyzer
from database.symbol import SymToken
from sqlalchemy import func
import json
from extensions import socketio
from utils.constants import (
    VALID_EXCHANGES,
    VALID_ACTIONS,
    VALID_PRICE_TYPES,
    VALID_PRODUCT_TYPES,
    REQUIRED_ORDER_FIELDS,
    DEFAULT_PRODUCT_TYPE,
    DEFAULT_PRICE_TYPE,
    DEFAULT_PRICE,
    DEFAULT_TRIGGER_PRICE,
    DEFAULT_DISCLOSED_QUANTITY
)

logger = logging.getLogger(__name__)

def check_rate_limits(user_id):
    """Check if user has hit rate limits recently"""
    try:
        cutoff = datetime.now(pytz.UTC) - timedelta(minutes=5)
        rate_limited = AnalyzerLog.query.filter(
            AnalyzerLog.created_at >= cutoff,
            AnalyzerLog.response_data.like('%rate limit%')
        ).count()
        return rate_limited > 0
    except Exception as e:
        logger.error(f"Error checking rate limits: {str(e)}")
        return False

def validate_symbol(symbol: str, exchange: str) -> bool:
    """Validate if symbol exists in the database for given exchange"""
    try:
        symbol_exists = SymToken.query.filter(
            SymToken.symbol == symbol,
            SymToken.exchange == exchange
        ).first() is not None
        return symbol_exists
    except Exception as e:
        logger.error(f"Error validating symbol: {str(e)}")
        return False

def analyze_api_request(order_data):
    """Analyze an API request before processing"""
    try:
        issues = []
        warnings = []

        # Check required fields
        missing_fields = [field for field in REQUIRED_ORDER_FIELDS if field not in order_data]
        if missing_fields:
            issues.append(f"Missing mandatory field(s): {', '.join(missing_fields)}")

        # Validate symbol and exchange
        if 'symbol' in order_data and 'exchange' in order_data:
            if not validate_symbol(order_data['symbol'], order_data['exchange']):
                issues.append(f"Invalid symbol '{order_data['symbol']}' for exchange '{order_data['exchange']}'")

        # Validate quantity
        if 'quantity' in order_data:
            try:
                quantity = float(order_data['quantity'])
                if quantity <= 0:
                    issues.append("Quantity must be greater than 0")
            except (ValueError, TypeError):
                issues.append("Invalid quantity value")

        # Validate exchange
        if 'exchange' in order_data:
            if order_data['exchange'] not in VALID_EXCHANGES:
                issues.append(f"Invalid exchange. Must be one of: {', '.join(VALID_EXCHANGES)}")

        # Validate action
        if 'action' in order_data:
            if order_data['action'] not in VALID_ACTIONS:
                issues.append(f"Invalid action. Must be one of: {', '.join(VALID_ACTIONS)}")

        # Validate product type (optional with default)
        product_type = order_data.get('product', DEFAULT_PRODUCT_TYPE)
        if product_type not in VALID_PRODUCT_TYPES:
            issues.append(f"Invalid product type. Must be one of: {', '.join(VALID_PRODUCT_TYPES)}")

        # Validate price type (optional with default)
        price_type = order_data.get('pricetype', DEFAULT_PRICE_TYPE)
        if price_type not in VALID_PRICE_TYPES:
            issues.append(f"Invalid price type. Must be one of: {', '.join(VALID_PRICE_TYPES)}")

        # Validate price values
        try:
            price = float(order_data.get('price', DEFAULT_PRICE))
            trigger_price = float(order_data.get('trigger_price', DEFAULT_TRIGGER_PRICE))
            disclosed_qty = float(order_data.get('disclosed_quantity', DEFAULT_DISCLOSED_QUANTITY))

            if price < 0:
                issues.append("Price cannot be negative")
            if trigger_price < 0:
                issues.append("Trigger price cannot be negative")
            if disclosed_qty < 0:
                issues.append("Disclosed quantity cannot be negative")

            # Additional price type specific validations
            if price_type == 'LIMIT' and price == 0:
                issues.append("Price is required for LIMIT orders")
            if price_type in ['SL', 'SL-M'] and trigger_price == 0:
                issues.append("Trigger price is required for SL/SL-M orders")

        except ValueError:
            issues.append("Invalid numeric value for price, trigger_price, or disclosed_quantity")

        # Check for potential rate limit issues
        try:
            if AnalyzerLog.query.filter(
                AnalyzerLog.created_at >= datetime.now(pytz.UTC) - timedelta(minutes=1)
            ).count() > 50:
                warnings.append("High request frequency detected. Consider reducing request rate.")
        except Exception as e:
            logger.error(f"Error checking rate limits: {str(e)}")
            warnings.append("Unable to check rate limits")

        # Prepare response
        response = {
            'status': 'success' if len(issues) == 0 else 'error',
            'message': ', '.join(issues) if issues else 'Request valid',
            'warnings': warnings
        }

        return response

    except Exception as e:
        logger.error(f"Error analyzing API request: {str(e)}")
        return {
            'status': 'error',
            'message': "Internal error analyzing request",
            'warnings': []
        }

def analyze_request(request_data):
    """Analyze and log a request"""
    try:
        # Analyze request first
        analysis = analyze_api_request(request_data)
        
        # Log to analyzer database
        try:
            async_log_analyzer(request_data, analysis)
        except Exception as e:
            logger.error(f"Error logging to analyzer database: {str(e)}")
        
        # Emit socket event for real-time updates
        try:
            socketio.emit('analyzer_update', {
                'request': {
                    'symbol': request_data.get('symbol', 'Unknown'),
                    'action': request_data.get('action', 'Unknown'),
                    'exchange': request_data.get('exchange', 'Unknown'),
                    'quantity': request_data.get('quantity', 0),
                    'price_type': request_data.get('pricetype', 'Unknown'),
                    'product_type': request_data.get('product', 'Unknown')
                },
                'response': analysis
            })
        except Exception as e:
            logger.error(f"Error emitting socket event: {str(e)}")

        # Return analysis results
        return True, analysis

    except Exception as e:
        logger.error(f"Error analyzing request: {str(e)}")
        error_response = {
            'status': 'error',
            'message': "Internal error analyzing request",
            'warnings': []
        }
        return False, error_response

def get_analyzer_stats():
    """Get analyzer statistics"""
    try:
        cutoff = datetime.now(pytz.UTC) - timedelta(hours=24)
        
        # Get recent requests
        recent_requests = AnalyzerLog.query.filter(
            AnalyzerLog.created_at >= cutoff
        ).all()

        # Initialize stats
        stats = {
            'total_requests': len(recent_requests),
            'sources': {},
            'symbols': set(),
            'issues': {
                'total': 0,
                'by_type': {
                    'rate_limit': 0,
                    'invalid_symbol': 0,
                    'missing_quantity': 0,
                    'invalid_exchange': 0,
                    'other': 0
                }
            }
        }

        # Process requests
        for req in recent_requests:
            try:
                request_data = json.loads(req.request_data)
                response_data = json.loads(req.response_data)
                
                # Update sources
                source = request_data.get('strategy', 'Unknown')
                stats['sources'][source] = stats['sources'].get(source, 0) + 1
                
                # Update symbols
                if 'symbol' in request_data:
                    stats['symbols'].add(request_data['symbol'])
                
                # Update issues
                if response_data.get('status') == 'error':
                    stats['issues']['total'] += 1
                    error_msg = response_data.get('message', '').lower()
                    
                    if 'rate limit' in error_msg:
                        stats['issues']['by_type']['rate_limit'] += 1
                    elif 'invalid symbol' in error_msg:
                        stats['issues']['by_type']['invalid_symbol'] += 1
                    elif 'quantity' in error_msg:
                        stats['issues']['by_type']['missing_quantity'] += 1
                    elif 'exchange' in error_msg:
                        stats['issues']['by_type']['invalid_exchange'] += 1
                    else:
                        stats['issues']['by_type']['other'] += 1

            except Exception as e:
                logger.error(f"Error processing request: {str(e)}")
                continue

        # Convert set to list for JSON serialization
        stats['symbols'] = list(stats['symbols'])
        return stats

    except Exception as e:
        logger.error(f"Error getting analyzer stats: {str(e)}")
        return {
            'total_requests': 0,
            'sources': {},
            'symbols': [],
            'issues': {
                'total': 0,
                'by_type': {
                    'rate_limit': 0,
                    'invalid_symbol': 0,
                    'missing_quantity': 0,
                    'invalid_exchange': 0,
                    'other': 0
                }
            }
        }
