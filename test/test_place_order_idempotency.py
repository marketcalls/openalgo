# test/test_place_order_idempotency.py
"""
Tests for application-level order idempotency via client_order_id.

Covers:
- OrderSchema acceptance/normalisation of client_order_id and tag
- The reservation store's reserve / record / release / replay lifecycle
- place_order_with_auth behaviour: dedupe replay, 409 on in-flight races,
  reservation release on broker failure, broker payload stripping
- Orderbook label echo
"""

import os
import tempfile

# Isolate the idempotency store before the module (and its engine) is
# imported. Unconditional assignment: an exported IDEMPOTENCY_DATABASE_URL
# must never point clean_store at a real database. File-backed, not in
# memory: the store engine uses NullPool, so sqlite:// would hand every
# operation a fresh, empty database.
_TMP_STORE_DIR = tempfile.mkdtemp(prefix="idempotency-test-")
os.environ["IDEMPOTENCY_DATABASE_URL"] = f"sqlite:///{_TMP_STORE_DIR}/idempotency-test.db"

import pytest  # noqa: E402
from marshmallow import ValidationError  # noqa: E402

from database import idempotency_db  # noqa: E402
from restx_api.schemas import OrderSchema  # noqa: E402
from services import place_order_service  # noqa: E402


@pytest.fixture(autouse=True)
def clean_store():
    idempotency_db.init_idempotency_db()
    idempotency_db.idempotency_session.query(idempotency_db.ClientOrderId).delete()
    idempotency_db.idempotency_session.commit()
    yield
    idempotency_db.idempotency_session.rollback()
    idempotency_db.idempotency_session.remove()


API_KEY = "test-api-key-1234"
OTHER_API_KEY = "other-api-key-5678"
CID = "retry-abc-123"

# The order_params shape reserve_client_order_id records (mirrors the
# place-order schema defaults: price/trigger_price default to 0.0, not NULL).
PARAMS = {
    "symbol": "RELIANCE",
    "exchange": "NSE",
    "action": "BUY",
    "quantity": 1,
    "price": 0.0,
    "pricetype": "MARKET",
    "product": "MIS",
    "trigger_price": 0.0,
}

BASE_ORDER = {
    "apikey": API_KEY,
    "symbol": "RELIANCE",
    "exchange": "NSE",
    "action": "BUY",
    "quantity": 1,
    "pricetype": "MARKET",
    "product": "MIS",
    "strategy": "test-strategy",
}


class TestOrderSchema:
    def test_accepts_client_order_id_and_tag(self):
        data = OrderSchema().load({**BASE_ORDER, "client_order_id": CID, "tag": "scalp-1"})
        assert data["client_order_id"] == CID
        assert data["tag"] == "scalp-1"

    def test_absent_fields_are_dropped(self):
        data = OrderSchema().load(BASE_ORDER)
        assert "client_order_id" not in data
        assert "tag" not in data

    def test_null_fields_are_dropped(self):
        data = OrderSchema().load({**BASE_ORDER, "client_order_id": None, "tag": None})
        assert "client_order_id" not in data
        assert "tag" not in data

    def test_client_order_id_max_length(self):
        with pytest.raises(ValidationError):
            OrderSchema().load({**BASE_ORDER, "client_order_id": "x" * 129})

    def test_empty_client_order_id_rejected(self):
        with pytest.raises(ValidationError):
            OrderSchema().load({**BASE_ORDER, "client_order_id": ""})


class TestReservationStore:
    def test_reserve_then_conflict(self):
        assert idempotency_db.reserve_client_order_id(API_KEY, CID) == ("reserved", None)
        assert idempotency_db.reserve_client_order_id(API_KEY, CID) == ("existing", "in_flight")

    def test_reserve_is_scoped_per_api_key(self):
        assert idempotency_db.reserve_client_order_id(API_KEY, CID) == ("reserved", None)
        assert idempotency_db.reserve_client_order_id(OTHER_API_KEY, CID) == ("reserved", None)

    def test_record_success_makes_replay_available(self):
        idempotency_db.reserve_client_order_id(API_KEY, CID, tag="scalp-1")
        idempotency_db.record_success(API_KEY, CID, "250106000012345")
        assert idempotency_db.reserve_client_order_id(API_KEY, CID) == ("existing", "placed")
        resolution = idempotency_db.get_resolution(API_KEY, CID)
        assert resolution["orderid"] == "250106000012345"
        assert resolution["status"] == "placed"
        assert resolution["tag"] == "scalp-1"

    def test_release_after_failure_allows_retry(self):
        idempotency_db.reserve_client_order_id(API_KEY, CID)
        idempotency_db.release_client_order_id(API_KEY, CID)
        assert idempotency_db.get_resolution(API_KEY, CID) is None
        assert idempotency_db.reserve_client_order_id(API_KEY, CID) == ("reserved", None)

    def test_release_ignores_completed_rows(self):
        # A failed retry must never erase a completed resolution.
        idempotency_db.reserve_client_order_id(API_KEY, CID)
        idempotency_db.record_success(API_KEY, CID, "ORD1")
        idempotency_db.release_client_order_id(API_KEY, CID)
        assert idempotency_db.get_resolution(API_KEY, CID)["orderid"] == "ORD1"

    def test_unknown_key_returns_none(self):
        assert idempotency_db.get_resolution(API_KEY, CID) is None

    def test_fractional_quantity_is_preserved(self):
        # Crypto/USDT perps trade fractional lots; the old Integer column plus
        # int() coercion made 1.1 and 1.9 indistinguishable.
        idempotency_db.reserve_client_order_id(
            API_KEY, CID, order_params={**PARAMS, "quantity": 1.1}
        )
        assert idempotency_db.get_resolution(API_KEY, CID)["quantity"] == 1.1

    def test_zero_price_is_recorded_not_nulled(self):
        # The old truthiness recording turned price 0.0 into NULL, which made
        # the replay check silently skip the price comparison.
        idempotency_db.reserve_client_order_id(
            API_KEY, CID, order_params={**PARAMS, "price": 0.0}
        )
        assert idempotency_db.get_resolution(API_KEY, CID)["price"] == 0.0

    def test_absent_shaping_params_get_schema_defaults(self):
        # place_order_with_auth sees the RAW request (validate_order_data
        # discards the schema-loaded dict), so the store must apply the
        # schema defaults itself or LIMIT-vs-MARKET corrections would
        # compare NULL against values.
        raw = {k: v for k, v in PARAMS.items() if k not in ("pricetype", "product", "price", "trigger_price")}
        idempotency_db.reserve_client_order_id(API_KEY, CID, order_params=raw)
        resolution = idempotency_db.get_resolution(API_KEY, CID)
        assert resolution["pricetype"] == "MARKET"
        assert resolution["product"] == "MIS"
        assert resolution["price"] == 0.0
        assert resolution["trigger_price"] == 0.0

    def test_request_shaping_params_are_recorded(self):
        idempotency_db.reserve_client_order_id(API_KEY, CID, order_params=PARAMS)
        resolution = idempotency_db.get_resolution(API_KEY, CID)
        assert resolution["product"] == "MIS"
        assert resolution["pricetype"] == "MARKET"
        assert resolution["trigger_price"] == 0.0

    def test_labels_lookup_by_orderid(self):
        idempotency_db.reserve_client_order_id(API_KEY, CID, tag="scalp-1")
        idempotency_db.record_success(API_KEY, CID, "ORD1")
        idempotency_db.reserve_client_order_id(API_KEY, "plain-cid")
        idempotency_db.record_success(API_KEY, "plain-cid", "ORD2")
        labels = idempotency_db.get_labels_for_orderids(API_KEY, ["ORD1", "ORD2", "ORD9"])
        assert labels["ORD1"] == {"client_order_id": CID, "tag": "scalp-1"}
        assert labels["ORD2"] == {"client_order_id": "plain-cid", "tag": None}
        assert "ORD9" not in labels

    def test_prune_and_label_lookups_are_indexed(self):
        # _prune_expired runs a created_at-range DELETE on every reserve and
        # get_labels_for_orderids maps orderids on every orderbook poll; on a
        # growing table both are full scans unless the columns are indexed.
        # Assert at the metadata level so the check needs no query planner.
        client_order_ids = idempotency_db.ClientOrderId.__table__
        index_cols = {
            ix.name: {c.name for c in ix.columns} for ix in client_order_ids.indexes
        }
        assert any(cols == {"created_at"} for cols in index_cols.values()), (
            "created_at must be indexed for TTL pruning"
        )
        assert any(
            cols == {"api_key_hash", "orderid"} for cols in index_cols.values()
        ), "(api_key_hash, orderid) must be indexed for orderbook label echo"


class _FakeResponse:
    def __init__(self, status):
        self.status = status


class _FakeBrokerModule:
    def __init__(self, order_id="250106000012345", status=200, exc=None):
        self.order_id = order_id
        self.status = status
        self.exc = exc
        self.calls = []

    def place_order_api(self, order_data, auth_token):
        self.calls.append(order_data)
        if self.exc is not None:
            raise self.exc
        return _FakeResponse(self.status), {}, self.order_id


@pytest.fixture
def fake_broker(monkeypatch):
    broker = _FakeBrokerModule()
    monkeypatch.setattr(
        place_order_service,
        "get_auth_token_broker",
        lambda api_key: ("fake-auth-token", "fakebroker"),
    )
    monkeypatch.setattr(place_order_service, "get_analyze_mode", lambda: False)
    monkeypatch.setattr(place_order_service, "import_broker_module", lambda name: broker)
    return broker


class TestPlaceOrderIdempotency:
    def test_first_call_places_and_echoes(self, fake_broker):
        ok, response, code = place_order_service.place_order(
            {**BASE_ORDER, "client_order_id": CID, "tag": "scalp-1"}, api_key=API_KEY
        )
        assert ok is True
        assert code == 200
        assert response["orderid"] == "250106000012345"
        assert response["client_order_id"] == CID
        assert response["tag"] == "scalp-1"
        assert len(fake_broker.calls) == 1

    def test_retry_with_same_id_replays_without_replacing(self, fake_broker):
        place_order_service.place_order({**BASE_ORDER, "client_order_id": CID}, api_key=API_KEY)
        ok, response, code = place_order_service.place_order(
            {**BASE_ORDER, "client_order_id": CID}, api_key=API_KEY
        )
        assert ok is True
        assert code == 200
        assert response["status"] == "success"
        assert response["orderid"] == "250106000012345"
        assert response["duplicate"] is True
        assert len(fake_broker.calls) == 1  # broker hit exactly once

    def test_retry_different_id_places_again(self, fake_broker):
        place_order_service.place_order({**BASE_ORDER, "client_order_id": CID}, api_key=API_KEY)
        ok, _, code = place_order_service.place_order(
            {**BASE_ORDER, "client_order_id": "another-id"}, api_key=API_KEY
        )
        assert ok is True
        assert code == 200
        assert len(fake_broker.calls) == 2

    def test_broker_payload_has_no_client_order_id(self, fake_broker):
        place_order_service.place_order({**BASE_ORDER, "client_order_id": CID}, api_key=API_KEY)
        assert fake_broker.calls, "broker should have been called"
        assert "client_order_id" not in fake_broker.calls[0]

    def test_broker_exception_keeps_reservation_unresolved(self, monkeypatch):
        broker = _FakeBrokerModule(exc=RuntimeError("broker down"))
        monkeypatch.setattr(
            place_order_service,
            "get_auth_token_broker",
            lambda api_key: ("fake-auth-token", "fakebroker"),
        )
        monkeypatch.setattr(place_order_service, "get_analyze_mode", lambda: False)
        monkeypatch.setattr(place_order_service, "import_broker_module", lambda name: broker)

        ok, response, code = place_order_service.place_order(
            {**BASE_ORDER, "client_order_id": CID}, api_key=API_KEY
        )
        assert ok is False
        assert code == 500
        # The exception is ambiguous — it may have hit after the broker
        # accepted the order. The reservation must survive as unresolved and
        # the same-id retry must be blocked instead of double-placing.
        resolution = idempotency_db.get_resolution(API_KEY, CID)
        assert resolution is not None and resolution["status"] == "unresolved"

        ok, response, code = place_order_service.place_order(
            {**BASE_ORDER, "client_order_id": CID}, api_key=API_KEY
        )
        assert ok is False
        assert code == 409
        assert len(broker.calls) == 1

    def test_ambiguous_500_keeps_reservation_unresolved(self, monkeypatch):
        # A transport failure converted into an adapter 500 is the exact
        # lost-ack shape the review reproduced: the request may have been
        # accepted, so the retry must not re-place.
        broker = _FakeBrokerModule(status=500, order_id=None)
        monkeypatch.setattr(
            place_order_service,
            "get_auth_token_broker",
            lambda api_key: ("fake-auth-token", "fakebroker"),
        )
        monkeypatch.setattr(place_order_service, "get_analyze_mode", lambda: False)
        monkeypatch.setattr(place_order_service, "import_broker_module", lambda name: broker)

        ok, response, code = place_order_service.place_order(
            {**BASE_ORDER, "client_order_id": CID}, api_key=API_KEY
        )
        assert ok is False
        resolution = idempotency_db.get_resolution(API_KEY, CID)
        assert resolution is not None and resolution["status"] == "unresolved"

        ok, response, code = place_order_service.place_order(
            {**BASE_ORDER, "client_order_id": CID}, api_key=API_KEY
        )
        assert ok is False
        assert code == 409
        assert len(broker.calls) == 1

    def test_rate_limited_429_releases_reservation(self, monkeypatch):
        broker = _FakeBrokerModule(status=429, order_id=None)
        monkeypatch.setattr(
            place_order_service,
            "get_auth_token_broker",
            lambda api_key: ("fake-auth-token", "fakebroker"),
        )
        monkeypatch.setattr(place_order_service, "get_analyze_mode", lambda: False)
        monkeypatch.setattr(place_order_service, "import_broker_module", lambda name: broker)

        ok, response, code = place_order_service.place_order(
            {**BASE_ORDER, "client_order_id": CID}, api_key=API_KEY
        )
        assert ok is False
        # 429 proves the broker refused the order: a retry with a fresh
        # placement is safe and must be allowed.
        assert idempotency_db.get_resolution(API_KEY, CID) is None

        broker.status = 200
        broker.order_id = "250106000012345"
        ok, response, code = place_order_service.place_order(
            {**BASE_ORDER, "client_order_id": CID}, api_key=API_KEY
        )
        assert ok is True
        assert code == 200
        assert len(broker.calls) == 2

    def test_broker_non_200_releases_reservation(self, monkeypatch):
        broker = _FakeBrokerModule(status=400, order_id=None)
        monkeypatch.setattr(
            place_order_service,
            "get_auth_token_broker",
            lambda api_key: ("fake-auth-token", "fakebroker"),
        )
        monkeypatch.setattr(place_order_service, "get_analyze_mode", lambda: False)
        monkeypatch.setattr(place_order_service, "import_broker_module", lambda name: broker)

        ok, response, code = place_order_service.place_order(
            {**BASE_ORDER, "client_order_id": CID}, api_key=API_KEY
        )
        assert ok is False
        assert idempotency_db.get_resolution(API_KEY, CID) is None

    def test_in_flight_reservation_returns_409(self, fake_broker):
        idempotency_db.reserve_client_order_id(API_KEY, CID)
        ok, response, code = place_order_service.place_order(
            {**BASE_ORDER, "client_order_id": CID}, api_key=API_KEY
        )
        assert ok is False
        assert code == 409
        assert "already in progress" in response["message"]
        assert len(fake_broker.calls) == 0

    def test_placed_without_orderid_returns_409(self, fake_broker):
        idempotency_db.reserve_client_order_id(API_KEY, CID)
        idempotency_db.record_success(API_KEY, CID, "ORD1")
        # Force the placed-without-orderid guard by wiping the orderid column.
        row = (
            idempotency_db.idempotency_session.query(idempotency_db.ClientOrderId)
            .filter_by(api_key_hash=idempotency_db._hash_api_key(API_KEY), client_order_id=CID)
            .one()
        )
        row.orderid = None
        idempotency_db.idempotency_session.commit()
        ok, response, code = place_order_service.place_order(
            {**BASE_ORDER, "client_order_id": CID}, api_key=API_KEY
        )
        assert ok is False
        assert code == 409

    def test_200_without_orderid_is_reported_unresolved(self, monkeypatch):
        broker = _FakeBrokerModule(status=200, order_id=None)
        monkeypatch.setattr(
            place_order_service,
            "get_auth_token_broker",
            lambda api_key: ("fake-auth-token", "fakebroker"),
        )
        monkeypatch.setattr(place_order_service, "get_analyze_mode", lambda: False)
        monkeypatch.setattr(place_order_service, "import_broker_module", lambda name: broker)

        ok, response, code = place_order_service.place_order(
            {**BASE_ORDER, "client_order_id": CID}, api_key=API_KEY
        )
        # The broker ACCEPTED the request, so this is not a plain failure:
        # reporting success would lie about the orderid, and releasing the
        # reservation would let a retry double-place. The placement must come
        # back as an explicit unresolved error and the key must stay claimed.
        assert ok is False
        assert code == 500
        assert "unresolved" in response["message"]
        resolution = idempotency_db.get_resolution(API_KEY, CID)
        assert resolution is not None and resolution["status"] == "unresolved"

    def test_200_without_orderid_retry_stays_blocked(self, monkeypatch):
        broker = _FakeBrokerModule(status=200, order_id=None)
        monkeypatch.setattr(
            place_order_service,
            "get_auth_token_broker",
            lambda api_key: ("fake-auth-token", "fakebroker"),
        )
        monkeypatch.setattr(place_order_service, "get_analyze_mode", lambda: False)
        monkeypatch.setattr(place_order_service, "import_broker_module", lambda name: broker)

        place_order_service.place_order({**BASE_ORDER, "client_order_id": CID}, api_key=API_KEY)
        broker.order_id = "250106000012345"
        ok, response, code = place_order_service.place_order(
            {**BASE_ORDER, "client_order_id": CID}, api_key=API_KEY
        )
        # Even after the broker recovers, a retry with the same id must not
        # re-place: the first request may already exist at the broker.
        assert ok is False
        assert code == 409
        assert len(broker.calls) == 1

    def test_200_without_orderid_non_idempotent_unchanged(self, monkeypatch):
        broker = _FakeBrokerModule(status=200, order_id=None)
        monkeypatch.setattr(
            place_order_service,
            "get_auth_token_broker",
            lambda api_key: ("fake-auth-token", "fakebroker"),
        )
        monkeypatch.setattr(place_order_service, "get_analyze_mode", lambda: False)
        monkeypatch.setattr(place_order_service, "import_broker_module", lambda name: broker)

        # Legacy behaviour without a client_order_id is untouched.
        ok, response, code = place_order_service.place_order(BASE_ORDER, api_key=API_KEY)
        assert ok is True
        assert code == 200
        assert response["orderid"] is None

    def test_reserve_store_failure_fails_closed_503(self, monkeypatch):
        broker = _FakeBrokerModule()
        monkeypatch.setattr(
            place_order_service,
            "get_auth_token_broker",
            lambda api_key: ("fake-auth-token", "fakebroker"),
        )
        monkeypatch.setattr(place_order_service, "get_analyze_mode", lambda: False)
        monkeypatch.setattr(place_order_service, "import_broker_module", lambda name: broker)
        monkeypatch.setattr(
            idempotency_db,
            "reserve_client_order_id",
            lambda *a, **k: (_ for _ in ()).throw(RuntimeError("database is locked")),
        )

        ok, response, code = place_order_service.place_order(
            {**BASE_ORDER, "client_order_id": CID}, api_key=API_KEY
        )
        # Without the store we cannot dedupe, so proceeding would risk a
        # double placement. Fail closed with a retryable error instead of
        # leaking the exception as an unstyled 500.
        assert ok is False
        assert code == 503
        assert "unavailable" in response["message"]
        assert len(broker.calls) == 0

    def test_resolution_read_failure_never_replaces(self, monkeypatch):
        broker = _FakeBrokerModule()
        monkeypatch.setattr(
            place_order_service,
            "get_auth_token_broker",
            lambda api_key: ("fake-auth-token", "fakebroker"),
        )
        monkeypatch.setattr(place_order_service, "get_analyze_mode", lambda: False)
        monkeypatch.setattr(place_order_service, "import_broker_module", lambda name: broker)
        monkeypatch.setattr(
            idempotency_db,
            "reserve_client_order_id",
            lambda *a, **k: ("existing", "placed"),
        )
        monkeypatch.setattr(
            idempotency_db,
            "get_resolution",
            lambda *a, **k: (_ for _ in ()).throw(RuntimeError("database is locked")),
        )

        # The id may already exist at the broker; an unreadable resolution
        # must block the placement, never fall through to a re-place.
        ok, response, code = place_order_service.place_order(
            {**BASE_ORDER, "client_order_id": CID}, api_key=API_KEY
        )
        assert ok is False
        assert code == 503
        assert len(broker.calls) == 0

    def test_no_client_order_id_is_unchanged(self, fake_broker):
        ok, response, code = place_order_service.place_order(BASE_ORDER, api_key=API_KEY)
        assert ok is True
        assert code == 200
        assert set(response) == {"status", "orderid"}
        assert "client_order_id" not in response


class TestSessionHygiene:
    """The store must not hold NullPool connections between operations.

    Registered in utils/db_sessions.SCOPED_SESSION_MODULES so request
    teardown releases it, and read helpers end their own transactions so
    background callers (strategy dispatch) never pin a connection.
    """

    def test_session_registered_in_central_cleanup_registry(self):
        from utils.db_sessions import SCOPED_SESSION_MODULES, remove_all_scoped_sessions

        assert ("database.idempotency_db", "idempotency_session") in SCOPED_SESSION_MODULES
        # Must not raise with the idempotency module loaded.
        remove_all_scoped_sessions()

    def test_reads_do_not_hold_transaction_open(self):
        idempotency_db.init_idempotency_db()
        idempotency_db.get_resolution(API_KEY, "unknown-id")
        assert not idempotency_db.idempotency_session().in_transaction()

    def test_label_reads_do_not_hold_transaction_open(self):
        idempotency_db.init_idempotency_db()
        idempotency_db.get_labels_for_orderids(API_KEY, ["123"])
        assert not idempotency_db.idempotency_session().in_transaction()

    def test_engine_uses_project_pooling_policy(self):
        from sqlalchemy.pool import NullPool

        assert isinstance(idempotency_db.idempotency_engine.pool, NullPool)


class TestUnresolvedReconciliation:
    """A retry of an unresolved key must reconcile with the broker first.

    The reconciliation compares the reservation's original parameters
    against the broker order book: exactly one live match replays that
    order, zero live matches (book reachable) releases the key for a fresh
    placement, and anything ambiguous keeps blocking the key.
    """

    MATCHING_ORDER = {
        "orderid": "250106000099999",
        "symbol": "RELIANCE",
        "exchange": "NSE",
        "action": "BUY",
        "quantity": 1,
        "price": 0.0,
        "pricetype": "MARKET",
        "product": "MIS",
        "trigger_price": 0.0,
        "order_status": "OPEN",
    }

    def test_raw_request_defaults_do_not_block_reconciliation(self, monkeypatch):
        # A request that omitted pricetype/product must reconcile against the
        # book once the store applied the schema defaults — the pre-fix code
        # stored NULL and the strict compare would then reject every match.
        broker = _FakeBrokerModule(status=500, order_id=None)
        raw_request = {
            k: v for k, v in BASE_ORDER.items() if k not in ("pricetype", "product")
        }
        monkeypatch.setattr(
            place_order_service,
            "get_auth_token_broker",
            lambda api_key: ("fake-auth-token", "fakebroker"),
        )
        monkeypatch.setattr(place_order_service, "get_analyze_mode", lambda: False)
        monkeypatch.setattr(place_order_service, "import_broker_module", lambda name: broker)
        broker.status = 500
        place_order_service.place_order({**raw_request, "client_order_id": CID}, api_key=API_KEY)
        assert idempotency_db.get_resolution(API_KEY, CID)["status"] == "unresolved"
        self._stub_orderbook(monkeypatch, [dict(self.MATCHING_ORDER)])

        ok, response, code = place_order_service.place_order(
            {**BASE_ORDER, "client_order_id": CID}, api_key=API_KEY
        )
        assert ok is True
        assert code == 200
        assert response["reconciled"] is True

    def _make_unresolved(self, monkeypatch, broker, **param_overrides):
        monkeypatch.setattr(
            place_order_service,
            "get_auth_token_broker",
            lambda api_key: ("fake-auth-token", "fakebroker"),
        )
        monkeypatch.setattr(place_order_service, "get_analyze_mode", lambda: False)
        monkeypatch.setattr(place_order_service, "import_broker_module", lambda name: broker)
        broker.status = 500  # ambiguous adapter failure -> unresolved
        place_order_service.place_order(
            {**BASE_ORDER, "client_order_id": CID, **param_overrides}, api_key=API_KEY
        )
        assert idempotency_db.get_resolution(API_KEY, CID)["status"] == "unresolved"
        broker.status = 200
        broker.order_id = "250106000012345"

    def _stub_orderbook(self, monkeypatch, orders, ok=True):
        from services import orderbook_service

        def fake_get_orderbook_with_auth(auth_token, broker, original_data=None):
            if not ok:
                return False, {"status": "error", "message": "order book unavailable"}, 503
            return True, {"status": "success", "data": {"orders": orders, "statistics": {}}}, 200

        monkeypatch.setattr(
            orderbook_service, "get_orderbook_with_auth", fake_get_orderbook_with_auth
        )

    def test_single_live_match_is_replayed(self, monkeypatch):
        broker = _FakeBrokerModule(status=500, order_id=None)
        self._make_unresolved(monkeypatch, broker)
        self._stub_orderbook(monkeypatch, [dict(self.MATCHING_ORDER)])

        ok, response, code = place_order_service.place_order(
            {**BASE_ORDER, "client_order_id": CID}, api_key=API_KEY
        )
        assert ok is True
        assert code == 200
        assert response["duplicate"] is True
        assert response["reconciled"] is True
        assert response["orderid"] == "250106000099999"
        # The broker was never asked to place again.
        assert len(broker.calls) == 1
        resolution = idempotency_db.get_resolution(API_KEY, CID)
        assert resolution["status"] == "placed"
        assert resolution["orderid"] == "250106000099999"

    def test_no_match_releases_key_and_places_fresh(self, monkeypatch):
        broker = _FakeBrokerModule(status=500, order_id=None)
        self._make_unresolved(monkeypatch, broker)
        self._stub_orderbook(monkeypatch, [])

        ok, response, code = place_order_service.place_order(
            {**BASE_ORDER, "client_order_id": CID}, api_key=API_KEY
        )
        # The book proves the attempt never placed: the retry places fresh.
        assert ok is True
        assert code == 200
        assert response["orderid"] == "250106000012345"
        assert "duplicate" not in response
        assert len(broker.calls) == 2

    def test_rejected_only_book_releases_key(self, monkeypatch):
        broker = _FakeBrokerModule(status=500, order_id=None)
        self._make_unresolved(monkeypatch, broker)
        rejected = dict(self.MATCHING_ORDER, order_status="REJECTED")
        self._stub_orderbook(monkeypatch, [rejected])

        ok, response, code = place_order_service.place_order(
            {**BASE_ORDER, "client_order_id": CID}, api_key=API_KEY
        )
        assert ok is True
        assert code == 200
        assert len(broker.calls) == 2

    def test_unavailable_book_keeps_key_blocked(self, monkeypatch):
        broker = _FakeBrokerModule(status=500, order_id=None)
        self._make_unresolved(monkeypatch, broker)
        self._stub_orderbook(monkeypatch, [], ok=False)

        ok, response, code = place_order_service.place_order(
            {**BASE_ORDER, "client_order_id": CID}, api_key=API_KEY
        )
        assert ok is False
        assert code == 409
        assert len(broker.calls) == 1

    def test_multiple_matches_keeps_key_blocked(self, monkeypatch):
        broker = _FakeBrokerModule(status=500, order_id=None)
        self._make_unresolved(monkeypatch, broker)
        self._stub_orderbook(
            monkeypatch, [dict(self.MATCHING_ORDER), dict(self.MATCHING_ORDER)]
        )

        ok, response, code = place_order_service.place_order(
            {**BASE_ORDER, "client_order_id": CID}, api_key=API_KEY
        )
        assert ok is False
        assert code == 409
        assert len(broker.calls) == 1

    def test_corrected_params_are_refused(self, monkeypatch):
        broker = _FakeBrokerModule(status=500, order_id=None)
        self._make_unresolved(monkeypatch, broker)
        self._stub_orderbook(monkeypatch, [dict(self.MATCHING_ORDER)])

        # A "corrected" retry (different quantity) must never reuse the key:
        # the ambiguous attempt may still be live with the original params.
        ok, response, code = place_order_service.place_order(
            {**BASE_ORDER, "client_order_id": CID, "quantity": 5}, api_key=API_KEY
        )
        assert ok is False
        assert code == 409
        assert "parameters differ" in response["message"]
        assert len(broker.calls) == 1

    def test_fractional_quantities_never_compare_equal(self, monkeypatch):
        broker = _FakeBrokerModule(status=500, order_id=None)
        self._make_unresolved(monkeypatch, broker, quantity=1.1, exchange="CRYPTO")
        book_row = dict(self.MATCHING_ORDER, exchange="CRYPTO", quantity=1.1)
        self._stub_orderbook(monkeypatch, [book_row])

        # 1.1 vs 1.9 must not collapse to the same int and slip through.
        ok, response, code = place_order_service.place_order(
            {**BASE_ORDER, "exchange": "CRYPTO", "quantity": 1.9, "client_order_id": CID},
            api_key=API_KEY,
        )
        assert ok is False
        assert code == 409
        assert "parameters differ" in response["message"]
        assert len(broker.calls) == 1

        # Same fractional quantity reconciles to the existing order.
        ok, response, code = place_order_service.place_order(
            {**BASE_ORDER, "exchange": "CRYPTO", "quantity": 1.1, "client_order_id": CID},
            api_key=API_KEY,
        )
        assert ok is True
        assert code == 200
        assert response["reconciled"] is True
        assert len(broker.calls) == 1

    def test_limit_price_must_match_for_price_fixed_types(self, monkeypatch):
        broker = _FakeBrokerModule(status=500, order_id=None)
        self._make_unresolved(monkeypatch, broker, pricetype="LIMIT", price=1500.5)
        self._stub_orderbook(
            monkeypatch, [dict(self.MATCHING_ORDER, pricetype="LIMIT", price=1500.5)]
        )

        # Same limit price reconciles.
        ok, response, code = place_order_service.place_order(
            {**BASE_ORDER, "pricetype": "LIMIT", "price": 1500.5, "client_order_id": CID},
            api_key=API_KEY,
        )
        assert ok is True
        assert code == 200
        assert len(broker.calls) == 1

    def test_different_limit_price_is_refused(self, monkeypatch):
        broker = _FakeBrokerModule(status=500, order_id=None)
        self._make_unresolved(monkeypatch, broker, pricetype="LIMIT", price=1500.5)
        self._stub_orderbook(
            monkeypatch, [dict(self.MATCHING_ORDER, pricetype="LIMIT", price=1500.5)]
        )

        # A different limit price is a corrected order, not a retry.
        ok, response, code = place_order_service.place_order(
            {**BASE_ORDER, "pricetype": "LIMIT", "price": 1600.0, "client_order_id": CID},
            api_key=API_KEY,
        )
        assert ok is False
        assert code == 409
        assert "parameters differ" in response["message"]
        assert len(broker.calls) == 1

    @pytest.mark.parametrize("field,value", [
        ("pricetype", "LIMIT"),
        ("product", "CNC"),
    ])
    def test_corrected_shaping_params_are_refused(self, monkeypatch, field, value):
        broker = _FakeBrokerModule(status=500, order_id=None)
        self._make_unresolved(monkeypatch, broker)
        self._stub_orderbook(monkeypatch, [dict(self.MATCHING_ORDER)])

        # A retry that changes pricetype/product must be refused: the
        # unresolved attempt may still be live with the original shape
        # (e.g. a LIMIT retry must not slip through a MARKET reservation).
        ok, response, code = place_order_service.place_order(
            {**BASE_ORDER, "client_order_id": CID, field: value}, api_key=API_KEY
        )
        assert ok is False
        assert code == 409
        assert "parameters differ" in response["message"]
        assert len(broker.calls) == 1

    def test_canceled_single_l_book_row_is_skipped(self, monkeypatch):
        broker = _FakeBrokerModule(status=500, order_id=None)
        self._make_unresolved(monkeypatch, broker)
        # Single-L 'CANCELED' appears on some broker adapters; it must be
        # treated as dead exactly like 'CANCELLED'.
        canceled = dict(self.MATCHING_ORDER, order_status="CANCELED")
        self._stub_orderbook(monkeypatch, [canceled])

        ok, response, code = place_order_service.place_order(
            {**BASE_ORDER, "client_order_id": CID}, api_key=API_KEY
        )
        assert ok is True
        assert code == 200
        assert len(broker.calls) == 2
