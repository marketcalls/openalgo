# blueprints/log.py

from flask import Blueprint, render_template, session, redirect, url_for, request, jsonify, send_file
from database.apilog_db import OrderLog
from utils.session import check_session_validity
from sqlalchemy import func
import pytz
from datetime import datetime
import logging
import json
import csv
import io
import os

logger = logging.getLogger(__name__)

log_bp = Blueprint('log_bp', __name__, url_prefix='/logs')

def sanitize_request_data(data):
    """Remove sensitive information from request data"""
    try:
        if isinstance(data, str):
            data = json.loads(data)
        if isinstance(data, dict):
            # Create a copy to avoid modifying the original
            sanitized = data.copy()
            # Remove apikey if present
            sanitized.pop('apikey', None)
            return sanitized
    except:
        return data
    return data

def format_log_entry(log, ist):
    """Format a single log entry"""
    try:
        request_data = sanitize_request_data(log.request_data)
        response_data = json.loads(log.response_data) if log.response_data else {}
        
        # Extract strategy from request data
        strategy = request_data.get('strategy', 'Unknown') if isinstance(request_data, dict) else 'Unknown'
        
        return {
            'id': log.id,
            'api_type': log.api_type,
            'request_data': request_data,
            'response_data': response_data,
            'strategy': strategy,
            'created_at': log.created_at.astimezone(ist).strftime('%Y-%m-%d %I:%M:%S %p')
        }
    except Exception as e:
        logger.error(f"Error formatting log {log.id}: {str(e)}")
        return {
            'id': log.id,
            'api_type': log.api_type,
            'request_data': log.request_data,
            'response_data': log.response_data,
            'strategy': 'Unknown',
            'created_at': log.created_at.astimezone(ist).strftime('%Y-%m-%d %I:%M:%S %p')
        }

def get_filtered_logs(start_date=None, end_date=None, search_query=None, page=1, per_page=20):
    """Get filtered logs with pagination"""
    ist = pytz.timezone('Asia/Kolkata')
    query = OrderLog.query

    # Apply date filters if provided
    if start_date:
        if isinstance(start_date, str):
            start_date = datetime.strptime(start_date, '%Y-%m-%d').date()
        query = query.filter(func.date(OrderLog.created_at) >= start_date)
    if end_date:
        if isinstance(end_date, str):
            end_date = datetime.strptime(end_date, '%Y-%m-%d').date()
        query = query.filter(func.date(OrderLog.created_at) <= end_date)
    
    # If no dates provided, default to today
    if not start_date and not end_date:
        today_ist = datetime.now(ist).date()
        query = query.filter(func.date(OrderLog.created_at) == today_ist)

    # Apply search filter if provided
    if search_query:
        search = f"%{search_query}%"
        query = query.filter(
            (OrderLog.api_type.ilike(search)) |
            (OrderLog.request_data.ilike(search)) |
            (OrderLog.response_data.ilike(search))
        )

    # Get total count for pagination
    total_logs = query.count()
    total_pages = (total_logs + per_page - 1) // per_page

    # Apply pagination if requested
    if page and per_page:
        query = query.order_by(OrderLog.created_at.desc())\
                    .offset((page - 1) * per_page)\
                    .limit(per_page)
    else:
        query = query.order_by(OrderLog.created_at.desc())

    # Format logs
    logs = [format_log_entry(log, ist) for log in query.all()]

    return logs, total_pages, total_logs

def generate_csv(logs):
    """Generate CSV file from logs"""
    output = io.StringIO()
    writer = csv.writer(output)
    
    # Write headers
    headers = ['ID', 'Timestamp', 'API Type', 'Strategy', 'Action', 'Exchange', 'Symbol', 
              'Product', 'Price Type', 'Quantity', 'Price', 'Order ID']
    writer.writerow(headers)
    
    # Write data
    for log in logs:
        request_data = log['request_data']
        row = [
            log['id'],
            log['created_at'],
            log['api_type'],
            log['strategy'],
            request_data.get('action', ''),
            request_data.get('exchange', ''),
            request_data.get('symbol', ''),
            request_data.get('product', ''),
            request_data.get('pricetype', ''),
            request_data.get('quantity', ''),
            request_data.get('price', ''),
            request_data.get('orderid', '')
        ]
        writer.writerow(row)
    
    output.seek(0)
    return output

@log_bp.route('/')
@check_session_validity
def view_logs():
    try:
        # Get parameters
        start_date = request.args.get('start_date')
        end_date = request.args.get('end_date')
        search_query = request.args.get('search', '').strip()
        page = int(request.args.get('page', 1))
        per_page = 20

        # Get filtered logs
        logs, total_pages, _ = get_filtered_logs(
            start_date=start_date,
            end_date=end_date,
            search_query=search_query,
            page=page,
            per_page=per_page
        )

        # If AJAX request, return JSON
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return jsonify({
                'logs': logs,
                'total_pages': total_pages,
                'current_page': page
            })

        logger.info(f"Found {len(logs)} log entries")
        return render_template('logs.html', 
                             logs=logs,
                             total_pages=total_pages, 
                             current_page=page,
                             search_query=search_query,
                             start_date=start_date,
                             end_date=end_date)
        
    except Exception as e:
        logger.error(f"Error fetching logs: {str(e)}")
        return render_template('logs.html', 
                             logs=[],
                             total_pages=1,
                             current_page=1,
                             search_query='',
                             start_date=None,
                             end_date=None)

@log_bp.route('/export')
@check_session_validity
def export_logs():
    try:
        # Get parameters
        start_date = request.args.get('start_date')
        end_date = request.args.get('end_date')
        search_query = request.args.get('search', '').strip()

        # Get all logs without pagination
        logs, _, _ = get_filtered_logs(
            start_date=start_date,
            end_date=end_date,
            search_query=search_query,
            page=None,
            per_page=None
        )

        # Generate CSV
        output = generate_csv(logs)
        
        # Generate filename with timestamp
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        filename = f'openalgo_logs_{timestamp}.csv'

        return send_file(
            io.BytesIO(output.getvalue().encode('utf-8')),
            mimetype='text/csv',
            as_attachment=True,
            download_name=filename
        )

    except Exception as e:
        logger.error(f"Error exporting logs: {str(e)}")
        return jsonify({'error': 'Failed to export logs'}), 500
