"""The three books, against the shapes the three services actually answer.

**Why this file exists beside the other one.** The tests in
``test_openscript_books.py`` were written against fakes shaped the way the author
believed a book was shaped: ``data`` as an object with the rows under a name.
The orderbook is that shape. The tradebook and the positionbook answer ``data``
as the list of rows itself. So two of the three books filtered an empty object,
answered success with nothing in it, and every test agreed, because every fake
had the shape the code expected rather than the shape the platform sends.

The constants below are copied from the services, with the line each came from,
and the first test holds them against the real modules. That is the part a fake
cannot do: agree with something that is not itself.
"""

import pytest

from services import openscript_books as books

TAG = "openscript_probe"


@pytest.fixture(autouse=True)
def tagged(monkeypatch):
    """Every order in these tests belongs to one strategy."""
    monkeypatch.setattr(books, "tag_for", lambda script: TAG)


def mine(**over):
    row = {"symbol": "TCS", "exchange": "NSE", "strategy": TAG, "quantity": 1}
    row.update(over)
    return row


def theirs(**over):
    return mine(strategy="someone_else", **over)


# ---------------------------------------------------------------------------
# The shapes, as the services really write them
# ---------------------------------------------------------------------------


def test_the_services_still_answer_the_shapes_these_tests_assume():
    """THE GUARD THE OTHER FILE DID NOT HAVE.

    Reads the service modules and checks each still writes ``data`` the way the
    tests below fake it. A fake cannot notice a service changing shape, which is
    exactly how two of these books came to return nothing: the shape was assumed
    once and never checked against the thing it was assuming about.
    """
    import inspect

    from services import orderbook_service, positionbook_service, tradebook_service

    orders = inspect.getsource(orderbook_service)
    trades = inspect.getsource(tradebook_service)
    positions = inspect.getsource(positionbook_service)

    # The orderbook wraps its rows in an object beside a statistics block.
    assert '"data": {"orders": formatted_orders' in orders

    # These two answer the list itself.
    assert '"data": formatted_trades' in trades
    assert '"data": formatted_positions' in positions


# ---------------------------------------------------------------------------
# The orderbook: rows under a name, beside statistics
# ---------------------------------------------------------------------------


def test_the_orderbook_keeps_its_object_shape_and_recounts(monkeypatch):
    answered = {
        "status": "success",
        "data": {
            "orders": [mine(orderid="1"), theirs(orderid="2"), mine(orderid="3")],
            "statistics": {"total_orders": 3, "open_orders": 3},
        },
    }
    monkeypatch.setattr(books, "_fetch", lambda *a: (True, answered))

    out = books.orderbook("probe.oscript", "key", "sandbox")

    assert [row["orderid"] for row in out["data"]["orders"]] == ["1", "3"]
    assert out["data"]["statistics"]["total_orders"] == 2


# ---------------------------------------------------------------------------
# The tradebook and the positionbook: a bare list
# ---------------------------------------------------------------------------


def test_the_tradebook_reads_a_bare_list_and_answers_one(monkeypatch):
    """THE DEFECT. Read as an object this filtered nothing and answered nothing.

    A trader reads an empty tradebook as a strategy that has not filled, which
    is the one answer that must never be given by mistake.
    """
    answered = {
        "status": "success",
        "data": [mine(orderid="1"), theirs(orderid="2"), mine(orderid="3")],
    }
    monkeypatch.setattr(books, "_fetch", lambda *a: (True, answered))

    out = books.tradebook("probe.oscript", "key", "sandbox")

    assert isinstance(out["data"], list), "a bare list must come back a bare list"
    assert [row["orderid"] for row in out["data"]] == ["1", "3"]


def test_the_positionbook_reads_a_bare_list_and_answers_one(monkeypatch):
    """The same defect, and the one the trader actually reported.

    The strategy was holding a position, the envelope carried its profit, and
    the rows were dropped on the way through.
    """
    calls = []

    def fetch(book, mode, api_key):
        calls.append(book)
        if book == "orderbook":
            return True, {"status": "success", "data": {"orders": [mine(orderid="1")]}}
        return True, {
            "status": "success",
            "total_pnl": 0.9,
            "data": [
                mine(quantity=1, pnl=0.5),
                {"symbol": "RELIANCE", "exchange": "NSE", "quantity": 4},
            ],
        }

    monkeypatch.setattr(books, "_fetch", fetch)

    out = books.positions("probe.oscript", "key", "sandbox")

    assert isinstance(out["data"], list)
    assert [row["symbol"] for row in out["data"]] == ["TCS"]
    # The envelope's own figures are the platform's and are carried through.
    assert out["total_pnl"] == 0.9


def test_a_positionbook_that_names_its_list_is_read_too(monkeypatch):
    """A broker module that wraps its rows must work as well as one that does not.

    Both spellings are in this codebase, so reading one is reading half of them.
    """

    def fetch(book, mode, api_key):
        if book == "orderbook":
            return True, {"status": "success", "data": {"orders": [mine()]}}
        return True, {"status": "success", "data": {"positions": [mine(), theirs(symbol="INFY")]}}

    monkeypatch.setattr(books, "_fetch", fetch)

    out = books.positions("probe.oscript", "key", "sandbox")

    assert isinstance(out["data"], dict)
    assert [row["symbol"] for row in out["data"]["positions"]] == ["TCS"]


# ---------------------------------------------------------------------------
# What must not change
# ---------------------------------------------------------------------------


def test_the_service_own_dict_is_never_narrowed_in_place(monkeypatch):
    """A book service may hold or cache what it returned."""
    answered = {"status": "success", "data": [mine(orderid="1"), theirs(orderid="2")]}
    monkeypatch.setattr(books, "_fetch", lambda *a: (True, answered))

    books.tradebook("probe.oscript", "key", "sandbox")

    assert len(answered["data"]) == 2, "the global tradebook was narrowed for everyone"


def test_a_shape_nobody_writes_answers_nothing_rather_than_raising(monkeypatch):
    for shape in (None, "text", 7, {"data": None}, {"data": "text"}, {}):
        monkeypatch.setattr(books, "_fetch", lambda *a, s=shape: (True, s))

        out = books.tradebook("probe.oscript", "key", "sandbox")

        assert out.get("status") in ("success", "error")
