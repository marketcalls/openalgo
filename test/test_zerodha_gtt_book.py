"""Zerodha GTT book: a caller must be able to follow a fired leg's order and confirm a cancel.

Kite's raw shapes are from https://kite.trade/docs/connect/v3/gtt/ and from a live account
(26 Nov 2026): after DELETE /gtt/triggers/{id} the GTT is left out of GET /gtt/triggers but
GET /gtt/triggers/{id} still answers with ``"status": "deleted"``.
"""

import pytest

import broker.zerodha.api.gtt_api as gtt_api
import broker.zerodha.mapping.gtt_data as gtt_data

SYMBOL = "NIFTY01DEC2625750CE"
KITE_SYMBOL = "NIFTY26D0125750CE"


def _kite_gtt(tid, status="active", results=(None, None)):
    orders = []
    for price, result in zip((4.5, 1995), results, strict=True):
        order = {
            "exchange": "NFO",
            "tradingsymbol": KITE_SYMBOL,
            "transaction_type": "SELL",
            "quantity": 65,
            "order_type": "LIMIT",
            "product": "NRML",
            "price": price,
        }
        if result is not None:
            order["result"] = result
        orders.append(order)
    return {
        "id": tid,
        "type": "two-leg",
        "status": status,
        "condition": {
            "exchange": "NFO",
            "tradingsymbol": KITE_SYMBOL,
            "trigger_values": [5, 2000],
            "last_price": 284.25,
        },
        "orders": orders,
        "created_at": "2026-11-26 23:02:47",
        "updated_at": "2026-11-26 23:02:51",
        "expires_at": "2026-12-02 00:00:00",
    }


def _result(order_id, status="success", reason=""):
    return {
        "exchange": "NFO",
        "tradingsymbol": KITE_SYMBOL,
        "order_type": "LIMIT",
        "transaction_type": "SELL",
        "quantity": 65,
        "timestamp": "2026-11-27 10:15:02",
        "triggered_at": 4.95,
        "order_result": {"status": status, "order_id": order_id, "rejection_reason": reason},
    }


@pytest.fixture(autouse=True)
def _symbols(monkeypatch):
    monkeypatch.setattr(gtt_data, "get_oa_symbol", lambda brsymbol, exchange: SYMBOL)
    cancelled = getattr(gtt_api, "_CANCELLED", {})  # module state: start and end each test empty
    cancelled.clear()
    yield
    cancelled.clear()


class FakeKite:
    """Kite's GTT endpoints: a list that leaves deleted GTTs out, and reads by id that do not."""

    def __init__(self, gtts=(), refuse_delete=False, fail_read=False):
        self.gtts = {str(g["id"]): g for g in gtts}
        self.refuse_delete = refuse_delete
        self.fail_read = fail_read
        self.reads = 0

    def _resp(self, body, code=200):
        class R:
            status_code = code
            text = str(body)

            def json(self):
                return body

        return R()

    def get(self, url, headers=None):
        tid = url.rsplit("/", 1)[-1]
        if tid == "triggers":
            listed = [g for g in self.gtts.values() if g["status"] != "deleted"]
            return self._resp({"status": "success", "data": listed})
        self.reads += 1
        if self.fail_read or tid not in self.gtts:
            return self._resp({"status": "error", "message": "Trigger not found"}, 404)
        return self._resp({"status": "success", "data": self.gtts[tid]})

    def delete(self, url, headers=None):
        tid = url.rsplit("/", 1)[-1]
        g = self.gtts.get(tid)
        if self.refuse_delete or g is None or g["status"] != "active":
            return self._resp({"status": "error", "message": "Trigger is not active"}, 400)
        g["status"] = "deleted"
        return self._resp({"status": "success", "data": {"trigger_id": int(tid)}})


@pytest.fixture
def kite(monkeypatch):
    fake = FakeKite([_kite_gtt(346576505)])
    monkeypatch.setattr(gtt_api, "get_httpx_client", lambda: fake)
    return fake


def _book(include_history=True):
    data, code = gtt_api.get_gtt_book("token", include_history=include_history)
    assert code == 200 and data["status"] == "success"
    return {g["trigger_id"]: g for g in data["data"]}


# ---------------------------------------------------------------- fired legs


def test_the_leg_that_fired_carries_the_order_it_placed():
    raw = {
        "status": "success",
        "data": [_kite_gtt(1, "triggered", (_result("261127000123456"), None))],
    }
    (row,) = gtt_data.map_gtt_book(raw, include_history=True)
    assert row["status"] == "triggered"
    assert [leg["triggered_order_id"] for leg in row["legs"]] == ["261127000123456", None]
    assert not any("rejection_reason" in leg for leg in row["legs"])


def test_a_target_leg_that_fired_is_the_second_leg():
    raw = {
        "status": "success",
        "data": [_kite_gtt(1, "triggered", (None, _result("261127000999")))],
    }
    (row,) = gtt_data.map_gtt_book(raw, include_history=True)
    assert [leg["triggered_order_id"] for leg in row["legs"]] == [None, "261127000999"]


def test_a_leg_whose_order_kite_could_not_place_carries_the_reason():
    failed = _result(
        "",
        status="failed",
        reason="Your order price is lower than the current lower circuit limit.",
    )
    raw = {"status": "success", "data": [_kite_gtt(1, "triggered", (failed, None))]}
    (row,) = gtt_data.map_gtt_book(raw, include_history=True)
    assert row["status"] == "triggered"  # Kite's own status, passed through
    assert [leg["triggered_order_id"] for leg in row["legs"]] == [None, None]
    assert (
        row["legs"][0]["rejection_reason"]
        == "Your order price is lower than the current lower circuit limit."
    )
    assert "rejection_reason" not in row["legs"][1]


def test_an_active_gtt_is_unchanged():
    raw = {"status": "success", "data": [_kite_gtt(1)]}
    (row,) = gtt_data.map_gtt_book(raw)
    assert row["status"] == "active" and row["symbol"] == SYMBOL
    assert row["trigger_prices"] == [5, 2000]
    assert [leg["price"] for leg in row["legs"]] == [4.5, 1995]
    assert [leg["triggered_order_id"] for leg in row["legs"]] == [None, None]


# ---------------------------------------------------------------- cancels


def test_a_cancelled_gtt_stays_in_the_history_book_as_kite_reports_it(kite):
    assert _book()["346576505"]["status"] == "active"
    data, code = gtt_api.cancel_gtt_order("346576505", "token")
    assert code == 200 and data == {"status": "success", "trigger_id": "346576505"}
    row = _book()["346576505"]
    assert row["status"] == "deleted"
    assert row["symbol"] == SYMBOL and row["trigger_prices"] == [5, 2000]


def test_the_active_book_still_lists_only_gtts_that_can_fire(kite):
    gtt_api.cancel_gtt_order("346576505", "token")
    assert _book(include_history=False) == {}


def test_a_cancelled_gtt_is_read_back_once_not_on_every_book(kite):
    gtt_api.cancel_gtt_order("346576505", "token")
    reads = kite.reads
    for _ in range(5):
        assert _book()["346576505"]["status"] == "deleted"
    assert kite.reads == reads


def test_an_accepted_cancel_that_cannot_be_read_back_is_still_listed(kite):
    kite.fail_read = True
    gtt_api.cancel_gtt_order("346576505", "token")
    row = _book()["346576505"]
    assert row["status"] == "deleted" and row["legs"] == []


def test_a_repeated_cancel_after_a_restart_lists_it_again(kite):
    gtt_api.cancel_gtt_order("346576505", "token")
    gtt_api._CANCELLED.clear()  # what a restart loses
    assert "346576505" not in _book()
    data, code = gtt_api.cancel_gtt_order("346576505", "token")  # Kite refuses: already cancelled
    assert data["status"] == "error" and code == 400
    assert _book()["346576505"]["status"] == "deleted"


def test_a_refused_cancel_of_an_active_gtt_does_not_list_it_cancelled(kite):
    kite.refuse_delete = True
    data, _ = gtt_api.cancel_gtt_order("346576505", "token")
    assert data["status"] == "error"
    assert _book()["346576505"]["status"] == "active"


def test_a_cancelled_gtt_kite_lists_again_is_not_duplicated(kite):
    gtt_api.cancel_gtt_order("346576505", "token")
    kite.gtts["346576505"]["status"] = "cancelled"  # a status Kite's list does show
    data, _ = gtt_api.get_gtt_book("token", include_history=True)
    assert [g["trigger_id"] for g in data["data"]] == ["346576505"]
    assert data["data"][0]["status"] == "cancelled"
