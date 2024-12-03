from flask import Blueprint, render_template, jsonify, request, session, flash, redirect, url_for
from database.analyzer_db import AnalyzerLog, db_session
from utils.session import check_session_validity
from sqlalchemy import func, desc
from utils.api_analyzer import get_analyzer_stats
import json
from datetime import datetime, timedelta
import pytz
import logging
import traceback

logger = logging.getLogger(__name__)

analyzer_bp = Blueprint('analyzer_bp', __name__, url_prefix='/analyzer')

def format_request(req, ist):
    """Format a single request entry"""
    try:
        request_data = json.loads(req.request_data) if isinstance(req.request_data, str) else req.request_data
        response_data = json.loads(req.response_data) if isinstance(req.response_data, str) else req.response_data
        
        return {
            'timestamp': req.created_at.astimezone(ist).strftime('%Y-%m-%d %H:%M:%S'),
            'source': request_data.get('strategy', 'Unknown'),
            'symbol': request_data.get('symbol', 'Unknown'),
            'exchange': request_data.get('exchange', 'Unknown'),
            'action': request_data.get('action', 'Unknown'),
            'quantity': request_data.get('quantity', 0),
            'price_type': request_data.get('price_type', 'Unknown'),
            'product_type': request_data.get('product_type', 'Unknown'),
            'request_data': request_data,
            'analysis': {
                'issues': response_data.get('status') == 'error',
                'error': response_data.get('message'),
                'error_type': 'error' if response_data.get('status') == 'error' else 'success',
                'warnings': response_data.get('warnings', [])
            }
        }
    except Exception as e:
        logger.error(f"Error formatting request {req.id}: {str(e)}")
        return None

def get_recent_requests():
    """Get recent analyzer requests"""
    try:
        ist = pytz.timezone('Asia/Kolkata')
        recent = AnalyzerLog.query.order_by(AnalyzerLog.created_at.desc()).limit(100).all()
        requests = []
        
        for req in recent:
            formatted = format_request(req, ist)
            if formatted:
                requests.append(formatted)
                
        return requests
    except Exception as e:
        logger.error(f"Error getting recent requests: {str(e)}")
        return []

@analyzer_bp.route('/')
@check_session_validity
def analyzer():
    """Render the analyzer dashboard"""
    try:
        # Get stats with proper structure
        stats = get_analyzer_stats()
        if not isinstance(stats, dict):
            stats = {
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

        # Get recent requests
        requests = get_recent_requests()

        # If AJAX request, return JSON
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return jsonify({
                'stats': stats,
                'requests': requests
            })

        return render_template('analyzer.html', stats=stats, requests=requests)
    except Exception as e:
        logger.error(f"Error rendering analyzer: {str(e)}\n{traceback.format_exc()}")
        flash('Error loading analyzer dashboard', 'error')
        return redirect(url_for('core_bp.home'))

@analyzer_bp.route('/stats')
@check_session_validity
def get_stats():
    """Get analyzer stats endpoint"""
    try:
        stats = get_analyzer_stats()
        return jsonify(stats)
    except Exception as e:
        logger.error(f"Error getting analyzer stats: {str(e)}")
        return jsonify({
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
        }), 500

@analyzer_bp.route('/requests')
@check_session_validity
def get_requests():
    """Get analyzer requests endpoint"""
    try:
        requests = get_recent_requests()
        return jsonify({'requests': requests})
    except Exception as e:
        logger.error(f"Error getting analyzer requests: {str(e)}")
        return jsonify({'requests': []}), 500

@analyzer_bp.route('/clear')
@check_session_validity
def clear_logs():
    """Clear analyzer logs"""
    try:
        # Delete all logs older than 24 hours
        cutoff = datetime.now(pytz.UTC) - timedelta(hours=24)
        AnalyzerLog.query.filter(AnalyzerLog.created_at < cutoff).delete()
        db_session.commit()
        flash('Analyzer logs cleared successfully', 'success')
    except Exception as e:
        logger.error(f"Error clearing analyzer logs: {str(e)}")
        flash('Error clearing analyzer logs', 'error')
    
    return redirect(url_for('analyzer_bp.analyzer'))
