"""The SMTP client verifies the mail server's certificate before it logs in.

Verification was switched off in every SMTP path (``check_hostname = False``,
``verify_mode = CERT_NONE``). Anyone on the network path between OpenAlgo and
the mail server could then present a certificate of their own, complete the
TLS handshake, and receive the SMTP username and password, and every email sent
afterwards, password reset links included.

Each test runs a mail server on 127.0.0.1 and checks what it received. The
forged cases must leave it with nothing; the trusted case must log in, which is
what proves the forged cases fail on the certificate and not on something else.
"""

from __future__ import annotations

import base64
import datetime
import smtplib
import socket
import ssl
import threading

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID

from utils import email_debug, email_utils

USERNAME = "trader@example.com"
PASSWORD = "app-password-1234"


def _certificate(tmp_path, name: str):
    """A self-signed certificate naming ``localhost`` only; returns (cert, key, pem)."""
    key = ec.generate_private_key(ec.SECP256R1())
    subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, name)])
    now = datetime.datetime.now(datetime.UTC)
    cert = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(subject)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - datetime.timedelta(minutes=5))
        .not_valid_after(now + datetime.timedelta(days=1))
        .add_extension(x509.SubjectAlternativeName([x509.DNSName(name)]), critical=False)
        .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
        .sign(key, hashes.SHA256())
    )
    pem = cert.public_bytes(serialization.Encoding.PEM)
    cert_file, key_file = tmp_path / "cert.pem", tmp_path / "key.pem"
    cert_file.write_bytes(pem)
    key_file.write_bytes(
        key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
    )
    return str(cert_file), str(key_file), pem.decode()


class MailServer:
    """One-connection SMTP server, STARTTLS or implicit TLS, recording AUTH."""

    def __init__(self, cert_file: str, key_file: str, implicit: bool):
        self.tls = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        self.tls.load_cert_chain(cert_file, key_file)
        self.implicit = implicit
        self.credentials: tuple[str, str] | None = None
        self.listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.listener.bind(("127.0.0.1", 0))
        self.listener.listen(1)
        self.listener.settimeout(10)
        self.port = self.listener.getsockname()[1]
        self.thread = threading.Thread(target=self._serve, daemon=True)
        self.thread.start()

    def _serve(self) -> None:
        try:
            conn, _ = self.listener.accept()
        except OSError:
            return
        conn.settimeout(10)
        try:
            secure = False
            if self.implicit:
                conn = self.tls.wrap_socket(conn, server_side=True)
                secure = True
            stream = conn.makefile("rwb")

            def say(line: str) -> None:
                stream.write(line.encode() + b"\r\n")
                stream.flush()

            say("220 mail.test ESMTP")
            while True:
                line = stream.readline().decode().strip()
                if not line:
                    return
                verb = line.split(" ", 1)[0].upper()
                if verb in ("EHLO", "HELO"):
                    say("250-mail.test")
                    say("250 AUTH PLAIN" if secure else "250 STARTTLS")
                elif verb == "STARTTLS":
                    say("220 Ready to start TLS")
                    conn = self.tls.wrap_socket(conn, server_side=True)
                    secure = True
                    stream = conn.makefile("rwb")
                elif verb == "AUTH":
                    _, user, password = base64.b64decode(line.split()[2]).split(b"\x00")
                    self.credentials = (user.decode(), password.decode())
                    say("235 2.7.0 Accepted")
                elif verb == "DATA":
                    say("354 End data with <CR><LF>.<CR><LF>")
                    while stream.readline().rstrip(b"\r\n") != b".":
                        pass
                    say("250 2.0.0 Queued")
                elif verb == "QUIT":
                    say("221 Bye")
                    return
                else:
                    say("250 OK")
        except (OSError, ssl.SSLError):
            return  # the client refused the certificate and hung up
        finally:
            conn.close()

    def close(self) -> None:
        self.listener.close()
        self.thread.join(5)


@pytest.fixture
def certificate(tmp_path):
    return _certificate(tmp_path, "localhost")


class Mode:
    def __init__(self, name: str):
        self.name = name
        self.port: int | None = None  # where a connection to 465 is sent


@pytest.fixture(params=["starttls", "implicit"])
def mode(request, monkeypatch):
    """Both ways the client opens TLS: STARTTLS on 587, and SMTPS on 465.

    Port 465 cannot be bound in a test, and the client picks SMTPS by that port
    number, so its connection is pointed at the test server's port instead.
    """
    chosen = Mode(request.param)
    if chosen.name == "implicit":
        real = socket.create_connection

        def to_test_port(address, *args, **kwargs):
            host, port = address
            return real((host, chosen.port if port == 465 else port), *args, **kwargs)

        monkeypatch.setattr(smtplib.socket, "create_connection", to_test_port)
    return chosen


def _start(certificate, mode: Mode, request) -> MailServer:
    cert_file, key_file, _ = certificate
    server = MailServer(cert_file, key_file, implicit=mode.name == "implicit")
    mode.port = server.port
    request.addfinalizer(server.close)
    return server


def _settings(server: MailServer, mode: Mode, host: str) -> dict:
    return {
        "smtp_server": host,
        "smtp_port": 465 if mode.name == "implicit" else server.port,
        "smtp_username": USERNAME,
        "smtp_password": PASSWORD,
        "smtp_from_email": USERNAME,
        "smtp_use_tls": True,
    }


def _trusting(monkeypatch, pem: str) -> None:
    """Trust the test certificate on top of the real context, as a real CA would be.

    ``raising=False`` so these tests also run against code that builds its
    context inline, which is how they were shown to fail before the fix rather
    than on a missing name. Renaming the helper cannot make them pass quietly:
    the certificate would go untrusted and the logging-in control would fail.
    """
    real = getattr(email_utils, "mail_tls_context", ssl.create_default_context)

    def context():
        ctx = real()
        ctx.load_verify_locations(cadata=pem)
        return ctx

    monkeypatch.setattr(email_utils, "mail_tls_context", context, raising=False)
    monkeypatch.setattr(email_debug, "mail_tls_context", context, raising=False)


def _run(entry: str, settings: dict, monkeypatch) -> dict:
    if entry == "send_email":
        return email_utils.send_email(USERNAME, "subject", "body", smtp_settings=settings)
    if entry == "validate_smtp_settings":
        return email_utils.validate_smtp_settings(settings)
    monkeypatch.setattr(email_debug, "get_smtp_settings", lambda: settings)
    return email_debug.debug_smtp_connection()


ENTRIES = ["send_email", "validate_smtp_settings", "debug_smtp_connection"]


@pytest.mark.parametrize("entry", ENTRIES)
def test_an_untrusted_certificate_gets_no_password(entry, certificate, mode, request, monkeypatch):
    """A certificate no authority vouches for: the man-in-the-middle case."""
    server = _start(certificate, mode, request)

    result = _run(entry, _settings(server, mode, "localhost"), monkeypatch)

    server.close()
    assert server.credentials is None, "the password was sent to an unverified server"
    assert result["success"] is False
    assert result["message"] == email_utils.CERTIFICATE_UNVERIFIED_MESSAGE


@pytest.mark.parametrize("entry", ENTRIES)
def test_a_certificate_for_another_name_gets_no_password(
    entry, certificate, mode, request, monkeypatch
):
    """A trusted certificate that names a different host than the one dialled."""
    _trusting(monkeypatch, certificate[2])
    server = _start(certificate, mode, request)

    result = _run(entry, _settings(server, mode, "127.0.0.1"), monkeypatch)

    server.close()
    assert server.credentials is None, "the password was sent to a server of another name"
    assert result["success"] is False
    assert result["message"] == email_utils.CERTIFICATE_UNVERIFIED_MESSAGE


@pytest.mark.parametrize("entry", ENTRIES)
def test_a_trusted_certificate_for_the_right_name_logs_in(
    entry, certificate, mode, request, monkeypatch
):
    """The control: without it, the two tests above could pass on any failure."""
    _trusting(monkeypatch, certificate[2])
    server = _start(certificate, mode, request)

    result = _run(entry, _settings(server, mode, "localhost"), monkeypatch)

    server.close()
    assert result["success"] is True, result
    assert server.credentials == (USERNAME, PASSWORD)


def test_the_context_requires_a_verified_certificate_and_name():
    context = email_utils.mail_tls_context()
    assert context.verify_mode == ssl.CERT_REQUIRED
    assert context.check_hostname is True


def test_the_debug_tool_prints_no_smtp_conversation(certificate, request, monkeypatch, capfd):
    """smtplib's debug output prints the AUTH line, which carries the password."""
    _trusting(monkeypatch, certificate[2])
    starttls = Mode("starttls")
    server = _start(certificate, starttls, request)

    result = _run("debug_smtp_connection", _settings(server, starttls, "localhost"), monkeypatch)

    server.close()
    assert result["success"] is True, result
    encoded = base64.b64encode(f"\0{USERNAME}\0{PASSWORD}".encode()).decode()
    captured = capfd.readouterr()
    assert encoded not in captured.out + captured.err
    assert "send: 'AUTH" not in captured.err
