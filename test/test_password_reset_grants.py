"""A password reset is approved once, used once, and lapses on its own.

A reset is approved by a TOTP code or by the emailed link, and the browser is
handed a token for the last step. The token's digest used to live only in the
session cookie. The cookie is signed, but it is the browser's to keep: the
server had no record of the reset, so it could not tell that a token had been
used. A copy of the cookie from before the reset, with its token, set the
password again, and nothing made the token lapse.

``password_reset_grants`` is the server's record. The last step needs the
cookie and an open row, and using the row removes it in the transaction that
writes the password.
"""

from __future__ import annotations

import re
import sys
import threading
import types
from datetime import datetime, timedelta
from pathlib import Path

import pyotp
import pytest
from flask import Flask

import blueprints.auth as auth_module
import database.auth_db as auth_db
import database.user_db as user_db
from database.engine_factory import create_db_engine

REPO_ROOT = Path(__file__).resolve().parent.parent
EMAIL = "trader@example.com"
FIRST = "First-Passw0rd!x"
SECOND = "Second-Passw0rd!y"
TOTP_SECRET = pyotp.random_base32()


@pytest.fixture
def users(tmp_path, monkeypatch):
    """The user tables on a file of their own, holding one account."""
    from sqlalchemy.orm import scoped_session, sessionmaker

    engine = create_db_engine(f"sqlite:///{(tmp_path / 'openalgo.db').as_posix()}")
    session = scoped_session(sessionmaker(autocommit=False, autoflush=False, bind=engine))
    monkeypatch.setattr(user_db, "engine", engine)
    monkeypatch.setattr(user_db, "db_session", session)
    monkeypatch.setattr(auth_module, "db_session", session)
    # Swapped by hand: monkeypatch reads the old value with getattr, and a
    # query property read on the declarative base itself raises.
    previous = user_db.Base.__dict__["query"]
    user_db.Base.query = session.query_property()
    user_db.Base.metadata.create_all(engine)
    user_db.username_cache.clear()

    account = user_db.User(username="trader", email=EMAIL, totp_secret=TOTP_SECRET, is_admin=True)
    account.set_password("Original-Passw0rd!")
    session.add(account)
    session.commit()
    account_id = account.id
    session.remove()
    try:
        yield types.SimpleNamespace(engine=engine, session=session, user_id=account_id)
    finally:
        user_db.username_cache.clear()
        user_db.Base.query = previous
        session.remove()
        engine.dispose()


@pytest.fixture
def site(users, monkeypatch):
    """The auth routes on an app of their own, with what a reset sends recorded."""
    sent: list[str] = []
    signed_out: list[str] = []
    monkeypatch.setattr(auth_db, "clear_user_sessions", lambda username: None)
    monkeypatch.setattr(
        auth_db, "revoke_all_sessions", lambda username: signed_out.append(username)
    )
    monkeypatch.setattr(auth_module.socketio, "emit", lambda *args, **kwargs: None)
    monkeypatch.setattr(auth_module, "get_smtp_settings", lambda: {"smtp_server": "smtp.test"})
    monkeypatch.setattr(
        auth_module, "send_password_reset_email", lambda email, link, username: sent.append(link)
    )
    monkeypatch.setenv("HOST_SERVER", "http://127.0.0.1:5000")

    app = Flask(__name__)
    app.secret_key = "test-secret"
    app.register_blueprint(auth_module.auth_bp)

    @app.teardown_appcontext
    def _release(_exc=None):
        users.session.remove()

    return types.SimpleNamespace(app=app, sent=sent, signed_out=signed_out, users=users)


def _password_is(users, password: str) -> bool:
    try:
        return user_db.User.query.filter_by(email=EMAIL).first().check_password(password)
    finally:
        users.session.remove()


def _open_grants(users) -> list:
    try:
        return user_db.PasswordResetGrant.query.all()
    finally:
        users.session.remove()


def _approve_by_totp(client) -> str:
    """Pass the TOTP step and return the token the browser is handed."""
    response = client.post(
        "/auth/reset-password",
        json={"step": "totp", "email": EMAIL, "totp_code": pyotp.TOTP(TOTP_SECRET).now()},
    )
    assert response.status_code == 200, response.get_json()
    return response.get_json()["token"]


def _set_password(client, token: str, password: str):
    return client.post(
        "/auth/reset-password",
        json={"step": "password", "email": EMAIL, "token": token, "password": password},
    )


def _browser_with(site, cookie: str):
    """Another browser carrying a copy of a session cookie."""
    client = site.app.test_client()
    client.set_cookie("session", cookie)
    return client


# ---------------------------------------------------------------------------
# TOTP approval
# ---------------------------------------------------------------------------


def test_a_reset_approved_by_totp_sets_the_password(site):
    client = site.app.test_client()
    token = _approve_by_totp(client)

    response = _set_password(client, token, FIRST)

    assert response.status_code == 200
    assert _password_is(site.users, FIRST)
    assert site.signed_out == ["trader"]
    assert _open_grants(site.users) == []


def test_the_cookie_and_token_from_before_the_reset_do_not_work_again(site):
    """The defect itself: the same pair, replayed, set the password twice."""
    client = site.app.test_client()
    token = _approve_by_totp(client)
    kept = client.get_cookie("session").value
    assert _set_password(client, token, FIRST).status_code == 200

    replay = _set_password(_browser_with(site, kept), token, SECOND)

    assert replay.status_code == 400
    assert _password_is(site.users, FIRST)
    assert not _password_is(site.users, SECOND)
    assert site.signed_out == ["trader"]


def test_an_approval_lapses_on_its_own(site):
    client = site.app.test_client()
    token = _approve_by_totp(client)
    grant = site.users.session.query(user_db.PasswordResetGrant).one()
    assert grant.expires_at - grant.created_at == timedelta(minutes=15)
    grant.expires_at = datetime.utcnow() - timedelta(seconds=1)
    site.users.session.commit()
    site.users.session.remove()

    response = _set_password(client, token, FIRST)

    assert response.status_code == 400
    assert not _password_is(site.users, FIRST)


def test_a_cookie_with_no_record_on_the_server_sets_nothing(site):
    """A reset started before the upgrade: the cookie alone used to be enough."""
    client = site.app.test_client()
    with client.session_transaction() as cookie:
        cookie["reset_token"] = auth_module._hash_reset_token("a-token-from-before")
        cookie["reset_email"] = EMAIL

    response = _set_password(client, "a-token-from-before", FIRST)

    assert response.status_code == 400
    assert not _password_is(site.users, FIRST)


def test_a_newer_approval_ends_the_one_before_it(site):
    older, newer = site.app.test_client(), site.app.test_client()
    old_token = _approve_by_totp(older)
    new_token = _approve_by_totp(newer)

    assert _set_password(older, old_token, FIRST).status_code == 400
    assert not _password_is(site.users, FIRST)
    assert _set_password(newer, new_token, SECOND).status_code == 200
    assert _password_is(site.users, SECOND)


def test_a_password_that_is_refused_does_not_use_the_approval_up(site):
    client = site.app.test_client()
    token = _approve_by_totp(client)

    assert _set_password(client, token, "weak").status_code == 400
    assert _set_password(client, token, FIRST).status_code == 200
    assert _password_is(site.users, FIRST)


def test_the_token_is_not_enough_without_the_browser_it_was_given_to(site):
    token = _approve_by_totp(site.app.test_client())

    response = _set_password(site.app.test_client(), token, FIRST)

    assert response.status_code == 400
    assert not _password_is(site.users, FIRST)


def test_only_the_digest_of_the_token_is_stored(site):
    token = _approve_by_totp(site.app.test_client())

    (grant,) = _open_grants(site.users)

    assert grant.token_hash == auth_module._hash_reset_token(token)
    assert token not in (grant.token_hash, grant.method)


def test_a_wrong_totp_code_records_nothing(site):
    response = site.app.test_client().post(
        "/auth/reset-password", json={"step": "totp", "email": EMAIL, "totp_code": "000000"}
    )

    assert response.status_code == 400
    assert _open_grants(site.users) == []


def test_a_reset_that_cannot_be_recorded_is_not_approved(site, monkeypatch):
    monkeypatch.setattr(auth_module, "issue_password_reset_grant", lambda *args: False)
    client = site.app.test_client()

    response = client.post(
        "/auth/reset-password",
        json={"step": "totp", "email": EMAIL, "totp_code": pyotp.TOTP(TOTP_SECRET).now()},
    )

    assert response.status_code == 500
    assert "token" not in response.get_json()
    with client.session_transaction() as cookie:
        assert "reset_token" not in cookie


# ---------------------------------------------------------------------------
# Emailed link
# ---------------------------------------------------------------------------


def _request_email(client) -> str:
    """Ask for the emailed link and return the token inside it."""
    response = client.post("/auth/reset-password", json={"step": "select_email", "email": EMAIL})
    assert response.status_code == 200, response.get_json()
    return client.application.config["sent"][-1].rsplit("/", 1)[-1]


@pytest.fixture
def mailbox(site):
    site.app.config["sent"] = site.sent
    return site


def test_an_emailed_link_sets_the_password_once(mailbox):
    client = mailbox.app.test_client()
    token = _request_email(client)
    kept = client.get_cookie("session").value

    landing = client.get(f"/auth/reset-password-email/{token}")
    assert "verified=true" in landing.headers["Location"]
    assert _set_password(client, token, FIRST).status_code == 200
    assert _password_is(mailbox.users, FIRST)

    # The same link in the browser that asked for it, as it was then.
    again = _browser_with(mailbox, kept)
    assert (
        "error=expired_link" in again.get(f"/auth/reset-password-email/{token}").headers["Location"]
    )
    assert _set_password(again, token, SECOND).status_code == 400
    assert _password_is(mailbox.users, FIRST)


def test_an_emailed_link_lasts_the_hour_the_email_promises(mailbox):
    client = mailbox.app.test_client()
    token = _request_email(client)
    grant = mailbox.users.session.query(user_db.PasswordResetGrant).one()
    assert grant.expires_at - grant.created_at == timedelta(hours=1)
    grant.expires_at = datetime.utcnow() - timedelta(seconds=1)
    mailbox.users.session.commit()
    mailbox.users.session.remove()

    landing = client.get(f"/auth/reset-password-email/{token}")

    assert "error=expired_link" in landing.headers["Location"]
    assert _set_password(client, token, FIRST).status_code == 400
    assert not _password_is(mailbox.users, FIRST)


def test_no_email_goes_out_for_a_reset_that_could_not_be_recorded(mailbox, monkeypatch):
    monkeypatch.setattr(auth_module, "issue_password_reset_grant", lambda *args: False)

    response = mailbox.app.test_client().post(
        "/auth/reset-password", json={"step": "select_email", "email": EMAIL}
    )

    assert response.status_code == 500
    assert mailbox.sent == []


# ---------------------------------------------------------------------------
# The record itself
# ---------------------------------------------------------------------------


def test_of_two_requests_arriving_together_one_sets_the_password(users, monkeypatch):
    """Staged at the write: the second arrives after the first has claimed.

    The first caller is held inside the password write, after it has used the
    approval up and before it commits. The second runs its whole call in that
    window, on a thread and a database session of its own, as a second request
    would.
    """
    token_hash = "a" * 64
    assert user_db.issue_password_reset_grant(users.user_id, token_hash, "totp")
    users.session.remove()

    first_is_writing, second_has_finished = threading.Event(), threading.Event()
    original = user_db.User.set_password

    def held(self, password):
        first_is_writing.set()
        # The second caller cannot finish while this transaction holds the
        # write, so the wait ends on the timeout; either way it has started.
        second_has_finished.wait(timeout=1.0)
        return original(self, password)

    monkeypatch.setattr(user_db.User, "set_password", held)
    results: dict[str, bool] = {}

    def first():
        try:
            results["first"] = user_db.reset_password_with_grant(users.user_id, token_hash, FIRST)
        finally:
            users.session.remove()

    def second():
        first_is_writing.wait(timeout=10)
        try:
            results["second"] = user_db.reset_password_with_grant(users.user_id, token_hash, SECOND)
        finally:
            users.session.remove()
            second_has_finished.set()

    threads = [threading.Thread(target=first), threading.Thread(target=second)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=60)

    assert results == {"first": True, "second": False}
    monkeypatch.setattr(user_db.User, "set_password", original)
    assert _password_is(users, FIRST)
    assert not _password_is(users, SECOND)
    assert _open_grants(users) == []


def test_a_password_change_ends_an_open_reset(users):
    token_hash = "b" * 64
    assert user_db.issue_password_reset_grant(users.user_id, token_hash, "totp")

    assert user_db.clear_password_reset_grants(users.user_id)

    assert not user_db.password_reset_grant_is_open(users.user_id, token_hash)
    assert not user_db.reset_password_with_grant(users.user_id, token_hash, FIRST)
    assert not _password_is(users, FIRST)


def test_both_password_change_routes_end_the_open_resets():
    source = (REPO_ROOT / "blueprints" / "auth.py").read_text(encoding="utf-8")
    changes = re.findall(
        r"user\.set_password\(new_password\)\n\s+db_session\.commit\(\)\n(?:\s+#[^\n]*\n)*\s+(\w+)\(user_id\)",
        source,
    )
    assert changes == ["clear_password_reset_grants", "clear_password_reset_grants"]


def test_the_old_password_stops_working_at_once(users):
    """The login cache held the old hash for 30 seconds after a reset."""
    assert user_db.authenticate_user("trader", "Original-Passw0rd!")
    token_hash = "c" * 64
    assert user_db.issue_password_reset_grant(users.user_id, token_hash, "totp")

    assert user_db.reset_password_with_grant(users.user_id, token_hash, FIRST)

    assert not user_db.authenticate_user("trader", "Original-Passw0rd!")
    assert user_db.authenticate_user("trader", FIRST)


def test_an_approval_belongs_to_its_account(users):
    """Another account's id with this account's token sets nothing.

    A second account is created for the purpose, so the claim is refused by
    the account on the record and not by the lookup of an id nobody has.
    """
    other = user_db.User(
        username="other", email="other@example.com", totp_secret=TOTP_SECRET, is_admin=False
    )
    other.set_password("Other-Passw0rd!z")
    users.session.add(other)
    users.session.commit()
    other_id = other.id
    users.session.remove()
    token_hash = "d" * 64
    assert user_db.issue_password_reset_grant(users.user_id, token_hash, "totp")

    assert not user_db.reset_password_with_grant(other_id, token_hash, FIRST)

    try:
        stored = user_db.User.query.filter_by(username="other").first()
        assert stored.check_password("Other-Passw0rd!z")
        assert not stored.check_password(FIRST)
    finally:
        users.session.remove()
    assert user_db.password_reset_grant_is_open(users.user_id, token_hash)
    assert not user_db.password_reset_grant_is_open(other_id, token_hash)


# ---------------------------------------------------------------------------
# Upgrade
# ---------------------------------------------------------------------------


def _run_migration(monkeypatch, db_file: Path, *args: str) -> int:
    sys.path.insert(0, str(REPO_ROOT / "upgrade"))
    try:
        import migrate_password_reset_grants as migration
    finally:
        sys.path.remove(str(REPO_ROOT / "upgrade"))
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_file.as_posix()}")
    monkeypatch.setattr(sys, "argv", ["migrate_password_reset_grants.py", *args])
    return migration.main()


def test_the_migration_adds_the_table_to_an_install_that_lacks_it(tmp_path, monkeypatch, capsys):
    import sqlite3

    db_file = tmp_path / "old.db"
    with sqlite3.connect(db_file) as old:
        old.execute("CREATE TABLE users (id INTEGER PRIMARY KEY, username TEXT)")
        old.execute("INSERT INTO users (username) VALUES ('trader')")

    def tables() -> set:
        with sqlite3.connect(db_file) as db:
            return {
                row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")
            }

    assert _run_migration(monkeypatch, db_file, "--status") == 0
    assert "Would create 1 table." in capsys.readouterr().out
    assert "password_reset_grants" not in tables()

    assert _run_migration(monkeypatch, db_file) == 0
    assert "password_reset_grants" in tables()

    assert _run_migration(monkeypatch, db_file) == 0
    assert "[SKIP]" in capsys.readouterr().out
    with sqlite3.connect(db_file) as db:
        assert db.execute("SELECT username FROM users").fetchall() == [("trader",)]


def test_the_migration_leaves_a_missing_database_alone(tmp_path, monkeypatch):
    db_file = tmp_path / "not-there.db"

    assert _run_migration(monkeypatch, db_file) == 0
    assert not db_file.exists()


def test_the_migration_is_registered_for_upgrades():
    registry = (REPO_ROOT / "upgrade" / "migrate_all.py").read_text(encoding="utf-8")
    assert '"migrate_password_reset_grants.py"' in registry
