"""Broker keys saved in OpenAlgo, the .env-first resolver, and the login layer.

A trader keeps keys for several brokers and logs in to one at a time. The .env
file comes first: the broker it names always uses its .env keys, and the saved
keys serve every other broker. The broker plugins read their keys from the
process environment, so choosing a broker writes its keys there.

Around that sits the login layer modelled on OpenAlgo Desktop: a broker login
is started by the server and the callback completes only a login this browser
started; a logout or password change ends every device's sign-in; a sign-in
that never reached a broker login ends at the daily rollover.

Each test runs on its own SQLite file and its own .env file.
"""

import os
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest
import pytz
from flask import Flask

import blueprints.auth as auth_bp_module
import database.auth_db as auth_db
import database.broker_keys_db as keys_db
import utils.broker_keys as broker_keys
import utils.broker_login as broker_login
import utils.broker_switch as broker_switch
from blueprints import brlogin
from blueprints.broker_config import broker_config_bp
from blueprints.broker_credentials import broker_credentials_bp
from database.engine_factory import create_db_engine
from utils.session import end_session_if_signed_out, last_rollover_boundary

ROOT = Path(__file__).resolve().parents[1]
IST = pytz.timezone("Asia/Kolkata")
USER = "trader"

ENV_ZERODHA = {
    "BROKER_API_KEY": "zkey123",
    "BROKER_API_SECRET": "zsecret456",
    "BROKER_API_KEY_MARKET": "",
    "BROKER_API_SECRET_MARKET": "",
    "REDIRECT_URL": "http://127.0.0.1:5000/zerodha/callback",
}
SAVED_FYERS = {
    "api_key": "FYAPP-100",
    "api_secret": "fyers-secret-value",
    "api_key_market": "",
    "api_secret_market": "",
}


# --------------------------------------------------------------------------
# Fixtures
# --------------------------------------------------------------------------


def _swap_store(monkeypatch, module, engine, session_name="db_session"):
    from sqlalchemy.orm import scoped_session, sessionmaker

    session = scoped_session(sessionmaker(autocommit=False, autoflush=False, bind=engine))
    monkeypatch.setattr(module, "engine", engine)
    monkeypatch.setattr(module, session_name, session)
    # Swapped by hand: monkeypatch reads the old value with getattr, and a
    # query property read on the declarative base itself raises.
    previous = module.Base.__dict__["query"]
    module.Base.query = session.query_property()
    module.Base.metadata.create_all(engine)
    return session, previous


@pytest.fixture
def stores(tmp_path, monkeypatch):
    """The auth tables and the broker keys table on a file of their own."""
    engine = create_db_engine(f"sqlite:///{(tmp_path / 'openalgo.db').as_posix()}")
    auth_session, auth_query = _swap_store(monkeypatch, auth_db, engine)
    keys_session, keys_query = _swap_store(monkeypatch, keys_db, engine)
    auth_db._session_revocation_cache.invalidate()
    # Tests store broker sessions directly, not through upsert_auth, which is
    # what drops this cache in the app.
    broker_keys.forget_logged_in_broker()
    broker_login.clear_pending_logins()
    try:
        yield SimpleNamespace(engine=engine, auth=auth_session, keys=keys_session)
    finally:
        auth_db._session_revocation_cache.invalidate()
        broker_keys.forget_logged_in_broker()
        broker_login.clear_pending_logins()
        auth_db.Base.query = auth_query
        keys_db.Base.query = keys_query
        auth_session.remove()
        keys_session.remove()
        engine.dispose()


@pytest.fixture
def environment(tmp_path, monkeypatch):
    """A clean process environment and a .env file the test controls.

    Every broker variable is registered with monkeypatch first, so whatever the
    code under test writes into os.environ is undone afterwards.
    """
    for var in broker_keys.ENV_VARS.values():
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("VALID_BROKERS", "zerodha,fyers,angel,compositedge,fivepaisa,dhan")
    monkeypatch.setenv("HOST_SERVER", "http://127.0.0.1:5000")
    env_file = tmp_path / ".env"
    monkeypatch.setattr(broker_keys, "env_file_path", lambda: env_file)
    monkeypatch.setattr(
        broker_keys, "_STARTUP_VALUES", dict.fromkeys(broker_keys.ENV_VARS.values())
    )

    def write(values):
        env_file.write_text("".join(f"{k} = '{v}'\n" for k, v in values.items()), encoding="utf-8")
        for var, value in values.items():
            os.environ[var] = value

    return SimpleNamespace(write=write, file=env_file)


def _save_fyers():
    ok, _ = keys_db.save_broker_keys("fyers", SAVED_FYERS, "http://127.0.0.1:5000/fyers/callback")
    assert ok


def _logged_in(broker, fresh=True):
    """Store a broker session and a device that signed in to it."""
    now = datetime.now(IST)
    login = now if fresh else last_rollover_boundary() - timedelta(hours=1)
    auth_db.db_session.add(
        auth_db.Auth(name=USER, auth=auth_db.encrypt_token("tok"), broker=broker, is_revoked=False)
    )
    auth_db.db_session.add(
        auth_db.ActiveSession(
            username=USER,
            session_id=os.urandom(8).hex(),
            broker=broker,
            login_time=login.replace(tzinfo=None),
            last_seen=login.replace(tzinfo=None),
        )
    )
    auth_db.db_session.commit()
    broker_keys.forget_logged_in_broker()


def _app(csrf=False):
    app = Flask(__name__)
    app.secret_key = "test-secret"
    app.config["WTF_CSRF_ENABLED"] = csrf
    app.register_blueprint(auth_bp_module.auth_bp)
    app.register_blueprint(brlogin.brlogin_bp)
    app.register_blueprint(broker_credentials_bp)
    app.register_blueprint(broker_config_bp)
    if csrf:
        from flask_wtf.csrf import CSRFProtect

        CSRFProtect(app).exempt(app.view_functions["brlogin.broker_callback"])

    # The same hook app.py registers ahead of every route. Wrapped, as there:
    # a before_request that returns a value answers the request with it.
    @app.before_request
    def _drop_ended_sessions():
        end_session_if_signed_out()

    app.broker_auth_functions = {}
    return app


def _signed_in(app, **extra):
    client = app.test_client()
    with client.session_transaction() as sess:
        sess["user"] = USER
        sess["auth_at"] = datetime.now(UTC).isoformat()
        sess.update(extra)
    return client


def _csrf(client):
    return client.get("/auth/csrf-token").get_json()["csrf_token"]


JSON = {"Accept": "application/json"}


def _probe(client):
    """Whether a browser is still signed in to OpenAlgo: 200, or 401 when it is not."""
    return client.get("/api/broker/list", headers=JSON).status_code


_REAL_BLOCKERS = broker_switch._blockers


@pytest.fixture(autouse=True)
def _nothing_runs(monkeypatch):
    """No Live automation, unless a test says otherwise (broker_switch._blockers)."""
    monkeypatch.setattr(broker_switch, "_blockers", lambda username: (0, 0, 0, 0))


# --------------------------------------------------------------------------
# The resolver: .env first, saved keys for every other broker
# --------------------------------------------------------------------------


def test_the_env_broker_wins_over_keys_saved_for_it(stores, environment):
    environment.write(ENV_ZERODHA)
    keys_db.save_broker_keys("zerodha", {"api_key": "saved-zerodha"}, None)

    keys = broker_keys.resolve("zerodha")

    assert keys.source == "env"
    assert keys.api_key == "zkey123"


def test_saved_keys_serve_every_other_broker(stores, environment):
    environment.write(ENV_ZERODHA)
    _save_fyers()

    keys = broker_keys.use_broker_keys("fyers")

    assert keys.source == "saved"
    assert os.environ["BROKER_API_KEY"] == "FYAPP-100"
    assert os.environ["BROKER_API_SECRET"] == "fyers-secret-value"
    assert os.environ["REDIRECT_URL"] == "http://127.0.0.1:5000/fyers/callback"


def test_switching_back_puts_the_env_keys_back(stores, environment):
    environment.write({**ENV_ZERODHA, "BROKER_API_KEY_MARKET": "zmarket"})
    _save_fyers()

    broker_keys.use_broker_keys("fyers")
    assert os.environ["BROKER_API_KEY_MARKET"] == ""
    broker_keys.use_broker_keys("zerodha")

    assert os.environ["BROKER_API_KEY"] == "zkey123"
    assert os.environ["BROKER_API_KEY_MARKET"] == "zmarket"
    assert os.environ["REDIRECT_URL"] == ENV_ZERODHA["REDIRECT_URL"]


def test_a_pure_env_install_writes_nothing(stores, environment):
    """The ~4,75,000 .env installs: their broker resolves to what is in place."""
    environment.write(ENV_ZERODHA)

    keys = broker_keys.resolve("zerodha")

    assert broker_keys._apply(keys) is False


def test_an_empty_value_never_creates_a_variable(stores, environment):
    environment.write(ENV_ZERODHA)
    os.environ.pop("BROKER_API_KEY_MARKET")
    _save_fyers()

    broker_keys.use_broker_keys("fyers")

    assert "BROKER_API_KEY_MARKET" not in os.environ


def test_no_keys_anywhere_is_refused_in_plain_words(stores, environment):
    environment.write(ENV_ZERODHA)

    with pytest.raises(broker_keys.BrokerKeysRefused) as refused:
        broker_keys.use_broker_keys("angel")

    assert "No API key is saved for Angel One" in str(refused.value)


def test_env_sets_no_broker_without_an_api_key(stores, environment):
    environment.write({**ENV_ZERODHA, "BROKER_API_KEY": ""})

    assert broker_keys.env_broker() is None
    assert broker_keys.resolve("zerodha") is None


def test_the_broker_list_names_each_broker_once_env_first(stores, environment, monkeypatch):
    environment.write(ENV_ZERODHA)
    _save_fyers()
    keys_db.save_broker_keys("zerodha", {"api_key": "shadowed"}, None)
    keys_db.save_broker_keys("upstox", {"api_key": "not-enabled"}, None)

    listed = broker_keys.configured_brokers()

    assert [(b["broker"], b["source"]) for b in listed] == [("zerodha", "env"), ("fyers", "saved")]


def test_key_layouts_are_checked():
    assert broker_keys.key_format_error("dhan", "only-one-part")
    assert broker_keys.key_format_error("dhan", "client:::key") is None
    assert broker_keys.key_format_error("fivepaisa", "a:::b") is not None
    assert broker_keys.key_format_error("zerodha", "anything") is None


# --------------------------------------------------------------------------
# One broker at a time
# --------------------------------------------------------------------------


def test_the_logged_in_broker_gets_its_keys_back(stores, environment):
    """A login to another broker writes that broker's keys while the logged-in
    one may still trade; when it does not complete, they are put back."""
    environment.write(ENV_ZERODHA)
    _save_fyers()
    _logged_in("zerodha")

    broker_keys.use_broker_keys("fyers")
    during = os.environ["BROKER_API_KEY"]
    broker_keys.restore_logged_in_broker_keys("fyers")
    after = os.environ["BROKER_API_KEY"]
    broker_keys.use_broker_keys("fyers")
    broker_keys.restore_logged_in_broker_keys("zerodha")

    assert (during, after) == ("FYAPP-100", "zkey123")
    # Nothing to put back for the broker that is itself logged in.
    assert os.environ["BROKER_API_KEY"] == "FYAPP-100"


def test_the_live_broker_itself_and_startup_are_allowed(stores, environment):
    environment.write(ENV_ZERODHA)
    _save_fyers()
    _logged_in("fyers")

    assert broker_keys.use_broker_keys("fyers").source == "saved"
    assert broker_keys.apply_logged_in_broker_keys().broker == "fyers"


def test_a_session_from_before_the_rollover_does_not_hold_the_slot(stores, environment):
    """A token left from yesterday is dead at the broker and must not block."""
    environment.write(ENV_ZERODHA)
    _save_fyers()
    _logged_in("zerodha", fresh=False)

    assert broker_keys.live_broker() is None
    assert broker_keys.use_broker_keys("fyers").broker == "fyers"


def test_a_revoked_token_does_not_hold_the_slot(stores, environment):
    environment.write(ENV_ZERODHA)
    _save_fyers()
    _logged_in("zerodha")
    row = auth_db.Auth.query.filter_by(name=USER).one()
    row.is_revoked = True
    auth_db.db_session.commit()

    assert broker_keys.live_broker() is None


def test_startup_restores_the_logged_in_brokers_keys(stores, environment):
    """A restart loses what a login wrote; startup writes it back."""
    environment.write(ENV_ZERODHA)
    _save_fyers()
    _logged_in("fyers")

    broker_keys.apply_logged_in_broker_keys()

    assert os.environ["BROKER_API_KEY"] == "FYAPP-100"


# --------------------------------------------------------------------------
# Storage
# --------------------------------------------------------------------------


def test_keys_are_encrypted_at_rest(stores, environment):
    _save_fyers()

    with stores.engine.connect() as conn:
        from sqlalchemy import text

        raw = conn.execute(text("SELECT api_key, api_secret FROM broker_keys")).one()

    assert "FYAPP-100" not in raw[0] and "fyers-secret-value" not in raw[1]
    assert (
        auth_db.decrypt_token(raw[1])
        == "openalgo.broker_keys.v1|fyers|api_secret|fyers-secret-value"
    )


def test_a_ciphertext_moved_to_another_row_or_field_is_not_trusted(stores, environment):
    """Each value is bound to its broker and field, as Desktop binds AES-GCM
    ciphertexts: copying the fyers secret into the angel row (or into fyers's
    own api_key column) must not make it angel's secret."""
    _save_fyers()
    keys_db.save_broker_keys("angel", {"api_key": "angel-app", "api_secret": "angel-secret"}, None)
    from sqlalchemy import text

    with stores.engine.begin() as conn:
        secret = conn.execute(
            text("SELECT api_secret FROM broker_keys WHERE broker = 'fyers'")
        ).scalar_one()
        conn.execute(
            text("UPDATE broker_keys SET api_secret = :v WHERE broker = 'angel'"), {"v": secret}
        )
        conn.execute(
            text("UPDATE broker_keys SET api_key = :v WHERE broker = 'fyers'"), {"v": secret}
        )

    assert keys_db.get_broker_keys("angel").api_secret == ""
    assert keys_db.get_broker_keys("fyers").api_key == ""
    assert broker_keys.resolve("fyers") is None


def test_the_salt_rotation_re_encrypts_saved_keys(tmp_path, monkeypatch):
    """utils/env_check._migrate_fernet_db moves every auth_db Fernet column off
    the legacy static salt; broker keys must be in its list, or they could not
    be read after the rotation."""
    import base64

    from cryptography.fernet import Fernet
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
    from sqlalchemy import text

    import utils.env_check as env_check

    pepper = "p" * 64
    new_salt = os.urandom(16).hex()

    def fernet(salt):
        kdf = PBKDF2HMAC(algorithm=hashes.SHA256(), length=32, salt=salt, iterations=100000)
        return Fernet(base64.urlsafe_b64encode(kdf.derive(pepper.encode())))

    db_file = tmp_path / "openalgo.db"
    engine = create_db_engine(f"sqlite:///{db_file.as_posix()}")
    keys_db.Base.metadata.create_all(engine)
    bound = "openalgo.broker_keys.v1|fyers|api_secret|fyers-secret-value"
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO broker_keys (broker, api_key, api_secret, api_key_market, "
                "api_secret_market, redirect_url) VALUES ('fyers', '', :s, '', '', '')"
            ),
            {"s": fernet(b"openalgo_static_salt").encrypt(bound.encode()).decode()},
        )
    engine.dispose()
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_file.as_posix()}")

    env_check._migrate_fernet_db(str(tmp_path / ".env"), pepper, new_salt)

    engine = create_db_engine(f"sqlite:///{db_file.as_posix()}")
    with engine.connect() as conn:
        stored = conn.execute(text("SELECT api_secret FROM broker_keys")).scalar_one()
    engine.dispose()
    assert fernet(bytes.fromhex(new_salt)).decrypt(stored.encode()).decode() == bound


def test_an_empty_field_keeps_the_saved_value(stores, environment):
    _save_fyers()

    keys_db.save_broker_keys("fyers", {"api_key": "", "api_secret": "rotated"}, None)
    stored = keys_db.get_broker_keys("fyers")

    assert stored.api_key == "FYAPP-100"
    assert stored.api_secret == "rotated"
    assert keys_db.save_broker_keys("angel", {"api_secret": "x"}, None)[0] is False


def test_a_missing_table_is_not_an_error(tmp_path, monkeypatch, caplog):
    engine = create_db_engine(f"sqlite:///{(tmp_path / 'empty.db').as_posix()}")
    monkeypatch.setattr(keys_db, "engine", engine)
    from sqlalchemy.orm import scoped_session, sessionmaker

    session = scoped_session(sessionmaker(bind=engine))
    monkeypatch.setattr(keys_db, "db_session", session)
    previous = keys_db.Base.__dict__["query"]
    keys_db.Base.query = session.query_property()
    try:
        assert keys_db.get_broker_keys("fyers") is None
        assert keys_db.list_broker_keys() == []
    finally:
        keys_db.Base.query = previous
        engine.dispose()
    assert not [r for r in caplog.records if r.levelname == "ERROR"]


# --------------------------------------------------------------------------
# Broker Configuration and Select Broker, as OpenAlgo Desktop has them
# --------------------------------------------------------------------------


def _put(client, broker, sign_out=False, **form):
    query = "?sign_out=true" if sign_out else ""
    return client.put(f"/api/broker/credentials/{broker}{query}", json=form)


def _forget(client, broker, sign_out=False):
    query = "?sign_out=true" if sign_out else ""
    return client.delete(f"/api/broker/credentials/{broker}{query}")


def _listed(client):
    data = client.get("/api/broker/list").get_json()["data"]
    return data, {b["id"]: b for b in data["brokers"]}


def test_the_broker_pages_need_an_openalgo_sign_in(stores, environment):
    client = _app().test_client()

    assert client.get("/api/broker/list", headers=JSON).status_code == 401
    assert client.put("/api/broker/credentials/fyers", json={}, headers=JSON).status_code == 401
    assert client.delete("/api/broker/credentials/fyers", headers=JSON).status_code == 401


def test_every_broker_is_listed_before_any_broker_login(stores, environment):
    """A new install adds its first broker here, before any broker login."""
    data, brokers = _listed(_signed_in(_app()))

    assert data["logged_in"] is None and data["switch_refusal"] is None
    assert sorted(brokers) == sorted(broker_keys.enabled_brokers())
    assert not any(b["configured"] or b["active"] for b in brokers.values())
    fyers = brokers["fyers"]
    assert fyers["name"] == "Fyers" and fyers["sign_in"] == "redirect"
    assert [f["label"] for f in fyers["fields"]] == ["App ID", "App Secret"]
    assert fyers["redirect_url"] == fyers["redirect_url_automatic"]
    assert fyers["redirect_url"] == "http://127.0.0.1:5000/fyers/callback"
    assert "NSE" in fyers["exchanges"]
    # A form broker has no redirect URL.
    assert brokers["angel"]["redirect_url"] is None


def test_the_list_never_returns_a_secret(stores, environment):
    environment.write(ENV_ZERODHA)
    _save_fyers()

    response = _signed_in(_app()).get("/api/broker/list")
    brokers = {b["id"]: b for b in response.get_json()["data"]["brokers"]}

    body = response.get_data(as_text=True)
    for secret in ("fyers-secret-value", "FYAPP-100", "zsecret456", "zkey123"):
        assert secret not in body
    saved = {b: {f["key"]: f["saved"] for f in brokers[b]["fields"]} for b in ("zerodha", "fyers")}
    # An API key shows a prefix, a secret no character of itself.
    assert saved["zerodha"] == {"api_key": "zkey12********", "api_secret": "********"}
    assert saved["fyers"] == {"api_key": "FYAPP-********", "api_secret": "********"}
    assert (brokers["zerodha"]["source"], brokers["fyers"]["source"]) == ("env", "saved")
    assert response.headers["Cache-Control"] == "no-store"


def test_the_list_names_the_logged_in_broker_and_why_it_cannot_switch(
    stores, environment, monkeypatch
):
    environment.write(ENV_ZERODHA)
    _save_fyers()
    _logged_in("zerodha")
    monkeypatch.setattr(broker_switch, "_blockers", lambda username: (0, 1, 0, 0))

    data, brokers = _listed(_signed_in(_app()))

    assert data["logged_in"] == "zerodha"
    assert brokers["zerodha"]["active"] and not brokers["fyers"]["active"]
    assert data["switch_refusal"].startswith("Zerodha still has 1 running Live OpenScript run.")


@pytest.mark.parametrize(
    "broker, form, expected, status",
    [
        ("fyers", {"api_key": "k\nREDIRECT_URL=x", "api_secret": "s"}, "line break", 400),
        ("fyers", {"api_key": "k" * 2000, "api_secret": "s"}, "longer than", 400),
        ("dhan", {"api_key": "plain", "api_secret": "s"}, "client_id:::api_key", 400),
        (
            "fyers",
            {
                "api_key": "k",
                "api_secret": "s",
                "redirect_url": "https://x.example/zerodha/callback",
            },
            "ending in /fyers/callback",
            400,
        ),
        (
            "fyers",
            {"api_key": "k", "api_secret": "s", "redirect_url": "javascript:x/fyers/callback"},
            "full address",
            400,
        ),
        (
            "angel",
            {"api_key": "k", "redirect_url": "https://x.example/angel/callback"},
            "does not use a redirect URL",
            400,
        ),
        ("fyers", {"api_key": "k"}, "Enter the App Secret to save Fyers.", 400),
        ("fyers", {}, "Nothing to save", 400),
        ("upstox-x", {"api_key": "k"}, "Choose a broker from the list.", 404),
    ],
)
def test_saving_refuses_bad_input(stores, environment, broker, form, expected, status):
    response = _put(_signed_in(_app()), broker, **form)

    assert response.status_code == status
    assert expected in response.get_json()["message"]
    assert keys_db.list_broker_keys() == []


def test_saving_a_broker_keeps_its_keys_in_openalgo(stores, environment):
    """Nothing is written to .env and nothing needs a restart."""
    environment.write(ENV_ZERODHA)
    before = environment.file.read_bytes()
    client = _signed_in(_app())

    saved = _put(client, "fyers", api_key="FYAPP-100", api_secret="fyers-secret-value")
    kept = _put(client, "fyers", api_secret="fyers-secret-2")
    _, brokers = _listed(client)

    assert saved.get_json() == {
        "status": "success",
        "message": "Saved your Fyers settings.",
        "signed_out": False,
    }
    assert kept.status_code == 200
    stored = broker_keys.resolve("fyers")
    assert (stored.api_key, stored.api_secret) == ("FYAPP-100", "fyers-secret-2")
    assert brokers["fyers"]["configured"] and not brokers["fyers"]["active"]
    assert environment.file.read_bytes() == before


def test_saving_the_env_brokers_keys_writes_env(stores, environment):
    """The broker .env names keeps its keys there, and .env still comes first."""
    environment.write(ENV_ZERODHA)

    response = _put(_signed_in(_app()), "zerodha", api_secret="new-zerodha-secret")

    assert response.status_code == 200
    assert "BROKER_API_SECRET = 'new-zerodha-secret'" in environment.file.read_text()
    assert keys_db.get_broker_keys("zerodha") is None
    assert broker_keys.resolve("zerodha").api_secret == "new-zerodha-secret"


def test_the_redirect_url_is_automatic_or_the_traders_own(stores, environment, monkeypatch):
    client = _signed_in(_app())
    custom = "https://trade.example.com/fyers/callback"

    _put(client, "fyers", api_key="FYAPP-100", api_secret="s", redirect_url="")
    monkeypatch.setenv("HOST_SERVER", "https://new.example.com")
    automatic = broker_keys.resolve("fyers").redirect_url
    _put(client, "fyers", redirect_url=custom)
    kept = broker_keys.resolve("fyers").redirect_url
    _put(client, "fyers", api_secret="s2")
    still = broker_keys.resolve("fyers").redirect_url
    # "Use automatic" sends the automatic address itself.
    _put(client, "fyers", redirect_url="https://new.example.com/fyers/callback")
    _, brokers = _listed(client)

    assert automatic == "https://new.example.com/fyers/callback"
    assert kept == still == custom
    assert keys_db.get_broker_keys("fyers").redirect_url == ""
    assert brokers["fyers"]["redirect_url_is_default"] is True


def test_new_keys_for_the_logged_in_broker_end_its_session_once_confirmed(
    stores, environment, monkeypatch
):
    """A session belongs to the keys it signed in with."""
    monkeypatch.setattr(auth_bp_module.socketio, "emit", lambda *a, **k: None)
    _save_fyers()
    _logged_in("fyers")
    client = _signed_in(_app())

    asked = _put(client, "fyers", api_secret="new-secret")
    unchanged = keys_db.get_broker_keys("fyers").api_secret
    confirmed = _put(client, "fyers", sign_out=True, api_secret="new-secret")

    assert asked.status_code == 409
    assert "confirm to save them" in asked.get_json()["message"]
    assert unchanged == "fyers-secret-value"
    assert confirmed.get_json()["signed_out"] is True
    assert confirmed.get_json()["message"] == (
        "Saved your Fyers keys and ended its session. Log in again to use them."
    )
    assert keys_db.get_broker_keys("fyers").api_secret == "new-secret"
    assert broker_keys.live_broker() is None
    assert _probe(client) == 200


def test_a_redirect_url_alone_leaves_the_session_running(stores, environment):
    _save_fyers()
    _logged_in("fyers")

    response = _put(
        _signed_in(_app()), "fyers", redirect_url="https://t.example.com/fyers/callback"
    )

    assert response.get_json()["signed_out"] is False
    assert broker_keys.live_broker() == "fyers"


def test_forgetting_a_broker(stores, environment, monkeypatch):
    monkeypatch.setattr(auth_bp_module.socketio, "emit", lambda *a, **k: None)
    environment.write(ENV_ZERODHA)
    _save_fyers()
    keys_db.save_broker_keys("upstox", {"api_key": "up", "api_secret": "us"}, None)
    monkeypatch.setenv("VALID_BROKERS", "zerodha,fyers,upstox")
    _logged_in("fyers")
    client = _signed_in(_app())

    env_broker = _forget(client, "zerodha")
    plain = _forget(client, "upstox")
    again = _forget(client, "upstox")
    asked = _forget(client, "fyers")
    confirmed = _forget(client, "fyers", sign_out=True)

    assert env_broker.status_code == 400 and ".env file" in env_broker.get_json()["message"]
    assert plain.get_json() == {
        "status": "success",
        "message": "Forgot your Upstox keys.",
        "signed_out": False,
    }
    assert again.status_code == 404
    assert asked.status_code == 409
    assert confirmed.get_json()["message"] == "Signed out of Fyers and forgot its keys."
    assert keys_db.get_broker_keys("fyers") is None
    assert broker_keys.live_broker() is None


def test_live_automation_keeps_the_logged_in_broker(stores, environment, monkeypatch):
    """Ending the session for new keys or a forget is refused like a switch."""
    _save_fyers()
    _logged_in("fyers")
    monkeypatch.setattr(broker_switch, "_blockers", lambda username: (0, 0, 1, 0))
    client = _signed_in(_app())

    saved = _put(client, "fyers", sign_out=True, api_secret="new")
    forgot = _forget(client, "fyers", sign_out=True)

    assert saved.status_code == forgot.status_code == 409
    assert "1 running Python strategy" in saved.get_json()["message"]
    assert keys_db.get_broker_keys("fyers").api_secret == "fyers-secret-value"
    assert broker_keys.live_broker() == "fyers"


def test_a_login_under_way_holds_off_its_keys(stores, environment):
    _save_fyers()
    holder = broker_keys.hold_login_slot("fyers")
    try:
        client = _signed_in(_app())
        saved = _put(client, "fyers", api_secret="new")
        forgot = _forget(client, "fyers")
    finally:
        broker_keys.release_login_slot(holder)

    assert saved.status_code == forgot.status_code == 409
    assert "A login to Fyers is under way" in saved.get_json()["message"]
    assert keys_db.get_broker_keys("fyers").api_secret == "fyers-secret-value"


def test_writes_need_the_csrf_token(stores, environment):
    client = _signed_in(_app(csrf=True))
    form = {"api_key": "FYAPP-100", "api_secret": "s"}

    refused = _put(client, "fyers", **form)
    accepted = client.put(
        "/api/broker/credentials/fyers", json=form, headers={"X-CSRFToken": _csrf(client)}
    )
    forget_refused = _forget(client, "fyers")

    assert refused.status_code == 400 and forget_refused.status_code == 400
    assert accepted.status_code == 200


def test_profile_server_settings_still_save_to_env(stores, environment):
    environment.write(ENV_ZERODHA)
    client = _signed_in(_app())

    saved = client.post("/api/broker/credentials", data={"host_server": "https://algo.example.com"})
    keys = client.post("/api/broker/credentials", data={"broker_api_key": "k"})

    assert saved.get_json()["restart_required"] is True
    assert "HOST_SERVER = 'https://algo.example.com'" in environment.file.read_text()
    # Keys are saved on Broker Configuration, not here.
    assert keys.status_code == 400


# --------------------------------------------------------------------------
# Starting a broker login on the server, and checking the answer
# --------------------------------------------------------------------------


@pytest.fixture
def completed(monkeypatch):
    """Record completed logins instead of running the real session setup."""
    calls = []

    def fake_success(auth_token, user, broker, **kwargs):
        from flask import g

        calls.append((auth_token, user, broker))
        g.broker_login_completed = True
        return "logged in"

    monkeypatch.setattr(brlogin, "handle_auth_success", fake_success)
    return calls


def test_open_dashboard_joins_the_live_session(stores, environment, monkeypatch):
    """On the web the logged-in broker may have been logged in to on another
    device, so Open Dashboard on its card joins that session first."""
    from flask import jsonify

    joined = []

    def fake_resume(username):
        joined.append(username)
        return jsonify({"status": "success", "redirect": "/dashboard"})

    _logged_in("zerodha")
    client = _signed_in(_app())
    monkeypatch.setattr(auth_bp_module, "_try_resume_broker_session", fake_resume)
    resumed = client.post("/auth/broker/resume")
    monkeypatch.setattr(auth_bp_module, "_try_resume_broker_session", lambda username: None)
    ended = client.post("/auth/broker/resume")

    assert resumed.get_json()["status"] == "success" and joined == [USER]
    assert ended.status_code == 409
    assert (
        ended.get_json()["message"] == "That broker session has ended. Log in to the broker again."
    )
    assert _app().test_client().post("/auth/broker/resume").status_code == 401
    assert _signed_in(_app(csrf=True)).post("/auth/broker/resume").status_code == 400


def test_the_server_builds_the_sign_in_address(stores, environment):
    _save_fyers()
    client = _signed_in(_app())

    body = client.post("/auth/broker/login", json={"broker": "fyers"}).get_json()

    assert body["url"].startswith(
        "https://api-t1.fyers.in/api/v3/generate-authcode?client_id=FYAPP-100"
    )
    assert "fyers-secret-value" not in body["url"]
    with client.session_transaction() as sess:
        assert sess["broker_login"]["broker"] == "fyers"


def test_a_login_to_another_broker_starts_unless_live_automation_runs(
    stores, environment, monkeypatch
):
    """Desktop parity: logging in to another broker is allowed while one is
    live (its session ends when the new login completes), and refused while
    the live broker still runs Live automation."""
    environment.write(ENV_ZERODHA)
    _save_fyers()
    _logged_in("zerodha")
    client = _signed_in(_app())

    started = client.post("/auth/broker/login", json={"broker": "fyers"})
    monkeypatch.setattr(broker_switch, "_blockers", lambda username: (1, 0, 0, 2))
    refused = client.post("/auth/broker/login", json={"broker": "fyers"})

    assert started.status_code == 200
    assert os.environ["BROKER_API_KEY"] == "zkey123"
    assert refused.status_code == 409
    assert refused.get_json()["message"] == (
        "Zerodha still has 1 running Live strategy and 2 positions under scalping "
        "protection. They are not moved to another broker. First stop the strategies "
        "and protection, then switch. Nothing was changed."
    )


def test_starting_a_login_needs_a_listed_broker(stores, environment):
    response = _signed_in(_app()).post("/auth/broker/login", json={"broker": "../etc"})

    assert response.status_code == 400


def test_an_answer_no_login_started_is_refused(stores, environment, completed):
    """PINNED DEFECT. Any request token arriving while the trader was signed in
    completed a login, so a link could connect OpenAlgo to someone else's account."""
    environment.write(ENV_ZERODHA)
    exchanged = []
    app = _app()
    app.broker_auth_functions = {
        "zerodha_auth": lambda code: exchanged.append(code) or ("attacker-token", None)
    }

    response = _signed_in(app).get("/zerodha/callback?request_token=attacker")

    assert response.status_code == 302
    assert (
        response.headers["Location"]
        .split("&broker=")[0]
        .endswith("/broker?error=login_not_started")
    )
    assert completed == []
    # Refused before the code ever reaches the broker.
    assert exchanged == []


def test_a_refusal_names_the_broker_so_its_card_shows_it(stores, environment, completed):
    """Select Broker shows the sentence on that broker's card, as OpenAlgo Desktop does."""
    environment.write(ENV_ZERODHA)
    app = _app()
    app.broker_auth_functions = {"zerodha_auth": lambda code: ("t", None)}

    response = _signed_in(app).get("/zerodha/callback?request_token=x")

    assert response.headers["Location"] == "/broker?error=login_not_started&broker=zerodha"


def test_a_sign_in_that_starts_at_the_callback_needs_a_started_login(stores, environment):
    """A link opening /<broker>/callback must not start a sign-in (some brokers
    text the trader an OTP when it does) unless the trader pressed Connect."""
    keys_db.save_broker_keys("angel", {"api_key": "angel-app"}, None)
    app = _app()
    app.broker_auth_functions = {"angel_auth": lambda *a: (None, None, "unused")}
    client = _signed_in(app)

    linked = client.get("/angel/callback")
    client.post("/auth/broker/login", json={"broker": "angel"})
    started = client.get("/angel/callback")

    assert (
        linked.headers["Location"].split("&broker=")[0].endswith("/broker?error=login_not_started")
    )
    assert started.headers["Location"].endswith("/broker/angel/totp")


def test_a_started_login_completes_once(stores, environment, completed):
    environment.write(ENV_ZERODHA)
    app = _app()
    app.broker_auth_functions = {"zerodha_auth": lambda code: ("access", None)}
    client = _signed_in(app)

    client.post("/auth/broker/login", json={"broker": "zerodha"})
    first = client.get("/zerodha/callback?request_token=ok")
    replay = client.get("/zerodha/callback?request_token=ok")

    assert first.get_data(as_text=True) == "logged in"
    assert completed == [("zkey123:access", USER, "zerodha")]
    assert (
        replay.headers["Location"].split("&broker=")[0].endswith("/broker?error=login_not_started")
    )


def test_the_callback_runs_with_the_saved_keys(stores, environment, completed):
    environment.write(ENV_ZERODHA)
    _save_fyers()
    seen = {}

    def fyers_auth(code):
        seen["key"] = os.getenv("BROKER_API_KEY")
        return "fy-token", None

    app = _app()
    app.broker_auth_functions = {"fyers_auth": fyers_auth}
    client = _signed_in(app)
    url = client.post("/auth/broker/login", json={"broker": "fyers"}).get_json()["url"]
    state = url.rsplit("state=", 1)[1]

    client.get(f"/fyers/callback?auth_code=c&state={state}")

    assert seen["key"] == "FYAPP-100"
    assert completed == [("fy-token", USER, "fyers")]


def test_a_state_broker_answer_is_checked_against_its_state(stores, environment, completed):
    _save_fyers()
    app = _app()
    app.broker_auth_functions = {"fyers_auth": lambda code: ("fy-token", None)}
    starter = _signed_in(app)
    starter.post("/auth/broker/login", json={"broker": "fyers"})

    # Another signed-in browser carrying a state it made up.
    wrong = _signed_in(app).get("/fyers/callback?auth_code=c&state=guessed")

    assert (
        wrong.headers["Location"].split("&broker=")[0].endswith("/broker?error=login_not_started")
    )
    assert completed == []


def _xts_post(client, state=None, token="xts-access"):
    query = f"?state={state}" if state else ""
    return client.post(
        f"/compositedge/callback{query}",
        data=f'session={{"accessToken": "{token}"}}',
        content_type="application/x-www-form-urlencoded",
    )


@pytest.fixture
def xts(stores, environment, monkeypatch):
    """CompositEdge with saved keys and an admin account, as the callback needs."""
    import database.user_db as user_db

    monkeypatch.setattr(user_db, "find_user_by_username", lambda: SimpleNamespace(username=USER))
    keys_db.save_broker_keys("compositedge", {"api_key": "ce-app", "api_secret": "ce-secret"}, None)
    app = _app()
    app.broker_auth_functions = {
        "compositedge_auth": lambda token: ("ce-token", "feed", "uid", None)
    }
    return app


def _started_xts_state(app):
    url = (
        _signed_in(app)
        .post("/auth/broker/login", json={"broker": "compositedge"})
        .get_json()["url"]
    )
    from urllib.parse import parse_qs, unquote, urlparse

    return_url = unquote(parse_qs(urlparse(url).query)["returnURL"][0])
    return parse_qs(urlparse(return_url).query)["state"][0]


def test_the_xts_return_address_carries_the_state(xts):
    url = (
        _signed_in(xts)
        .post("/auth/broker/login", json={"broker": "compositedge"})
        .get_json()["url"]
    )

    assert url.startswith(
        "https://xts.compositedge.com/interactive/thirdparty?appKey=ce-app&returnURL="
    )
    assert "http%3A%2F%2F127.0.0.1%3A5000%2Fcompositedge%2Fcallback%3Fstate%3D" in url


def test_an_xts_post_without_the_state_is_refused(xts, completed):
    """PINNED DEFECT. CompositEdge posts back without the cookie, and any such
    post logged the admin in with no password and no check at all."""
    _started_xts_state(xts)
    stranger = xts.test_client()

    missing = _xts_post(stranger)
    guessed = _xts_post(stranger, state="guessed")

    assert (
        missing.headers["Location"].split("&broker=")[0].endswith("/broker?error=login_not_started")
    )
    assert (
        guessed.headers["Location"].split("&broker=")[0].endswith("/broker?error=login_not_started")
    )
    with stranger.session_transaction() as sess:
        assert "user" not in sess and "logged_in" not in sess
    assert completed == []


def test_an_xts_post_with_the_state_completes_once(xts, completed):
    state = _started_xts_state(xts)

    accepted = _xts_post(xts.test_client(), state=state)
    replay = _xts_post(xts.test_client(), state=state)

    assert accepted.get_data(as_text=True) == "logged in"
    assert completed == [("ce-token", USER, "compositedge")]
    assert (
        replay.headers["Location"].split("&broker=")[0].endswith("/broker?error=login_not_started")
    )


def test_a_login_form_post_needs_the_csrf_token(stores, environment):
    keys_db.save_broker_keys("angel", {"api_key": "angel-app"}, None)
    calls = []
    app = _app(csrf=True)
    app.broker_auth_functions = {
        "angel_auth": lambda *args: calls.append(args) or (None, None, "Wrong PIN")
    }
    client = _signed_in(app)
    form = {"userid": "A1", "pin": "1234", "totp": "123456"}

    refused = client.post("/angel/callback", data=form, headers={"Accept": "application/json"})
    client.post(
        "/angel/callback",
        data={**form, "csrf_token": _csrf(client)},
        headers={"Accept": "application/json"},
    )

    assert refused.status_code == 400
    assert refused.get_json()["code"] == "form_expired"
    assert calls == [("A1", "1234", "123456")]


# --------------------------------------------------------------------------
# Sessions: a logout ends every device's sign-in; a broker-less sign-in ends
# at the rollover
# --------------------------------------------------------------------------


def test_a_revocation_ends_every_earlier_sign_in(stores, environment):
    # A broker is configured, so a signed-in browser gets 200 from the probe.
    environment.write(ENV_ZERODHA)
    app = _app()
    other_device = _signed_in(app)
    assert _probe(other_device) == 200

    auth_db.revoke_all_sessions(USER)

    assert _probe(other_device) == 401
    with other_device.session_transaction() as sess:
        assert "user" not in sess
    assert _probe(_signed_in(app)) == 200


def test_a_revoked_broker_session_is_no_longer_valid(stores, environment):
    from utils.session import is_session_valid

    app = _app()
    signed_in = datetime.now(IST).isoformat()
    with app.test_request_context("/"):
        from flask import session

        session.update(user=USER, logged_in=True, login_time=signed_in, auth_at=signed_in)
        assert is_session_valid() is True
        auth_db.revoke_all_sessions(USER)
        assert is_session_valid() is False


def test_a_broker_less_sign_in_ends_at_the_rollover(stores, environment):
    environment.write(ENV_ZERODHA)
    app = _app()
    stale = _signed_in(app)
    with stale.session_transaction() as sess:
        sess["auth_at"] = (last_rollover_boundary() - timedelta(minutes=1)).isoformat()
    legacy = app.test_client()
    with legacy.session_transaction() as sess:
        sess["user"] = USER

    assert _probe(stale) == 401
    assert _probe(legacy) == 401
    assert _probe(_signed_in(app)) == 200


def test_logout_and_password_changes_record_the_revocation(stores, environment, monkeypatch):
    revoked = []
    monkeypatch.setattr(auth_db, "revoke_all_sessions", lambda name: revoked.append(name))
    monkeypatch.setattr(auth_bp_module, "upsert_auth", lambda *a, **k: 1)
    monkeypatch.setattr(auth_bp_module.socketio, "emit", lambda *a, **k: None)
    app = _app()

    broker_less = _signed_in(app)
    broker_less.post("/auth/logout", headers={"Sec-Fetch-Site": "same-origin"})
    assert revoked == []  # signing out of the broker page ends only that browser

    logged_in = _signed_in(app, logged_in=True, login_time=datetime.now(IST).isoformat())
    logged_in.post("/auth/logout", headers={"Sec-Fetch-Site": "same-origin"})
    assert revoked == [USER]


# --------------------------------------------------------------------------
# The websocket proxy, 5paisa, the migration and the startup check
# --------------------------------------------------------------------------


def test_the_proxy_puts_the_keys_in_place_after_importing_the_adapter(monkeypatch):
    import websocket_proxy.broker_factory as factory

    order = []
    monkeypatch.setattr(
        factory, "_get_adapter_class", lambda name: order.append("import") or object
    )
    monkeypatch.setattr(
        broker_keys,
        "use_broker_keys",
        lambda broker, check_live=True: order.append(("keys", broker, check_live)),
    )

    factory.create_broker_adapter("fyers", use_pooling=False)

    assert order == ["import", ("keys", "fyers", False)]


def test_fivepaisa_reads_its_keys_when_called(monkeypatch):
    """PINNED DEFECT. 5paisa split BROKER_API_KEY at import, so importing it with
    another broker's keys in place raised, and it kept stale keys after a switch."""
    import importlib

    monkeypatch.setenv("BROKER_API_KEY", "not-a-5paisa-key")
    order_api = importlib.reload(importlib.import_module("broker.fivepaisa.api.order_api"))
    data = importlib.reload(importlib.import_module("broker.fivepaisa.api.data"))

    monkeypatch.setenv("BROKER_API_KEY", "UK:::UID:::CL1")

    assert order_api._client_request() == {"head": {"key": "UK"}, "body": {"ClientCode": "CL1"}}
    assert data._fivepaisa_keys() == ("UK", "UID", "CL1")


def _migrate(db_file, *args):
    env = {**os.environ, "DATABASE_URL": f"sqlite:///{db_file.as_posix()}"}
    return subprocess.run(
        [sys.executable, str(Path("upgrade") / "migrate_broker_keys.py"), *args],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
    )


def test_the_migration_adds_its_tables_once(tmp_path):
    db_file = tmp_path / "openalgo.db"
    import sqlite3
    from contextlib import closing

    # closing(): a sqlite3 connection used as a context manager commits but
    # stays open, and Windows cannot remove a file that is still open.
    with closing(sqlite3.connect(db_file)) as conn:
        conn.execute("CREATE TABLE users (id INTEGER PRIMARY KEY)")
        conn.commit()

    status = _migrate(db_file, "--status")
    assert status.returncode == 0, status.stdout + status.stderr
    assert "Would create 3 table(s)." in status.stdout

    first = _migrate(db_file)
    again = _migrate(db_file)

    assert first.returncode == 0 and "[OK] Created broker_keys" in first.stdout
    assert again.returncode == 0 and "[SKIP] All tables already exist" in again.stdout
    with closing(sqlite3.connect(db_file)) as conn:
        names = {r[0] for r in conn.execute("SELECT name FROM sqlite_master")}
    assert {
        "broker_keys",
        "session_revocations",
        "broker_login_states",
        "ix_broker_keys_broker",
    } <= names


def test_the_migration_adds_only_what_is_missing(tmp_path):
    """A database that already has some of the tables (an earlier build of
    this change, or a start that created them) gets the rest, and its rows
    are left alone."""
    import sqlite3
    from contextlib import closing

    db_file = tmp_path / "openalgo.db"
    with closing(sqlite3.connect(db_file)) as conn:
        conn.execute(
            "CREATE TABLE broker_keys (id INTEGER PRIMARY KEY, broker VARCHAR(50) NOT NULL UNIQUE, "
            "api_key TEXT NOT NULL, api_secret TEXT NOT NULL, api_key_market TEXT NOT NULL, "
            "api_secret_market TEXT NOT NULL, redirect_url VARCHAR(500) NOT NULL, "
            "created_at DATETIME, updated_at DATETIME)"
        )
        conn.execute(
            "INSERT INTO broker_keys (broker, api_key, api_secret, api_key_market, "
            "api_secret_market, redirect_url) VALUES ('fyers', 'c1', 'c2', '', '', '')"
        )
        conn.commit()

    status = _migrate(db_file, "--status")
    applied = _migrate(db_file)

    assert "Would create 2 table(s)." in status.stdout
    assert "broker_keys            present" in status.stdout
    assert "[OK] Created session_revocations" in applied.stdout
    assert "Created broker_keys" not in applied.stdout
    with closing(sqlite3.connect(db_file)) as conn:
        assert conn.execute("SELECT broker, api_key FROM broker_keys").fetchall() == [
            ("fyers", "c1")
        ]


def test_the_migration_creates_no_database(tmp_path):
    db_file = tmp_path / "absent.db"

    result = _migrate(db_file)

    assert result.returncode == 0
    assert not db_file.exists()


def _run_startup_check(tmp_path, redirect_url):
    """Run the real startup check against a copy of .sample.env."""
    root = tmp_path / "install"
    (root / "utils").mkdir(parents=True)
    (root / "utils" / "env_check.py").write_text(
        (ROOT / "utils" / "env_check.py").read_text(encoding="utf-8"), encoding="utf-8"
    )
    sample = (ROOT / ".sample.env").read_text(encoding="utf-8")
    (root / ".sample.env").write_text(sample, encoding="utf-8")
    lines = []
    for line in sample.splitlines():
        key = line.split("=", 1)[0].strip()
        if key == "REDIRECT_URL":
            line = f"REDIRECT_URL = '{redirect_url}'"
        elif key in ("BROKER_API_KEY", "BROKER_API_SECRET") and not redirect_url:
            line = f"{key} = ''"
        elif key in ("APP_KEY", "API_KEY_PEPPER"):
            line = f"{key} = '{os.urandom(32).hex()}'"
        lines.append(line)
    (root / ".env").write_text("\n".join(lines) + "\n", encoding="utf-8")
    env = {k: v for k, v in os.environ.items() if not k.startswith(("BROKER_", "REDIRECT_"))}
    return subprocess.run(
        [
            sys.executable,
            "-c",
            "import sys; sys.path.insert(0, sys.argv[1]); "
            "from utils.env_check import load_and_check_env_variables as check; "
            "check(); print('STARTED')",
            str(root),
        ],
        cwd=root,
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
    )


def test_startup_accepts_an_env_without_a_broker(tmp_path):
    result = _run_startup_check(tmp_path, "")

    assert "STARTED" in result.stdout, result.stdout + result.stderr
    assert "add your broker keys in Broker Configuration" in result.stdout


def _bare_install(tmp_path):
    """A fresh download: the startup check and .sample.env, no .env, no database."""
    root = tmp_path / "fresh"
    (root / "utils").mkdir(parents=True)
    (root / "utils" / "env_check.py").write_text(
        (ROOT / "utils" / "env_check.py").read_text(encoding="utf-8"), encoding="utf-8"
    )
    (root / ".sample.env").write_bytes((ROOT / ".sample.env").read_bytes())
    return root


def _start(root):
    env = {k: v for k, v in os.environ.items() if not k.startswith(("BROKER_", "REDIRECT_"))}
    for key in ("APP_KEY", "API_KEY_PEPPER", "FERNET_SALT", "DATABASE_URL"):
        env.pop(key, None)
    return subprocess.run(
        [
            sys.executable,
            "-c",
            "import sys; sys.path.insert(0, sys.argv[1]); "
            "from utils.env_check import load_and_check_env_variables as check; "
            "check(); print('STARTED')",
            str(root),
        ],
        cwd=root,
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
    )


def test_a_fresh_download_starts_and_writes_its_own_env(tmp_path):
    """Download OpenAlgo, run it: .env is created with fresh keys and no broker."""
    from dotenv import dotenv_values

    root = _bare_install(tmp_path)

    result = _start(root)

    assert "STARTED" in result.stdout, result.stdout + result.stderr
    assert "Created .env from .sample.env" in result.stdout
    created = dotenv_values(root / ".env")
    sample = dotenv_values(root / ".sample.env")
    assert len(created["APP_KEY"]) == 64 and len(created["API_KEY_PEPPER"]) == 64
    assert len(created["FERNET_SALT"]) == 32
    for key in ("APP_KEY", "API_KEY_PEPPER", "FERNET_SALT"):
        assert "PLACEHOLDER" not in created[key]
        int(created[key], 16)
    for key in ("BROKER_API_KEY", "BROKER_API_SECRET", "REDIRECT_URL"):
        assert created[key] == ""
    assert created["FLASK_HOST_IP"] == sample["FLASK_HOST_IP"] == "127.0.0.1"
    assert created["ENV_CONFIG_VERSION"] == sample["ENV_CONFIG_VERSION"]
    if os.name == "posix":
        assert (root / ".env").stat().st_mode & 0o077 == 0
    assert not list(root.glob(".env.*.tmp"))


def test_every_fresh_install_gets_its_own_keys(tmp_path):
    from dotenv import dotenv_values

    first, second = _bare_install(tmp_path / "a"), _bare_install(tmp_path / "b")
    _start(first)
    _start(second)

    assert dotenv_values(first / ".env")["APP_KEY"] != dotenv_values(second / ".env")["APP_KEY"]


@pytest.mark.parametrize("database", ["openalgo.db", "openalgo2.db", "logs.db"])
def test_no_env_is_made_over_an_existing_database(tmp_path, database):
    """New keys would make the stored passwords and tokens unreadable, whatever
    the database is called (a second instance keeps openalgo2.db)."""
    root = _bare_install(tmp_path)
    (root / "db").mkdir()
    (root / "db" / database).write_bytes(b"")

    result = _start(root)

    assert result.returncode == 1
    assert not (root / ".env").exists()
    assert "restore your .env" in result.stdout


def test_a_fresh_clone_with_only_the_db_readme_gets_its_env(tmp_path):
    root = _bare_install(tmp_path)
    (root / "db").mkdir()
    (root / "db" / "readme.txt").write_text("database files live here\n", encoding="utf-8")

    result = _start(root)

    assert "STARTED" in result.stdout, result.stdout + result.stderr
    assert (root / ".env").exists()


def test_an_existing_env_is_never_rewritten(tmp_path):
    from utils.env_check import create_env_from_sample

    env = tmp_path / ".env"
    env.write_text("APP_KEY = 'mine'\n", encoding="utf-8")

    assert create_env_from_sample(str(env), str(ROOT / ".sample.env")) is False
    assert env.read_text(encoding="utf-8") == "APP_KEY = 'mine'\n"


def test_a_route_needing_a_broker_login_keeps_a_broker_less_sign_in(stores, environment):
    """PINNED DEFECT. Found driving the broker keys page: a browser error made
    the page report it to a route that needs a broker login, the decorator
    treated the broker-less sign-in as expired, revoked tokens, broadcast a
    logout and cleared the session, so the next save went back to /login."""
    from utils.session import check_session_validity

    _logged_in("zerodha")
    app = _app()

    @app.route("/needs-broker")
    @check_session_validity
    def needs_broker():
        return "ok"

    client = _signed_in(app)
    refused = client.get("/needs-broker", headers={"Accept": "application/json"})

    assert refused.status_code == 401
    with client.session_transaction() as sess:
        assert sess["user"] == USER
    assert client.get("/api/broker/credentials").status_code == 200
    assert auth_db.Auth.query.filter_by(name=USER).one().is_revoked is False


REAL_ENV_LINES = {
    "APP_KEY": "a1" * 32,
    "API_KEY_PEPPER": "b2" * 32,
    "FERNET_SALT": "c3" * 16,
    "BROKER_API_KEY": "zkey123",
    "BROKER_API_SECRET": "zsecret456",
    "BROKER_API_KEY_MARKET": "",
    "BROKER_API_SECRET_MARKET": "",
    "REDIRECT_URL": "http://127.0.0.1:5000/zerodha/callback",
}


def _existing_install(tmp_path):
    """An install that already has a .env with its own keys and broker."""
    root = _bare_install(tmp_path)
    lines = []
    for line in (root / ".sample.env").read_text(encoding="utf-8").splitlines():
        key = line.split("=", 1)[0].strip()
        if key in REAL_ENV_LINES and not line.lstrip().startswith("#"):
            line = f"{key} = '{REAL_ENV_LINES[key]}'"
        lines.append(line)
    # API_KEY_PEPPER then FERNET_SALT adjacent, as a provisioned install has them.
    text = "\n".join(lines) + "\n"
    (root / ".env").write_text(text, encoding="utf-8")
    return root


def test_startup_never_changes_an_existing_envs_keys_or_broker(tmp_path):
    """An existing .env keeps its APP_KEY, pepper, salt and broker values, on a
    server or a container restart. The only edit startup may make to such a
    file is moving the FERNET_SALT line next to API_KEY_PEPPER, value kept;
    after that, starting again leaves the file byte for byte as it was."""
    import hashlib

    from dotenv import dotenv_values

    root = _existing_install(tmp_path)

    first = _start(root)
    settled = hashlib.sha256((root / ".env").read_bytes()).hexdigest()
    second = _start(root)

    assert "STARTED" in first.stdout, first.stdout + first.stderr
    assert "STARTED" in second.stdout
    assert "Created .env" not in first.stdout
    after = dotenv_values(root / ".env")
    for key, value in REAL_ENV_LINES.items():
        assert after[key] == value, key
    assert hashlib.sha256((root / ".env").read_bytes()).hexdigest() == settled


def test_using_saving_and_forgetting_other_brokers_never_writes_the_env_file(stores, environment):
    """Broker keys reach the plugins through the process environment only; the
    .env file is read, never written, by using a broker, saving or forgetting
    another broker's keys, or starting a login."""
    environment.write(ENV_ZERODHA)
    _save_fyers()
    before = environment.file.read_bytes()
    client = _signed_in(_app())

    broker_keys.use_broker_keys("fyers")
    broker_keys.use_broker_keys("zerodha")
    _put(client, "fyers", api_secret="other")
    _forget(client, "fyers")
    client.post("/auth/broker/login", json={"broker": "zerodha"})

    assert environment.file.read_bytes() == before


# --------------------------------------------------------------------------
# The started-login state lives in the database, as hashes
# --------------------------------------------------------------------------


def _start_zerodha(app):
    client = _signed_in(app)
    client.post("/auth/broker/login", json={"broker": "zerodha"})
    with client.session_transaction() as sess:
        marker = dict(sess["broker_login"])
    return client, marker


def test_a_started_login_survives_a_restart(stores, environment, completed):
    """The trader is at the broker's site when OpenAlgo restarts: the login
    still completes, because its state is in the database, not in memory."""
    environment.write(ENV_ZERODHA)
    app = _app()
    app.broker_auth_functions = {"zerodha_auth": lambda code: ("access", None)}
    client, _marker = _start_zerodha(app)
    cookie = client.get_cookie("session").value

    restarted = _app()
    restarted.broker_auth_functions = {"zerodha_auth": lambda code: ("access", None)}
    browser = restarted.test_client()
    browser.set_cookie("session", cookie)
    answer = browser.get("/zerodha/callback?request_token=ok")

    assert answer.get_data(as_text=True) == "logged in"
    assert completed == [("zkey123:access", USER, "zerodha")]


def test_only_digests_of_the_login_state_are_stored(stores, environment):
    import hashlib

    from sqlalchemy import text

    environment.write(ENV_ZERODHA)
    _client, marker = _start_zerodha(_app())

    with stores.engine.connect() as conn:
        row = conn.execute(text("SELECT nonce_hash, state_hash FROM broker_login_states")).one()

    assert row[0] == hashlib.sha256(marker["nonce"].encode()).hexdigest()
    assert row[1] == hashlib.sha256(marker["state"].encode()).hexdigest()
    assert marker["nonce"] not in row and marker["state"] not in row


def test_an_expired_login_is_refused(stores, environment, completed):
    from sqlalchemy import text

    environment.write(ENV_ZERODHA)
    app = _app()
    app.broker_auth_functions = {"zerodha_auth": lambda code: ("access", None)}
    client, _marker = _start_zerodha(app)
    with stores.engine.begin() as conn:
        conn.execute(text("UPDATE broker_login_states SET expires_at = '2000-01-01 00:00:00'"))

    answer = client.get("/zerodha/callback?request_token=ok")

    assert (
        answer.headers["Location"].split("&broker=")[0].endswith("/broker?error=login_not_started")
    )
    assert completed == []


def test_the_started_logins_stay_few(stores, environment):
    environment.write(ENV_ZERODHA)
    client = _signed_in(_app())

    for _ in range(keys_db.MAX_LOGIN_STATES + 5):
        client.post("/auth/broker/login", json={"broker": "zerodha"})

    assert keys_db.BrokerLoginState.query.count() == keys_db.MAX_LOGIN_STATES


def test_a_started_login_is_used_up_by_exactly_one_answer(stores, environment):
    keys_db.record_login_state("zerodha", "nonce-1", "state-1")
    state_id = keys_db.find_login_state("zerodha", nonce="nonce-1")

    assert keys_db.consume_login_state(state_id) is True
    assert keys_db.consume_login_state(state_id) is False
    assert keys_db.find_login_state("zerodha", nonce="nonce-1") is None


def test_a_copied_sample_env_starts_with_fresh_keys_and_no_broker(tmp_path):
    """cp .sample.env .env, then start: the public placeholder keys are replaced
    with fresh random ones and the "<broker>" placeholder means no broker is set
    in .env, so the broker is added in OpenAlgo. It used to stop startup."""
    from dotenv import dotenv_values

    root = _bare_install(tmp_path)
    (root / ".env").write_bytes((root / ".sample.env").read_bytes())

    first = _start(root)
    keys = dotenv_values(root / ".env")
    second = _start(root)

    assert "STARTED" in first.stdout, first.stdout + first.stderr
    assert "No broker is set in .env" in first.stdout
    assert "Created .env" not in first.stdout
    for key, length in (("APP_KEY", 64), ("API_KEY_PEPPER", 64), ("FERNET_SALT", 32)):
        assert "PLACEHOLDER" not in keys[key], key
        assert len(keys[key]) == length and int(keys[key], 16) >= 0
    # A later start keeps the keys it was given.
    assert "STARTED" in second.stdout
    assert dotenv_values(root / ".env") == keys


def _hand_over(broker, **session_values):
    """Run the completion hand-over as a login to `broker` from this browser."""
    from utils.auth_utils import _hand_over_from_live_broker

    with _app().test_request_context("/"):
        from flask import session

        session["user"] = USER
        session.update(session_values)
        refusal = _hand_over_from_live_broker(USER, broker)
        return refusal, dict(session)


def test_a_completed_login_to_another_broker_ends_the_live_session(
    stores, environment, monkeypatch
):
    """Desktop parity: the old session ends when the new login completes, on
    every device; the browser that logged in stays signed in."""
    monkeypatch.setattr(auth_bp_module.socketio, "emit", lambda *a, **k: None)
    environment.write(ENV_ZERODHA)
    _save_fyers()
    _logged_in("zerodha")
    app = _app()
    other_device = _signed_in(app, logged_in=True, login_time=datetime.now(IST).isoformat())

    refusal, this_session = _hand_over("fyers")

    assert refusal is None
    assert broker_keys.live_broker() is None
    assert auth_db.Auth.query.filter_by(name=USER).one().is_revoked is True
    assert _probe(other_device) == 401
    with app.test_request_context("/"):
        from flask import session

        session.update(this_session)
        from utils.session import sign_in_revoked

        assert sign_in_revoked() is False


def test_a_login_that_would_strand_live_automation_does_not_complete(
    stores, environment, monkeypatch
):
    """Checked again when the login completes: the old broker stays logged in,
    and the trader is sent back to its card with the reason."""
    environment.write(ENV_ZERODHA)
    _save_fyers()
    _logged_in("zerodha")
    monkeypatch.setattr(broker_switch, "_blockers", lambda username: (2, 0, 0, 0))
    from utils.auth_utils import handle_auth_success

    refusal, _ = _hand_over("fyers")
    with _app().test_request_context("/fyers/callback"):
        from flask import session

        session["user"] = USER
        answer = handle_auth_success("fy-token", USER, "fyers")

    assert refusal.startswith("Zerodha still has 2 running Live strategies.")
    assert answer.headers["Location"] == "/broker?error=switch_refused&broker=fyers"
    assert broker_keys.live_broker() == "zerodha"


def test_a_logged_in_crypto_broker_keeps_its_session_past_the_rollover(
    stores, environment, monkeypatch
):
    """Delta Exchange trades around the clock. The installer turns the daily
    expiry off when it is chosen at install time; a crypto broker whose keys are
    saved in OpenAlgo never passed the installer, so the logged-in broker
    decides. An abandoned Delta login decides nothing: its callback put Delta's
    keys in the environment, but the stored session is unchanged."""
    from utils.session import is_session_expiry_disabled

    monkeypatch.delenv("DISABLE_SESSION_EXPIRY", raising=False)
    monkeypatch.setenv("VALID_BROKERS", "zerodha,deltaexchange")
    environment.write(ENV_ZERODHA)
    keys_db.save_broker_keys("deltaexchange", {"api_key": "d-key", "api_secret": "d-sec"}, None)
    broker_keys.forget_logged_in_broker()

    broker_keys.use_broker_keys("deltaexchange")
    assert os.environ["BROKER_API_KEY"] == "d-key"
    assert is_session_expiry_disabled() is False

    _logged_in("deltaexchange")
    broker_keys.forget_logged_in_broker()
    assert is_session_expiry_disabled() is True
    assert broker_keys.broker_type("../zerodha") == ""


def _password_changed_today(broker):
    """A live broker token whose device sessions a password change cleared."""
    now = datetime.now(IST).replace(tzinfo=None)
    auth_db.db_session.add(
        auth_db.Auth(name=USER, auth=auth_db.encrypt_token("tok"), broker=broker, is_revoked=False)
    )
    auth_db.db_session.add(
        auth_db.LoginAttempt(
            username=USER, status="success", login_type="oauth", broker=broker, timestamp=now
        )
    )
    auth_db.db_session.commit()


def test_a_password_change_does_not_free_the_broker_slot(stores, environment):
    """PINNED DEFECT (review). A password change clears every device session but
    leaves the broker token live; the slot was judged by device sessions alone,
    so a login to another broker wrote its keys under the live session."""
    environment.write(ENV_ZERODHA)
    _save_fyers()
    _password_changed_today("zerodha")

    assert auth_db.get_active_sessions(USER) == []
    client = _signed_in(_app())
    started = client.post("/auth/broker/login", json={"broker": "fyers"})
    listed = client.get("/api/broker/list").get_json()["data"]

    # Still the logged-in broker, and starting another login wrote nothing.
    assert listed["logged_in"] == "zerodha"
    assert started.status_code == 200
    assert os.environ["BROKER_API_KEY"] == "zkey123"


def test_a_login_recorded_before_the_rollover_does_not_hold_the_slot(stores, environment):
    environment.write(ENV_ZERODHA)
    _save_fyers()
    auth_db.db_session.add(
        auth_db.Auth(
            name=USER, auth=auth_db.encrypt_token("tok"), broker="zerodha", is_revoked=False
        )
    )
    auth_db.db_session.add(
        auth_db.LoginAttempt(
            username=USER,
            status="success",
            login_type="oauth",
            broker="zerodha",
            timestamp=(last_rollover_boundary() - timedelta(hours=2)).replace(tzinfo=None),
        )
    )
    auth_db.db_session.commit()

    assert broker_keys.live_broker() is None


def test_a_sign_in_is_never_stamped_at_or_before_the_last_revocation(stores, environment):
    """PINNED DEFECT (review). Windows with Python 3.12 ticks about every 15 ms:
    ending a broker session revoked and re-stamped this browser in one tick,
    and the browser it promised to keep signed in read as ended."""
    from sqlalchemy import text

    from utils.session import mark_signed_in, sign_in_revoked

    future = datetime.now(UTC) + timedelta(milliseconds=50)
    with stores.engine.begin() as conn:
        conn.execute(
            text("INSERT INTO session_revocations (username, revoked_at) VALUES (:u, :t)"),
            {"u": USER, "t": future.replace(tzinfo=None)},
        )
    auth_db._session_revocation_cache.invalidate()

    with _app().test_request_context("/"):
        from flask import session

        session["user"] = USER
        mark_signed_in()

        assert datetime.fromisoformat(session["auth_at"]) > future
        assert sign_in_revoked() is False


def test_what_counts_as_live_automation(tmp_path, monkeypatch):
    """Strategy module runs in Live mode, OpenScript runs started Live, and while
    the platform is live, running Python strategies and protected positions."""
    import database.settings_db as settings_db
    import database.strategy_module_db as sm
    import services.openscript_run_config as run_config
    import services.openscript_running as running

    engine = create_db_engine(f"sqlite:///{(tmp_path / 'sm.db').as_posix()}")
    session, previous = _swap_store(monkeypatch, sm, engine)
    try:
        for i, (status, mode) in enumerate(
            [("running", "live"), ("running", "sandbox"), ("stopped", "live")]
        ):
            strategy = sm.SmStrategy(
                user_id=USER,
                name=f"s{i}",
                universe_tab="index",
                underlying="NIFTY",
                underlying_exchange="NSE_INDEX",
                webhook_token_hash=f"{i:064d}",
                status=status,
            )
            session.add(strategy)
            session.flush()
            run = sm.SmStrategyRun(strategy_id=strategy.id, mode=mode)
            session.add(run)
            session.flush()
            strategy.current_run_id = run.id
        session.commit()
        modes = {"a": "live", "b": "sandbox", "c": ""}
        monkeypatch.setattr(running, "all_running", lambda: dict.fromkeys(modes, {}))
        monkeypatch.setattr(run_config, "run_mode_of", lambda name: modes[name])
        python_host = SimpleNamespace(snapshot_running_strategies=lambda: [("1", "x"), ("2", "y")])
        monitor = SimpleNamespace(protected_count=lambda: 3)
        scalping = SimpleNamespace(get_scalping_risk_monitor=lambda: monitor)
        monkeypatch.setitem(sys.modules, "blueprints.python_strategy", python_host)
        monkeypatch.setitem(sys.modules, "services.scalping_risk_monitor_service", scalping)

        monkeypatch.setattr(settings_db, "get_analyze_mode", lambda: False)
        live_platform = _REAL_BLOCKERS(USER)
        monkeypatch.setattr(settings_db, "get_analyze_mode", lambda: True)
        analyzer = _REAL_BLOCKERS(USER)
    finally:
        sm.Base.query = previous
        session.remove()
        engine.dispose()

    # An OpenScript run with no recorded mode follows the platform.
    assert live_platform == (1, 2, 2, 3)
    assert analyzer == (1, 1, 0, 0)


def test_no_strategy_table_means_none_running(tmp_path, monkeypatch):
    import database.strategy_module_db as sm

    engine = create_db_engine(f"sqlite:///{(tmp_path / 'empty.db').as_posix()}")
    from sqlalchemy.orm import scoped_session, sessionmaker

    monkeypatch.setattr(sm, "db_session", scoped_session(sessionmaker(bind=engine)))
    previous = sm.Base.__dict__["query"]
    sm.Base.query = sm.db_session.query_property()
    try:
        assert sm.count_live_running_strategies(USER) == 0
    finally:
        sm.Base.query = previous
        engine.dispose()


def test_a_check_that_cannot_run_refuses_the_switch(monkeypatch):
    def broken(username):
        raise RuntimeError("database unavailable")

    monkeypatch.setattr(broker_switch, "_blockers", broken)

    assert broker_switch.switch_refusal("zerodha", USER) == (
        "OpenAlgo could not check whether anything still runs on Zerodha. "
        "Nothing was changed. Try again."
    )


def test_a_login_to_the_logged_in_broker_ends_nothing(stores, environment):
    environment.write(ENV_ZERODHA)
    _logged_in("zerodha")

    refusal, _ = _hand_over("zerodha")

    assert refusal is None
    assert broker_keys.live_broker() == "zerodha"


def test_a_login_that_does_not_complete_puts_the_live_brokers_keys_back(stores, environment):
    """The callback of a login to another broker writes that broker's keys
    while the logged-in one may still trade; refused, failed or only showing a
    form, the logged-in broker gets its keys back."""
    environment.write(ENV_ZERODHA)
    _save_fyers()
    _logged_in("zerodha")
    broker_keys.use_broker_keys("zerodha")
    app = _app()
    seen = {}

    def failing_exchange(code):
        seen["key"] = os.getenv("BROKER_API_KEY")
        return None, "Invalid auth code"

    app.broker_auth_functions = {"fyers_auth": failing_exchange}
    client = _signed_in(app)
    url = client.post("/auth/broker/login", json={"broker": "fyers"}).get_json()["url"]
    client.get(f"/fyers/callback?auth_code=c&state={url.rsplit('state=', 1)[1]}")

    assert seen["key"] == "FYAPP-100"
    assert os.environ["BROKER_API_KEY"] == "zkey123"


def test_a_refused_callback_leaves_the_keys_of_a_login_under_way(stores, environment, monkeypatch):
    """PINNED DEFECT (security review). Every callback that did not complete put
    the logged-in broker's keys back, including a refused or forged one that
    never took the slot, so it could overwrite the keys of another login in the
    middle of its exchange. Only the request holding the slot restores."""
    environment.write(ENV_ZERODHA)
    _save_fyers()
    _logged_in("zerodha")
    restored = []
    monkeypatch.setattr(brlogin, "restore_logged_in_broker_keys", restored.append)
    holder = broker_keys.hold_login_slot("fyers")
    try:
        broker_keys.use_broker_keys("fyers")
        forged = _signed_in(_app()).get("/angel/callback?request_token=x")
    finally:
        broker_keys.release_login_slot(holder)

    assert (
        forged.headers["Location"].split("&broker=")[0].endswith("/broker?error=login_not_started")
    )
    assert restored == []
    assert os.environ["BROKER_API_KEY"] == "FYAPP-100"


def test_the_keys_of_a_login_under_way_are_never_restored_over(stores, environment):
    environment.write(ENV_ZERODHA)
    _save_fyers()
    _logged_in("zerodha")
    holder = broker_keys.hold_login_slot("fyers")
    try:
        broker_keys.use_broker_keys("fyers")
        broker_keys.restore_logged_in_broker_keys("angel")
        during = os.environ["BROKER_API_KEY"]
    finally:
        broker_keys.release_login_slot(holder)

    assert during == "FYAPP-100"


def test_a_resume_waits_for_a_login_to_another_broker(stores, environment):
    environment.write(ENV_ZERODHA)
    _save_fyers()
    _logged_in("zerodha")
    holder = broker_keys.hold_login_slot("fyers")
    try:
        broker_keys.use_broker_keys("fyers")
        with _app().test_request_context("/"):
            resumed = auth_bp_module._try_resume_broker_session(USER)
        during = os.environ["BROKER_API_KEY"]
    finally:
        broker_keys.release_login_slot(holder)

    assert resumed is None
    assert during == "FYAPP-100"


def test_a_completed_login_keeps_its_own_keys(stores, environment, completed):
    environment.write(ENV_ZERODHA)
    _save_fyers()
    _logged_in("zerodha")
    app = _app()
    app.broker_auth_functions = {"fyers_auth": lambda code: ("fy-token", None)}
    client = _signed_in(app)
    url = client.post("/auth/broker/login", json={"broker": "fyers"}).get_json()["url"]

    client.get(f"/fyers/callback?auth_code=c&state={url.rsplit('state=', 1)[1]}")

    assert completed == [("fy-token", USER, "fyers")]
    assert os.environ["BROKER_API_KEY"] == "FYAPP-100"


def test_a_password_change_ends_every_other_sign_in(stores, environment, monkeypatch):
    revoked = []
    monkeypatch.setattr(auth_db, "revoke_all_sessions", lambda name: revoked.append(name))
    monkeypatch.setattr(auth_db, "clear_user_sessions", lambda name: None)
    monkeypatch.setattr(auth_bp_module.socketio, "emit", lambda *a, **k: None)
    user = SimpleNamespace(check_password=lambda pw: True, set_password=lambda pw: None)
    monkeypatch.setattr(
        auth_bp_module,
        "User",
        SimpleNamespace(
            query=SimpleNamespace(filter_by=lambda **k: SimpleNamespace(first=lambda: user))
        ),
    )
    monkeypatch.setattr(auth_bp_module, "db_session", SimpleNamespace(commit=lambda: None))
    client = _signed_in(_app(), logged_in=True, login_time=datetime.now(IST).isoformat())

    response = client.post(
        "/auth/change-password",
        data={
            "old_password": "Old-pass1!",
            "new_password": "New-pass2!",
            "confirm_password": "New-pass2!",
        },
    )

    assert response.status_code == 200, response.get_data(as_text=True)
    assert revoked == [USER]


def test_a_started_login_is_won_by_exactly_one_of_two_racing_answers(stores, environment):
    """Answers for one login arriving together (a double redirect, a replay):
    the delete decides, so exactly one completes it."""
    import threading

    keys_db.record_login_state("zerodha", "nonce-race", "state-race")
    state_id = keys_db.find_login_state("zerodha", nonce="nonce-race")
    barrier = threading.Barrier(8)
    results = []

    def answer():
        barrier.wait()
        results.append(keys_db.consume_login_state(state_id))

    threads = [threading.Thread(target=answer) for _ in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=30)

    assert sorted(results) == [False] * 7 + [True]


def test_an_answer_whose_login_was_used_up_meanwhile_is_refused(stores, environment, completed):
    """Two answers for one login pass the entry check together. The one whose
    code exchange finishes second finds the login used up and must not
    complete a second time."""
    environment.write(ENV_ZERODHA)
    app = _app()
    client, marker = _start_zerodha(app)

    def exchange_while_the_other_answer_wins(code):
        keys_db.consume_login_state(keys_db.find_login_state("zerodha", nonce=marker["nonce"]))
        return "access", None

    app.broker_auth_functions = {"zerodha_auth": exchange_while_the_other_answer_wins}
    answer = client.get("/zerodha/callback?request_token=ok")

    assert (
        answer.headers["Location"].split("&broker=")[0].endswith("/broker?error=login_not_started")
    )
    assert completed == []


def test_an_answer_replayed_with_the_earlier_cookie_is_refused(stores, environment, completed):
    """Sessions are signed cookies, so the cookie from before the answer still
    carries the marker. The started login itself is used up, so a replay with
    that cookie, or a second redirect sent with it, completes nothing."""
    environment.write(ENV_ZERODHA)
    app = _app()
    app.broker_auth_functions = {"zerodha_auth": lambda code: ("access", None)}
    client, _marker = _start_zerodha(app)
    cookie = client.get_cookie("session").value

    first = client.get("/zerodha/callback?request_token=ok")
    replay_browser = app.test_client()
    replay_browser.set_cookie("session", cookie)
    replay = replay_browser.get("/zerodha/callback?request_token=ok")

    assert first.get_data(as_text=True) == "logged in"
    assert (
        replay.headers["Location"].split("&broker=")[0].endswith("/broker?error=login_not_started")
    )
    assert completed == [("zkey123:access", USER, "zerodha")]


def test_the_last_check_matches_an_answer_by_itself(stores, environment):
    """verify_broker_return is what completes a login. The callback's entry
    check usually refuses first, so its own matching is pinned here."""
    keys_db.record_login_state("zerodha", "nonce-z", "state-z")
    keys_db.record_login_state("fyers", "nonce-f", "state-f")

    with _app().test_request_context():
        # Nothing started from this browser, and no state.
        with pytest.raises(broker_login.BrokerLoginRefused):
            broker_login.verify_broker_return("zerodha")
        # A broker that answers with the cookie cannot complete on a state alone.
        with pytest.raises(broker_login.BrokerLoginRefused):
            broker_login.verify_broker_return("zerodha", state="state-z")
        # A state issued for another broker.
        with pytest.raises(broker_login.BrokerLoginRefused):
            broker_login.verify_broker_return("pocketful", state="state-f")

        broker_login.verify_broker_return("fyers", state="state-f")
        with pytest.raises(broker_login.BrokerLoginRefused):
            broker_login.verify_broker_return("fyers", state="state-f")


def test_dhan_consent_needs_a_started_login(stores, environment, monkeypatch):
    """PINNED DEFECT (review). /dhan/initiate-oauth asked Dhan for a consent
    for any signed-in browser that opened it, a link from another site too."""
    from broker.dhan.api import auth_api as dhan_auth

    keys_db.save_broker_keys("dhan", {"api_key": "1100:::dhan-key", "api_secret": "s"}, None)
    asked = []
    monkeypatch.setattr(
        dhan_auth, "generate_consent", lambda client: asked.append(client) or ("c1", None)
    )
    monkeypatch.setattr(dhan_auth, "get_login_url", lambda consent: "https://auth.dhan.co/login")
    client = _signed_in(_app())

    linked = client.get("/dhan/initiate-oauth")
    assert (
        linked.headers["Location"].split("&broker=")[0].endswith("/broker?error=login_not_started")
    )
    assert asked == []

    client.post("/auth/broker/login", json={"broker": "dhan"})
    started = client.get("/dhan/initiate-oauth")
    assert started.status_code == 200
    assert asked == ["1100"]


def test_iifl_capital_carries_the_state_and_its_answer_is_checked(
    stores, environment, completed, monkeypatch
):
    """IIFL Capital returns to the callback address as given, by a GET or a
    POST; the state rides on that address, as OpenAlgo Desktop sends it."""
    from urllib.parse import parse_qs, urlparse

    import database.user_db as user_db

    monkeypatch.setattr(user_db, "find_user_by_username", lambda: SimpleNamespace(username=USER))
    monkeypatch.setenv("VALID_BROKERS", "iiflcapital")
    keys_db.save_broker_keys("iiflcapital", {"api_key": "iifl-app", "api_secret": "iifl-sec"}, None)
    app = _app()
    app.broker_auth_functions = {"iiflcapital_auth": lambda code, client: ("iifl-token", None)}
    starter = _signed_in(app)
    starter.post("/auth/broker/login", json={"broker": "iiflcapital"})

    start = starter.get("/iiflcapital/callback")
    return_url = parse_qs(urlparse(start.headers["Location"]).query)["redirecturl"][0]
    state = parse_qs(urlparse(return_url).query)["state"][0]

    forged = app.test_client().post(
        "/iiflcapital/callback?state=guessed", data={"authCode": "x", "clientId": "c"}
    )
    answered = app.test_client().post(
        f"/iiflcapital/callback?state={state}", data={"authCode": "a1", "clientId": "c1"}
    )

    assert (
        forged.headers["Location"].split("&broker=")[0].endswith("/broker?error=login_not_started")
    )
    assert answered.get_data(as_text=True) == "logged in"
    assert [c[2] for c in completed] == ["iiflcapital"]


def test_a_state_broker_answer_needs_its_state_even_in_the_browser_that_started(
    stores, environment, completed
):
    """PINNED DEFECT (review). The browser marker alone let any code through for
    a broker that echoes the state: with a login pending for Fyers, a link
    carrying someone else's code and a wrong or missing state completed it."""
    _save_fyers()
    exchanged = []
    app = _app()
    app.broker_auth_functions = {
        "fyers_auth": lambda code: exchanged.append(code) or ("fy-token", None)
    }
    client = _signed_in(app)
    url = client.post("/auth/broker/login", json={"broker": "fyers"}).get_json()["url"]
    state = url.rsplit("state=", 1)[1]

    wrong = client.get("/fyers/callback?auth_code=attacker&state=guessed")
    missing = client.get("/fyers/callback?auth_code=attacker")
    right = client.get(f"/fyers/callback?auth_code=mine&state={state}")

    assert (
        wrong.headers["Location"].split("&broker=")[0].endswith("/broker?error=login_not_started")
    )
    assert (
        missing.headers["Location"].split("&broker=")[0].endswith("/broker?error=login_not_started")
    )
    assert right.get_data(as_text=True) == "logged in"
    # Refused before the code ever reaches the broker.
    assert exchanged == ["mine"]
    assert completed == [("fy-token", USER, "fyers")]


def test_an_iifl_capital_answer_without_its_state_never_completes(
    stores, environment, completed, monkeypatch
):
    """IIFL Capital starts at the callback with no state, so a stateless request
    from the browser that pressed Connect gets in; an answer without the state
    must still not complete the login."""
    monkeypatch.setenv("VALID_BROKERS", "iiflcapital")
    keys_db.save_broker_keys("iiflcapital", {"api_key": "iifl-app", "api_secret": "iifl-sec"}, None)
    app = _app()
    app.broker_auth_functions = {"iiflcapital_auth": lambda code, client: ("iifl-token", None)}
    client = _signed_in(app)
    client.post("/auth/broker/login", json={"broker": "iiflcapital"})

    answer = client.get("/iiflcapital/callback?authCode=attacker&clientId=c")

    assert (
        answer.headers["Location"].split("&broker=")[0].endswith("/broker?error=login_not_started")
    )
    assert completed == []


def test_an_rmoney_login_still_starts_at_the_callback(stores, environment, monkeypatch):
    """RMoney's callback builds its sign-in address when opened with no answer,
    which carries no state yet: the browser that pressed Connect gets in, with
    its own state on the return address, and any other browser does not."""
    from urllib.parse import parse_qs, unquote, urlparse

    monkeypatch.setenv("VALID_BROKERS", "rmoney")
    keys_db.save_broker_keys("rmoney", {"api_key": "rm-app", "api_secret": "rm-sec"}, None)
    app = _app()
    app.broker_auth_functions = {"rmoney_auth": lambda *args: (None, None)}
    client = _signed_in(app)
    client.post("/auth/broker/login", json={"broker": "rmoney"})

    other = _signed_in(app).get("/rmoney/callback")
    start = client.get("/rmoney/callback")

    return_url = unquote(parse_qs(urlparse(start.headers["Location"]).query)["returnURL"][0])
    with client.session_transaction() as sess:
        state = sess["broker_login"]["state"]
    assert return_url.endswith(f"/rmoney/callback?state={state}")
    assert (
        other.headers["Location"].split("&broker=")[0].endswith("/broker?error=login_not_started")
    )


# --------------------------------------------------------------------------
# One login at a time writes its keys: the broker login slot
# --------------------------------------------------------------------------


def test_starting_a_login_leaves_the_keys_in_place(stores, environment):
    """Starting a login only builds the sign-in address. It used to write the
    keys too, which let a second device's start replace them underneath a
    login that was still exchanging its code."""
    environment.write(ENV_ZERODHA)
    _save_fyers()
    broker_keys.use_broker_keys("zerodha")

    response = _signed_in(_app()).post("/auth/broker/login", json={"broker": "fyers"})

    assert response.status_code == 200
    assert os.environ["BROKER_API_KEY"] == "zkey123"


def test_a_login_under_way_keeps_another_brokers_login_out(stores, environment, completed):
    """PINNED DEFECT (review). Two devices logging in to different brokers at
    once: while one callback exchanged its code, the other put its own keys in
    place, and the first stored its token alongside the second broker's keys."""
    environment.write(ENV_ZERODHA)
    _save_fyers()
    app = _app()
    other = _signed_in(app)
    url = other.post("/auth/broker/login", json={"broker": "fyers"}).get_json()["url"]
    state = url.rsplit("state=", 1)[1]
    during = {}

    def zerodha_exchange(code):
        # The other device starts and answers while this exchange is under way.
        during["start"] = other.post("/auth/broker/login", json={"broker": "fyers"}).status_code
        during["answer"] = other.get(f"/fyers/callback?auth_code=c&state={state}")
        during["key"] = os.getenv("BROKER_API_KEY")
        return "access", None

    app.broker_auth_functions = {
        "zerodha_auth": zerodha_exchange,
        "fyers_auth": lambda code: ("fy-token", None),
    }
    client = _signed_in(app)
    client.post("/auth/broker/login", json={"broker": "zerodha"})
    client.get("/zerodha/callback?request_token=ok")

    assert during["start"] == 409
    assert (
        during["answer"]
        .headers["Location"]
        .split("&broker=")[0]
        .endswith("/broker?error=broker_unavailable")
    )
    assert during["key"] == "zkey123"
    assert completed == [("zkey123:access", USER, "zerodha")]
    assert os.environ["BROKER_API_KEY"] == "zkey123"
    # The slot is free again once that login has finished.
    assert other.post("/auth/broker/login", json={"broker": "fyers"}).status_code == 200


def test_a_login_that_fails_gives_the_slot_back(stores, environment):
    environment.write(ENV_ZERODHA)
    app = _app()
    client = _signed_in(app)

    app.broker_auth_functions = {"zerodha_auth": lambda code: (None, "Invalid request token")}
    client.post("/auth/broker/login", json={"broker": "zerodha"})
    client.get("/zerodha/callback?request_token=bad")
    assert broker_keys.login_slot_broker() is None

    def broken(code):
        raise RuntimeError("the broker did not answer")

    app.broker_auth_functions = {"zerodha_auth": broken}
    client.post("/auth/broker/login", json={"broker": "zerodha"})
    try:
        client.get("/zerodha/callback?request_token=ok")
    except RuntimeError:
        pass
    assert broker_keys.login_slot_broker() is None


def test_a_stuck_login_holds_the_slot_for_a_while_only(monkeypatch):
    now = [1000.0]
    monkeypatch.setattr(broker_keys, "time", SimpleNamespace(monotonic=lambda: now[0]))
    stuck = broker_keys.hold_login_slot("zerodha")
    with pytest.raises(broker_keys.BrokerKeysRefused, match="A login to Zerodha is under way"):
        broker_keys.hold_login_slot("fyers")

    now[0] += broker_keys.LOGIN_SLOT_SECONDS + 1
    fyers = broker_keys.hold_login_slot("fyers")
    # The stuck login finishing late frees nothing of the one that took over.
    broker_keys.release_login_slot(stuck)
    assert broker_keys.login_slot_broker() == "fyers"
    broker_keys.release_login_slot(fyers)
    assert broker_keys.login_slot_broker() is None


def test_logins_racing_for_the_slot_let_exactly_one_broker_in():
    """Logins to the same broker share the slot; another broker waits for all of them."""
    import threading

    barrier = threading.Barrier(8)
    held = []
    lock = threading.Lock()

    def take(broker):
        barrier.wait()
        try:
            holder = broker_keys.hold_login_slot(broker)
        except broker_keys.BrokerKeysRefused:
            return
        with lock:
            held.append((broker, holder))

    threads = [threading.Thread(target=take, args=(b,)) for b in ("zerodha", "fyers") * 4]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=30)

    assert len(held) == 4
    assert len({broker for broker, _ in held}) == 1
    for _, holder in held[:-1]:
        broker_keys.release_login_slot(holder)
    assert broker_keys.login_slot_broker() == held[-1][0]
    broker_keys.release_login_slot(held[-1][1])
    assert broker_keys.login_slot_broker() is None


def test_a_link_to_another_brokers_callback_leaves_a_logged_in_session_alone(stores, environment):
    """PINNED DEFECT (review, older than this change). A logged-in session that
    opened /<other broker>/callback was switched to that broker."""
    app = _app()
    app.add_url_rule("/dashboard", "dashboard_bp.dashboard", lambda: "dashboard")
    client = _signed_in(
        app, logged_in=True, login_time=datetime.now(IST).isoformat(), broker="zerodha"
    )

    client.get("/fyers/callback?auth_code=x")

    with client.session_transaction() as sess:
        assert sess["broker"] == "zerodha"


@pytest.fixture
def password_paths(monkeypatch):
    """The two other password routes, with the user store and teardown stubbed."""
    revoked = []
    monkeypatch.setattr(auth_db, "revoke_all_sessions", lambda name: revoked.append(name))
    monkeypatch.setattr(auth_db, "clear_user_sessions", lambda name: None)
    monkeypatch.setattr(auth_bp_module.socketio, "emit", lambda *a, **k: None)
    user = SimpleNamespace(
        username=USER, check_password=lambda pw: True, set_password=lambda pw: None
    )
    monkeypatch.setattr(
        auth_bp_module,
        "User",
        SimpleNamespace(
            query=SimpleNamespace(filter_by=lambda **k: SimpleNamespace(first=lambda: user))
        ),
    )
    monkeypatch.setattr(auth_bp_module, "find_user_by_email", lambda email: user)
    monkeypatch.setattr(auth_bp_module, "db_session", SimpleNamespace(commit=lambda: None))
    return revoked


def test_the_form_password_change_ends_every_other_sign_in(stores, environment, password_paths):
    client = _signed_in(_app(), logged_in=True, login_time=datetime.now(IST).isoformat())

    response = client.post(
        "/auth/change",
        json={"old_password": "Old-pass1!", "new_password": "New-pass2!"},
    )

    assert response.status_code == 200, response.get_data(as_text=True)
    assert password_paths == [USER]


def test_a_password_reset_ends_every_sign_in(stores, environment, password_paths):
    client = _app().test_client()
    with client.session_transaction() as sess:
        sess["reset_token"] = auth_bp_module._hash_reset_token("reset-token-1")
        sess["reset_email"] = "trader@example.com"

    response = client.post(
        "/auth/reset-password",
        json={
            "step": "password",
            "email": "trader@example.com",
            "token": "reset-token-1",
            "password": "New-pass2!",
        },
    )

    assert response.status_code == 200, response.get_data(as_text=True)
    assert password_paths == [USER]


def test_a_crypto_login_gets_a_cookie_past_the_rollover(stores, environment, monkeypatch):
    """PINNED DEFECT (review round 2). The cookie lifetime is set before the
    login's session is stored, so it must follow the broker being logged in
    to, not the stored session, or a Delta Exchange login with keys saved in
    OpenAlgo got a cookie that ran out at the next rollover."""
    from utils.session import get_session_expiry_time

    monkeypatch.delenv("DISABLE_SESSION_EXPIRY", raising=False)
    broker_keys.forget_logged_in_broker()

    assert get_session_expiry_time("deltaexchange") == timedelta(days=365)
    assert get_session_expiry_time("zerodha") < timedelta(days=1)
