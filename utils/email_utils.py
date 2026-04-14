"""
Email Utility Functions for OpenAlgo

This module provides email sending functionality for SMTP configuration testing
and password reset notifications.
"""

import smtplib
import ssl
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

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
                "success": False,
                "message": "SMTP settings not configured. Please configure SMTP settings first.",
            }

        # Validate required settings
        required_fields = [
            "smtp_server",
            "smtp_port",
            "smtp_username",
            "smtp_password",
            "smtp_from_email",
        ]
        missing_fields = [field for field in required_fields if not smtp_settings.get(field)]

        if missing_fields:
            return {
                "success": False,
                "message": f"Missing required SMTP settings: {', '.join(missing_fields)}",
            }

        # Create test email content
        subject = "OpenAlgo - SMTP Test Successful"

        # Create modern minimalistic HTML email
        html_content = f"""
<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>SMTP Test</title>
</head>
<body style="margin: 0; padding: 0; background-color: #0a0a0a; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif;">
    <table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="min-height: 100vh;">
        <tr>
            <td align="center" style="padding: 40px 20px;">
                <table role="presentation" width="100%" style="max-width: 480px; background-color: #141414; border-radius: 16px; overflow: hidden; border: 1px solid #262626;">
                    <!-- Header -->
                    <tr>
                        <td style="padding: 40px 40px 30px 40px; text-align: center;">
                            <div style="width: 56px; height: 56px; background: linear-gradient(135deg, #22c55e 0%, #16a34a 100%); border-radius: 14px; margin: 0 auto 24px auto;">
                                <table role="presentation" width="100%" height="100%">
                                    <tr>
                                        <td align="center" valign="middle" style="font-size: 28px; color: #1a1a1a;">&#10003;</td>
                                    </tr>
                                </table>
                            </div>
                            <h1 style="margin: 0; font-size: 24px; font-weight: 600; color: #fafafa; letter-spacing: -0.5px;">Connection Verified</h1>
                            <p style="margin: 12px 0 0 0; font-size: 15px; color: #a1a1aa;">Your SMTP configuration is working</p>
                        </td>
                    </tr>

                    <!-- Details Card -->
                    <tr>
                        <td style="padding: 0 40px 30px 40px;">
                            <table role="presentation" width="100%" style="background-color: #1c1c1c; border-radius: 12px; border: 1px solid #262626;">
                                <tr>
                                    <td style="padding: 20px;">
                                        <table role="presentation" width="100%">
                                            <tr>
                                                <td style="padding: 8px 0; border-bottom: 1px solid #262626;">
                                                    <span style="font-size: 13px; color: #71717a;">Server</span><br>
                                                    <span style="font-size: 14px; color: #e4e4e7; font-weight: 500;">{smtp_settings["smtp_server"]}:{smtp_settings["smtp_port"]}</span>
                                                </td>
                                            </tr>
                                            <tr>
                                                <td style="padding: 8px 0; border-bottom: 1px solid #262626;">
                                                    <span style="font-size: 13px; color: #71717a;">Security</span><br>
                                                    <span style="font-size: 14px; color: #22c55e; font-weight: 500;">{"TLS/SSL Enabled" if smtp_settings.get("smtp_use_tls") else "No Encryption"}</span>
                                                </td>
                                            </tr>
                                            <tr>
                                                <td style="padding: 8px 0;">
                                                    <span style="font-size: 13px; color: #71717a;">Sent to</span><br>
                                                    <span style="font-size: 14px; color: #e4e4e7; font-weight: 500;">{recipient_email}</span>
                                                </td>
                                            </tr>
                                        </table>
                                    </td>
                                </tr>
                            </table>
                        </td>
                    </tr>

                    <!-- Footer -->
                    <tr>
                        <td style="padding: 0 40px 40px 40px; text-align: center;">
                            <p style="margin: 0; font-size: 13px; color: #52525b;">
                                {datetime.now().strftime("%B %d, %Y at %H:%M UTC")}
                            </p>
                            <p style="margin: 16px 0 0 0; font-size: 12px; color: #3f3f46;">
                                Sent by <span style="color: #a1a1aa;">OpenAlgo</span>
                            </p>
                        </td>
                    </tr>
                </table>
            </td>
        </tr>
    </table>
</body>
</html>
        """

        # Create plain text version
        text_content = f"""
SMTP Configuration Test - Success

Your OpenAlgo SMTP configuration is working correctly.

Server: {smtp_settings["smtp_server"]}:{smtp_settings["smtp_port"]}
Security: {"TLS/SSL Enabled" if smtp_settings.get("smtp_use_tls") else "No Encryption"}
Sent to: {recipient_email}

Date: {datetime.now().strftime("%B %d, %Y at %H:%M UTC")}

--
Sent by OpenAlgo
        """

        # Send the email
        result = send_email(
            recipient_email=recipient_email,
            subject=subject,
            text_content=text_content,
            html_content=html_content,
            smtp_settings=smtp_settings,
        )

        if result["success"]:
            logger.info(f"Test email sent successfully to {recipient_email}")
            return {
                "success": True,
                "message": f"Test email sent successfully to {recipient_email}. Please check your inbox (and spam folder).",
            }
        else:
            return result

    except Exception as e:
        error_msg = f"Failed to send test email: {str(e)}"
        logger.exception(error_msg)
        return {"success": False, "message": error_msg}


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
            return {"success": False, "message": "SMTP not configured"}

        subject = "Reset your OpenAlgo password"

        html_content = f"""
<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Password Reset</title>
</head>
<body style="margin: 0; padding: 0; background-color: #0a0a0a; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif;">
    <table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="min-height: 100vh;">
        <tr>
            <td align="center" style="padding: 40px 20px;">
                <table role="presentation" width="100%" style="max-width: 480px; background-color: #141414; border-radius: 16px; overflow: hidden; border: 1px solid #262626;">
                    <!-- Header -->
                    <tr>
                        <td style="padding: 40px 40px 24px 40px; text-align: center;">
                            <div style="width: 56px; height: 56px; background: linear-gradient(135deg, #3b82f6 0%, #1d4ed8 100%); border-radius: 14px; margin: 0 auto 24px auto;">
                                <table role="presentation" width="100%" height="100%">
                                    <tr>
                                        <td align="center" valign="middle" style="font-size: 24px; color: #ffffff;">&#128274;</td>
                                    </tr>
                                </table>
                            </div>
                            <h1 style="margin: 0; font-size: 24px; font-weight: 600; color: #fafafa; letter-spacing: -0.5px;">Reset your password</h1>
                            <p style="margin: 12px 0 0 0; font-size: 15px; color: #a1a1aa; line-height: 1.5;">Hi {user_name}, we received a request to reset your password.</p>
                        </td>
                    </tr>

                    <!-- Button -->
                    <tr>
                        <td style="padding: 8px 40px 32px 40px; text-align: center;">
                            <a href="{reset_link}" style="display: inline-block; background: linear-gradient(135deg, #3b82f6 0%, #2563eb 100%); color: #ffffff; padding: 14px 32px; text-decoration: none; border-radius: 10px; font-size: 15px; font-weight: 600; letter-spacing: 0.3px;">Reset Password</a>
                        </td>
                    </tr>

                    <!-- Divider -->
                    <tr>
                        <td style="padding: 0 40px;">
                            <div style="height: 1px; background-color: #262626;"></div>
                        </td>
                    </tr>

                    <!-- Security Notice -->
                    <tr>
                        <td style="padding: 24px 40px;">
                            <table role="presentation" width="100%">
                                <tr>
                                    <td style="padding-bottom: 12px;">
                                        <span style="font-size: 13px; color: #71717a; display: flex; align-items: center;">
                                            <span style="margin-right: 8px;">&#9201;</span> Link expires in 1 hour
                                        </span>
                                    </td>
                                </tr>
                                <tr>
                                    <td>
                                        <span style="font-size: 13px; color: #71717a; display: flex; align-items: center;">
                                            <span style="margin-right: 8px;">&#128274;</span> Never share this link
                                        </span>
                                    </td>
                                </tr>
                            </table>
                        </td>
                    </tr>

                    <!-- Link fallback -->
                    <tr>
                        <td style="padding: 0 40px 24px 40px;">
                            <p style="margin: 0 0 8px 0; font-size: 12px; color: #52525b;">If the button doesn't work, copy this link:</p>
                            <p style="margin: 0; font-size: 12px; color: #3b82f6; word-break: break-all; background-color: #1c1c1c; padding: 12px; border-radius: 8px; border: 1px solid #262626;">{reset_link}</p>
                        </td>
                    </tr>

                    <!-- Footer -->
                    <tr>
                        <td style="padding: 16px 40px 32px 40px; text-align: center;">
                            <p style="margin: 0; font-size: 12px; color: #3f3f46;">
                                Didn't request this? You can safely ignore this email.
                            </p>
                            <p style="margin: 16px 0 0 0; font-size: 12px; color: #3f3f46;">
                                Sent by <span style="color: #a1a1aa;">OpenAlgo</span>
                            </p>
                        </td>
                    </tr>
                </table>
            </td>
        </tr>
    </table>
</body>
</html>
        """

        text_content = f"""
Reset your password

Hi {user_name},

We received a request to reset your OpenAlgo password. Click the link below to set a new password:

{reset_link}

This link expires in 1 hour. Never share this link with anyone.

If you didn't request this, you can safely ignore this email.

--
Sent by OpenAlgo
        """

        return send_email(
            recipient_email=recipient_email,
            subject=subject,
            text_content=text_content,
            html_content=html_content,
            smtp_settings=smtp_settings,
        )

    except Exception as e:
        error_msg = f"Failed to send password reset email: {str(e)}"
        logger.exception(error_msg)
        return {"success": False, "message": error_msg}


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
                return {"success": False, "message": "SMTP settings not configured"}

        # Create message
        message = MIMEMultipart("alternative")
        message["Subject"] = subject
        message["From"] = smtp_settings["smtp_from_email"]
        message["To"] = recipient_email

        # Add text content
        text_part = MIMEText(text_content, "plain")
        message.attach(text_part)

        # Add HTML content if provided
        if html_content:
            html_part = MIMEText(html_content, "html")
            message.attach(html_part)

        # Determine connection method based on port and settings
        smtp_port = smtp_settings["smtp_port"]
        use_tls = smtp_settings.get("smtp_use_tls", True)

        # Create SSL context
        context = ssl.create_default_context()
        # For Gmail relay, we might need to be less strict about certificates
        context.check_hostname = False
        context.verify_mode = ssl.CERT_NONE

        # Choose connection method based on port
        if smtp_port == 465:
            # Port 465 uses SSL from the start (SMTPS)
            logger.info(f"Using SMTP_SSL for port {smtp_port}")
            server = smtplib.SMTP_SSL(smtp_settings["smtp_server"], smtp_port, context=context)
            # Send EHLO after SSL connection
            helo_hostname = smtp_settings.get("smtp_helo_hostname") or smtp_settings["smtp_server"]
            server.ehlo(helo_hostname)
        else:
            # Port 587 or others use SMTP with STARTTLS
            logger.info(f"Using SMTP with STARTTLS for port {smtp_port}")
            server = smtplib.SMTP(smtp_settings["smtp_server"], smtp_port)

            # Send initial EHLO
            helo_hostname = smtp_settings.get("smtp_helo_hostname") or smtp_settings["smtp_server"]
            server.ehlo(helo_hostname)

            # Enable TLS if configured
            if use_tls:
                server.starttls(context=context)
                # MUST send EHLO again after STARTTLS
                server.ehlo(helo_hostname)

        # Enable debug output for troubleshooting (uncomment if needed)
        # server.set_debuglevel(1)

        # Login and send email
        server.login(smtp_settings["smtp_username"], smtp_settings["smtp_password"])
        server.sendmail(smtp_settings["smtp_from_email"], recipient_email, message.as_string())
        server.quit()

        logger.info(f"Email sent successfully to {recipient_email}")
        return {"success": True, "message": "Email sent successfully"}

    except smtplib.SMTPAuthenticationError as e:
        error_msg = "SMTP Authentication failed. Please check your username and password."
        logger.error(f"SMTP Auth Error: {e}")
        return {"success": False, "message": error_msg}
    except smtplib.SMTPServerDisconnected as e:
        error_msg = "SMTP Server disconnected. Please check your server settings."
        logger.error(f"SMTP Disconnected: {e}")
        return {"success": False, "message": error_msg}
    except smtplib.SMTPException as e:
        error_str = str(e)
        logger.error(f"SMTP Exception: {e}")

        # Provide specific guidance for common Gmail errors
        if "Mail relay denied" in error_str and "smtp-relay.gmail.com" in smtp_settings.get(
            "smtp_server", ""
        ):
            error_msg = """Gmail Workspace relay denied. Solutions:
            1. Register your server IP (49.207.195.248) in Google Admin Console → Apps → Gmail → SMTP relay
            2. Or switch to personal Gmail: smtp.gmail.com:587 with App Password
            3. See: https://support.google.com/a/answer/6140680"""
        elif "Authentication failed" in error_str:
            error_msg = "SMTP Authentication failed. For Gmail, use App Password instead of regular password."
        else:
            error_msg = f"SMTP Error: {error_str}"

        return {"success": False, "message": error_msg}
    except Exception as e:
        error_msg = f"Failed to send email: {str(e)}"
        logger.exception(f"Email sending failed: {e}")
        return {"success": False, "message": error_msg}


def validate_smtp_settings(smtp_settings):
    """
    Validate SMTP settings without sending an email.

    Args:
        smtp_settings (dict): SMTP configuration

    Returns:
        dict: Validation result
    """
    try:
        required_fields = [
            "smtp_server",
            "smtp_port",
            "smtp_username",
            "smtp_password",
            "smtp_from_email",
        ]
        missing_fields = [field for field in required_fields if not smtp_settings.get(field)]

        if missing_fields:
            return {
                "success": False,
                "message": f"Missing required fields: {', '.join(missing_fields)}",
            }

        # Test connection without sending email
        smtp_port = smtp_settings["smtp_port"]
        use_tls = smtp_settings.get("smtp_use_tls", True)

        # Create SSL context
        context = ssl.create_default_context()
        context.check_hostname = False
        context.verify_mode = ssl.CERT_NONE

        # Choose connection method based on port
        if smtp_port == 465:
            # Port 465 uses SSL from the start (SMTPS)
            server = smtplib.SMTP_SSL(smtp_settings["smtp_server"], smtp_port, context=context)
            # Send EHLO after SSL connection
            helo_hostname = smtp_settings.get("smtp_helo_hostname") or smtp_settings["smtp_server"]
            server.ehlo(helo_hostname)
        else:
            # Port 587 or others use SMTP with STARTTLS
            server = smtplib.SMTP(smtp_settings["smtp_server"], smtp_port)

            # Send initial EHLO
            helo_hostname = smtp_settings.get("smtp_helo_hostname") or smtp_settings["smtp_server"]
            server.ehlo(helo_hostname)

            # Enable TLS if configured
            if use_tls:
                server.starttls(context=context)
                # MUST send EHLO again after STARTTLS
                server.ehlo(helo_hostname)

        server.login(smtp_settings["smtp_username"], smtp_settings["smtp_password"])
        server.quit()

        return {"success": True, "message": "SMTP connection successful"}

    except Exception as e:
        return {"success": False, "message": f"SMTP validation failed: {str(e)}"}
