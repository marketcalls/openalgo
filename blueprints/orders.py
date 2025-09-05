from flask import Blueprint, jsonify, request, render_template, session, redirect, url_for, Response
from importlib import import_module
from database.auth_db import get_auth_token
from utils.session import check_session_validity
from services.place_smart_order_service import place_smart_order
from services.close_position_service import close_position
from services.orderbook_service import get_orderbook
from services.tradebook_service import get_tradebook
from services.positionbook_service import get_positionbook
from services.holdings_service import get_holdings
from utils.logging import get_logger
import csv
import io

logger = get_logger(__name__)

# Define the blueprint
orders_bp = Blueprint('orders_bp', __name__, url_prefix='/')

def dynamic_import(broker, module_name, function_names):
    module_functions = {}
    try:
        # Import the module based on the broker name
        module = import_module(f'broker.{broker}.{module_name}')
        for name in function_names:
            module_functions[name] = getattr(module, name)
        return module_functions
    except (ImportError, AttributeError) as e:
        logger.error(f"Error importing functions {function_names} from {module_name} for broker {broker}: {e}")

        return None
def generate_orderbook_csv(order_data):
    """Generate CSV file from orderbook data"""
    output = io.StringIO()
    writer = csv.writer(output)
    
    # Write headers matching the terminal display
    headers = ['Trading Symbol', 'Exchange', 'Transaction Type', 'Quantity', 'Price', 
              'Trigger Price', 'Order Type', 'Product Type', 'Order ID', 'Status', 'Time']
    writer.writerow(headers)
    
    # Write data in the same order as the headers
    for order in order_data:
        row = [
            order.get('symbol', ''),
            order.get('exchange', ''),
            order.get('action', ''),
            order.get('quantity', ''),
            order.get('price', ''),
            order.get('trigger_price', ''),
            order.get('pricetype', ''),
            order.get('product', ''),
            order.get('orderid', ''),
            order.get('order_status', ''),
            order.get('timestamp', '')
        ]
        writer.writerow(row)
    
    return output.getvalue()

def generate_tradebook_csv(trade_data):
    """Generate CSV file from tradebook data"""
    output = io.StringIO()
    writer = csv.writer(output)
    
    # Write headers
    headers = ['Trading Symbol', 'Exchange', 'Product Type', 'Transaction Type', 'Fill Size', 
              'Fill Price', 'Trade Value', 'Order ID', 'Fill Time']
    writer.writerow(headers)
    
    # Write data
    for trade in trade_data:
        row = [
            trade.get('symbol', ''),
            trade.get('exchange', ''),
            trade.get('product', ''),
            trade.get('action', ''),
            trade.get('quantity', ''),
            trade.get('average_price', ''),
            trade.get('trade_value', ''),
            trade.get('orderid', ''),
            trade.get('timestamp', '')
        ]
        writer.writerow(row)
    
    return output.getvalue()

def generate_positions_csv(positions_data):
    """Generate CSV file from positions data"""
    output = io.StringIO()
    writer = csv.writer(output)
    
    # Write headers - updated to match terminal output exactly
    headers = ['Symbol', 'Exchange', 'Product Type', 'Net Qty', 'Avg Price', 'LTP', 'P&L']
    writer.writerow(headers)
    
    # Write data
    for position in positions_data:
        row = [
            position.get('symbol', ''),
            position.get('exchange', ''),
            position.get('product', ''),
            position.get('quantity', ''),
            position.get('average_price', ''),
            position.get('ltp', ''),
            position.get('pnl', '')
        ]
        writer.writerow(row)
    
    return output.getvalue()

@orders_bp.route('/orderbook')
@check_session_validity
def orderbook():
    login_username = session['user']
    auth_token = get_auth_token(login_username)
    
    if auth_token is None:
        logger.warning(f"No auth token found for user {login_username}")
        return redirect(url_for('auth.logout'))

    broker = session.get('broker')
    if not broker:
        logger.error("Broker not set in session")
        return "Broker not set in session", 400
    
    # Use the centralized orderbook service
    success, response, status_code = get_orderbook(auth_token=auth_token, broker=broker)
    
    if not success:
        logger.error(f"Failed to get orderbook data: {response.get('message', 'Unknown error')}")
        if status_code == 404:
            return "Failed to import broker module", 500
        return redirect(url_for('auth.logout'))
    
    data = response.get('data', {})
    order_data = data.get('orders', [])
    order_stats = data.get('statistics', {})

    return render_template('orderbook.html', order_data=order_data, order_stats=order_stats)

@orders_bp.route('/tradebook')
@check_session_validity
def tradebook():
    login_username = session['user']
    auth_token = get_auth_token(login_username)
    
    if auth_token is None:
        logger.warning(f"No auth token found for user {login_username}")
        return redirect(url_for('auth.logout'))

    broker = session.get('broker')
    if not broker:
        logger.error("Broker not set in session")
        return "Broker not set in session", 400
    
    # Use the centralized tradebook service
    success, response, status_code = get_tradebook(auth_token=auth_token, broker=broker)
    
    if not success:
        logger.error(f"Failed to get tradebook data: {response.get('message', 'Unknown error')}")
        if status_code == 404:
            return "Failed to import broker module", 500
        return redirect(url_for('auth.logout'))
    
    tradebook_data = response.get('data', [])

    return render_template('tradebook.html', tradebook_data=tradebook_data)

@orders_bp.route('/positions')
@check_session_validity
def positions():
    login_username = session['user']
    auth_token = get_auth_token(login_username)
    
    if auth_token is None:
        logger.warning(f"No auth token found for user {login_username}")
        return redirect(url_for('auth.logout'))

    broker = session.get('broker')
    if not broker:
        logger.error("Broker not set in session")
        return "Broker not set in session", 400
    
    # Use the centralized positionbook service
    success, response, status_code = get_positionbook(auth_token=auth_token, broker=broker)
    
    if not success:
        logger.error(f"Failed to get positions data: {response.get('message', 'Unknown error')}")
        if status_code == 404:
            return "Failed to import broker module", 500
        return redirect(url_for('auth.logout'))
    
    positions_data = response.get('data', [])
    
    return render_template('positions.html', positions_data=positions_data)

@orders_bp.route('/holdings')
@check_session_validity
def holdings():
    login_username = session['user']
    auth_token = get_auth_token(login_username)
    
    if auth_token is None:
        logger.warning(f"No auth token found for user {login_username}")
        return redirect(url_for('auth.logout'))

    broker = session.get('broker')
    if not broker:
        logger.error("Broker not set in session")
        return "Broker not set in session", 400
    
    # Use the centralized holdings service
    success, response, status_code = get_holdings(auth_token=auth_token, broker=broker)
    
    if not success:
        logger.error(f"Failed to get holdings data: {response.get('message', 'Unknown error')}")
        if status_code == 404:
            return "Failed to import broker module", 500
        return redirect(url_for('auth.logout'))
    
    data = response.get('data', {})
    holdings_data = data.get('holdings', [])
    portfolio_stats = data.get('statistics', {})
    
    return render_template('holdings.html', holdings_data=holdings_data, portfolio_stats=portfolio_stats)

@orders_bp.route('/orderbook/export')
@check_session_validity
def export_orderbook():
    try:
        broker = session.get('broker')
        if not broker:
            logger.error("Broker not set in session")
            return "Broker not set in session", 400

        api_funcs = dynamic_import(broker, 'api.order_api', ['get_order_book'])
        mapping_funcs = dynamic_import(broker, 'mapping.order_data', ['map_order_data', 'transform_order_data'])

        if not api_funcs or not mapping_funcs:
            logger.error(f"Error loading broker-specific modules for {broker}")
            return "Error loading broker-specific modules", 500

        login_username = session['user']
        auth_token = get_auth_token(login_username)

        if auth_token is None:
            logger.warning(f"No auth token found for user {login_username}")
            return redirect(url_for('auth.logout'))

        order_data = api_funcs['get_order_book'](auth_token)
        if 'status' in order_data and order_data['status'] == 'error':
            logger.error("Error in order data response")
            return redirect(url_for('auth.logout'))

        order_data = mapping_funcs['map_order_data'](order_data=order_data)
        order_data = mapping_funcs['transform_order_data'](order_data)

        csv_data = generate_orderbook_csv(order_data)
        return Response(
            csv_data,
            mimetype='text/csv',
            headers={'Content-Disposition': 'attachment; filename=orderbook.csv'}
        )
    except Exception as e:
        logger.error(f"Error exporting orderbook: {str(e)}")
        return "Error exporting orderbook", 500

@orders_bp.route('/tradebook/export')
@check_session_validity
def export_tradebook():
    try:
        broker = session.get('broker')
        if not broker:
            logger.error("Broker not set in session")
            return "Broker not set in session", 400

        api_funcs = dynamic_import(broker, 'api.order_api', ['get_trade_book'])
        mapping_funcs = dynamic_import(broker, 'mapping.order_data', ['map_trade_data', 'transform_tradebook_data'])

        if not api_funcs or not mapping_funcs:
            logger.error(f"Error loading broker-specific modules for {broker}")
            return "Error loading broker-specific modules", 500

        login_username = session['user']
        auth_token = get_auth_token(login_username)

        if auth_token is None:
            logger.warning(f"No auth token found for user {login_username}")
            return redirect(url_for('auth.logout'))

        tradebook_data = api_funcs['get_trade_book'](auth_token)
        if 'status' in tradebook_data and tradebook_data['status'] == 'error':
            logger.error("Error in tradebook data response")
            return redirect(url_for('auth.logout'))

        tradebook_data = mapping_funcs['map_trade_data'](tradebook_data)
        tradebook_data = mapping_funcs['transform_tradebook_data'](tradebook_data)

        csv_data = generate_tradebook_csv(tradebook_data)
        return Response(
            csv_data,
            mimetype='text/csv',
            headers={'Content-Disposition': 'attachment; filename=tradebook.csv'}
        )
    except Exception as e:
        logger.error(f"Error exporting tradebook: {str(e)}")
        return "Error exporting tradebook", 500

@orders_bp.route('/positions/export')
@check_session_validity
def export_positions():
    try:
        broker = session.get('broker')
        if not broker:
            logger.error("Broker not set in session")
            return "Broker not set in session", 400

        api_funcs = dynamic_import(broker, 'api.order_api', ['get_positions'])
        mapping_funcs = dynamic_import(broker, 'mapping.order_data', [
            'map_position_data', 'transform_positions_data'
        ])

        if not api_funcs or not mapping_funcs:
            logger.error(f"Error loading broker-specific modules for {broker}")
            return "Error loading broker-specific modules", 500

        login_username = session['user']
        auth_token = get_auth_token(login_username)

        if auth_token is None:
            logger.warning(f"No auth token found for user {login_username}")
            return redirect(url_for('auth.logout'))

        positions_data = api_funcs['get_positions'](auth_token)
        if 'status' in positions_data and positions_data['status'] == 'error':
            logger.error("Error in positions data response")
            return redirect(url_for('auth.logout'))

        positions_data = mapping_funcs['map_position_data'](positions_data)
        positions_data = mapping_funcs['transform_positions_data'](positions_data)

        csv_data = generate_positions_csv(positions_data)
        return Response(
            csv_data,
            mimetype='text/csv',
            headers={'Content-Disposition': 'attachment; filename=positions.csv'}
        )
    except Exception as e:
        logger.error(f"Error exporting positions: {str(e)}")
        return "Error exporting positions", 500

@orders_bp.route('/close_position', methods=['POST'])
@check_session_validity
def close_position():
    """Close a specific position directly using the broker API"""
    try:
        # Get data from request
        data = request.json
        symbol = data.get('symbol')
        exchange = data.get('exchange')
        product = data.get('product')
        
        if not all([symbol, exchange, product]):
            return jsonify({
                'status': 'error',
                'message': 'Missing required parameters (symbol, exchange, product)'
            }), 400
        
        # Get auth token from session
        login_username = session['user']
        auth_token = get_auth_token(login_username)
        broker_name = session.get('broker')
        
        if not auth_token or not broker_name:
            return jsonify({
                'status': 'error',
                'message': 'Authentication error'
            }), 401
        
        # Dynamically import broker-specific modules for API
        api_funcs = dynamic_import(broker_name, 'api.order_api', ['place_smartorder_api', 'get_open_position'])
        
        if not api_funcs:
            logger.error(f"Error loading broker-specific modules for {broker_name}")
            return jsonify({
                'status': 'error',
                'message': 'Error loading broker modules'
            }), 500
        
        # Get the functions we need
        place_smartorder_api = api_funcs['place_smartorder_api']
        
        # Prepare order data for direct broker API call
        order_data = {
            "strategy": "UI Exit Position",
            "exchange": exchange,
            "symbol": symbol,
            "action": "BUY",  # Will be determined by the smart order API based on current position
            "product": product,
            "pricetype": "MARKET",
            "quantity": "0",
            "price": "0",
            "trigger_price": "0",
            "disclosed_quantity": "0",
            "position_size": "0"  # Setting to 0 to close the position
        }
        
        # Call the broker API directly
        res, response, orderid = place_smartorder_api(order_data, auth_token)
        
        # Format the response based on presence of orderid and broker's response
        if orderid:
            response_data = {
                'status': 'success',
                'message': response.get('message') if response and 'message' in response else 'Position close order placed successfully.',
                'orderid': orderid
            }
            status_code = 200
        else:
            # No orderid, definite error
            response_data = {
                'status': 'error',
                'message': response.get('message') if response and 'message' in response else 'Failed to close position (broker did not return order ID).'
            }
            if res and hasattr(res, 'status') and isinstance(res.status, int) and res.status >= 400:
                status_code = res.status  # Use broker's HTTP error code if available
            else:
                status_code = 400 # Default to Bad Request
        
        return jsonify(response_data), status_code
        
    except Exception as e:
        logger.error(f"Error in close_position endpoint: {str(e)}")
        return jsonify({
            'status': 'error',
            'message': f'An error occurred: {str(e)}'
        }), 500

@orders_bp.route('/close_all_positions', methods=['POST'])
@check_session_validity
def close_all_positions():
    """Close all open positions using the broker API"""
    try:
        # Get auth token from session
        login_username = session['user']
        auth_token = get_auth_token(login_username)
        broker_name = session.get('broker')
        
        if not auth_token or not broker_name:
            return jsonify({
                'status': 'error',
                'message': 'Authentication error'
            }), 401
        
        # Dynamically import broker-specific modules for API
        api_funcs = dynamic_import(broker_name, 'api.order_api', ['close_all_positions'])
        
        if not api_funcs or 'close_all_positions' not in api_funcs:
            logger.error(f"Error loading broker-specific modules for {broker_name}")
            return jsonify({
                'status': 'error',
                'message': 'Error loading broker modules'
            }), 500
        
        # Use the broker's close_all_positions function directly
        response_code, status_code = api_funcs['close_all_positions']('', auth_token)
        
        if status_code == 200:
            response_data = {
                'status': 'success',
                'message': 'All Open Positions Squared Off'
            }
            return jsonify(response_data), 200
        else:
            message = response_code.get('message', 'Failed to close positions') if isinstance(response_code, dict) else 'Failed to close positions'
            error_response = {
                'status': 'error',
                'message': message
            }
            return jsonify(error_response), status_code
        
    except Exception as e:
        logger.error(f"Error in close_all_positions endpoint: {str(e)}")
        return jsonify({
            'status': 'error',
            'message': f'An error occurred: {str(e)}'
        }), 500

@orders_bp.route('/cancel_all_orders', methods=['POST'])
@check_session_validity
def cancel_all_orders_ui():
    """Cancel all open orders using the broker API from UI"""
    try:
        # Get auth token from session
        login_username = session['user']
        auth_token = get_auth_token(login_username)
        broker_name = session.get('broker')
        
        if not auth_token or not broker_name:
            return jsonify({
                'status': 'error',
                'message': 'Authentication error'
            }), 401
        
        # Import the cancel_all_orders service
        from services.cancel_all_order_service import cancel_all_orders
        
        # Call the service with auth_token and broker
        success, response_data, status_code = cancel_all_orders(
            order_data={},
            auth_token=auth_token,
            broker=broker_name
        )
        
        # Format the response for UI
        if success and status_code == 200:
            canceled_count = len(response_data.get('canceled_orders', []))
            failed_count = len(response_data.get('failed_cancellations', []))
            
            if canceled_count > 0 or failed_count == 0:
                message = f'Successfully canceled {canceled_count} orders'
                if failed_count > 0:
                    message += f' (Failed to cancel {failed_count} orders)'
                return jsonify({
                    'status': 'success',
                    'message': message,
                    'canceled_orders': response_data.get('canceled_orders', []),
                    'failed_cancellations': response_data.get('failed_cancellations', [])
                }), 200
            else:
                return jsonify({
                    'status': 'info',
                    'message': 'No open orders to cancel'
                }), 200
        else:
            return jsonify(response_data), status_code
        
    except Exception as e:
        logger.error(f"Error in cancel_all_orders_ui endpoint: {str(e)}")
        return jsonify({
            'status': 'error',
            'message': f'An error occurred: {str(e)}'
        }), 500
