"""Kotak order tag (`ig`, echoed back as GuiOrdId).

Kotak treats `ig` as a client order id: a value already used on the account is
rejected with "Client OrderID already exists". With a fixed ig="openalgo" only
the first order of the day went through (#2177). These pin that every Place
Order carries a fresh, non-blank tag in the `<prefix>-<uuid4>` shape Kotak's
own apps use, and that Modify Order still sends none.
"""

import uuid

import pytest

import broker.kotak.mapping.transform_data as td


@pytest.fixture(autouse=True)
def _no_symbol_db(monkeypatch):
    monkeypatch.setattr(td, "get_br_symbol", lambda symbol, exchange: symbol)


def order(**kw):
    base = {"symbol": "NIFTY06OCT2622900CE", "exchange": "NFO", "action": "BUY",
            "quantity": "65", "pricetype": "MARKET", "product": "NRML"}
    base.update(kw)
    return base


def test_every_order_gets_a_different_tag():
    tags = {td.transform_data(order(), "1")["ig"] for _ in range(50)}
    assert len(tags) == 50


def test_default_tag_is_openalgo_prefix_plus_uuid():
    tag = td.transform_data(order(), "1")["ig"]
    prefix, _, rest = tag.partition("-")
    assert prefix == "openalgo"
    assert uuid.UUID(rest).version == 4   # raises if not a uuid
    assert len(tag) <= 52


def test_caller_tag_becomes_the_prefix_and_is_still_unique():
    a = td.transform_data(order(order_tag="ironcondor"), "1")["ig"]
    b = td.transform_data(order(order_tag="ironcondor"), "1")["ig"]
    assert a.startswith("ironcondor-") and b.startswith("ironcondor-") and a != b


def test_long_or_blank_caller_tag_is_bounded_and_never_blank():
    long_tag = td.transform_data(order(order_tag="x" * 100), "1")["ig"]
    assert long_tag.startswith("x" * 15 + "-") and len(long_tag) <= 52
    assert td.transform_data(order(order_tag="   "), "1")["ig"].startswith("openalgo-")


def test_modify_payload_has_no_tag():
    data = order(orderid="261005000086261", price="10", pricetype="LIMIT")
    assert "ig" not in td.transform_modify_order_data(data, "1")
