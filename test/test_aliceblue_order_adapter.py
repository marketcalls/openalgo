"""AliceBlue order-update token handling.

createWsToken answers HTTP 200 with an EMPTY body when the account is not
enabled for the Order Status Feed. raise_for_status() passes, response.json()
raises a bare "Expecting value: line 1 column 1 (char 0)", and because every
attempt fails identically the adapter reconnected every 60s forever - observed
live past attempt 31, telling the operator nothing about the cause.

The adapter must now say what is wrong, and give up rather than log-storm.
"""

import os
import sys
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

adapter_mod = pytest.importorskip("broker.aliceblue.streaming.aliceblue_order_adapter")

OrderTokenUnavailable = adapter_mod.OrderTokenUnavailable
MAX_FAILURES = adapter_mod.MAX_CONSECUTIVE_TOKEN_FAILURES


def _adapter():
    return adapter_mod.AliceBlueOrderUpdateAdapter(
        user_id="rajandran", alice_ucc="1614986", auth_token="bearer-xyz"
    )


def _response(status=200, text="", json_payload=None):
    r = MagicMock()
    r.status_code = status
    r.text = text
    r.raise_for_status = MagicMock()
    if json_payload is None:
        r.json = MagicMock(side_effect=ValueError("Expecting value: line 1 column 1 (char 0)"))
    else:
        r.json = MagicMock(return_value=json_payload)
    return r


def _client_returning(response):
    client = MagicMock()
    client.get = MagicMock(return_value=response)
    return client


def test_empty_body_raises_a_diagnosable_error_not_a_json_decode_error():
    """The live symptom: 200 + empty body."""
    a = _adapter()
    with patch.object(adapter_mod, "get_httpx_client", return_value=_client_returning(_response())):
        with pytest.raises(OrderTokenUnavailable) as exc:
            a._fetch_order_token()

    message = str(exc.value)
    assert "empty body" in message
    assert "Order Status Feed" in message, "the message must name the likely cause"
    assert "Expecting value" not in message, "the opaque JSON error must not be what surfaces"


def test_non_json_body_is_reported_with_a_snippet():
    a = _adapter()
    response = _response(text="<html>gateway error</html>")
    with patch.object(adapter_mod, "get_httpx_client", return_value=_client_returning(response)):
        with pytest.raises(OrderTokenUnavailable) as exc:
            a._fetch_order_token()

    assert "non-JSON" in str(exc.value)
    assert "gateway error" in str(exc.value)


def test_missing_order_token_reports_broker_status():
    a = _adapter()
    payload = {"status": "Not_Ok", "message": "Not subscribed", "result": []}
    response = _response(text='{"status":"Not_Ok"}', json_payload=payload)
    with patch.object(adapter_mod, "get_httpx_client", return_value=_client_returning(response)):
        with pytest.raises(OrderTokenUnavailable) as exc:
            a._fetch_order_token()

    assert "Not subscribed" in str(exc.value)


def test_a_valid_response_returns_the_token():
    a = _adapter()
    payload = {"status": "Ok", "result": [{"orderToken": "tok-123"}]}
    response = _response(text='{"status":"Ok"}', json_payload=payload)
    with patch.object(adapter_mod, "get_httpx_client", return_value=_client_returning(response)):
        assert a._fetch_order_token() == "tok-123"


def test_repeated_failures_stop_the_adapter_instead_of_retrying_forever():
    """The log-storm guard: give up after MAX_CONSECUTIVE_TOKEN_FAILURES."""
    a = _adapter()
    a.disconnect = MagicMock()

    with patch.object(a, "_fetch_order_token", side_effect=OrderTokenUnavailable("nope")):
        for attempt in range(1, MAX_FAILURES + 1):
            with pytest.raises(OrderTokenUnavailable):
                a.get_ws_url()
            if attempt < MAX_FAILURES:
                assert not a.disconnect.called, f"gave up early at attempt {attempt}"

    assert a.disconnect.called, (
        f"adapter kept reconnecting past {MAX_FAILURES} identical failures"
    )


def test_the_failure_counter_resets_after_a_success():
    """A transient blip must not creep the adapter toward a permanent stop."""
    a = _adapter()
    a.disconnect = MagicMock()

    with patch.object(a, "_fetch_order_token", side_effect=OrderTokenUnavailable("blip")):
        with pytest.raises(OrderTokenUnavailable):
            a.get_ws_url()
    assert a._token_failures == 1

    with patch.object(a, "_fetch_order_token", return_value="tok-123"):
        assert a.get_ws_url() == adapter_mod.ALICEBLUE_ORDER_UPDATE_WS_URL
    assert a._token_failures == 0
    assert not a.disconnect.called
