"""IIFL market-data token: one token shared by the web worker and the feed.

An XTS market-data session keeps one live token per app key; a login ends the
token before it. The REST data path (web worker) and the live feed (websocket
proxy process) each logged in on their own whenever their token was refused,
so each login ended the other's token. On a live install that ran every five
seconds from 15:25 to 15:35 IST: the feed's subscriptions failed with
``e-session-0007 Invalid Token`` and history requests failed with the same
words. These tests pin the fix: both sides use the stored token, a refusal is
answered with the token the other side already renewed, and a login happens
only when the stored token is the refused one.

The first test of the store reproduces the old behaviour with a stand-in for
the pre-fix refresh, so the pair cannot pass vacuously.
"""

import base64
import json
import threading
import time

import pytest

import database.auth_db as auth_db
from utils import xts_market_token
from utils.xts_market_token import MarketDataTokenStore

BROKER = "iifl"


REPLY_USER_ID = "85703272"  # the login reply's userID, which the socket address takes


def jwt_for(n):
    """A token shaped like an XTS market-data JWT, distinct per ``n``. Its
    userID claim carries a suffix the login reply's userID does not, as real
    ones do ("1048131_856F2F2AF32542B762129")."""
    header = base64.urlsafe_b64encode(b'{"alg":"HS256"}').decode().rstrip("=")
    claims = {"userID": f"{REPLY_USER_ID}_856F2F2AF32542B762129", "n": n}
    payload = base64.urlsafe_b64encode(json.dumps(claims).encode()).decode().rstrip("=")
    return f"{header}.{payload}.sig{n}"


class FakeIifl:
    """IIFL's market-data login: each login ends the token before it."""

    def __init__(self):
        self.logins = 0
        self.live = None
        self._lock = threading.Lock()

    def login(self):
        with self._lock:
            self.logins += 1
            self.live = jwt_for(self.logins)
            return self.live, REPLY_USER_ID, None

    def accepts(self, token):
        return token is not None and token == self.live


@pytest.fixture()
def fresh_db():
    auth_db.init_db()
    auth_db.Auth.query.delete()
    auth_db.db_session.commit()
    auth_db.auth_cache.clear()
    auth_db.feed_token_cache.clear()
    yield
    auth_db.Auth.query.delete()
    auth_db.db_session.commit()
    auth_db.db_session.remove()
    auth_db.feed_token_cache.clear()


@pytest.fixture()
def spy_teardown(monkeypatch):
    """The two side effects that tear the shared feed down."""
    calls = []
    monkeypatch.setattr(
        "database.cache_invalidation.publish_all_cache_invalidation",
        lambda name: calls.append(("publish", name)) or True,
    )
    monkeypatch.setattr(
        "websocket_proxy.broker_factory.cleanup_pools_for_user",
        lambda name, broker_name=None: calls.append(("cleanup", name)) or 0,
    )
    return calls


def signed_in(feed_token, revoked=False):
    """An IIFL auth row as a broker login leaves it."""
    row = auth_db.Auth(
        name="trader",
        auth=auth_db.encrypt_token("interactive-token"),
        feed_token=auth_db.encrypt_token(feed_token) if feed_token else None,
        broker=BROKER,
        is_revoked=revoked,
    )
    auth_db.db_session.add(row)
    auth_db.db_session.commit()


def stored_plaintext():
    return auth_db.read_market_data_token(BROKER)[1]


# --------------------------------------------------------------------------
# Database layer
# --------------------------------------------------------------------------


def test_read_returns_the_stored_token(fresh_db):
    signed_in("tok-A")
    blob, plain = auth_db.read_market_data_token(BROKER)
    assert plain == "tok-A"
    assert blob and blob != "tok-A"  # ciphertext, not the token


def test_read_without_a_signed_in_row(fresh_db):
    assert auth_db.read_market_data_token(BROKER) == (None, None)
    signed_in("tok-A", revoked=True)
    assert auth_db.read_market_data_token(BROKER) == (None, None)


def test_replace_is_a_compare_and_set_on_the_stored_value(fresh_db, spy_teardown):
    signed_in("tok-A")
    blob, _ = auth_db.read_market_data_token(BROKER)

    assert auth_db.replace_market_data_token(BROKER, blob, "tok-B") is True
    assert stored_plaintext() == "tok-B"

    # The row no longer holds what was read: a second writer loses.
    assert auth_db.replace_market_data_token(BROKER, blob, "tok-C") is False
    assert stored_plaintext() == "tok-B"

    # A renewed feed token is not a new broker session: no feed teardown.
    assert spy_teardown == []


def test_replace_never_revives_a_signed_out_row(fresh_db):
    signed_in("tok-A")
    blob, _ = auth_db.read_market_data_token(BROKER)
    row = auth_db.Auth.query.filter_by(name="trader").first()
    row.is_revoked = True
    auth_db.db_session.commit()

    assert auth_db.replace_market_data_token(BROKER, blob, "tok-B") is False
    row = auth_db.Auth.query.filter_by(name="trader").first()
    auth_db.db_session.refresh(row)
    assert row.is_revoked is True
    assert auth_db.decrypt_token(row.feed_token) == "tok-A"


def test_replace_reaches_the_cached_feed_token_readers(fresh_db):
    signed_in("tok-A")
    assert auth_db.get_feed_token("trader") == "tok-A"  # now cached
    blob, _ = auth_db.read_market_data_token(BROKER)
    auth_db.replace_market_data_token(BROKER, blob, "tok-B")
    assert auth_db.get_feed_token("trader") == "tok-B"


# --------------------------------------------------------------------------
# The shared store
# --------------------------------------------------------------------------


def test_old_behaviour_each_refusal_logged_in_and_ended_the_other_side(fresh_db):
    """The defect itself: two sides that each log in on refusal never agree."""
    iifl = FakeIifl()
    worker_token = feed_token = iifl.login()[0]  # the broker login
    logins_at_start = iifl.logins

    for _ in range(5):  # the cycle seen in the journal
        feed_token = iifl.login()[0]  # feed reconnects: own login
        assert not iifl.accepts(worker_token)  # ...which ended the worker's
        worker_token = iifl.login()[0]  # worker refresh: own login
        assert not iifl.accepts(feed_token)  # ...which ended the feed's

    assert iifl.logins - logins_at_start == 10


def test_a_refusal_adopts_the_token_the_other_side_renewed(fresh_db):
    iifl = FakeIifl()
    signed_in(iifl.login()[0])  # broker login stores token 1
    old = stored_plaintext()
    worker = MarketDataTokenStore(BROKER, iifl.login)  # web worker process
    feed = MarketDataTokenStore(BROKER, iifl.login)  # websocket proxy process

    # The token expires: the worker's next request is refused and renews.
    iifl.live = None
    renewed = worker.renew(rejected=old)
    assert iifl.accepts(renewed)
    assert stored_plaintext() == renewed

    # The feed is refused the same old token: it adopts, no second login.
    logins = iifl.logins
    assert feed.renew(rejected=old) == renewed
    assert iifl.logins == logins
    assert iifl.accepts(renewed)  # both sides hold the one live token


def test_a_refused_stored_token_is_renewed_once(fresh_db):
    iifl = FakeIifl()
    signed_in(iifl.login()[0])
    old = stored_plaintext()
    iifl.live = None  # expired at the broker

    store = MarketDataTokenStore(BROKER, iifl.login)
    renewed = store.renew(rejected=old)
    assert renewed != old and iifl.accepts(renewed)
    assert stored_plaintext() == renewed
    assert iifl.logins == 2  # the broker login and this one


def test_concurrent_refusals_in_one_process_log_in_once(fresh_db):
    slow = FakeIifl()
    original = slow.login

    def slow_login():
        time.sleep(0.3)  # long enough for every caller to arrive meanwhile
        return original()

    signed_in(original()[0])
    old = stored_plaintext()
    store = MarketDataTokenStore(BROKER, slow_login)

    results, barrier = [], threading.Barrier(6)

    def refused():
        barrier.wait()
        results.append(store.renew(rejected=old))

    threads = [threading.Thread(target=refused) for _ in range(6)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(10)

    assert slow.logins == 2  # the broker login and exactly one renewal
    assert len(set(results)) == 1 and slow.accepts(results[0])


def test_a_failed_login_returns_none(fresh_db):
    signed_in("tok-A")
    store = MarketDataTokenStore(BROKER, lambda: (None, None, "API Error (Feed): blocked"))
    assert store.renew(rejected="tok-A") is None
    assert stored_plaintext() == "tok-A"


def test_after_a_sign_out_the_renewed_token_is_used_but_not_stored(fresh_db):
    iifl = FakeIifl()
    signed_in(iifl.login()[0], revoked=True)
    store = MarketDataTokenStore(BROKER, iifl.login)
    token = store.renew(rejected=None)
    assert iifl.accepts(token)
    row = auth_db.Auth.query.filter_by(name="trader").first()
    auth_db.db_session.refresh(row)
    assert row.is_revoked is True


def test_one_store_per_broker_per_process():
    a = xts_market_token.market_data_tokens("iifl-test-store", lambda: (None, None, "x"))
    b = xts_market_token.market_data_tokens("iifl-test-store", lambda: (None, None, "y"))
    assert a is b


# --------------------------------------------------------------------------
# The two IIFL callers
# --------------------------------------------------------------------------


def test_rest_refusal_takes_the_feeds_renewed_token_without_a_login(fresh_db, monkeypatch):
    import broker.iifl.api.data as data

    iifl = FakeIifl()
    signed_in(iifl.login()[0])
    stale = stored_plaintext()
    # The feed renewed and stored a newer token meanwhile.
    blob, _ = auth_db.read_market_data_token(BROKER)
    auth_db.replace_market_data_token(BROKER, blob, iifl.login()[0])
    logins = iifl.logins

    monkeypatch.setattr(data, "_MARKET_TOKENS", MarketDataTokenStore(BROKER, iifl.login))

    def fake_api(endpoint, auth, method="GET", payload="", feed_token=None, params=None):
        if iifl.accepts(feed_token):
            return {"type": "success", "result": {"ok": True}}
        return {"type": "error", "description": "Invalid Token"}

    monkeypatch.setattr(data, "get_api_response", fake_api)

    handler = data.BrokerData("interactive-token", feed_token=stale)
    response = handler._market_data_request("/instruments/quotes", method="POST")

    assert response["type"] == "success"
    assert iifl.logins == logins  # adopted, not a login that ends the feed's token
    assert handler.feed_token == stored_plaintext()


class _FakeSio:
    def __init__(self, accepts):
        self.accepts = accepts
        self.connected = False
        self.urls = []
        self.disconnects = 0

    def connect(self, url, **kwargs):
        self.urls.append(url)
        token = url.split("token=")[1].split("&")[0]
        if not self.accepts(token):
            raise ConnectionError("Connection refused by the server")
        self.connected = True

    def disconnect(self):
        self.disconnects += 1
        self.connected = False

    def on(self, *args, **kwargs):
        pass


def _client(monkeypatch, iifl):
    import broker.iifl.streaming.iifl_websocket as ws

    monkeypatch.setattr(ws, "_MARKET_TOKENS", MarketDataTokenStore(BROKER, iifl.login))
    monkeypatch.setattr(ws.socketio, "Client", lambda **kw: _FakeSio(iifl.accepts))
    return ws, ws.IiflWebSocketClient(api_key="k", api_secret="s", user_id="trader")


def test_feed_learns_the_reply_user_id_with_one_login_then_reuses_the_token(fresh_db, monkeypatch):
    iifl = FakeIifl()
    signed_in(iifl.login()[0])  # the broker login
    _ws, client = _client(monkeypatch, iifl)

    client.connect()
    # One login to learn the reply's userID (the token's claim is not it);
    # its token is stored for the web worker.
    assert iifl.logins == 2
    assert f"userID={REPLY_USER_ID}&" in client.sio.urls[-1]
    assert stored_plaintext() == client.market_data_token
    assert iifl.accepts(client.market_data_token)

    # Every later connect in this process uses the stored token: no login.
    for _ in range(3):
        client.sio.disconnect()
        client.connect()
    assert iifl.logins == 2
    assert f"userID={REPLY_USER_ID}&" in client.sio.urls[-1]


def test_worker_adopts_the_token_the_feed_stored(fresh_db, monkeypatch):
    import broker.iifl.api.data as data

    iifl = FakeIifl()
    signed_in(iifl.login()[0])
    worker_token = stored_plaintext()
    _ws, client = _client(monkeypatch, iifl)
    client.connect()  # its learning login ends the worker's token
    logins = iifl.logins

    monkeypatch.setattr(data, "_MARKET_TOKENS", MarketDataTokenStore(BROKER, iifl.login))

    def fake_api(endpoint, auth, method="GET", payload="", feed_token=None, params=None):
        if iifl.accepts(feed_token):
            return {"type": "success", "result": {}}
        return {"type": "error", "description": "Invalid Token"}

    monkeypatch.setattr(data, "get_api_response", fake_api)
    handler = data.BrokerData("interactive-token", feed_token=worker_token)
    assert handler._market_data_request("/instruments/quotes")["type"] == "success"
    assert iifl.logins == logins  # adopted the feed's token
    assert iifl.accepts(client.market_data_token)  # the feed's token still lives


def test_feed_renews_once_when_the_stored_token_is_refused(fresh_db, monkeypatch):
    iifl = FakeIifl()
    signed_in(iifl.login()[0])
    _ws, client = _client(monkeypatch, iifl)
    client.connect()  # learns the reply userID
    logins = iifl.logins

    iifl.live = None  # the stored token expired overnight
    client.sio.disconnect()
    client.connect()

    assert iifl.logins == logins + 1
    assert client.sio.connected and iifl.accepts(client.market_data_token)
    assert stored_plaintext() == client.market_data_token


def test_subscription_refusal_adopts_the_worker_token_and_reconnects(fresh_db, monkeypatch):
    iifl = FakeIifl()
    signed_in(iifl.login()[0])
    ws, client = _client(monkeypatch, iifl)
    client.connect()
    client.connected = True  # what the socket's connect event sets
    connected_sio = client.sio
    feed_token = client.market_data_token

    # The web worker renews (one login) and stores the token.
    worker = MarketDataTokenStore(BROKER, iifl.login)
    iifl.live = None
    worker.renew(rejected=feed_token)
    logins = iifl.logins

    class Refused:
        status_code = 400
        text = '{"type":"error","code":"e-session-0007","description":"Invalid Token"}'

    monkeypatch.setattr(ws.requests, "post", lambda *a, **k: Refused())
    client.subscribe("c1", 1, [{"exchangeSegment": 1, "exchangeInstrumentID": 26000}])

    deadline = time.time() + 5
    while connected_sio.disconnects == 0 and time.time() < deadline:
        time.sleep(0.05)

    assert connected_sio.disconnects == 1  # reconnect with the stored token
    assert iifl.logins == logins  # adopted the worker's token: no login


def test_a_row_with_no_revoked_value_counts_as_signed_in(fresh_db):
    """is_revoked is nullable; the rest of auth_db reads NULL as signed in."""
    signed_in("tok-A")
    row = auth_db.Auth.query.filter_by(name="trader").first()
    row.is_revoked = None
    auth_db.db_session.commit()
    blob, plain = auth_db.read_market_data_token(BROKER)
    assert plain == "tok-A"
    assert auth_db.replace_market_data_token(BROKER, blob, "tok-B") is True
    assert stored_plaintext() == "tok-B"
