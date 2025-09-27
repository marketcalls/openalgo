from flask import Blueprint, jsonify, render_template, request, flash, redirect, url_for
from database.traffic_db import IPBan, Error404Tracker, InvalidAPIKeyTracker, logs_session
from database.settings_db import get_security_settings, set_security_settings
from utils.session import check_session_validity
from limiter import limiter
import logging
from datetime import datetime

logger = logging.getLogger(__name__)

security_bp = Blueprint('security_bp', __name__, url_prefix='/security')

@security_bp.route('/', methods=['GET'])
@check_session_validity
@limiter.limit("60/minute")
def security_dashboard():
    """Display security dashboard with banned IPs and 404 tracking"""
    try:
        # Get security settings
        security_settings = get_security_settings()

        # Get all banned IPs
        banned_ips = IPBan.get_all_bans()

        # Get suspicious IPs (1+ 404 errors to show all tracking)
        suspicious_ips = Error404Tracker.get_suspicious_ips(min_errors=1)

        # Get suspicious API users (1+ invalid API key attempts to show all)
        suspicious_api_users = InvalidAPIKeyTracker.get_suspicious_api_users(min_attempts=1)

        # Format data for display
        banned_data = [{
            'ip_address': ban.ip_address,
            'ban_reason': ban.ban_reason,
            'banned_at': ban.banned_at.strftime('%d-%m-%Y %I:%M:%S %p') if ban.banned_at else 'Unknown',
            'expires_at': ban.expires_at.strftime('%d-%m-%Y %I:%M:%S %p') if ban.expires_at else 'Permanent',
            'is_permanent': ban.is_permanent,
            'ban_count': ban.ban_count,
            'created_by': ban.created_by
        } for ban in banned_ips]

        suspicious_data = [{
            'ip_address': tracker.ip_address,
            'error_count': tracker.error_count,
            'first_error_at': tracker.first_error_at.strftime('%d-%m-%Y %I:%M:%S %p') if tracker.first_error_at else 'Unknown',
            'last_error_at': tracker.last_error_at.strftime('%d-%m-%Y %I:%M:%S %p') if tracker.last_error_at else 'Unknown',
            'paths_attempted': tracker.paths_attempted
        } for tracker in suspicious_ips]

        api_abuse_data = [{
            'ip_address': tracker.ip_address,
            'attempt_count': tracker.attempt_count,
            'first_attempt_at': tracker.first_attempt_at.strftime('%d-%m-%Y %I:%M:%S %p') if tracker.first_attempt_at else 'Unknown',
            'last_attempt_at': tracker.last_attempt_at.strftime('%d-%m-%Y %I:%M:%S %p') if tracker.last_attempt_at else 'Unknown',
            'api_keys_tried': tracker.api_keys_tried
        } for tracker in suspicious_api_users]

        return render_template('security/dashboard.html',
                             banned_ips=banned_data,
                             suspicious_ips=suspicious_data,
                             api_abuse_ips=api_abuse_data,
                             security_settings=security_settings)
    except Exception as e:
        logger.error(f"Error loading security dashboard: {e}")
        return render_template('security/dashboard.html',
                             banned_ips=[],
                             suspicious_ips=[],
                             api_abuse_ips=[],
                             security_settings=get_security_settings())

@security_bp.route('/ban', methods=['POST'])
@check_session_validity
@limiter.limit("30/minute")
def ban_ip():
    """Manually ban an IP address"""
    try:
        data = request.get_json()
        ip_address = data.get('ip_address', '').strip()
        reason = data.get('reason', 'Manual ban').strip()
        duration_hours = int(data.get('duration_hours', 24))
        permanent = data.get('permanent', False)

        if not ip_address:
            return jsonify({'error': 'IP address is required'}), 400

        # Prevent banning localhost
        if ip_address in ['127.0.0.1', '::1', 'localhost']:
            return jsonify({'error': 'Cannot ban localhost'}), 400

        success = IPBan.ban_ip(
            ip_address=ip_address,
            reason=reason,
            duration_hours=duration_hours,
            permanent=permanent,
            created_by='manual'
        )

        if success:
            logger.info(f"Manual IP ban: {ip_address} - {reason}")
            return jsonify({'success': True, 'message': f'IP {ip_address} has been banned'})
        else:
            return jsonify({'error': 'Failed to ban IP'}), 500

    except Exception as e:
        logger.error(f"Error banning IP: {e}")
        return jsonify({'error': str(e)}), 500

@security_bp.route('/unban', methods=['POST'])
@check_session_validity
@limiter.limit("30/minute")
def unban_ip():
    """Unban an IP address"""
    try:
        data = request.get_json()
        ip_address = data.get('ip_address', '').strip()

        if not ip_address:
            return jsonify({'error': 'IP address is required'}), 400

        success = IPBan.unban_ip(ip_address)

        if success:
            logger.info(f"IP unbanned: {ip_address}")
            return jsonify({'success': True, 'message': f'IP {ip_address} has been unbanned'})
        else:
            return jsonify({'error': 'IP not found in ban list'}), 404

    except Exception as e:
        logger.error(f"Error unbanning IP: {e}")
        return jsonify({'error': str(e)}), 500

@security_bp.route('/ban-host', methods=['POST'])
@check_session_validity
@limiter.limit("30/minute")
def ban_host():
    """Ban by host/domain"""
    try:
        data = request.get_json()
        host = data.get('host', '').strip()
        reason = data.get('reason', f'Host ban: {host}').strip()
        permanent = data.get('permanent', False)

        if not host:
            return jsonify({'error': 'Host is required'}), 400

        # Check if this looks like an IP address
        import re
        ip_pattern = re.compile(r'^(\d{1,3}\.){3}\d{1,3}$')

        if ip_pattern.match(host):
            # It's an IP address, ban it directly
            success = IPBan.ban_ip(
                ip_address=host,
                reason=f"Manual ban: {reason}",
                duration_hours=24 if not permanent else None,
                permanent=permanent,
                created_by='manual'
            )
            if success:
                return jsonify({
                    'success': True,
                    'message': f'Banned IP: {host}'
                })
            else:
                return jsonify({'error': f'Failed to ban IP: {host}'}), 500

        # Get IPs from recent traffic logs that match this host
        from database.traffic_db import TrafficLog
        matching_logs = TrafficLog.query.filter(
            TrafficLog.host.like(f'%{host}%')
        ).distinct(TrafficLog.client_ip).all()

        if not matching_logs:
            # No traffic found, but we can still note this for future reference
            logger.warning(f"Attempted to ban host {host} but no traffic found from it")
            return jsonify({
                'error': f'No traffic found from host: {host}. To ban specific IPs, use the IP ban form instead.',
                'suggestion': 'Use the Manual IP Ban form above to ban specific IP addresses directly.'
            }), 404

        banned_count = 0
        for log in matching_logs:
            if log.client_ip and log.client_ip not in ['127.0.0.1', '::1']:
                success = IPBan.ban_ip(
                    ip_address=log.client_ip,
                    reason=f"Host ban: {host} - {reason}",
                    duration_hours=24 if not permanent else None,
                    permanent=permanent,
                    created_by='host_ban'
                )
                if success:
                    banned_count += 1

        logger.info(f"Host ban completed: {host} - {banned_count} IPs banned")
        return jsonify({
            'success': True,
            'message': f'Banned {banned_count} IPs associated with host: {host}'
        })

    except Exception as e:
        logger.error(f"Error banning host: {e}")
        return jsonify({'error': str(e)}), 500

@security_bp.route('/clear-404', methods=['POST'])
@check_session_validity
@limiter.limit("10/minute")
def clear_404_tracker():
    """Clear 404 tracker for a specific IP"""
    try:
        data = request.get_json()
        ip_address = data.get('ip_address', '').strip()

        if not ip_address:
            return jsonify({'error': 'IP address is required'}), 400

        tracker = Error404Tracker.query.filter_by(ip_address=ip_address).first()
        if tracker:
            logs_session.delete(tracker)
            logs_session.commit()
            logger.info(f"Cleared 404 tracker for IP: {ip_address}")
            return jsonify({'success': True, 'message': f'404 tracker cleared for {ip_address}'})
        else:
            return jsonify({'error': 'No tracker found for this IP'}), 404

    except Exception as e:
        logger.error(f"Error clearing 404 tracker: {e}")
        logs_session.rollback()
        return jsonify({'error': str(e)}), 500

@security_bp.route('/stats', methods=['GET'])
@check_session_validity
@limiter.limit("60/minute")
def security_stats():
    """Get security statistics"""
    try:
        # Count banned IPs
        total_bans = IPBan.query.count()
        permanent_bans = IPBan.query.filter_by(is_permanent=True).count()
        temp_bans = total_bans - permanent_bans

        # Count suspicious IPs
        suspicious_count = Error404Tracker.query.filter(
            Error404Tracker.error_count >= 5
        ).count()

        # Count IPs near threshold (15-19 404s)
        near_threshold = Error404Tracker.query.filter(
            Error404Tracker.error_count >= 15,
            Error404Tracker.error_count < 20
        ).count()

        return jsonify({
            'total_bans': total_bans,
            'permanent_bans': permanent_bans,
            'temporary_bans': temp_bans,
            'suspicious_ips': suspicious_count,
            'near_threshold': near_threshold
        })

    except Exception as e:
        logger.error(f"Error getting security stats: {e}")
        return jsonify({'error': str(e)}), 500

@security_bp.route('/settings', methods=['POST'])
@check_session_validity
@limiter.limit("10/minute")
def update_security_settings():
    """Update security threshold settings"""
    try:
        data = request.get_json()

        # Validate input ranges
        threshold_404 = int(data.get('threshold_404', 20))
        ban_duration_404 = int(data.get('ban_duration_404', 24))
        threshold_api = int(data.get('threshold_api', 10))
        ban_duration_api = int(data.get('ban_duration_api', 48))
        repeat_offender_limit = int(data.get('repeat_offender_limit', 3))

        # Validate reasonable ranges
        if threshold_404 < 1 or threshold_404 > 1000:
            return jsonify({'error': '404 threshold must be between 1 and 1000'}), 400
        if ban_duration_404 < 1 or ban_duration_404 > 8760:  # Max 1 year
            return jsonify({'error': 'Ban duration must be between 1 hour and 1 year'}), 400
        if threshold_api < 1 or threshold_api > 100:
            return jsonify({'error': 'API threshold must be between 1 and 100'}), 400
        if ban_duration_api < 1 or ban_duration_api > 8760:
            return jsonify({'error': 'Ban duration must be between 1 hour and 1 year'}), 400
        if repeat_offender_limit < 1 or repeat_offender_limit > 10:
            return jsonify({'error': 'Repeat offender limit must be between 1 and 10'}), 400

        # Update settings
        set_security_settings(
            threshold_404=threshold_404,
            ban_duration_404=ban_duration_404,
            threshold_api=threshold_api,
            ban_duration_api=ban_duration_api,
            repeat_offender_limit=repeat_offender_limit
        )

        logger.info(f"Security settings updated: 404={threshold_404}/{ban_duration_404}h, API={threshold_api}/{ban_duration_api}h, Repeat={repeat_offender_limit}")

        return jsonify({
            'success': True,
            'message': 'Security settings updated successfully',
            'settings': {
                '404_threshold': threshold_404,
                '404_ban_duration': ban_duration_404,
                'api_threshold': threshold_api,
                'api_ban_duration': ban_duration_api,
                'repeat_offender_limit': repeat_offender_limit
            }
        })

    except ValueError as e:
        logger.error(f"Invalid value in security settings: {e}")
        return jsonify({'error': 'Invalid numeric value provided'}), 400
    except Exception as e:
        logger.error(f"Error updating security settings: {e}")
        return jsonify({'error': str(e)}), 500

@security_bp.teardown_app_request
def shutdown_session(exception=None):
    logs_session.remove()