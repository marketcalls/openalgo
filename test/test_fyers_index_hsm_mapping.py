"""Index subscriptions on the Fyers HSM feed use the index's display name.

The feed's scrip token for an index is "if|<segment>|<name>". The official
SDK sends the display name ("if|nse_cm|Nifty IT"); FyersTokenConverter had a
13-entry table of those and sent the ticker stem ("NIFTYIT") for every other
index. The feed accepted the stem when measured on 2026-09-29, but that is
undocumented, so the converter now sends what the SDK sends: Fyers publishes
the full table (121 entries) and fyers-apiv3 3.1.18 fetches it on connect
with a bundled fallback. A symbol in neither table still gets the stem.

No network: the shared HTTP client is replaced with a stub.
"""

import pytest

import broker.fyers.streaming.fyers_token_converter as ftc

FYTOKEN = "101000000026008"  # NSE:NIFTYIT-INDEX; segment 1010 is nse_cm


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload

    def raise_for_status(self):
        pass

    def json(self):
        return self.payload


class FakeClient:
    """Stands in for utils.httpx_client.get_httpx_client()."""

    def __init__(self, payload=None, error=None):
        self.payload = payload
        self.error = error
        self.calls = []

    def get(self, url, timeout=None):
        self.calls.append((url, timeout))
        if self.error:
            raise self.error
        return FakeResponse(self.payload)


@pytest.fixture(autouse=True)
def fresh_cache():
    ftc.FyersTokenConverter._index_mapping_cache = None
    yield
    ftc.FyersTokenConverter._index_mapping_cache = None


def converter(monkeypatch, client):
    monkeypatch.setattr(ftc, "get_httpx_client", lambda: client)
    return ftc.FyersTokenConverter("appid:token")


def test_an_index_outside_the_old_table_gets_its_display_name(monkeypatch):
    conv = converter(monkeypatch, FakeClient({"NSE:NIFTYIT-INDEX": "Nifty IT"}))

    token = conv._convert_to_hsm_token("NSE:NIFTYIT-INDEX", FYTOKEN, "SymbolUpdate")

    assert token == "if|nse_cm|Nifty IT"


def test_a_name_missing_from_both_tables_is_still_guessed(monkeypatch):
    # The residual behaviour, pinned so a change to it is deliberate.
    conv = converter(monkeypatch, FakeClient({"NSE:NIFTYIT-INDEX": "Nifty IT"}))

    token = conv._convert_to_hsm_token("NSE:MADEUP-INDEX", FYTOKEN, "SymbolUpdate")

    assert token == "if|nse_cm|MADEUP"


def test_a_failed_fetch_falls_back_to_the_bundled_copy(monkeypatch):
    conv = converter(monkeypatch, FakeClient(error=RuntimeError("offline")))

    assert conv.index_mappings["NSE:NIFTY50-INDEX"] == "Nifty 50"
    # The bundled copy is the full published table, not the old 13 names.
    assert conv.index_mappings["NSE:NIFTYIT-INDEX"] == "Nifty IT"
    assert len(conv.index_mappings) > 100


def test_the_table_is_fetched_once_per_process(monkeypatch):
    client = FakeClient({"NSE:NIFTYIT-INDEX": "Nifty IT"})

    converter(monkeypatch, client)
    converter(monkeypatch, client)

    assert client.calls == [(ftc.FyersTokenConverter.INDEX_MAPPING_URL, 10)]


def test_a_failed_fetch_is_retried_by_the_next_connect(monkeypatch):
    client = FakeClient(error=RuntimeError("offline"))

    converter(monkeypatch, client)
    converter(monkeypatch, client)

    assert len(client.calls) == 2


def test_the_live_table_wins_over_the_bundled_copy(monkeypatch):
    conv = converter(monkeypatch, FakeClient({"NSE:NIFTY50-INDEX": "Nifty 50 renamed"}))

    assert conv.index_mappings["NSE:NIFTY50-INDEX"] == "Nifty 50 renamed"
    assert conv.index_mappings["NSE:NIFTYBANK-INDEX"] == "Nifty Bank"  # bundled entries kept


def test_the_manual_fallback_uses_the_same_table(monkeypatch):
    conv = converter(monkeypatch, FakeClient({"NSE:NIFTYIT-INDEX": "Nifty IT"}))

    tokens, mapping, invalid = conv._manual_conversion(["NSE:NIFTYIT-INDEX"], "SymbolUpdate")

    assert tokens == ["if|nse_cm|Nifty IT"]
    assert mapping == {"if|nse_cm|Nifty IT": "NSE:NIFTYIT-INDEX"}
    assert invalid == []
