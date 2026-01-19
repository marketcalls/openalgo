"""
Email Utility Functions for OpenAlgo

This module provides email sending functionality for SMTP configuration testing
and password reset notifications.
"""

import smtplib
import ssl
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime
from database.settings_db import get_smtp_settings
from utils.logging import get_logger

logger = get_logger(__name__)

class EmailSendError(Exception):
    """Custom exception for email sending errors"""
    pass

def send_test_email(recipient_email, sender_name="OpenAlgo Admin"):
    """
    Send a test email to verify SMTP configuration.
    
    Args:
        recipient_email (str): Email address to send test email to
        sender_name (str): Name of the sender
        
    Returns:
        dict: Result dictionary with success status and message
    """
    try:
        smtp_settings = get_smtp_settings()
        if not smtp_settings:
            return {
                'success': False,
                'message': 'SMTP settings not configured. Please configure SMTP settings first.'
            }
        
        # Validate required settings
        required_fields = ['smtp_server', 'smtp_port', 'smtp_username', 'smtp_password', 'smtp_from_email']
        missing_fields = [field for field in required_fields if not smtp_settings.get(field)]
        
        if missing_fields:
            return {
                'success': False,
                'message': f'Missing required SMTP settings: {", ".join(missing_fields)}'
            }
        
        # Create test email content
        subject = "OpenAlgo SMTP Configuration Test"
        
        # Create HTML email content
        html_content = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <meta charset="utf-8">
            <title>OpenAlgo SMTP Test</title>
            <style>
                body {{ font-family: Arial, sans-serif; line-height: 1.6; color: #333; }}
                .container {{ max-width: 600px; margin: 0 auto; padding: 20px; }}
                .header {{ background: #2563eb; color: white; padding: 20px; text-align: center; border-radius: 8px 8px 0 0; }}
                .content {{ background: #f8f9fa; padding: 30px; border-radius: 0 0 8px 8px; }}
                .success-badge {{ background: #10b981; color: white; padding: 8px 16px; border-radius: 20px; display: inline-block; margin: 10px 0; }}
                .info-box {{ background: white; padding: 20px; border-radius: 8px; margin: 20px 0; border-left: 4px solid #2563eb; }}
                .footer {{ text-align: center; margin-top: 30px; color: #6b7280; font-size: 14px; }}
            </style>
        </head>
        <body>
            <div class="container">
                <div class="header">
                    <h1>🎉 SMTP Configuration Test</h1>
                </div>
                <div class="content">
                    <div class="success-badge">✅ Test Successful!</div>
                    
                    <p>Congratulations! Your OpenAlgo SMTP configuration is working correctly.</p>
                    
                    <div class="info-box">
                        <h3>📋 Test Details:</h3>
                        <ul>
                            <li><strong>Test Date:</strong> {datetime.now().strftime('%Y-%m-%d %H:%M:%S UTC')}</li>
                            <li><strong>SMTP Server:</strong> {smtp_settings['smtp_server']}:{smtp_settings['smtp_port']}</li>
                            <li><strong>Security:</strong> {'TLS/SSL Enabled' if smtp_settings.get('smtp_use_tls') else 'No Encryption'}</li>
                            <li><strong>From Address:</strong> {smtp_settings['smtp_from_email']}</li>
                            <li><strong>Recipient:</strong> {recipient_email}</li>
                        </ul>
                    </div>
                    
                    <p>🔐 <strong>What this means:</strong></p>
                    <ul>
                        <li>Password reset emails will work correctly</li>
                        <li>System notifications can be sent</li>
                        <li>Your SMTP credentials are properly configured</li>
                    </ul>
                    
                    <p><strong>Next Steps:</strong></p>
                    <ul>
                        <li>You can now use the password reset functionality</li>
                        <li>Consider setting up email notifications for important events</li>
                        <li>Keep your SMTP credentials secure</li>
                    </ul>
                </div>
                <div class="footer">
                    <p>This is an automated test email from OpenAlgo.<br>
                    If you didn't request this test, please contact your system administrator.</p>
                </div>
            </div>
        </body>
        </html>
        """
        
        # Create plain text version
        text_content = f"""
OpenAlgo SMTP Configuration Test

✅ Test Successful!

Congratulations! Your OpenAlgo SMTP configuration is working correctly.

Test Details:
- Test Date: {datetime.now().strftime('%Y-%m-%d %H:%M:%S UTC')}
- SMTP Server: {smtp_settings['smtp_server']}:{smtp_settings['smtp_port']}
- Security: {'TLS/SSL Enabled' if smtp_settings.get('smtp_use_tls') else 'No Encryption'}
- From Address: {smtp_settings['smtp_from_email']}
- Recipient: {recipient_email}

What this means:
- Password reset emails will work correctly
- System notifications can be sent
- Your SMTP credentials are properly configured

Next Steps:
- You can now use the password reset functionality
- Consider setting up email notifications for important events
- Keep your SMTP credentials secure

---
This is an automated test email from OpenAlgo.
If you didn't request this test, please contact your system administrator.
        """
        
        # Send the email
        result = send_email(
            recipient_email=recipient_email,
            subject=subject,
            text_content=text_content,
            html_content=html_content,
            smtp_settings=smtp_settings
        )
        
        if result['success']:
            logger.info(f"Test email sent successfully to {recipient_email}")
            return {
                'success': True,
                'message': f'Test email sent successfully to {recipient_email}. Please check your inbox (and spam folder).'
            }
        else:
            return result
            
    except Exception as e:
        error_msg = f"Failed to send test email: {str(e)}"
        logger.error(error_msg)
        return {
            'success': False,
            'message': error_msg
        }

def send_password_reset_email(recipient_email, reset_link, user_name="User"):
    """
    Send password reset email.
    
    Args:
        recipient_email (str): Email address to send reset email to
        reset_link (str): Password reset link
        user_name (str): Name of the user
        
    Returns:
        dict: Result dictionary with success status and message
    """
    try:
        smtp_settings = get_smtp_settings()
        if not smtp_settings:
            return {
                'success': False,
                'message': 'SMTP not configured'
            }
        
        subject = "OpenAlgo Password Reset Request"
        
        html_content = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <meta charset="utf-8">
            <title>Password Reset</title>
            <style>
                body {{ font-family: Arial, sans-serif; line-height: 1.6; color: #333; }}
                .container {{ max-width: 600px; margin: 0 auto; padding: 20px; }}
                .header {{ background: #dc2626; color: white; padding: 20px; text-align: center; border-radius: 8px 8px 0 0; }}
                .content {{ background: #f8f9fa; padding: 30px; border-radius: 0 0 8px 8px; }}
                .reset-button {{ display: inline-block; background: #2563eb !important; color: #ffffff !important; padding: 12px 30px; text-decoration: none !important; border-radius: 6px; margin: 20px 0; font-weight: bold; border: none; -webkit-text-fill-color: #ffffff !important; }}
                .reset-button:hover {{ background: #1d4ed8 !important; color: #ffffff !important; -webkit-text-fill-color: #ffffff !important; }}
                .reset-button:visited {{ color: #ffffff !important; -webkit-text-fill-color: #ffffff !important; }}
                .reset-button:active {{ color: #ffffff !important; -webkit-text-fill-color: #ffffff !important; }}
                .reset-button span {{ color: #ffffff !important; -webkit-text-fill-color: #ffffff !important; }}
                .reset-button * {{ color: #ffffff !important; -webkit-text-fill-color: #ffffff !important; }}
                .warning-box {{ background: #fef3c7; border: 1px solid #f59e0b; padding: 15px; border-radius: 6px; margin: 20px 0; }}
                .footer {{ text-align: center; margin-top: 30px; color: #6b7280; font-size: 14px; }}
            </style>
        </head>
        <body>
            <div class="container">
                <div class="header">
                    <h1>🔒 Password Reset Request</h1>
                </div>
                <div class="content">
                    <p>Hello {user_name},</p>
                    
                    <p>We received a request to reset your OpenAlgo account password. If you made this request, click the button below to reset your password:</p>
                    
                    <div style="text-align: center;">
                        <a href="{reset_link}" class="reset-button" style="display: inline-block; background: #2563eb !important; color: #ffffff !important; padding: 12px 30px; text-decoration: none !important; border-radius: 6px; margin: 20px 0; font-weight: bold; border: none; mso-padding-alt: 0; text-align: center; -webkit-text-fill-color: #ffffff !important;"><!--[if mso]><i style="letter-spacing: 30px; mso-font-width: -100%; mso-text-raise: 30pt;">&nbsp;</i><![endif]--><span style="mso-text-raise: 15pt; color: #ffffff !important; -webkit-text-fill-color: #ffffff !important;">Reset My Password</span><!--[if mso]><i style="letter-spacing: 30px; mso-font-width: -100%;">&nbsp;</i><![endif]--></a>
                    </div>
                    
                    <div class="warning-box">
                        <strong>⚠️ Security Notice:</strong>
                        <ul>
                            <li>This link will expire in 1 hour</li>
                            <li>If you didn't request this reset, please ignore this email</li>
                            <li>Never share this link with anyone</li>
                        </ul>
                    </div>
                    
                    <p>If the button above doesn't work, copy and paste this link into your browser:</p>
                    <p style="word-break: break-all; background: #e5e7eb; padding: 10px; border-radius: 4px;">{reset_link}</p>
                    
                    <p>If you didn't request this password reset, you can safely ignore this email. Your password will not be changed.</p>
                </div>
                <div class="footer">
                    <p>This is an automated email from OpenAlgo.<br>
                    For security reasons, please do not reply to this email.</p>
                </div>
            </div>
        </body>
        </html>
        """
        
        text_content = f"""
OpenAlgo Password Reset Request

Hello {user_name},

We received a request to reset your OpenAlgo account password. If you made this request, use the link below to reset your password:

{reset_link}

Security Notice:
- This link will expire in 1 hour
- If you didn't request this reset, please ignore this email
- Never share this link with anyone

If you didn't request this password reset, you can safely ignore this email. Your password will not be changed.

---
This is an automated email from OpenAlgo.
For security reasons, please do not reply to this email.
        """
        
        return send_email(
            recipient_email=recipient_email,
            subject=subject,
            text_content=text_content,
            html_content=html_content,
            smtp_settings=smtp_settings
        )
        
    except Exception as e:
        error_msg = f"Failed to send password reset email: {str(e)}"
        logger.error(error_msg)
        return {
            'success': False,
            'message': error_msg
        }

def send_email(recipient_email, subject, text_content, html_content=None, smtp_settings=None):
    """
    Generic email sending function.
    
    Args:
        recipient_email (str): Recipient email address
        subject (str): Email subject
        text_content (str): Plain text content
        html_content (str, optional): HTML content
        smtp_settings (dict, optional): SMTP settings (fetched if not provided)
        
    Returns:
        dict: Result dictionary with success status and message
    """
    try:
        if not smtp_settings:
            smtp_settings = get_smtp_settings()
            if not smtp_settings:
                return {
                    'success': False,
                    'message': 'SMTP settings not configured'
                }
        
        # Create message
        message = MIMEMultipart("alternative")
        message["Subject"] = subject
        message["From"] = smtp_settings['smtp_from_email']
        message["To"] = recipient_email
        
        # Add text content
        text_part = MIMEText(text_content, "plain")
        message.attach(text_part)
        
        # Add HTML content if provided
        if html_content:
            html_part = MIMEText(html_content, "html")
            message.attach(html_part)
        
        # Determine connection method based on port and settings
        smtp_port = smtp_settings['smtp_port']
        use_tls = smtp_settings.get('smtp_use_tls', True)
        
        # Create SSL context
        context = ssl.create_default_context()
        # For Gmail relay, we might need to be less strict about certificates
        context.check_hostname = False
        context.verify_mode = ssl.CERT_NONE
        
        # Choose connection method based on port
        if smtp_port == 465:
            # Port 465 uses SSL from the start (SMTPS)
            logger.info(f"Using SMTP_SSL for port {smtp_port}")
            server = smtplib.SMTP_SSL(smtp_settings['smtp_server'], smtp_port, context=context)
        else:
            # Port 587 or others use SMTP with STARTTLS
            logger.info(f"Using SMTP with STARTTLS for port {smtp_port}")
            server = smtplib.SMTP(smtp_settings['smtp_server'], smtp_port)
            
            # Enable TLS if configured
            if use_tls:
                server.starttls(context=context)
        
        # Enable debug output for troubleshooting (uncomment if needed)
        # server.set_debuglevel(1)
        
        # Set HELO hostname if specified
        if smtp_settings.get('smtp_helo_hostname'):
            logger.info(f"Setting HELO hostname: {smtp_settings['smtp_helo_hostname']}")
            try:
                server.ehlo(smtp_settings['smtp_helo_hostname'])
            except Exception as e:
                logger.warning(f"EHLO with custom hostname failed, trying HELO: {e}")
                try:
                    server.helo(smtp_settings['smtp_helo_hostname'])
                except Exception as e2:
                    logger.warning(f"HELO with custom hostname failed: {e2}")
        
        # Login and send email
        server.login(smtp_settings['smtp_username'], smtp_settings['smtp_password'])
        server.sendmail(smtp_settings['smtp_from_email'], recipient_email, message.as_string())
        server.quit()
        
        logger.info(f"Email sent successfully to {recipient_email}")
        return {
            'success': True,
            'message': 'Email sent successfully'
        }
        
    except smtplib.SMTPAuthenticationError as e:
        error_msg = "SMTP Authentication failed. Please check your username and password."
        logger.error(f"SMTP Auth Error: {e}")
        return {
            'success': False,
            'message': error_msg
        }
    except smtplib.SMTPServerDisconnected as e:
        error_msg = "SMTP Server disconnected. Please check your server settings."
        logger.error(f"SMTP Disconnected: {e}")
        return {
            'success': False,
            'message': error_msg
        }
    except smtplib.SMTPException as e:
        error_str = str(e)
        logger.error(f"SMTP Exception: {e}")
        
        # Provide specific guidance for common Gmail errors
        if "Mail relay denied" in error_str and "smtp-relay.gmail.com" in smtp_settings.get('smtp_server', ''):
            error_msg = """Gmail Workspace relay denied. Solutions:
            1. Register your server IP (49.207.195.248) in Google Admin Console → Apps → Gmail → SMTP relay
            2. Or switch to personal Gmail: smtp.gmail.com:587 with App Password
            3. See: https://support.google.com/a/answer/6140680"""
        elif "Authentication failed" in error_str:
            error_msg = "SMTP Authentication failed. For Gmail, use App Password instead of regular password."
        else:
            error_msg = f"SMTP Error: {error_str}"
        
        return {
            'success': False,
            'message': error_msg
        }
    except Exception as e:
        error_msg = f"Failed to send email: {str(e)}"
        logger.error(f"Email sending failed: {e}")
        return {
            'success': False,
            'message': error_msg
        }

def validate_smtp_settings(smtp_settings):
    """
    Validate SMTP settings without sending an email.
    
    Args:
        smtp_settings (dict): SMTP configuration
        
    Returns:
        dict: Validation result
    """
    try:
        required_fields = ['smtp_server', 'smtp_port', 'smtp_username', 'smtp_password', 'smtp_from_email']
        missing_fields = [field for field in required_fields if not smtp_settings.get(field)]
        
        if missing_fields:
            return {
                'success': False,
                'message': f'Missing required fields: {", ".join(missing_fields)}'
            }
        
        # Test connection without sending email
        smtp_port = smtp_settings['smtp_port']
        use_tls = smtp_settings.get('smtp_use_tls', True)
        
        # Create SSL context
        context = ssl.create_default_context()
        context.check_hostname = False
        context.verify_mode = ssl.CERT_NONE
        
        # Choose connection method based on port
        if smtp_port == 465:
            # Port 465 uses SSL from the start (SMTPS)
            server = smtplib.SMTP_SSL(smtp_settings['smtp_server'], smtp_port, context=context)
        else:
            # Port 587 or others use SMTP with STARTTLS
            server = smtplib.SMTP(smtp_settings['smtp_server'], smtp_port)
            
            # Enable TLS if configured
            if use_tls:
                server.starttls(context=context)
        
        # Set HELO hostname if specified
        if smtp_settings.get('smtp_helo_hostname'):
            try:
                server.ehlo(smtp_settings['smtp_helo_hostname'])
            except Exception as e:
                try:
                    server.helo(smtp_settings['smtp_helo_hostname'])
                except Exception:
                    pass  # Continue without custom HELO
        
        server.login(smtp_settings['smtp_username'], smtp_settings['smtp_password'])
        server.quit()
        
        return {
            'success': True,
            'message': 'SMTP connection successful'
        }
        
    except Exception as e:
        return {
            'success': False,
            'message': f'SMTP validation failed: {str(e)}'
        }