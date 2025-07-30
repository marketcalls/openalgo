#!/usr/bin/env python3
"""
Test script for SMTP email functionality

This script tests the email sending capabilities without requiring the full
Flask application to be running.

Usage:
    python test/test_email_functionality.py --email your-email@example.com
    python test/test_email_functionality.py --email your-email@example.com --setup-smtp
"""

import os
import sys
import argparse

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utils.email_utils import send_test_email, validate_smtp_settings
from database.settings_db import set_smtp_settings, get_smtp_settings, init_db

def setup_test_smtp():
    """Setup test SMTP configuration (Gmail example)"""
    print("\n📧 SMTP Configuration Setup")
    print("=" * 40)
    
    smtp_server = input("SMTP Server (e.g., smtp.gmail.com): ").strip()
    if not smtp_server:
        smtp_server = "smtp.gmail.com"
    
    smtp_port = input("SMTP Port (default: 587): ").strip()
    smtp_port = int(smtp_port) if smtp_port else 587
    
    smtp_username = input("Username/Email: ").strip()
    smtp_password = input("Password/App Password: ").strip()
    
    smtp_from_email = input(f"From Email (default: {smtp_username}): ").strip()
    if not smtp_from_email:
        smtp_from_email = smtp_username
    
    use_tls = input("Use TLS/SSL? (Y/n): ").strip().lower()
    use_tls = use_tls != 'n'
    
    print("\n💾 Saving SMTP settings...")
    
    try:
        set_smtp_settings(
            smtp_server=smtp_server,
            smtp_port=smtp_port,
            smtp_username=smtp_username,
            smtp_password=smtp_password,
            smtp_use_tls=use_tls,
            smtp_from_email=smtp_from_email
        )
        print("✅ SMTP settings saved successfully!")
        return True
    except Exception as e:
        print(f"❌ Failed to save SMTP settings: {e}")
        return False

def test_smtp_connection():
    """Test SMTP connection without sending email"""
    print("\n🔧 Testing SMTP Connection...")
    
    smtp_settings = get_smtp_settings()
    if not smtp_settings:
        print("❌ No SMTP settings found. Please configure SMTP first.")
        return False
    
    result = validate_smtp_settings(smtp_settings)
    
    if result['success']:
        print("✅ SMTP connection successful!")
        print(f"📧 Server: {smtp_settings['smtp_server']}:{smtp_settings['smtp_port']}")
        print(f"🔐 TLS: {'Enabled' if smtp_settings.get('smtp_use_tls') else 'Disabled'}")
        return True
    else:
        print(f"❌ SMTP connection failed: {result['message']}")
        return False

def send_test_email_interactive(test_email):
    """Send test email interactively"""
    print(f"\n📨 Sending test email to: {test_email}")
    
    smtp_settings = get_smtp_settings()
    if not smtp_settings:
        print("❌ No SMTP settings found. Use --setup-smtp to configure.")
        return False
    
    print("📧 SMTP Configuration:")
    print(f"   Server: {smtp_settings['smtp_server']}:{smtp_settings['smtp_port']}")
    print(f"   From: {smtp_settings['smtp_from_email']}")
    print(f"   TLS: {'Enabled' if smtp_settings.get('smtp_use_tls') else 'Disabled'}")
    print()
    
    try:
        result = send_test_email(test_email, sender_name="Test Script")
        
        if result['success']:
            print("✅ Test email sent successfully!")
            print(f"📬 Message: {result['message']}")
            print("\n💡 Next steps:")
            print("   1. Check your inbox (and spam folder)")
            print("   2. Verify the email content and formatting")
            print("   3. Your SMTP configuration is working correctly")
            return True
        else:
            print(f"❌ Failed to send test email: {result['message']}")
            print("\n🔧 Troubleshooting tips:")
            print("   1. Verify your SMTP credentials")
            print("   2. Check if 2FA is enabled (use App Password)")
            print("   3. Ensure 'Less secure app access' is enabled (Gmail)")
            print("   4. Check firewall and network connectivity")
            return False
            
    except Exception as e:
        print(f"❌ Unexpected error: {e}")
        return False

def main():
    parser = argparse.ArgumentParser(description='Test SMTP email functionality')
    parser.add_argument('--email', '-e', required=True, 
                       help='Email address to send test email to')
    parser.add_argument('--setup-smtp', action='store_true',
                       help='Setup SMTP configuration interactively')
    parser.add_argument('--test-connection', action='store_true',
                       help='Test SMTP connection without sending email')
    
    args = parser.parse_args()
    
    print("🚀 OpenAlgo Email Test Script")
    print("=" * 40)
    
    # Load environment variables from .env if it exists
    env_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), '.env')
    if os.path.exists(env_path):
        print(f"📋 Loading environment from: {env_path}")
        with open(env_path, 'r') as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith('#') and '=' in line:
                    key, value = line.split('=', 1)
                    os.environ[key] = value.strip('"\'')
    
    # Initialize database
    try:
        init_db()
        print("✅ Database initialized")
    except Exception as e:
        print(f"❌ Database initialization failed: {e}")
        return 1
    
    success = True
    
    # Setup SMTP if requested
    if args.setup_smtp:
        success = setup_test_smtp()
        if not success:
            return 1
    
    # Test connection if requested
    if args.test_connection:
        success = test_smtp_connection()
        if not success:
            return 1
    
    # Send test email
    if args.email:
        success = send_test_email_interactive(args.email)
    
    if success:
        print("\n🎉 All tests completed successfully!")
        return 0
    else:
        print("\n❌ Some tests failed. Check the output above for details.")
        return 1

if __name__ == "__main__":
    sys.exit(main())