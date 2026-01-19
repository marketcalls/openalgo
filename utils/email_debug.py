"""
Debug utility for SMTP email testing

This module provides detailed debugging information for SMTP connections.
Use this to troubleshoot email connection issues.
"""

import smtplib
import ssl
import logging
from database.settings_db import get_smtp_settings
from utils.logging import get_logger

logger = get_logger(__name__)

def debug_smtp_connection():
    """
    Debug SMTP connection with detailed logging.
    Returns detailed connection information for troubleshooting.
    """
    smtp_settings = get_smtp_settings()
    if not smtp_settings:
        return {
            'success': False,
            'message': 'No SMTP settings found',
            'details': []
        }
    
    details = []
    success = False
    error_message = ""
    
    try:
        smtp_server = smtp_settings['smtp_server']
        smtp_port = smtp_settings['smtp_port']
        smtp_username = smtp_settings['smtp_username']
        smtp_password = smtp_settings['smtp_password']
        use_tls = smtp_settings.get('smtp_use_tls', True)
        
        details.append(f"🔧 SMTP Server: {smtp_server}")
        details.append(f"🔧 SMTP Port: {smtp_port}")
        details.append(f"🔧 Username: {smtp_username}")
        details.append(f"🔧 Password: {'*' * min(len(smtp_password), 16)}")
        details.append(f"🔧 Use TLS: {use_tls}")
        details.append(f"🔧 HELO Hostname: {smtp_settings.get('smtp_helo_hostname') or 'default'}")
        
        # Create SSL context
        context = ssl.create_default_context()
        context.check_hostname = False
        context.verify_mode = ssl.CERT_NONE
        
        details.append("🔒 SSL Context created (hostname verification disabled)")
        
        # Choose connection method based on port
        if smtp_port == 465:
            details.append("📡 Using SMTP_SSL (port 465)")
            server = smtplib.SMTP_SSL(smtp_server, smtp_port, context=context)
        else:
            details.append(f"📡 Using SMTP with STARTTLS (port {smtp_port})")
            server = smtplib.SMTP(smtp_server, smtp_port)
            
            if use_tls:
                details.append("🔒 Starting TLS...")
                server.starttls(context=context)
                details.append("✅ TLS started successfully")
        
        details.append("🔌 Connection established")
        
        # Enable debug output
        server.set_debuglevel(1)
        
        # Test authentication
        details.append("🔐 Attempting authentication...")
        server.login(smtp_username, smtp_password)
        details.append("✅ Authentication successful")
        
        # Get server capabilities
        try:
            capabilities = server.ehlo_or_helo_if_needed()
            if hasattr(server, 'ehlo_resp'):
                details.append(f"📋 Server capabilities: {server.ehlo_resp.decode('utf-8')}")
        except Exception as e:
            details.append(f"⚠️ Could not get server capabilities: {e}")
        
        server.quit()
        details.append("✅ Connection closed successfully")
        
        success = True
        error_message = "Connection test successful"
        
    except smtplib.SMTPAuthenticationError as e:
        error_message = f"Authentication failed: {e}"
        details.append(f"❌ Authentication error: {e}")
        details.append("💡 Try using App Password for Gmail")
        
    except smtplib.SMTPServerDisconnected as e:
        error_message = f"Server disconnected: {e}"
        details.append(f"❌ Server disconnected: {e}")
        details.append("💡 Try different port (465 for SSL, 587 for STARTTLS)")
        
    except smtplib.SMTPConnectError as e:
        error_message = f"Connection failed: {e}"
        details.append(f"❌ Connection error: {e}")
        details.append("💡 Check server address and port")
        
    except ssl.SSLError as e:
        error_message = f"SSL error: {e}"
        details.append(f"❌ SSL error: {e}")
        details.append("💡 Try toggling TLS setting or different port")
        
    except Exception as e:
        error_message = f"Unexpected error: {e}"
        details.append(f"❌ Unexpected error: {e}")
    
    return {
        'success': success,
        'message': error_message,
        'details': details
    }

def test_gmail_configurations():
    """
    Test common Gmail configurations to find the working one.
    """
    smtp_settings = get_smtp_settings()
    if not smtp_settings:
        return "No SMTP settings found"
    
    configurations = [
        {
            'name': 'Gmail Workspace (SSL)',
            'server': 'smtp-relay.gmail.com',
            'port': 465,
            'ssl_mode': 'SSL'
        },
        {
            'name': 'Gmail Personal (STARTTLS)',
            'server': 'smtp.gmail.com',
            'port': 587,
            'ssl_mode': 'STARTTLS'
        },
        {
            'name': 'Gmail Personal (SSL)',
            'server': 'smtp.gmail.com',
            'port': 465,
            'ssl_mode': 'SSL'
        }
    ]
    
    results = []
    
    for config in configurations:
        results.append(f"\n🧪 Testing {config['name']}:")
        results.append(f"   Server: {config['server']}:{config['port']}")
        results.append(f"   Mode: {config['ssl_mode']}")
        
        try:
            # Create SSL context
            context = ssl.create_default_context()
            context.check_hostname = False
            context.verify_mode = ssl.CERT_NONE
            
            # Test connection
            if config['port'] == 465:
                server = smtplib.SMTP_SSL(config['server'], config['port'], context=context)
            else:
                server = smtplib.SMTP(config['server'], config['port'])
                server.starttls(context=context)
            
            # Test authentication
            server.login(smtp_settings['smtp_username'], smtp_settings['smtp_password'])
            server.quit()
            
            results.append("   ✅ SUCCESS!")
            
        except Exception as e:
            results.append(f"   ❌ Failed: {e}")
    
    return '\n'.join(results)

if __name__ == "__main__":
    # Can be run standalone for debugging
    print("🔍 SMTP Debug Information")
    print("=" * 50)
    
    result = debug_smtp_connection()
    print(f"\nResult: {result['message']}")
    print("\nDetails:")
    for detail in result['details']:
        print(f"  {detail}")
    
    if not result['success']:
        print("\n🧪 Testing different Gmail configurations:")
        print(test_gmail_configurations())