"""Tests for server-side URL sanitization of browser error reports."""

from urllib.parse import parse_qs, urlsplit

from blueprints.admin import _sanitize_client_error_url


def test_server_redacts_sensitive_query_values_and_fragments():
    """Keep safe query context while redacting sensitive values before logging."""
    sanitized = _sanitize_client_error_url(
        "https://app.example.com/search?symbol=INFY&token=test-token-not-real&apiKey=test-token-not-real#results"
    )
    parsed = urlsplit(sanitized)

    assert f"{parsed.scheme}://{parsed.netloc}{parsed.path}" == "https://app.example.com/search"
    assert parse_qs(parsed.query) == {
        "symbol": ["INFY"],
        "token": ["[redacted]"],
        "apiKey": ["[redacted]"],
    }
    assert parsed.fragment == ""
    assert "test-token-not-real" not in sanitized


def test_server_handles_extension_and_opaque_urls_safely():
    """Keep extension filenames but drop opaque URL content."""
    assert (
        _sanitize_client_error_url("chrome-extension://abcdef/content.js?token=test-token-not-real")
        == "chrome-extension://abcdef/content.js"
    )
    assert _sanitize_client_error_url("data:text/html;base64,PAYLOAD") == "data:"
    assert _sanitize_client_error_url("blob:http://host/uuid") == "blob:"


def test_server_falls_back_for_malformed_urls():
    """Avoid raising or retaining a fragment when URL parsing fails."""
    assert _sanitize_client_error_url("http://[?token=test-token-not-real#fragment") == "http://["
