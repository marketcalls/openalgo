# csp.py

from flask import request, current_app
import os
from functools import wraps

def get_csp_config():
    """
    Get Content Security Policy configuration from environment variables.
    Returns a dictionary with CSP directives.
    """
    csp_config = {}
    
    # Check if CSP is enabled
    csp_enabled = os.getenv('CSP_ENABLED', 'TRUE').upper() == 'TRUE'
    
    if not csp_enabled:
        return None
    
    # Default source directive
    default_src = os.getenv('CSP_DEFAULT_SRC', "'self'")
    if default_src:
        csp_config['default-src'] = default_src
    
    # Script source directive
    script_src = os.getenv('CSP_SCRIPT_SRC', "'self' https://cdn.socket.io")
    if script_src:
        csp_config['script-src'] = script_src
    
    # Style source directive
    style_src = os.getenv('CSP_STYLE_SRC', "'self' 'unsafe-inline'")
    if style_src:
        csp_config['style-src'] = style_src
    
    # Image source directive
    img_src = os.getenv('CSP_IMG_SRC', "'self' data:")
    if img_src:
        csp_config['img-src'] = img_src
    
    # Connect source directive (for WebSockets, etc.)
    connect_src = os.getenv('CSP_CONNECT_SRC', "'self' wss: ws:")
    if connect_src:
        csp_config['connect-src'] = connect_src
    
    # Font source directive
    font_src = os.getenv('CSP_FONT_SRC', "'self'")
    if font_src:
        csp_config['font-src'] = font_src
    
    # Object source directive
    object_src = os.getenv('CSP_OBJECT_SRC', "'none'")
    if object_src:
        csp_config['object-src'] = object_src
    
    # Media source directive
    media_src = os.getenv('CSP_MEDIA_SRC', "'self'")
    if media_src:
        csp_config['media-src'] = media_src
    
    # Frame source directive
    frame_src = os.getenv('CSP_FRAME_SRC', "'self'")
    if frame_src:
        csp_config['frame-src'] = frame_src
    
    # Child source directive (deprecated but included for compatibility)
    child_src = os.getenv('CSP_CHILD_SRC')
    if child_src:
        csp_config['child-src'] = child_src
    
    # Form action directive
    form_action = os.getenv('CSP_FORM_ACTION', "'self'")
    if form_action:
        csp_config['form-action'] = form_action
    
    # Base URI directive
    base_uri = os.getenv('CSP_BASE_URI', "'self'")
    if base_uri:
        csp_config['base-uri'] = base_uri
    
    # Frame ancestors directive (clickjacking protection)
    frame_ancestors = os.getenv('CSP_FRAME_ANCESTORS', "'self'")
    if frame_ancestors:
        csp_config['frame-ancestors'] = frame_ancestors
    
    # Additional custom directives
    upgrade_insecure_requests = os.getenv('CSP_UPGRADE_INSECURE_REQUESTS', 'FALSE').upper() == 'TRUE'
    if upgrade_insecure_requests:
        csp_config['upgrade-insecure-requests'] = ''
    
    # Report URI for CSP violations
    report_uri = os.getenv('CSP_REPORT_URI')
    if report_uri:
        csp_config['report-uri'] = report_uri
    
    # Report-To directive for CSP violations reporting
    report_to = os.getenv('CSP_REPORT_TO')
    if report_to:
        csp_config['report-to'] = report_to
    
    return csp_config


def build_csp_header(csp_config):
    """
    Build the Content Security Policy header value from the configuration.
    """
    if not csp_config:
        return None
    
    directives = []
    for directive, value in csp_config.items():
        if value:
            directives.append(f"{directive} {value}")
        else:
            directives.append(directive)
    
    return "; ".join(directives)


def get_security_headers():
    """
    Get additional security headers configuration from environment variables.
    """
    headers = {}
    
    # Referrer Policy
    referrer_policy = os.getenv('REFERRER_POLICY', 'strict-origin-when-cross-origin')
    if referrer_policy:
        headers['Referrer-Policy'] = referrer_policy
    
    # Permissions Policy
    permissions_policy = os.getenv('PERMISSIONS_POLICY', 'camera=(), microphone=(), geolocation=(), payment=(), usb=(), screen-wake-lock=(), web-share=()')
    if permissions_policy:
        headers['Permissions-Policy'] = permissions_policy
    
    return headers


def apply_csp_middleware(app):
    """
    Apply Content Security Policy and other security headers middleware to the Flask application.
    """
    @app.after_request
    def add_security_headers(response):
        # Add CSP header
        csp_config = get_csp_config()
        if csp_config:
            csp_header = build_csp_header(csp_config)
            if csp_header:
                # Use Content-Security-Policy-Report-Only for testing if configured
                header_type = 'Content-Security-Policy'
                if os.getenv('CSP_REPORT_ONLY', 'FALSE').upper() == 'TRUE':
                    header_type = 'Content-Security-Policy-Report-Only'
                
                response.headers[header_type] = csp_header
        
        # Add other security headers
        security_headers = get_security_headers()
        for header_name, header_value in security_headers.items():
            response.headers[header_name] = header_value
        
        return response
