"""CSRF protection for /auth/logout.

Logout is not a "safe" endpoint here: it revokes the broker token, publishes
CACHE_INVALIDATE_ALL (tearing down the shared WebSocket feed), clears every
device's session and flushes the symbol cache. A forced logout is therefore an
availability attack on a live trading session, not a nuisance.

Two layers guard it, and both are exercised below:

* POST is covered by Flask-WTF's CSRF token. SameSite=Lax is not sufficient on
  its own, because ports are not part of the same-site check - another service
  on the same host is same-site and its POST would carry the cookie.
* GET cannot be token-checked (Flask-WTF never validates safe methods) and Lax
  does attach the cookie to top-level cross-site navigations, so it is covered
  by a fetch-metadata check instead.

This replaces an earlier version that drove a live server over HTTP. That one
swallowed ConnectionError and returned a bool, so with no server running it was
reported as passing while asserting behaviour that no longer held.
"""

import os
import sys

import pytest
from flask import Flask

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import blueprints.auth as auth_bp_module  # noqa: E402


def _app():
    app = Flask(__name__)
    app.secret_key = "test-secret"
    app.register_blueprint(auth_bp_module.auth_bp)
    return app


def _client_with_session(app, **session_values):
    client = app.test_client()
    with client.session_transaction() as session:
        session.update(session_values)
    return client


@pytest.mark.parametrize("fetch_site", ["cross-site", "same-site"])
def test_foreign_initiated_logout_is_rejected(fetch_site):
    """A logout initiated from another origin must be refused, not honoured.

    "same-site" is rejected alongside "cross-site" because OpenAlgo is a single
    self-hosted origin - anything same-site but not same-origin is a different
    service sharing the host, typically another app on another localhost port.
    """
    app = _app()
    client = _client_with_session(app, user="rajandran")

    response = client.get("/auth/logout", headers={"Sec-Fetch-Site": fetch_site})

    assert response.status_code == 403
    with client.session_transaction() as session:
        # The victim stays logged in; a refused request must not be a logout.
        assert session["user"] == "rajandran"


def test_foreign_initiated_logout_does_not_run_teardown(monkeypatch):
    """A refused logout must not revoke the broker token or kill the feed."""
    calls = []
    monkeypatch.setattr(auth_bp_module, "upsert_auth", lambda *a, **k: calls.append("upsert_auth"))
    monkeypatch.setattr(auth_bp_module.socketio, "emit", lambda *a, **k: calls.append("emit"))

    app = _app()
    client = _client_with_session(app, user="rajandran", logged_in=True, broker="dhan")

    response = client.post("/auth/logout", headers={"Sec-Fetch-Site": "cross-site"})

    assert response.status_code == 403
    assert calls == []
    with client.session_transaction() as session:
        assert session["logged_in"] is True


@pytest.mark.parametrize("fetch_site", ["same-origin", "none"])
def test_same_origin_logout_is_allowed(fetch_site):
    """Our own pages ("same-origin") and typed URLs / bookmarks ("none") work."""
    app = _app()
    client = _client_with_session(app, user="rajandran")

    response = client.get("/auth/logout", headers={"Sec-Fetch-Site": fetch_site})

    assert response.status_code == 302
    with client.session_transaction() as session:
        assert "user" not in session


def test_logout_without_fetch_metadata_is_allowed():
    """A missing Sec-Fetch-Site is trusted, deliberately.

    Mounting the attack requires a browser, since the victim's cookie has to be
    attached automatically, and every browser new enough to do that sends the
    header. A client old enough to omit it is not carrying the cookie either, so
    failing closed here would only break non-browser callers for no gain.
    """
    app = _app()
    client = _client_with_session(app, user="rajandran")

    response = client.get("/auth/logout")

    assert response.status_code == 302
    with client.session_transaction() as session:
        assert "user" not in session


def test_logout_view_is_not_csrf_exempt():
    """POST must keep Flask-WTF's token check.

    Guards the regression directly: the endpoint was exempted for years under
    the comment "safe - only destroys session", which was not true of it.

    Read as text rather than imported: importing app.py boots the whole
    application (databases, scheduler, broker plugin discovery) and would hang
    the suite.
    """
    app_py = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "app.py")
    with open(app_py, encoding="utf-8") as handle:
        source = handle.read()

    assert 'csrf.exempt(app.view_functions["auth.logout"])' not in source
