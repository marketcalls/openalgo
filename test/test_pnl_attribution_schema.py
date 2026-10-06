"""
The /api/v1/pnl/attribution request schema and its registration.

Run with: uv run pytest test/test_pnl_attribution_schema.py -v
"""

import pytest
from marshmallow import ValidationError

from restx_api.account_schema import PnlAttributionSchema


def test_positions_request_defaults_m2m_off():
    data = PnlAttributionSchema().load({"apikey": "k", "kind": "positions"})
    assert data["kind"] == "positions"
    assert data["m2m"] is False


def test_m2m_can_be_requested():
    data = PnlAttributionSchema().load({"apikey": "k", "kind": "positions", "m2m": True})
    assert data["m2m"] is True


def test_holdings_request_is_accepted():
    assert PnlAttributionSchema().load({"apikey": "k", "kind": "holdings"})["kind"] == "holdings"


@pytest.mark.parametrize(
    "body",
    [
        {"kind": "positions"},  # no api key
        {"apikey": "k"},  # no kind
        {"apikey": "k", "kind": "orders"},  # unknown kind
        {"apikey": "", "kind": "positions"},  # empty api key
    ],
)
def test_bad_requests_are_rejected(body):
    with pytest.raises(ValidationError):
        PnlAttributionSchema().load(body)


def test_the_namespace_is_mounted_on_the_pnl_path():
    from restx_api import api

    mounted = {ns.name: api.get_ns_path(ns) for ns in api.namespaces}
    assert mounted.get("pnl_attribution") == "/pnl"
    assert mounted.get("pnl") == "/pnl"  # the existing P&L namespace is untouched


def test_a_body_that_is_not_an_object_is_a_validation_error():
    # Whatever the body parses to, the schema rejects it; the endpoint additionally
    # loads {} for a body that does not parse, so the answer is a 400, never a 500.
    for body in ({}, [], "m2m", None):
        with pytest.raises(ValidationError):
            PnlAttributionSchema().load(body)
