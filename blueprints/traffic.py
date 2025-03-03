from flask import Blueprint, jsonify, render_template, request, session, Response
from database.traffic_db import TrafficLog, logs_session
from utils.session import check_session_validity
from limiter import limiter
from sqlalchemy import func
import logging
from datetime import datetime
import pytz
import csv
import io

logger = logging.getLogger(__name__)

traffic_bp = Blueprint('traffic_bp', __name__, url_prefix='/traffic')

def convert_to_ist(timestamp):
    """Convert UTC timestamp to IST"""
    if isinstance(timestamp, str):
        timestamp = datetime.fromisoformat(timestamp.replace('Z', '+00:00'))
    utc = pytz.timezone('UTC')
    ist = pytz.timezone('Asia/Kolkata')
    if timestamp.tzinfo is None:
        timestamp = utc.localize(timestamp)
    return timestamp.astimezone(ist)

def format_ist_time(timestamp):
    """Format timestamp in IST with 12-hour format"""
    ist_time = convert_to_ist(timestamp)
    return ist_time.strftime('%d-%m-%Y %I:%M:%S %p')

def generate_csv(logs):
    """Generate CSV file from traffic logs"""
    output = io.StringIO()
    writer = csv.writer(output)
    
    # Write header
    writer.writerow(['Timestamp', 'Client IP', 'Method', 'Path', 'Status Code', 'Duration (ms)', 'Host', 'Error'])
    
    # Write data
    for log in logs:
        writer.writerow([
            format_ist_time(log.timestamp),
            log.client_ip,
            log.method,
            log.path,
            log.status_code,
            round(log.duration_ms, 2),
            log.host,
            log.error
        ])
    
    return output.getvalue()

@traffic_bp.route('/', methods=['GET'])
@check_session_validity
@limiter.limit("60/minute")
def traffic_dashboard():
    """Display traffic monitoring dashboard"""
    stats = TrafficLog.get_stats()
    recent_logs = TrafficLog.get_recent_logs(limit=100)
    # Convert TrafficLog objects to dictionaries with IST timestamps
    logs_data = [{
        'timestamp': format_ist_time(log.timestamp),
        'client_ip': log.client_ip,
        'method': log.method,
        'path': log.path,
        'status_code': log.status_code,
        'duration_ms': round(log.duration_ms, 2),
        'host': log.host,
        'error': log.error
    } for log in recent_logs]
    return render_template('traffic/dashboard.html',
                         stats=stats,
                         logs=logs_data)

@traffic_bp.route('/api/logs', methods=['GET'])
@check_session_validity
@limiter.limit("60/minute")
def get_logs():
    """API endpoint to get traffic logs"""
    try:
        limit = min(int(request.args.get('limit', 100)), 1000)
        logs = TrafficLog.get_recent_logs(limit=limit)
        return jsonify([{
            'timestamp': format_ist_time(log.timestamp),
            'client_ip': log.client_ip,
            'method': log.method,
            'path': log.path,
            'status_code': log.status_code,
            'duration_ms': round(log.duration_ms, 2),
            'host': log.host,
            'error': log.error
        } for log in logs])
    except Exception as e:
        logger.error(f"Error fetching traffic logs: {e}")
        return jsonify({'error': str(e)}), 500

@traffic_bp.route('/api/stats', methods=['GET'])
@check_session_validity
@limiter.limit("60/minute")
def get_stats():
    """API endpoint to get traffic statistics"""
    try:
        # Get overall stats
        all_logs = TrafficLog.query
        overall_stats = {
            'total_requests': all_logs.count(),
            'error_requests': all_logs.filter(TrafficLog.status_code >= 400).count(),
            'avg_duration': round(float(all_logs.with_entities(func.avg(TrafficLog.duration_ms)).scalar() or 0), 2)
        }
        
        # Get API-specific stats
        api_logs = TrafficLog.query.filter(TrafficLog.path.like('/api/v1/%'))
        api_stats = {
            'total_requests': api_logs.count(),
            'error_requests': api_logs.filter(TrafficLog.status_code >= 400).count(),
            'avg_duration': round(float(api_logs.with_entities(func.avg(TrafficLog.duration_ms)).scalar() or 0), 2)
        }
        
        # Get endpoint usage stats
        endpoint_stats = {}
        for endpoint in [
            'placeorder', 'placesmartorder', 'modifyorder', 'cancelorder',
            'quotes', 'history', 'depth', 'intervals', 'funds', 'orderbook',
            'tradebook', 'positionbook', 'holdings', 'basketorder', 'splitorder',
            'orderstatus', 'openposition'
        ]:
            path = f'/api/v1/{endpoint}'
            endpoint_logs = TrafficLog.query.filter(TrafficLog.path.like(f'{path}%'))
            endpoint_stats[endpoint] = {
                'total': endpoint_logs.count(),
                'errors': endpoint_logs.filter(TrafficLog.status_code >= 400).count(),
                'avg_duration': round(float(endpoint_logs.with_entities(func.avg(TrafficLog.duration_ms)).scalar() or 0), 2)
            }
        
        return jsonify({
            'overall': overall_stats,
            'api': api_stats,
            'endpoints': endpoint_stats
        })
    except Exception as e:
        logger.error(f"Error fetching traffic stats: {e}")
        return jsonify({'error': str(e)}), 500

@traffic_bp.route('/export', methods=['GET'])
@check_session_validity
@limiter.limit("10/minute")
def export_logs():
    """Export traffic logs to CSV"""
    try:
        # Get all logs for the current day
        logs = TrafficLog.get_recent_logs(limit=None)  # None to get all logs
        
        # Generate CSV
        csv_data = generate_csv(logs)
        
        # Create the response
        response = Response(
            csv_data,
            mimetype='text/csv',
            headers={'Content-Disposition': 'attachment; filename=traffic_logs.csv'}
        )
        
        return response
        
    except Exception as e:
        logger.error(f"Error exporting traffic logs: {e}")
        return jsonify({'error': str(e)}), 500

@traffic_bp.teardown_app_request
def shutdown_session(exception=None):
    logs_session.remove()
