"""Reproduction for issue #2015: the ban system can lock out every client.

Behind Docker or a reverse proxy with TRUST_PROXY_HEADERS off, every request
reaches OpenAlgo from the bridge gateway (172.17.0.1). Banning that address
bans the only path the operator has, so these tests assert the ban paths
refuse to do it.
"""

import pytest

from database.traffic_db import (
    Error404Tracker,
    InvalidAPIKeyTracker,
    IPBan,
    LogBase,
    logs_engine,
    logs_session,
)
from utils.ip_helper import is_unroutable_ip

GATEWAY = "172.17.0.1"


@pytest.fixture(autouse=True)
def clean_db(monkeypatch):
    LogBase.metadata.create_all(logs_engine)
    logs_session.query(IPBan).delete()
    logs_session.query(Error404Tracker).delete()
    logs_session.query(InvalidAPIKeyTracker).delete()
    logs_session.commit()
    import database.traffic_db as tdb

    tdb._ip_ban_cache.clear()
    monkeypatch.setattr(
        tdb,
        "get_security_settings",
        lambda: {
            "auto_ban_enabled": True,
            "404_threshold": 2,
            "404_ban_duration": 0,
            "api_threshold": 2,
            "api_ban_duration": 0,
            "repeat_offender_limit": 3,
        },
    )
    yield
    logs_session.remove()


def test_auto_ban_spares_the_container_gateway():
    """A 404 flood arriving via the Docker gateway must not ban the gateway."""
    Error404Tracker.track_404(GATEWAY, "/wp-admin")
    Error404Tracker.track_404(GATEWAY, "/.env")

    assert not IPBan.is_ip_banned(GATEWAY), (
        "auto-ban banned the container gateway - every client is now locked out"
    )


def test_auto_ban_still_bans_a_public_address():
    """The guard must not disarm auto-ban for real internet traffic."""
    Error404Tracker.track_404("45.33.32.156", "/wp-admin")
    Error404Tracker.track_404("45.33.32.156", "/.env")

    assert IPBan.is_ip_banned("45.33.32.156")


# ------------------------------------------------- manual ban via the dashboard


@pytest.fixture
def client(monkeypatch):
    from flask import Flask

    import utils.session as session_mod
    from limiter import limiter

    monkeypatch.setattr(session_mod, "is_session_valid", lambda: True)
    monkeypatch.setattr(limiter, "enabled", False)

    from blueprints.security import security_bp

    app = Flask(__name__)
    app.config.update(TESTING=True, SECRET_KEY="test")
    app.register_blueprint(security_bp, url_prefix="/security")
    return app.test_client()


def test_manual_ban_refuses_the_callers_own_ip(client):
    """Banning the address your own request arrives from is always a lockout."""
    resp = client.post(
        "/security/ban",
        json={"ip_address": GATEWAY, "reason": "Quick ban from dashboard"},
        environ_base={"REMOTE_ADDR": GATEWAY},
    )

    assert resp.status_code == 400, resp.get_json()
    assert not IPBan.is_ip_banned(GATEWAY)


def test_manual_ban_still_allows_a_different_ip(client):
    """The guard must not block banning anyone else."""
    resp = client.post(
        "/security/ban",
        json={"ip_address": "45.33.32.156", "reason": "bot"},
        environ_base={"REMOTE_ADDR": GATEWAY},
    )

    assert resp.status_code == 200, resp.get_json()
    assert IPBan.is_ip_banned("45.33.32.156")


def test_api_key_auto_ban_spares_the_container_gateway():
    """An invalid-API-key flood via the gateway must not ban the gateway."""
    InvalidAPIKeyTracker.track_invalid_api_key(GATEWAY, "hash-a")
    InvalidAPIKeyTracker.track_invalid_api_key(GATEWAY, "hash-b")

    assert not IPBan.is_ip_banned(GATEWAY)


def test_api_key_auto_ban_still_bans_a_public_address():
    InvalidAPIKeyTracker.track_invalid_api_key("45.33.32.156", "hash-a")
    InvalidAPIKeyTracker.track_invalid_api_key("45.33.32.156", "hash-b")

    assert IPBan.is_ip_banned("45.33.32.156")


# ------------------------------------------------------------- the classifier


@pytest.mark.parametrize(
    "ip",
    ["172.17.0.1", "192.168.1.10", "10.0.0.5", "127.0.0.1", "::1", "169.254.1.1", "localhost", ""],
)
def test_unroutable_addresses_are_protected(ip):
    assert is_unroutable_ip(ip)


@pytest.mark.parametrize("ip", ["45.33.32.156", "8.8.8.8", "2606:4700:4700::1111"])
def test_public_addresses_remain_bannable(ip):
    assert not is_unroutable_ip(ip)
