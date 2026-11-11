"""The default Socket.IO namespace admits only a signed-in broker session.

Every server broadcast goes to the default namespace with no room: live order
events, analyzer updates, the signed-in device list, scalping levels, the
WhatsApp pairing QR. Socket.IO is served ahead of Flask's routing, so no route
decorator or ``before_request`` hook sees a connection, and python-socketio
accepts a connect that has no handler. Before
``extensions.require_signed_in_session`` a client with no cookie connected and
received all of it.

The first test asserts that on the shared server itself, in a subprocess:
``init_app`` on the module-level ``socketio`` rebinds it, and this suite
shares one interpreter. The rest use a server of their own with the same
handler, so they can sign a session in and out.
"""

from __future__ import annotations

import json
import subprocess
import sys
import types
from datetime import datetime, timedelta
from pathlib import Path

import pytest
import pytz
from flask import Flask, request, session

REPO_ROOT = Path(__file__).resolve().parent.parent
IST = pytz.timezone("Asia/Kolkata")

SHARED_SERVER_PROBE = """
import json
from flask import Flask
from extensions import socketio

app = Flask(__name__)
app.config["SECRET_KEY"] = "probe"

# A handler on the default namespace, as blueprints/strategy_module.py has:
# it is what makes the server know the namespace at all.
@socketio.on("strategy_subscribe")
def _subscribe(data):
    pass

socketio.init_app(app)
client = socketio.test_client(app)
connected = client.is_connected()
socketio.emit("order_update", {"symbol": "PROBE"})
received = client.get_received() if connected else []
print(json.dumps({"connected": connected, "received": [r["name"] for r in received]}))
"""


def test_the_shared_server_refuses_a_client_with_no_session():
    """The defect itself: no cookie, connected, and handed a live order."""
    result = subprocess.run(
        [sys.executable, "-c", SHARED_SERVER_PROBE],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    answer = json.loads(result.stdout.strip().splitlines()[-1])
    assert answer == {"connected": False, "received": []}


@pytest.fixture
def server(monkeypatch):
    """A Flask app and Socket.IO server carrying the connect guard.

    ``/seed`` writes the posted fields into the session, the way a login
    does, so a test decides exactly what the browser's cookie holds.
    """
    import database.auth_db as auth_db
    import extensions
    import utils.session as session_utils

    monkeypatch.setattr(session_utils, "is_session_expiry_disabled", lambda: False)
    revoked = {"at": None}
    monkeypatch.setattr(auth_db, "get_sessions_revoked_at", lambda username: revoked["at"])
    monkeypatch.setattr(auth_db, "get_pre_broker_revoked_at", lambda username: None)

    app = Flask(__name__)
    app.config["SECRET_KEY"] = "test-only"

    @app.route("/seed", methods=["POST"])
    def seed():
        session.clear()
        session.update(request.get_json())
        return "ok"

    sio = extensions.SerializedSocketIO(async_mode="threading")
    sio.on_event("connect", extensions.require_signed_in_session)
    sio.init_app(app)
    return types.SimpleNamespace(app=app, sio=sio, revoked=revoked)


def _connect(server, cookie: dict | None):
    """A Socket.IO client whose browser carries ``cookie`` in its session."""
    http = server.app.test_client()
    if cookie is not None:
        assert http.post("/seed", json=cookie).status_code == 200
    return server.sio.test_client(server.app, flask_test_client=http)


def _broker_session(signed_in: datetime | None = None) -> dict:
    stamp = (signed_in or datetime.now(IST)).isoformat()
    return {"user": "trader", "logged_in": True, "login_time": stamp, "auth_at": stamp}


def _receives_a_broadcast(server, client) -> bool:
    server.sio.emit("order_update", {"symbol": "SBIN"})
    return any(packet["name"] == "order_update" for packet in client.get_received())


def test_a_signed_in_broker_session_connects_and_is_pushed_to(server):
    client = _connect(server, _broker_session())
    assert client.is_connected()
    assert _receives_a_broadcast(server, client)


def test_no_cookie_is_refused_and_receives_nothing(server):
    listener = _connect(server, None)
    assert not listener.is_connected()
    # The broadcast still reaches the trader's own browser, and only it.
    trader = _connect(server, _broker_session())
    assert _receives_a_broadcast(server, trader)
    assert not listener.is_connected()


def test_a_password_sign_in_with_no_broker_login_is_refused(server):
    stamp = datetime.now(IST).isoformat()
    client = _connect(server, {"user": "trader", "auth_at": stamp})
    assert not client.is_connected()


def test_a_session_from_before_the_daily_rollover_is_refused(server):
    client = _connect(server, _broker_session(datetime.now(IST) - timedelta(days=2)))
    assert not client.is_connected()


def test_a_sign_in_ended_on_another_device_is_refused(server):
    signed_in = datetime.now(IST)
    server.revoked["at"] = signed_in + timedelta(seconds=1)
    client = _connect(server, _broker_session(signed_in))
    assert not client.is_connected()


def test_a_broker_login_with_no_user_is_refused(server):
    cookie = _broker_session()
    del cookie["user"]
    client = _connect(server, cookie)
    assert not client.is_connected()


def test_a_check_that_fails_refuses_the_connection(server, monkeypatch):
    import utils.session as session_utils

    def broken():
        raise RuntimeError("the session store is unreadable")

    monkeypatch.setattr(session_utils, "is_session_valid", broken)
    client = _connect(server, _broker_session())
    assert not client.is_connected()
