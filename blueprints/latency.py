from flask import Blueprint, jsonify, render_template, request, session, Response
from database.latency_db import OrderLatency, latency_session
from utils.session import check_session_validity
from limiter import limiter
import logging
from sqlalchemy import func
from collections import defaultdict
import numpy as np
from datetime import datetime
import pytz
import csv
import io

logger = logging.getLogger(__name__)

latency_bp = Blueprint('latency_bp', __name__, url_prefix='/latency')

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

def get_histogram_data(broker=None):
    """Get histogram data for RTT distribution"""
    try:
        query = OrderLatency.query
        if broker:
            query = query.filter_by(broker=broker)
        
        # Get all RTT values
        rtts = [r[0] for r in query.with_entities(OrderLatency.rtt_ms).all()]
        
        if not rtts:
            return {
                'bins': [],
                'counts': [],
                'avg_rtt': 0,
                'min_rtt': 0,
                'max_rtt': 0
            }
        
        # Calculate statistics
        avg_rtt = sum(rtts) / len(rtts)
        min_rtt = min(rtts)
        max_rtt = max(rtts)
        
        # Create histogram bins
        bin_count = 30  # Number of bins
        bin_width = (max_rtt - min_rtt) / bin_count if max_rtt > min_rtt else 1
        
        # Create histogram using numpy
        counts, bins = np.histogram(rtts, bins=bin_count, range=(min_rtt, max_rtt))
        
        # Convert to list for JSON serialization
        counts = counts.tolist()
        bins = bins.tolist()
        
        # Create bin labels (use the start of each bin)
        bin_labels = [f"{bins[i]:.1f}" for i in range(len(bins)-1)]
        
        data = {
            'bins': bin_labels,
            'counts': counts,
            'avg_rtt': float(avg_rtt),
            'min_rtt': float(min_rtt),
            'max_rtt': float(max_rtt)
        }
        
        logger.info(f"Histogram data for broker {broker}: {data}")
        return data
        
    except Exception as e:
        logger.error(f"Error getting histogram data: {e}")
        return {
            'bins': [],
            'counts': [],
            'avg_rtt': 0,
            'min_rtt': 0,
            'max_rtt': 0
        }

def generate_csv(logs):
    """Generate CSV file from latency logs"""
    output = io.StringIO()
    writer = csv.writer(output)
    
    # Write header
    writer.writerow(['Timestamp', 'Broker', 'Order ID', 'Symbol', 'Order Type', 'RTT (ms)', 'Overhead (ms)', 'Total Latency (ms)', 'Status'])
    
    # Write data
    for log in logs:
        writer.writerow([
            format_ist_time(log.timestamp),
            log.broker,
            log.order_id,
            log.symbol,
            log.order_type,
            round(log.rtt_ms, 2),
            round(log.overhead_ms, 2),
            round(log.total_latency_ms, 2),
            log.status
        ])
    
    return output.getvalue()

@latency_bp.route('/', methods=['GET'])
@check_session_validity
@limiter.limit("60/minute")
def latency_dashboard():
    """Display latency monitoring dashboard"""
    stats = OrderLatency.get_latency_stats()
    recent_logs = OrderLatency.get_recent_logs(limit=100)
    
    # Get histogram data for each broker
    broker_histograms = {}
    brokers = [b[0] for b in OrderLatency.query.with_entities(OrderLatency.broker).distinct().all()]
    for broker in brokers:
        if broker:  # Skip None values
            broker_histograms[broker] = get_histogram_data(broker)
    
    logger.info(f"Broker histograms data: {broker_histograms}")
    
    # Format timestamps in IST
    for log in recent_logs:
        log.formatted_timestamp = format_ist_time(log.timestamp)
    
    return render_template('latency/dashboard.html',
                         stats=stats,
                         logs=recent_logs,
                         broker_histograms=broker_histograms)

@latency_bp.route('/api/logs', methods=['GET'])
@check_session_validity
@limiter.limit("60/minute")
def get_logs():
    """API endpoint to get latency logs"""
    try:
        limit = min(int(request.args.get('limit', 100)), 1000)
        logs = OrderLatency.get_recent_logs(limit=limit)
        return jsonify([{
            'timestamp': convert_to_ist(log.timestamp).isoformat(),
            'id': log.id,
            'order_id': log.order_id,
            'broker': log.broker,
            'symbol': log.symbol,
            'order_type': log.order_type,
            'rtt_ms': log.rtt_ms,
            'validation_latency_ms': log.validation_latency_ms,
            'response_latency_ms': log.response_latency_ms,
            'overhead_ms': log.overhead_ms,
            'total_latency_ms': log.total_latency_ms,
            'status': log.status,
            'error': log.error
        } for log in logs])
    except Exception as e:
        logger.error(f"Error fetching latency logs: {e}")
        return jsonify({'error': str(e)}), 500

@latency_bp.route('/api/stats', methods=['GET'])
@check_session_validity
@limiter.limit("60/minute")
def get_stats():
    """API endpoint to get latency statistics"""
    try:
        stats = OrderLatency.get_latency_stats()
        
        # Add histogram data for each broker
        broker_histograms = {}
        for broker in stats.get('broker_stats', {}):
            broker_histograms[broker] = get_histogram_data(broker)
        
        stats['broker_histograms'] = broker_histograms
        return jsonify(stats)
    except Exception as e:
        logger.error(f"Error fetching latency stats: {e}")
        return jsonify({'error': str(e)}), 500

@latency_bp.route('/api/broker/<broker>/stats', methods=['GET'])
@check_session_validity
@limiter.limit("60/minute")
def get_broker_stats(broker):
    """API endpoint to get broker-specific latency statistics"""
    try:
        stats = OrderLatency.get_latency_stats()
        broker_stats = stats.get('broker_stats', {}).get(broker, {})
        if not broker_stats:
            return jsonify({'error': 'Broker not found'}), 404
        
        # Add histogram data
        broker_stats['histogram'] = get_histogram_data(broker)
        return jsonify(broker_stats)
    except Exception as e:
        logger.error(f"Error fetching broker stats: {e}")
        return jsonify({'error': str(e)}), 500

@latency_bp.route('/export', methods=['GET'])
@check_session_validity
@limiter.limit("10/minute")
def export_logs():
    """Export latency logs to CSV"""
    try:
        # Get all logs for the current day
        logs = OrderLatency.get_recent_logs(limit=None)  # None to get all logs
        
        # Generate CSV
        csv_data = generate_csv(logs)
        
        # Create the response
        response = Response(
            csv_data,
            mimetype='text/csv',
            headers={'Content-Disposition': 'attachment; filename=latency_logs.csv'}
        )
        
        return response
        
    except Exception as e:
        logger.error(f"Error exporting latency logs: {e}")
        return jsonify({'error': str(e)}), 500

@latency_bp.teardown_app_request
def shutdown_session(exception=None):
    latency_session.remove()
