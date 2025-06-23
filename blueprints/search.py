from flask import Blueprint, render_template, session, redirect, url_for, request, flash, jsonify
from database.symbol import enhanced_search_symbols
from utils.session import check_session_validity
from typing import List, Dict
from utils.logging import get_logger

logger = get_logger(__name__)

search_bp = Blueprint('search_bp', __name__, url_prefix='/search')

@search_bp.route('/token')
@check_session_validity
def token():
    """Route for the search form page"""
    return render_template('token.html')

@search_bp.route('/')
@check_session_validity
def search():
    """Main search route for full results page"""
    query = request.args.get('symbol', '').strip()
    exchange = request.args.get('exchange')
    
    if not query:
        logger.info("Empty search query received")
        flash('Please enter a search term.', 'error')
        return render_template('token.html')
    
    logger.info(f"Searching for symbol: {query}, exchange: {exchange}")
    results = enhanced_search_symbols(query, exchange)
    
    if not results:
        logger.info(f"No results found for query: {query}")
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
    
    logger.info(f"Found {len(results_dicts)} results for query: {query}")
    return render_template('search.html', results=results_dicts)

@search_bp.route('/api/search')
@check_session_validity
def api_search():
    """API endpoint for AJAX search suggestions"""
    query = request.args.get('q', '').strip()
    exchange = request.args.get('exchange')
    
    if not query:
        logger.debug("Empty API search query received")
        return jsonify({'results': []})
    
    logger.debug(f"API search for symbol: {query}, exchange: {exchange}")
    results = enhanced_search_symbols(query, exchange)
    results_dicts = [{
        'symbol': result.symbol,
        'brsymbol': result.brsymbol,
        'name': result.name,
        'exchange': result.exchange,
        'token': result.token
    } for result in results]
    
    logger.debug(f"API search found {len(results_dicts)} results")
    return jsonify({'results': results_dicts})
