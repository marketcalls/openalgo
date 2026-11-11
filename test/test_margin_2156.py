"""
Issue #2156: margin calculator mismatch for basket orders.

Flattrade: GetBasketMargin's marginusedtrade is the account's margin after the
trade, so it includes margin already in use. The basket's own post-trade
margin (Flattrade web, "Include existing margin" unticked) is
marginusedtrade - Limits.marginused.

Kotak: check-margin's reqdMrgn is ordMrgn + mrgnUsd (margin already used), so
the order's own margin is ordMrgn. A basket with a failed leg returned
"success" with the failed legs left out — all zeros when every leg failed.
"""

import json
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from broker.flattrade.mapping.margin_data import (  # noqa: E402
    parse_limits_margin_used,
)
from broker.flattrade.mapping.margin_data import (
    parse_margin_response as flattrade_parse,
)
from broker.kotak.mapping.margin_data import (  # noqa: E402
    parse_batch_margin_response,
)
from broker.kotak.mapping.margin_data import (
    parse_margin_response as kotak_parse,
)

# ---------------------------------------------------------------- Flattrade


def test_flattrade_subtracts_margin_already_in_use():
    # Issue figures: web basket shows Post Trade Margin 178201.58 with
    # "Include existing margin" unticked.
    response = {"stat": "Ok", "marginused": "324330.00", "marginusedtrade": "186778.30"}
    result = flattrade_parse(response, existing_margin_used=8576.72)
    assert result["status"] == "success"
    assert result["data"]["total_margin_required"] == 178201.58


def test_flattrade_with_nothing_in_use_reports_marginusedtrade():
    response = {"stat": "Ok", "marginused": "315753.18", "marginusedtrade": "178201.58"}
    assert flattrade_parse(response)["data"]["total_margin_required"] == 178201.58


def test_flattrade_missing_post_trade_margin_is_an_error_not_naked_margin():
    result = flattrade_parse({"stat": "Ok", "marginused": "315753.18"})
    assert result["status"] == "error"


def test_flattrade_rejection_keeps_broker_reason():
    result = flattrade_parse({"stat": "Not_Ok", "emsg": "Session Expired"})
    assert result == {"status": "error", "message": "Session Expired"}


def test_flattrade_limits_without_marginused_means_zero_in_use():
    # Noren omits zero-valued fields.
    assert parse_limits_margin_used({"stat": "Ok", "cash": "500000.00"}) == 0.0
    assert parse_limits_margin_used({"stat": "Ok", "marginused": "8576.72"}) == 8576.72


def test_flattrade_failed_limits_is_reported_as_unknown():
    assert parse_limits_margin_used({"stat": "Not_Ok", "emsg": "Session Expired"}) is None
    assert parse_limits_margin_used(None) is None


class _Resp:
    def __init__(self, data):
        self._data = data
        self.status_code = 200
        self.text = json.dumps(data)

    def json(self):
        return self._data


class _Client:
    def __init__(self, replies):
        self.replies = replies
        self.urls = []

    def post(self, url, headers=None, content=None):
        self.urls.append(url)
        return _Resp(self.replies[url.rsplit("/", 1)[-1]])


def _run_flattrade(monkeypatch, replies):
    from broker.flattrade.api import funds, margin_api

    client = _Client(replies)
    monkeypatch.setenv("BROKER_API_KEY", "FZ00000:::secret")
    monkeypatch.setattr(margin_api, "get_httpx_client", lambda: client)
    monkeypatch.setattr(funds, "get_httpx_client", lambda: client)
    monkeypatch.setattr(margin_api.DATA_LIMITER, "acquire", lambda: None)
    monkeypatch.setattr(funds.DATA_LIMITER, "acquire", lambda: None)
    monkeypatch.setattr(
        margin_api,
        "transform_margin_positions",
        lambda positions, userid, auth_token=None: {"uid": userid, "tsym": "X", "basketlists": []},
    )
    _, result = margin_api.calculate_margin_api([{}], "token")
    return client, result


def test_flattrade_api_subtracts_limits_marginused(monkeypatch):
    client, result = _run_flattrade(
        monkeypatch,
        {
            "GetBasketMargin": {
                "stat": "Ok",
                "marginused": "324330.00",
                "marginusedtrade": "186778.30",
            },
            "Limits": {"stat": "Ok", "marginused": "8576.72"},
        },
    )
    assert result["data"]["total_margin_required"] == 178201.58
    assert [u.rsplit("/", 1)[-1] for u in client.urls] == ["GetBasketMargin", "Limits"]


def test_flattrade_api_fails_when_limits_fails(monkeypatch):
    _, result = _run_flattrade(
        monkeypatch,
        {
            "GetBasketMargin": {"stat": "Ok", "marginusedtrade": "186778.30"},
            "Limits": {"stat": "Not_Ok", "emsg": "Session Expired"},
        },
    )
    assert result["status"] == "error"
    assert "Session Expired" in result["message"]


def test_flattrade_api_skips_limits_when_basket_rejected(monkeypatch):
    client, result = _run_flattrade(
        monkeypatch,
        {"GetBasketMargin": {"stat": "Not_Ok", "emsg": "Invalid Input"}},
    )
    assert result == {"status": "error", "message": "Invalid Input"}
    assert len(client.urls) == 1


# -------------------------------------------------------------------- Kotak


def test_kotak_reports_order_margin_not_required_margin():
    # Example from kotak-api-docs/10-portfolio-margins.md.
    response = {
        "avlCash": "10197.480000",
        "totMrgnUsd": "12540.400000",
        "mrgnUsd": "40.400000",
        "ordMrgn": "12500.000000",
        "rmsVldtd": "NOT_OK",
        "reqdMrgn": "12540.400000",
        "avlMrgn": "10197.480000",
        "insufFund": "2342.920000",
        "stat": "Ok",
        "stCode": 200,
    }
    assert kotak_parse(response)["data"]["total_margin_required"] == 12500.0


def test_kotak_missing_order_margin_is_an_error():
    assert kotak_parse({"stat": "Ok", "reqdMrgn": "12540.4"})["status"] == "error"


def _ok(value):
    return {
        "status": "success",
        "data": {"total_margin_required": value, "span_margin": 0, "exposure_margin": 0},
    }


def test_kotak_basket_sums_legs():
    result = parse_batch_margin_response([_ok(160000.0), _ok(26778.3)])
    assert result["status"] == "success"
    assert result["data"]["total_margin_required"] == 186778.3


def test_kotak_basket_with_every_leg_failed_is_an_error_not_zero():
    failed = {"status": "error", "message": "Invalid session"}
    result = parse_batch_margin_response([failed, failed])
    assert result == {"status": "error", "message": "Invalid session"}


def test_kotak_basket_with_one_failed_leg_is_an_error():
    result = parse_batch_margin_response(
        [_ok(160000.0), {"status": "error", "message": "Invalid token"}]
    )
    assert result["status"] == "error"
    assert result["message"] == "Invalid token"


def _run_kotak(monkeypatch, replies):
    """Drive Kotak's calculate_margin_api with check-margin faked per leg."""
    from broker.kotak.api import margin_api

    calls = []

    class _KotakClient:
        def post(self, url, headers=None, content=None):
            calls.append(content)
            return _Resp(replies[len(calls) - 1])

    monkeypatch.setattr(margin_api, "get_httpx_client", lambda: _KotakClient())
    monkeypatch.setattr(
        margin_api, "transform_margin_position", lambda position: {"tok": position["symbol"]}
    )
    legs = [{"symbol": "CRUDEOIL19OCT26FUT"}, {"symbol": "CRUDEOIL19NOV26FUT"}]
    _, result = margin_api.calculate_margin_api(
        legs, "token:::sid:::https://kotak.example:::access"
    )
    return calls, result


def test_kotak_api_two_legs_sum_order_margins(monkeypatch):
    calls, result = _run_kotak(
        monkeypatch,
        [
            {"stat": "Ok", "ordMrgn": "160000.00", "mrgnUsd": "8576.72", "reqdMrgn": "168576.72"},
            {"stat": "Ok", "ordMrgn": "26778.30", "mrgnUsd": "8576.72", "reqdMrgn": "35355.02"},
        ],
    )
    assert len(calls) == 2
    assert result["status"] == "success"
    assert result["data"]["total_margin_required"] == 186778.3


def test_kotak_api_failed_first_leg_reports_reason_not_zero(monkeypatch):
    # The issue's screenshot: a two-leg basket came back "success" with 0.
    calls, result = _run_kotak(
        monkeypatch,
        [{"stat": "Not_Ok", "emsg": "Invalid session", "stCode": 1003}],
    )
    assert len(calls) == 1
    assert result == {"status": "error", "message": "Invalid session"}
