"""Nuvama answers an empty book with HTTP 222 and an error object.

Each book has its own "nothing here" code (ETRD0007 orders, ETRD0002 trades,
ETRD0004 positions). An empty book must read as no rows, not as a failure:
an empty order book used to show "Failed to fetch orders" (#2479). A real
error code is still a failure. No account, no network: nuvama_request is
replaced by a canned answer.
"""

import pytest

import broker.nuvama.api.order_api as oa
from broker.nuvama.api.baseurl import NuvamaResponse

AUTH = "AUTH:::SOURCE:::APPID:::ACC01:::EQ:::KEY01"


def _answer(monkeypatch, status, body):
    monkeypatch.setattr(oa, "nuvama_request", lambda *a, **k: NuvamaResponse(status, body, "", {}))


@pytest.mark.parametrize(
    ("read", "key", "code"),
    [
        (oa.get_order_book, "ord", "ETRD0007"),
        (oa.get_trade_book, "trade", "ETRD0002"),
        (oa.get_positions, "pos", "ETRD0004"),
    ],
)
def test_empty_book_reads_as_no_rows(monkeypatch, read, key, code):
    _answer(
        monkeypatch,
        222,
        {"error": {"actCd": "54", "errCd": code, "errMsg": "Seems like there are none"}},
    )
    assert read(AUTH) == {"data": {key: []}}


def test_other_error_is_still_a_failure(monkeypatch):
    _answer(
        monkeypatch,
        222,
        {"error": {"actCd": "52", "errCd": "EGN0011", "errMsg": "Session Expired"}},
    )
    assert oa.get_order_book(AUTH) == {"status": "error", "message": "Session Expired"}
