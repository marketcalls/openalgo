"""What a trader is told when Google's SMTP relay refuses a message.

The message once told every install to allow one fixed IP address in the Google
Admin console. That was one machine's address: on any other server, following
the advice could not fix the relay. The relay checks the sending server's own
public address, so the message has to name that and no number at all.
"""

import re
import smtplib

from utils import email_utils

IP_ADDRESS = re.compile(r"\b\d{1,3}(?:\.\d{1,3}){3}\b")


class RelayRefuses:
    """An SMTP connection whose relay refuses the recipient, as Google's does."""

    def __init__(self, *args, **kwargs):
        pass

    def ehlo(self, *args):
        pass

    def login(self, *args):
        pass

    def sendmail(self, *args):
        raise smtplib.SMTPRecipientsRefused({"to@example.com": (550, b"5.7.0 Mail relay denied")})

    def close(self):
        pass


def test_a_refused_gmail_relay_points_at_this_server_not_a_fixed_address(monkeypatch):
    monkeypatch.setattr(email_utils.smtplib, "SMTP", RelayRefuses)
    settings = {
        "smtp_server": "smtp-relay.gmail.com",
        "smtp_port": 587,
        "smtp_username": "trader@example.com",
        "smtp_password": "app-password",
        "smtp_from_email": "trader@example.com",
        "smtp_use_tls": False,
    }

    result = email_utils.send_email("to@example.com", "subject", "body", smtp_settings=settings)

    assert result["success"] is False
    assert not IP_ADDRESS.search(result["message"]), result["message"]
    assert result["message"] == email_utils.GMAIL_RELAY_DENIED_MESSAGE
