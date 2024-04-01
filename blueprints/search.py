from flask import Blueprint, render_template, session, redirect, url_for, request, flash
from database.symbol import search_symbols

search_bp = Blueprint('search_bp', __name__, url_prefix='/search')

@search_bp.route('/token')
def token():
    if not session.get('logged_in'):
        return redirect(url_for('auth_bp.login'))
    return render_template('token.html')

@search_bp.route('/')
def search():
    if not session.get('logged_in'):
        return redirect(url_for('auth_bp.login'))
    
    symbol = request.args.get('symbol')
    exchange = request.args.get('exchange')
    results = search_symbols(symbol,exchange)
    
    if not results:
        flash('No Matching Symbols Found.', 'error')
        return render_template('token.html')
    else:
        # Since results are now objects, we can't directly zip them with columns
        # Instead, we access attributes directly
        results_dicts = [{
            'symbol': result.symbol,
            'brsymbol': result.brsymbol,
            'name': result.name,
            'exchange': result.exchange,
            'brexchange': result.brexchange,
            'token': result.token,
            'expiry': result.expiry,
            'strike': result.strike,
            'lotsize': result.lotsize,
            'instrumenttype': result.instrumenttype,
            'tick_size': result.tick_size
        } for result in results]
        return render_template('search.html', results=results_dicts)

