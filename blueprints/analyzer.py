from flask import Blueprint, render_template, jsonify, request, session, flash, redirect, url_for, Response
from database.analyzer_db import AnalyzerLog, db_session
from utils.session import check_session_validity
from sqlalchemy import func, desc
from utils.api_analyzer import get_analyzer_stats
import json
from datetime import datetime, timedelta
import pytz
from utils.logging import get_logger
import traceback
import io
import csv

logger = get_logger(__name__)

analyzer_bp = Blueprint('analyzer_bp', __name__, url_prefix='/analyzer')

def format_request(req, ist):
    """Format a single request entry"""
    try:
        request_data = json.loads(req.request_data) if isinstance(req.request_data, str) else req.request_data
        response_data = json.loads(req.response_data) if isinstance(req.response_data, str) else req.response_data
        
        # Base request info
        formatted_request = {
            'timestamp': req.created_at.astimezone(ist).strftime('%Y-%m-%d %H:%M:%S'),
            'api_type': req.api_type,
            'source': request_data.get('strategy', 'Unknown'),
            'request_data': request_data,
            'response_data': response_data,  # Include complete response data
            'analysis': {
                'issues': response_data.get('status') == 'error',
                'error': response_data.get('message'),
                'error_type': 'error' if response_data.get('status') == 'error' else 'success',
                'warnings': response_data.get('warnings', [])
            }
        }

        # Add fields based on API type
        if req.api_type in ['placeorder', 'placesmartorder']:
            formatted_request.update({
                'symbol': request_data.get('symbol', 'Unknown'),
                'exchange': request_data.get('exchange', 'Unknown'),
                'action': request_data.get('action', 'Unknown'),
                'quantity': request_data.get('quantity', 0),
                'price_type': request_data.get('pricetype', 'Unknown'),
                'product_type': request_data.get('product', 'Unknown')
            })
            if req.api_type == 'placesmartorder':
                formatted_request['position_size'] = request_data.get('position_size', 0)
        elif req.api_type == 'cancelorder':
            formatted_request.update({
                'orderid': request_data.get('orderid', 'Unknown')
            })
        
        return formatted_request
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

def get_filtered_requests(start_date=None, end_date=None):
    """Get analyzer requests with date filtering"""
    try:
        ist = pytz.timezone('Asia/Kolkata')
        query = AnalyzerLog.query

        # Apply date filters if provided
        if start_date:
            if isinstance(start_date, str):
                start_date = datetime.strptime(start_date, '%Y-%m-%d').date()
            query = query.filter(func.date(AnalyzerLog.created_at) >= start_date)
        if end_date:
            if isinstance(end_date, str):
                end_date = datetime.strptime(end_date, '%Y-%m-%d').date()
            query = query.filter(func.date(AnalyzerLog.created_at) <= end_date)
        
        # If no dates provided, default to today
        if not start_date and not end_date:
            today_ist = datetime.now(ist).date()
            query = query.filter(func.date(AnalyzerLog.created_at) == today_ist)

        # Get results ordered by created_at
        results = query.order_by(AnalyzerLog.created_at.desc()).all()
        requests = []
        
        for req in results:
            formatted = format_request(req, ist)
            if formatted:
                requests.append(formatted)
                
        return requests
    except Exception as e:
        logger.error(f"Error getting filtered requests: {str(e)}\n{traceback.format_exc()}")
        return []

def generate_csv(requests):
    """Generate CSV from analyzer requests"""
    try:
        output = io.StringIO()
        writer = csv.writer(output)
        
        # Write headers
        headers = ['Timestamp', 'API Type', 'Source', 'Symbol', 'Exchange', 'Action', 
                  'Quantity', 'Price Type', 'Product Type', 'Status', 'Error Message']
        writer.writerow(headers)
        
        # Write data
        for req in requests:
            row = [
                req['timestamp'],
                req['api_type'],
                req['source'],
                req.get('symbol', ''),
                req.get('exchange', ''),
                req.get('action', ''),
                req.get('quantity', ''),
                req.get('price_type', ''),
                req.get('product_type', ''),
                'Error' if req['analysis']['issues'] else 'Success',
                req['analysis'].get('error', '')
            ]
            writer.writerow(row)
        
        return output.getvalue()
    except Exception as e:
        logger.error(f"Error generating CSV: {str(e)}\n{traceback.format_exc()}")
        return ""

@analyzer_bp.route('/')
@check_session_validity
def analyzer():
    """Render the analyzer dashboard"""
    try:
        # Get date parameters
        start_date = request.args.get('start_date')
        end_date = request.args.get('end_date')

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

        # Get filtered requests
        requests = get_filtered_requests(start_date, end_date)
        
        return render_template('analyzer.html', 
                             requests=requests, 
                             stats=stats,
                             start_date=start_date,
                             end_date=end_date)
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

@analyzer_bp.route('/export', methods=['GET'])
@check_session_validity
def export_requests():
    """Export analyzer requests to CSV"""
    try:
        start_date = request.args.get('start_date')
        end_date = request.args.get('end_date')
        
        # Get filtered requests
        requests = get_filtered_requests(start_date, end_date)
        
        # Generate CSV
        csv_data = generate_csv(requests)
        
        # Create the response
        output = Response(csv_data, mimetype='text/csv')
        output.headers["Content-Disposition"] = f"attachment; filename=analyzer_logs_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
        return output
    except Exception as e:
        logger.error(f"Error exporting requests: {str(e)}\n{traceback.format_exc()}")
        flash('Error exporting requests', 'error')
        return redirect(url_for('analyzer_bp.analyzer'))
