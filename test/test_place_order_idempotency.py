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

# Isolate the idempotency store before the module (and its engine) is imported.
os.environ.setdefault("IDEMPOTENCY_DATABASE_URL", "sqlite:///db/idempotency-test.db")
os.makedirs("db", exist_ok=True)

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

    def test_broker_failure_releases_reservation(self, monkeypatch):
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
        # The retry after a failure must be allowed to proceed.
        assert idempotency_db.get_resolution(API_KEY, CID) is None

        broker.exc = None
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
        assert resolution is not None and resolution["status"] == "in_flight"

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
