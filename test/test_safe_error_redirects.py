"""Regression tests for the CSRF and admin rate-limit error redirects.

Both handlers used to redirect straight to ``request.referrer``. The Referer
header is attacker-controlled on any request the attacker crafts directly, so
an external, protocol-relative, or backslash-disguised referrer turned the
error path into an open redirect. Both handlers now resolve their target
through ``utils.safe_redirect.safe_local_redirect_target`` instead.
"""

import os
import sys

import pytest
from flask import Flask, abort

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import blueprints.admin as admin_bp_module  # noqa: E402
import blueprints.react_app as react_app_module  # noqa: E402
from utils.safe_redirect import safe_local_redirect_target  # noqa: E402

HOST = "app.example.com"


# --- safe_local_redirect_target: unit coverage -----------------------------


@pytest.mark.parametrize(
    "candidate",
    [
        None,
        "",
        "   ",
        "http://evil.com",
        "https://evil.com/phish",
        "http://evil.com/app.example.com",  # host is only a path segment here
        "HTTP://EVIL.COM",
        "http://app.example.com.evil.com/phish",  # suffix trick, not a subdomain match
        "http://app.example.com@evil.com/phish",  # userinfo trick
        "//evil.com",
        "//evil.com/phish",
        "//app.example.com/phish",  # protocol-relative is never a real Referer
        "/\\evil.com",
        "\\/evil.com",
        "\\\\evil.com",
        "%2F%2Fevil.com",
        "%2f%2Fevil.com/phish",
        "/%5c%5cevil.com",
        "javascript:alert(1)",
        "data:text/html,<script>alert(1)</script>",
        "ftp://app.example.com/phish",
        "https:evil.com",
        "https:///evil.com",
        "relative/without/leading/slash",
        "/redirect\r\nSet-Cookie: pwned=1",
        "/redirect\nLocation: http://evil.com",
    ],
)
def test_unsafe_targets_fall_back(candidate):
    assert safe_local_redirect_target(candidate, "/fallback", HOST) == "/fallback"


@pytest.mark.parametrize(
    ("candidate", "expected"),
    [
        ("/dashboard", "/dashboard"),
        ("/settings/profile", "/settings/profile"),
        ("/search?q=orders", "/search?q=orders"),
        ("/search?q=hello%20world", "/search?q=hello world"),
        ("/orders#history", "/orders#history"),
        ("  /dashboard  ", "/dashboard"),
        # Real browsers send an absolute URL, not a bare path.
        ("http://app.example.com/dashboard", "/dashboard"),
        ("https://app.example.com/settings/profile?tab=security", "/settings/profile?tab=security"),
        ("HTTP://APP.EXAMPLE.COM/dashboard", "/dashboard"),
        ("http://app.example.com", "/"),
    ],
)
def test_safe_same_origin_targets_are_preserved(candidate, expected):
    assert safe_local_redirect_target(candidate, "/fallback", HOST) == expected


def test_missing_referrer_uses_fallback():
    assert safe_local_redirect_target(None, "/admin", HOST) == "/admin"


# --- admin_bp rate-limit handler: end-to-end wiring -------------------------


# admin_bp has no active route left that raises 429 directly (they were all
# migrated to React), so add a throwaway one purely to exercise the
# blueprint's own @admin_bp.errorhandler(429) through a real request. This
# has to happen once at import time: Flask locks a blueprint against further
# route additions after its first registration to an app.
@admin_bp_module.admin_bp.route("/_test/trigger-429")
def _trigger_429():
    abort(429)


def _admin_app():
    app = Flask(__name__)
    app.secret_key = "test-secret"
    app.register_blueprint(admin_bp_module.admin_bp)
    # The handler's fallback resolves react.react_admin_index via url_for(),
    # so that blueprint has to be registered too for a real request to work.
    app.register_blueprint(react_app_module.react_bp)
    return app


def test_admin_ratelimit_handler_rejects_external_referrer():
    app = _admin_app()
    with app.test_client() as client:
        response = client.get(
            "/admin/_test/trigger-429", headers={"Referer": "https://evil.com/phish"}
        )

    assert response.status_code == 302
    assert response.headers["Location"] == "/admin"


def test_admin_ratelimit_handler_rejects_protocol_relative_referrer():
    app = _admin_app()
    with app.test_client() as client:
        response = client.get("/admin/_test/trigger-429", headers={"Referer": "//evil.com"})

    assert response.status_code == 302
    assert response.headers["Location"] == "/admin"


def test_admin_ratelimit_handler_keeps_same_origin_referrer():
    app = _admin_app()
    with app.test_client() as client:
        response = client.get(
            "/admin/_test/trigger-429", headers={"Referer": "http://localhost/admin/holidays"}
        )

    assert response.status_code == 302
    assert response.headers["Location"] == "/admin/holidays"


def test_admin_ratelimit_handler_falls_back_without_referrer():
    app = _admin_app()
    with app.test_client() as client:
        response = client.get("/admin/_test/trigger-429")

    assert response.status_code == 302
    assert response.headers["Location"] == "/admin"
