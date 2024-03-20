from flask import Blueprint, jsonify, request, render_template, session, redirect, url_for
from api.order_api import get_order_book, get_trade_book, get_positions, get_holdings
from mapping.order_data import calculate_order_statistics, map_order_data,map_trade_data, map_portfolio_data, calculate_portfolio_statistics
from mapping.order_data import transform_order_data, transform_tradebook_data, transform_positions_data, transform_holdings_data
# Define the blueprint
orders_bp = Blueprint('orders_bp', __name__, url_prefix='/')

@orders_bp.route('/orderbook')
def orderbook():
    if not session.get('logged_in'):
        return redirect(url_for('auth.login'))
    
    order_data = get_order_book()
    #print(order_data)
    if order_data['status'] == 'error':
        return redirect(url_for('auth.logout'))

    
    order_data = map_order_data(order_data=order_data)       
    #print(order_data)

    order_stats = calculate_order_statistics(order_data)
    
    
    order_data = transform_order_data(order_data)
    

    # Pass the data (or lack thereof) to the orderbook.html template
    return render_template('orderbook.html', order_data=order_data, order_stats=order_stats)


@orders_bp.route('/tradebook')
def tradebook():
    if not session.get('logged_in'):
        return redirect(url_for('auth.login'))
    

    tradebook_data = get_trade_book()

    
    # Check if 'data' is None

    if tradebook_data['status'] == 'error':
        return redirect(url_for('auth.logout'))

    
    tradebook_data = map_trade_data(trade_data=tradebook_data) 
    print(tradebook_data)

    tradebook_data = transform_tradebook_data(tradebook_data)
    
    

    return render_template('tradebook.html', tradebook_data=tradebook_data)


@orders_bp.route('/positions')
def positions():
    if not session.get('logged_in'):
        return redirect(url_for('auth.login'))
    
    positions_data = get_positions()
    print(positions_data)

    if positions_data['status'] == 'error':
        return redirect(url_for('auth.logout'))


    positions_data = map_order_data(positions_data)
    

    positions_data = transform_positions_data(positions_data)
    print(positions_data)
        
    return render_template('positions.html', positions_data=positions_data)

@orders_bp.route('/holdings')
def holdings():
    if not session.get('logged_in'):
        return redirect(url_for('auth.login'))
    
        
    holdings_data = get_holdings()
    
    if holdings_data['status'] == 'error':
        return redirect(url_for('auth.logout'))
 

    holdings_data = map_portfolio_data(holdings_data)
    print(holdings_data)

    portfolio_stats = calculate_portfolio_statistics(holdings_data)

    holdings_data = transform_holdings_data(holdings_data)
    
    

    return render_template('holdings.html', holdings_data=holdings_data,portfolio_stats=portfolio_stats)


