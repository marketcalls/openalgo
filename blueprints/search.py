from flask import Blueprint, render_template, session, redirect, url_for, request, flash, jsonify
from database.symbol import enhanced_search_symbols
from typing import List, Dict

search_bp = Blueprint('search_bp', __name__, url_prefix='/search')

@search_bp.route('/token')
def token():
    """Route for the search form page"""
    if not session.get('logged_in'):
        return redirect(url_for('auth_bp.login'))
    return render_template('token.html')

@search_bp.route('/')
def search():
    """Main search route for full results page"""
    if not session.get('logged_in'):
        return redirect(url_for('auth_bp.login'))
    
    query = request.args.get('symbol', '').strip()
    exchange = request.args.get('exchange')
    
    if not query:
        flash('Please enter a search term.', 'error')
        return render_template('token.html')
    
    results = enhanced_search_symbols(query, exchange)
    
    if not results:
        flash('No matching symbols found.', 'error')
        return render_template('token.html')
    
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

@search_bp.route('/api/search')
def api_search():
    """API endpoint for AJAX search suggestions"""
    if not session.get('logged_in'):
        return jsonify({'error': 'Not authenticated'}), 401
    
    query = request.args.get('q', '').strip()
    exchange = request.args.get('exchange')
    
    if not query:
        return jsonify({'results': []})
    
    results = enhanced_search_symbols(query, exchange)
    results_dicts = [{
        'symbol': result.symbol,
        'brsymbol': result.brsymbol,
        'name': result.name,
        'exchange': result.exchange,
        'token': result.token
    } for result in results]
    
    return jsonify({'results': results_dicts})