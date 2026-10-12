"""Public product evidence must never spend the authenticated order allowance."""

from copy import deepcopy

import httpx
import pytest

from broker.deltaexchange.api import data, order_api


def product(product_id=101, symbol="P-ETH-2500-121026", **changes):
    return {"id": product_id, "symbol": symbol, "contract_value": "0.01", **changes}


def fill(product_id=101, symbol="P-ETH-2500-121026", **changes):
    return {"product_id": product_id, "product_symbol": symbol, "product": None, **changes}


@pytest.fixture(autouse=True)
def refuse_private_product_request(monkeypatch):
    def private(*args, **kwargs):
        pytest.fail("Public metadata must not call the authenticated request helper")

    monkeypatch.setattr(order_api, "get_api_response", private)


def public_responses(monkeypatch, responses):
    calls = []
    replies = iter(responses)

    def read(path, timeout=15.0, params=None):
        calls.append((path, timeout, deepcopy(params)))
        reply = next(replies)
        if isinstance(reply, Exception):
            raise reply
        return httpx.Response(200, json=deepcopy(reply))

    monkeypatch.setattr(data, "_public_get", read)
    return calls


def catalogue(products, after=None):
    return {"success": True, "result": products, "meta": {"after": after}}


def test_single_expired_product_uses_documented_public_symbol_once(monkeypatch):
    calls = public_responses(monkeypatch, [{"success": True, "result": product(state="expired")}])
    rows = [fill(), fill()]
    assert order_api._attach_native_fill_products(rows, "private-key") == rows
    assert [path for path, _, _ in calls] == ["/v2/products/P-ETH-2500-121026"]
    assert all(row["product"]["id"] == 101 for row in rows)


def test_many_products_are_resolved_in_one_public_catalogue_call(monkeypatch):
    products = [product(i, f"P-ETH-{i}-121026") for i in range(1, 51)]
    calls = public_responses(monkeypatch, [catalogue(products, "more-unneeded-products")])
    rows = [fill(p["id"], p["symbol"]) for p in products]
    assert len(order_api._attach_native_fill_products(rows, "private-key")) == 50
    assert calls == [("/v2/products", 15.0, {"page_size": 500, "states": "live"})]


def test_catalogue_follows_opaque_cursor_then_fetches_omitted_expired_symbol(monkeypatch):
    calls = public_responses(
        monkeypatch,
        [
            catalogue([product()], "next+/opaque="),
            catalogue([]),
            {"success": True, "result": product(102, "expired-symbol", state="expired")},
        ],
    )
    rows = [fill(), fill(102, "expired-symbol"), fill(102, "expired-symbol")]
    assert len(order_api._attach_native_fill_products(rows, "private-key")) == 3
    assert calls[1][2]["after"] == "next+/opaque="
    assert [path for path, _, _ in calls] == [
        "/v2/products",
        "/v2/products",
        "/v2/products/expired-symbol",
    ]


def test_catalogue_bound_falls_back_only_for_missing_products(monkeypatch):
    monkeypatch.setattr(order_api, "TRADEBOOK_PRODUCT_MAX_PAGES", 1, raising=False)
    calls = public_responses(
        monkeypatch,
        [
            catalogue([product()], "more"),
            {"success": True, "result": product(102, "expired-symbol")},
        ],
    )
    rows = [fill(), fill(102, "expired-symbol")]
    assert len(order_api._attach_native_fill_products(rows, "private-key")) == 2
    assert [path for path, _, _ in calls] == ["/v2/products", "/v2/products/expired-symbol"]


@pytest.mark.parametrize(
    "bad",
    [
        {"success": False},
        {"success": True, "result": {}},
        {"success": True, "result": [], "meta": {}},
        catalogue([], []),
        httpx.ReadError("transport detail must not reach the trader"),
    ],
)
def test_failed_catalogue_never_becomes_a_partial_or_empty_success(monkeypatch, bad):
    calls = public_responses(monkeypatch, [bad])
    result = order_api._attach_native_fill_products([fill(), fill(102, "other")], "private-key")
    assert result["status"] == "error" and result["data"] == {}
    assert "transport detail" not in result["message"]
    assert len(calls) == 1


def test_repeated_catalogue_cursor_refuses_instead_of_looping(monkeypatch):
    calls = public_responses(monkeypatch, [catalogue([], "same"), catalogue([], "same")])
    result = order_api._attach_native_fill_products([fill(), fill(102, "other")], "private-key")
    assert result["status"] == "error"
    assert len(calls) == 2


@pytest.mark.parametrize("metadata", [product(999), product(symbol="different-symbol")])
def test_symbol_response_must_match_both_native_fill_identifiers(monkeypatch, metadata):
    public_responses(monkeypatch, [{"success": True, "result": metadata}])
    assert order_api._attach_native_fill_products([fill()], "private-key")["status"] == "error"


def test_symbol_is_a_single_url_encoded_path_segment(monkeypatch):
    public_responses(monkeypatch, [{"success": True, "result": product(symbol="native+/symbol?")}])
    calls = []
    original = data._public_get

    def read(path, **kwargs):
        calls.append(path)
        return original(path, **kwargs)

    monkeypatch.setattr(data, "_public_get", read)
    assert isinstance(
        order_api._attach_native_fill_products([fill(symbol="native+/symbol?")], "key"), list
    )
    assert calls == ["/v2/products/native%2B%2Fsymbol%3F"]


def test_public_429_retry_accounts_only_against_public_bucket(monkeypatch):
    quota = []
    cooldowns = []
    requests = []

    def response(request):
        requests.append(request)
        if len(requests) == 1:
            return httpx.Response(429, headers={"X-RATE-LIMIT-RESET": "0"})
        return httpx.Response(200, json={"success": True, "result": product()})

    client = httpx.Client(transport=httpx.MockTransport(response))
    monkeypatch.setattr(data, "get_httpx_client", lambda: client)
    monkeypatch.setattr(data, "consume", lambda path, **kwargs: quota.append(kwargs["bucket"]))
    monkeypatch.setattr(
        data, "note_429", lambda headers, **kwargs: cooldowns.append(kwargs["bucket"])
    )
    monkeypatch.setattr(data.time, "sleep", lambda seconds: None)
    try:
        assert isinstance(order_api._attach_native_fill_products([fill()], "private-key"), list)
    finally:
        client.close()
    assert quota == [data.PUBLIC, data.PUBLIC] and cooldowns == [data.PUBLIC]
    assert all(
        not any(h in request.headers for h in ("api-key", "signature", "timestamp"))
        for request in requests
    )


def test_embedded_native_metadata_needs_no_public_request(monkeypatch):
    calls = public_responses(monkeypatch, [])
    rows = [fill(product=product())]
    assert order_api._attach_native_fill_products(rows, "private-key") == rows
    assert not calls


def test_distinct_product_limit_is_checked_before_any_public_read(monkeypatch):
    monkeypatch.setattr(order_api, "TRADEBOOK_MAX_PRODUCTS", 1)
    calls = public_responses(monkeypatch, [])
    result = order_api._attach_native_fill_products([fill(), fill(102, "other")], "private-key")
    assert result["status"] == "error" and not calls


def test_conflicting_fill_symbols_are_refused_before_lookup(monkeypatch):
    calls = public_responses(monkeypatch, [])
    result = order_api._attach_native_fill_products([fill(), fill(symbol="other")], "private-key")
    assert result["status"] == "error" and not calls


def test_conflicting_catalogue_product_facts_refuse_book(monkeypatch):
    public_responses(monkeypatch, [catalogue([product(), product(contract_value="1")])])
    result = order_api._attach_native_fill_products([fill(), fill(102, "other")], "private-key")
    assert result["status"] == "error" and result["data"] == {}


def test_unsuccessful_public_http_status_refuses_metadata(monkeypatch):
    monkeypatch.setattr(
        data,
        "_public_get",
        lambda *args, **kwargs: httpx.Response(429, json={"success": True, "result": product()}),
    )
    assert order_api._attach_native_fill_products([fill()], "private-key")["status"] == "error"
