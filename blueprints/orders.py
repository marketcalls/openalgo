from flask import Blueprint, jsonify, request, render_template, session, redirect, url_for
from api.order_api import get_order_book, get_trade_book, get_positions, get_holdings
from mapping.order_data import calculate_order_statistics, map_order_data

# Define the blueprint
orders_bp = Blueprint('orders_bp', __name__, url_prefix='/')

@orders_bp.route('/orderbook')
def orderbook():
    if not session.get('logged_in'):
        return redirect(url_for('auth.login'))
    
    order_data = get_order_book()

    if order_data['status'] == 'error':
        return redirect(url_for('auth.logout'))

    
    order_data = map_order_data(order_data=order_data)       
    #print(order_data)

    order_stats = calculate_order_statistics(order_data)
    print(order_stats)

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

    tradebook_data = map_order_data(order_data=tradebook_data) 
    print(tradebook_data)



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
        
    return render_template('positions.html', positions_data=positions_data)

@orders_bp.route('/holdings')
def holdings():
    if not session.get('logged_in'):
        return redirect(url_for('auth.login'))
    
    holdings_data = get_holdings()

    
    # Check if 'data' is None or an empty list
    if holdings_data.get('data') is None or not holdings_data['data']:
        # Handle the case where there is no data
        # For example, you might want to display a message to the user
        # or pass an empty list or dictionary to the template.
        print("No data available.")
        holdings_data = {}  # or set it to an empty list if it's supposed to be a list
    else:
        holdings_data = holdings_data['data']
        print(holdings)
    return render_template('holdings.html', holdings_data=holdings_data)


