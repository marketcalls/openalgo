from datetime import datetime, timedelta
import pytz
from database.analyzer_db import AnalyzerLog, db_session
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
    REQUIRED_SMART_ORDER_FIELDS,
    REQUIRED_CANCEL_ORDER_FIELDS,
    REQUIRED_CANCEL_ALL_ORDER_FIELDS,
    REQUIRED_CLOSE_POSITION_FIELDS,
    REQUIRED_MODIFY_ORDER_FIELDS,
    DEFAULT_PRODUCT_TYPE,
    DEFAULT_PRICE_TYPE,
    DEFAULT_PRICE,
    DEFAULT_TRIGGER_PRICE,
    DEFAULT_DISCLOSED_QUANTITY
)
from utils.logging import get_logger

logger = get_logger(__name__)

# Global variable to track order sequence
_order_sequence = 0

def generate_order_id():
    """Generate a sequential order ID in format YYMMDDXXXXXXXX"""
    global _order_sequence
    now = datetime.now()
    date_prefix = now.strftime("%y%m%d")
    
    # Get the last order from analyzer logs to ensure sequence continuity
    try:
        last_order = AnalyzerLog.query.filter(
            AnalyzerLog.response_data.like('%"orderid": "%"')
        ).order_by(AnalyzerLog.created_at.desc()).first()
        
        if last_order:
            try:
                last_response = json.loads(last_order.response_data)
                last_orderid = last_response.get('orderid', '')
                if len(last_orderid) >= 5:  # Ensure there's a sequence number
                    _order_sequence = int(last_orderid[-5:])
            except (json.JSONDecodeError, ValueError):
                pass
    except Exception as e:
        logger.error(f"Error getting last order sequence: {e}")
    
    # Increment sequence
    _order_sequence += 1
    
    # Reset sequence if it exceeds 99999
    if _order_sequence > 99999:
        _order_sequence = 1
    
    # Format: YYMMDDXXXXX (where XXXXX is the sequence padded to 5 digits)
    return f"{date_prefix}{_order_sequence:05d}"

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

def analyze_smart_order_request(order_data):
    """Analyze a smart order API request"""
    try:
        issues = []
        warnings = []

        # Check required fields for smart order
        missing_fields = [field for field in REQUIRED_SMART_ORDER_FIELDS if field not in order_data]
        if missing_fields:
            issues.append(f"Missing mandatory field(s): {', '.join(missing_fields)}")

        # Validate symbol and exchange
        if 'symbol' in order_data and 'exchange' in order_data:
            if not validate_symbol(order_data['symbol'], order_data['exchange']):
                issues.append(f"Invalid symbol '{order_data['symbol']}' for exchange '{order_data['exchange']}'")

        # Validate quantity - Allow zero for smart orders since it's used for position checking
        if 'quantity' in order_data:
            try:
                quantity = float(order_data['quantity'])
                if quantity < 0:  # Only check for negative values
                    issues.append("Quantity cannot be negative")
            except (ValueError, TypeError):
                issues.append("Invalid quantity value")

        # Validate position_size - Allow any number including zero for position management
        if 'position_size' in order_data:
            try:
                float(order_data['position_size'])  # Just validate it's a valid number
            except (ValueError, TypeError):
                issues.append("Invalid position size value")

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
        logger.error(f"Error analyzing smart order request: {str(e)}")
        return {
            'status': 'error',
            'message': "Internal error analyzing request",
            'warnings': []
        }

def analyze_cancel_order_request(order_data):
    """Analyze a cancel order request"""
    try:
        issues = []
        warnings = []

        # Check required fields using the constant
        missing_fields = [field for field in REQUIRED_CANCEL_ORDER_FIELDS if field not in order_data]
        if missing_fields:
            issues.append(f"Missing mandatory field(s): {', '.join(missing_fields)}")

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
        logger.error(f"Error analyzing cancel order request: {str(e)}")
        return {
            'status': 'error',
            'message': "Internal error analyzing request",
            'warnings': []
        }

def analyze_cancel_all_order_request(order_data):
    """Analyze a cancel all order request"""
    try:
        issues = []
        warnings = []

        # Check required fields using the constant
        missing_fields = [field for field in REQUIRED_CANCEL_ALL_ORDER_FIELDS if field not in order_data]
        if missing_fields:
            issues.append(f"Missing mandatory field(s): {', '.join(missing_fields)}")

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
        logger.error(f"Error analyzing cancel all order request: {str(e)}")
        return {
            'status': 'error',
            'message': "Internal error analyzing request",
            'warnings': []
        }

def analyze_close_position_request(order_data):
    """Analyze a close position request"""
    try:
        issues = []
        warnings = []

        # Check required fields using the constant
        missing_fields = [field for field in REQUIRED_CLOSE_POSITION_FIELDS if field not in order_data]
        if missing_fields:
            issues.append(f"Missing mandatory field(s): {', '.join(missing_fields)}")

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
        logger.error(f"Error analyzing close position request: {str(e)}")
        return {
            'status': 'error',
            'message': "Internal error analyzing request",
            'warnings': []
        }

def analyze_modify_order_request(order_data):
    """Analyze a modify order request"""
    try:
        issues = []
        warnings = []

        # Check required fields using the constant
        missing_fields = [field for field in REQUIRED_MODIFY_ORDER_FIELDS if field not in order_data]
        if missing_fields:
            issues.append(f"Missing mandatory field(s): {', '.join(missing_fields)}")

        # Validate symbol and exchange
        if 'symbol' in order_data and 'exchange' in order_data:
            if not validate_symbol(order_data['symbol'], order_data['exchange']):
                issues.append(f"Invalid symbol '{order_data['symbol']}' for exchange '{order_data['exchange']}'")

        # Validate exchange
        if 'exchange' in order_data:
            if order_data['exchange'] not in VALID_EXCHANGES:
                issues.append(f"Invalid exchange. Must be one of: {', '.join(VALID_EXCHANGES)}")

        # Validate action
        if 'action' in order_data:
            if order_data['action'] not in VALID_ACTIONS:
                issues.append(f"Invalid action. Must be one of: {', '.join(VALID_ACTIONS)}")

        # Validate product type
        if 'product' in order_data:
            if order_data['product'] not in VALID_PRODUCT_TYPES:
                issues.append(f"Invalid product type. Must be one of: {', '.join(VALID_PRODUCT_TYPES)}")

        # Validate price type
        if 'pricetype' in order_data:
            if order_data['pricetype'] not in VALID_PRICE_TYPES:
                issues.append(f"Invalid price type. Must be one of: {', '.join(VALID_PRICE_TYPES)}")

        # Validate numeric fields
        try:
            # Validate quantity
            if 'quantity' in order_data:
                quantity = float(order_data['quantity'])
                if quantity <= 0:
                    issues.append("Quantity must be greater than 0")

            # Validate price values
            price = float(order_data.get('price', '0'))
            trigger_price = float(order_data.get('trigger_price', '0'))
            disclosed_qty = float(order_data.get('disclosed_quantity', '0'))

            if price < 0:
                issues.append("Price cannot be negative")
            if trigger_price < 0:
                issues.append("Trigger price cannot be negative")
            if disclosed_qty < 0:
                issues.append("Disclosed quantity cannot be negative")

            # Additional price type specific validations
            if order_data.get('pricetype') == 'LIMIT' and price == 0:
                issues.append("Price is required for LIMIT orders")
            if order_data.get('pricetype') in ['SL', 'SL-M'] and trigger_price == 0:
                issues.append("Trigger price is required for SL/SL-M orders")

        except ValueError:
            issues.append("Invalid numeric value for price, trigger_price, quantity, or disclosed_quantity")

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
        logger.error(f"Error analyzing modify order request: {str(e)}")
        return {
            'status': 'error',
            'message': "Internal error analyzing request",
            'warnings': []
        }

def analyze_request(request_data, api_type='placeorder', should_log=False):
    """Analyze a request - logging is now handled by API endpoints"""
    try:
        # Choose appropriate analyzer based on API type
        if api_type == 'placesmartorder':
            analysis = analyze_smart_order_request(request_data)
        elif api_type == 'cancelorder':
            analysis = analyze_cancel_order_request(request_data)
        elif api_type == 'cancelallorder':
            analysis = analyze_cancel_all_order_request(request_data)
        elif api_type == 'closeposition':
            analysis = analyze_close_position_request(request_data)
        elif api_type == 'modifyorder':
            analysis = analyze_modify_order_request(request_data)
        else:
            analysis = analyze_api_request(request_data)
        
        # Return analysis results without logging
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
