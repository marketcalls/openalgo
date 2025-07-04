from flask_restx import Namespace, Resource, fields
from flask import request, jsonify, make_response, Response
from marshmallow import ValidationError
from database.auth_db import get_auth_token_broker
from limiter import limiter
import os
import importlib
import pandas as pd
from datetime import datetime, timezone, timedelta
import pytz

from .data_schemas import TickerSchema
from utils.logging import get_logger

API_RATE_LIMIT = os.getenv("API_RATE_LIMIT", "10 per second")
api = Namespace('ticker', description='Stock Ticker Data API')

# Initialize logger
logger = get_logger(__name__)

# Initialize schema
ticker_schema = TickerSchema()

def import_broker_module(broker_name):
    try:
        module_path = f'broker.{broker_name}.api.data'
        broker_module = importlib.import_module(module_path)
        return broker_module
    except ImportError as error:
        logger.exception(f"Error importing broker module '{module_path}': {error}")
        return None

class TextResponse(Response):
    """Custom Response class that supports both text and JSON properties"""
    @property
    def json(self):
        return getattr(self, '_json', None)
    
    @json.setter
    def json(self, value):
        self._json = value

def convert_timestamp(timestamp, interval):
    """Convert timestamp to appropriate format based on interval"""
    # Convert timestamp to datetime in UTC
    dt = datetime.fromtimestamp(timestamp, tz=timezone.utc)
    
    # Convert to IST
    ist = pytz.timezone('Asia/Kolkata')
    dt_ist = dt.astimezone(ist)
    
    # For daily data: just return the date
    if interval.upper() == 'D':
        return dt_ist.strftime('%Y-%m-%d')
    
    # For intraday: return date and time separately
    return dt_ist.strftime('%Y-%m-%d'), dt_ist.strftime('%H:%M:%S')

def validate_and_adjust_date_range(start_date, end_date, interval):
    """
    Validate and adjust date range based on interval to prevent large queries
    
    Rules:
    - D, W, M intervals: maximum 10 years from end_date
    - All other intervals: maximum 30 days from end_date
    
    Returns tuple: (adjusted_start_date, adjusted_end_date, was_adjusted)
    """
    try:
        # Parse dates
        if isinstance(start_date, str):
            start_dt = datetime.strptime(start_date, '%Y-%m-%d')
        else:
            start_dt = start_date
            
        if isinstance(end_date, str):
            end_dt = datetime.strptime(end_date, '%Y-%m-%d')
        else:
            end_dt = end_date
        
        # Determine maximum allowed range based on interval
        interval_upper = interval.upper()
        if interval_upper in ['D', 'W', 'M']:
            # Daily, Weekly, Monthly: 10 years maximum
            max_days = 10 * 365  # 10 years
        else:
            # Intraday intervals: 30 days maximum
            max_days = 30
        
        # Calculate the earliest allowed start date
        earliest_start = end_dt - timedelta(days=max_days)
        
        # Check if adjustment is needed
        if start_dt < earliest_start:
            adjusted_start = earliest_start.strftime('%Y-%m-%d')
            logger.warning(f"Date range adjusted: {start_date} -> {adjusted_start} (interval: {interval}, max days: {max_days})")
            return adjusted_start, end_date, True
        
        return start_date, end_date, False
        
    except Exception as e:
        logger.error(f"Error in date range validation: {e}")
        # Return original dates if parsing fails
        return start_date, end_date, False

@api.route('/<string:symbol>')
@api.doc(params={
    'symbol': 'Stock symbol with exchange (e.g., NSE:RELIANCE)',
    'interval': 'Time interval (e.g., D, 5m, 1h)',
    'from': 'Start date (YYYY-MM-DD)',
    'to': 'End date (YYYY-MM-DD)',
    'adjusted': 'Adjust for splits (true/false)',
    'sort': 'Sort order (asc/desc)',
    'apikey': 'API Key for authentication',
    'format': 'Response format (json/txt). Default: json',
})
class Ticker(Resource):
    @limiter.limit(API_RATE_LIMIT)
    def get(self, symbol):
        """Get aggregate bars for a stock over a given date range with specified interval"""
        try:
            # Default to NSE:RELIANCE if no symbol is provided
            if not symbol:
                symbol = "NSE:RELIANCE"
            
            # Split exchange and symbol
            parts = symbol.split(':')
            if len(parts) == 2:
                exchange, symbol = parts
            else:
                exchange = "NSE"
                symbol = "RELIANCE"
            
            # Get parameters from query string
            ticker_data = {
                'apikey': request.args.get('apikey'),
                'symbol': symbol,
                'exchange': exchange,
                'interval': request.args.get('interval', 'D'),
                'start_date': request.args.get('from'),
                'end_date': request.args.get('to')
            }

            # Get format parameter
            response_format = request.args.get('format', 'json').lower()

            # Validate request data using HistorySchema since we're reusing that functionality
            from .data_schemas import HistorySchema
            history_schema = HistorySchema()
            history_data = history_schema.load(ticker_data)

            # Apply date range restrictions to prevent large queries
            if history_data.get('start_date') and history_data.get('end_date'):
                adjusted_start, adjusted_end, was_adjusted = validate_and_adjust_date_range(
                    history_data['start_date'], 
                    history_data['end_date'], 
                    history_data['interval']
                )
                history_data['start_date'] = adjusted_start
                history_data['end_date'] = adjusted_end
                
                if was_adjusted:
                    logger.info(f"Date range restricted for {history_data['symbol']} ({history_data['interval']}): {adjusted_start} to {adjusted_end}")

            api_key = history_data['apikey']
            AUTH_TOKEN, broker = get_auth_token_broker(api_key)
            if AUTH_TOKEN is None:
                if response_format == 'txt':
                    response = TextResponse('Invalid openalgo apikey\n')
                    response.content_type = 'text/plain'
                    response.json = {'request_id': f"ticker_{symbol}_{history_data['interval']}"}
                    return response, 403
                return make_response(jsonify({
                    'status': 'error',
                    'message': 'Invalid openalgo apikey'
                }), 403)

            broker_module = import_broker_module(broker)
            if broker_module is None:
                if response_format == 'txt':
                    response = TextResponse('Broker-specific module not found\n')
                    response.content_type = 'text/plain'
                    response.json = {'request_id': f"ticker_{symbol}_{history_data['interval']}"}
                    return response, 404
                return make_response(jsonify({
                    'status': 'error',
                    'message': 'Broker-specific module not found'
                }), 404)

            try:
                # Initialize broker's data handler
                data_handler = broker_module.BrokerData(AUTH_TOKEN)
                
                # Use chunked API call
                df = data_handler.get_history(
                    history_data['symbol'],
                    history_data['exchange'],
                    history_data['interval'],
                    history_data['start_date'],
                    history_data['end_date']
                )
                
                if not isinstance(df, pd.DataFrame):
                    raise ValueError("Invalid data format returned from broker")

                # Format the response based on the format parameter
                if response_format == 'txt':
                    # Convert timestamps to datetime format
                    text_output = []
                    interval = history_data['interval']
                    symbol_with_exchange = f"{history_data['exchange']}:{history_data['symbol']}"
                    
                    for _, row in df.iterrows():
                        # Convert timestamp based on interval
                        timestamp = convert_timestamp(row['timestamp'], interval)
                        # Convert volume to integer by removing decimal point
                        volume = int(row['volume'])
                        if interval.upper() == 'D':
                            # Daily format: Ticker,Date_YMD,Open,High,Low,Close,Volume
                            text_output.append(f"{symbol_with_exchange},{timestamp},{row['open']},{row['high']},{row['low']},{row['close']},{volume}")
                        else:
                            # Intraday format: Ticker,Date_YMD,Time,Open,High,Low,Close,Volume
                            date, time = timestamp
                            text_output.append(f"{symbol_with_exchange},{date},{time},{row['open']},{row['high']},{row['low']},{row['close']},{volume}")
                    
                    # Create plain text response
                    response = TextResponse('\n'.join(text_output))
                    response.content_type = 'text/plain'
                    response.json = {'request_id': f"ticker_{symbol}_{history_data['interval']}"}
                    return response
                else:
                    # Return JSON format
                    return make_response(jsonify({
                        'status': 'success',
                        'data': df.to_dict(orient='records')
                    }), 200)

            except Exception as e:
                logger.exception(f"Error in broker_module.get_history: {e}")
                if response_format == 'txt':
                    response = TextResponse(str(e))
                    response.content_type = 'text/plain'
                    response.json = {'request_id': f"ticker_{symbol}_{history_data['interval']}"}
                    return response, 500
                return make_response(jsonify({
                    'status': 'error',
                    'message': str(e)
                }), 500)

        except ValidationError as err:
            if response_format == 'txt':
                response = TextResponse(str(err.messages))
                response.content_type = 'text/plain'
                response.json = {'request_id': 'ticker_validation_error'}
                return response, 400
            return make_response(jsonify({
                'status': 'error',
                'message': err.messages
            }), 400)
        except Exception as e:
            logger.exception(f"Unexpected error in ticker endpoint: {e}")
            if response_format == 'txt':
                response = TextResponse('An unexpected error occurred')
                response.content_type = 'text/plain'
                response.json = {'request_id': 'ticker_unknown_error'}
                return response, 500
            return make_response(jsonify({
                'status': 'error',
                'message': 'An unexpected error occurred'
            }), 500)
