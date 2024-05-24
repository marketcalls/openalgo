from flask import Blueprint, jsonify, request, render_template, session, redirect, url_for
from importlib import import_module
from database.auth_db import get_auth_token

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
        print(f"Error importing functions {function_names} from {module_name} for broker {broker}: {e}")
        return None

@orders_bp.route('/orderbook')
def orderbook():
    if not session.get('logged_in'):
        return redirect(url_for('auth.login'))

    broker = session.get('broker')
    if not broker:
        return "Broker not set in session", 400

    # Dynamically import broker-specific modules for API and mapping
    api_funcs = dynamic_import(broker, 'api.order_api', ['get_order_book'])
    mapping_funcs = dynamic_import(broker, 'mapping.order_data', [
        'calculate_order_statistics', 'map_order_data', 
        'transform_order_data'
    ])

    if not api_funcs or not mapping_funcs:
        return "Error loading broker-specific modules", 500

    # Static import used for auth token retrieval
    login_username = session['user']
    auth_token = get_auth_token(login_username)

    if auth_token is None:
        return redirect(url_for('auth.logout'))

    order_data = api_funcs['get_order_book'](auth_token)
    print(order_data)
    if 'status' in order_data:
        if order_data['status'] == 'error':
            return redirect(url_for('auth.logout'))

    order_data = mapping_funcs['map_order_data'](order_data=order_data)
    order_stats = mapping_funcs['calculate_order_statistics'](order_data)
    order_data = mapping_funcs['transform_order_data'](order_data)

    # Fix for empty Angel OrderBook
    # if(order_data[0]['symbol']=='' or order_data[0]['exchange']==''):
    #     order_data[0]['quantity'] = ''
    #     order_data[0]['price'] = ''
    #     order_data[0]['trigger_price'] = ''
    return render_template('orderbook.html', order_data=order_data, order_stats=order_stats)

@orders_bp.route('/tradebook')
def tradebook():
    if not session.get('logged_in'):
        return redirect(url_for('auth.login'))

    broker = session.get('broker')
    if not broker:
        return "Broker not set in session", 400

    # Dynamically import broker-specific modules for API and mapping
    api_funcs = dynamic_import(broker, 'api.order_api', ['get_trade_book'])
    mapping_funcs = dynamic_import(broker, 'mapping.order_data', [
        'map_trade_data', 'transform_tradebook_data'
    ])

    if not api_funcs or not mapping_funcs:
        return "Error loading broker-specific modules", 500

    login_username = session['user']
    auth_token = get_auth_token(login_username)

    if auth_token is None:
        return redirect(url_for('auth.logout'))

    # Using the dynamically imported `get_trade_book` function
    get_trade_book = api_funcs['get_trade_book']
    tradebook_data = get_trade_book(auth_token)
    print(tradebook_data)
  
    if 'status' in tradebook_data and tradebook_data['status'] == 'error':
        return redirect(url_for('auth.logout'))

    # Using the dynamically imported mapping functions
    map_trade_data = mapping_funcs['map_trade_data']
    transform_tradebook_data = mapping_funcs['transform_tradebook_data']

    tradebook_data = map_trade_data(trade_data=tradebook_data)
    tradebook_data = transform_tradebook_data(tradebook_data)

    return render_template('tradebook.html', tradebook_data=tradebook_data)


@orders_bp.route('/positions')
def positions():
    if not session.get('logged_in'):
        return redirect(url_for('auth.login'))
    
    broker = session.get('broker')
    if not broker:
        return "Broker not set in session", 400

    # Dynamically import broker-specific modules for API and mapping
    api_funcs = dynamic_import(broker, 'api.order_api', ['get_positions'])
    mapping_funcs = dynamic_import(broker, 'mapping.order_data', [
        'map_position_data', 'transform_positions_data'
    ])

    if not api_funcs or not mapping_funcs:
        return "Error loading broker-specific modules", 500

    login_username = session['user']
    auth_token = get_auth_token(login_username)

    if auth_token is None:
        return redirect(url_for('auth.logout'))

    # Using the dynamically imported `get_positions` function
    get_positions = api_funcs['get_positions']
    positions_data = get_positions(auth_token)
    print(positions_data)
   
    if 'status' in positions_data and positions_data['status'] == 'error':
        return redirect(url_for('auth.logout'))

    # Using the dynamically imported mapping functions
    map_position_data = mapping_funcs['map_position_data']
    transform_positions_data = mapping_funcs['transform_positions_data']

    positions_data = map_position_data(positions_data)
    positions_data = transform_positions_data(positions_data)
    
    return render_template('positions.html', positions_data=positions_data)


@orders_bp.route('/holdings')
def holdings():
    if not session.get('logged_in'):
        return redirect(url_for('auth.login'))
    
    broker = session.get('broker')
    if not broker:
        return "Broker not set in session", 400

    # Dynamically import broker-specific modules for API and mapping
    api_funcs = dynamic_import(broker, 'api.order_api', ['get_holdings'])
    mapping_funcs = dynamic_import(broker, 'mapping.order_data', [
        'map_portfolio_data', 'calculate_portfolio_statistics', 'transform_holdings_data'
    ])

    if not api_funcs or not mapping_funcs:
        return "Error loading broker-specific modules", 500

    login_username = session['user']
    auth_token = get_auth_token(login_username)

    if auth_token is None:
        return redirect(url_for('auth.logout'))

    # Using the dynamically imported `get_holdings` function
    get_holdings = api_funcs['get_holdings']
    holdings_data = get_holdings(auth_token)
   
    print(holdings_data)

    if 'status' in holdings_data and holdings_data['status'] == 'error':
        return redirect(url_for('auth.logout'))

    # Using the dynamically imported mapping functions
    map_portfolio_data = mapping_funcs['map_portfolio_data']
    calculate_portfolio_statistics = mapping_funcs['calculate_portfolio_statistics']
    transform_holdings_data = mapping_funcs['transform_holdings_data']

    holdings_data = map_portfolio_data(holdings_data)
    portfolio_stats = calculate_portfolio_statistics(holdings_data)
    holdings_data = transform_holdings_data(holdings_data)
    
    return render_template('holdings.html', holdings_data=holdings_data, portfolio_stats=portfolio_stats)
