"""The Flow options nodes can trade MCX commodities.

Both options nodes derived the exchange from a hardcoded two-branch check --
SENSEX family to BFO, everything else to NFO -- so a commodity underlying was
unreachable: there was no way to express it in the editor, and an imported
workflow naming one had its order routed to NFO, where the contract does not
exist.

Two separate things had to be true for MCX to work end to end:

* the node must resolve MCX as both the quote exchange and the option exchange,
  because MCX has no separate derivatives segment; and
* the ATM reference must come from the near-month future, because MCX lists no
  spot instrument at all. get_option_symbol quoted the bare base symbol, which
  on MCX can only ever fail.
"""

import os
import re
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.flow_executor_service import (  # noqa: E402
    MCX_OPTION_UNDERLYINGS,
    resolve_option_exchanges,
)
from services.option_symbol_service import NO_SPOT_EXCHANGES  # noqa: E402

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class TestExchangeResolution:
    @pytest.mark.parametrize(
        "underlying", ["NIFTY", "BANKNIFTY", "FINNIFTY", "MIDCPNIFTY", "NIFTYNXT50"]
    )
    def test_an_nse_index_still_quotes_the_index_and_trades_on_nfo(self, underlying):
        assert resolve_option_exchanges(underlying) == ("NSE_INDEX", "NFO")

    @pytest.mark.parametrize("underlying", ["SENSEX", "BANKEX", "SENSEX50"])
    def test_a_bse_index_still_quotes_the_index_and_trades_on_bfo(self, underlying):
        assert resolve_option_exchanges(underlying) == ("BSE_INDEX", "BFO")

    @pytest.mark.parametrize("underlying", MCX_OPTION_UNDERLYINGS)
    def test_a_commodity_quotes_and_trades_on_mcx(self, underlying):
        """MCX is not NFO-to-NSE: the future, the option and the quote share it."""
        assert resolve_option_exchanges(underlying) == ("MCX", "MCX")

    def test_the_underlying_is_matched_case_insensitively(self):
        assert resolve_option_exchanges("crudeoil") == ("MCX", "MCX")
        assert resolve_option_exchanges("  Gold  ") == ("MCX", "MCX")

    def test_an_unknown_underlying_falls_back_to_nse(self):
        assert resolve_option_exchanges("") == ("NSE_INDEX", "NFO")
        assert resolve_option_exchanges("NOTAPRODUCT") == ("NSE_INDEX", "NFO")


class TestDeclaredExchangeIsOnlyAFallback:
    """The node's own `exchange` field decides only what the name cannot."""

    def test_a_named_underlying_ignores_a_stale_declared_exchange(self):
        """DEFAULT_NODE_DATA ships exchange "NSE_INDEX" and the editor rewrites
        it only when the dropdown changes, so an imported SENSEX workflow can
        still carry the default. Trusting it would route that order to NFO.
        """
        assert resolve_option_exchanges("SENSEX", "NSE_INDEX") == ("BSE_INDEX", "BFO")
        assert resolve_option_exchanges("CRUDEOIL", "NSE_INDEX") == ("MCX", "MCX")

    def test_an_unlisted_commodity_is_reachable_by_declaring_mcx(self):
        """The dropdown ships the liquid products; import is not limited to them."""
        assert resolve_option_exchanges("MENTHAOIL", "MCX") == ("MCX", "MCX")

    def test_a_stock_option_declares_nfo_and_quotes_the_equity_segment(self):
        assert resolve_option_exchanges("SBIN", "NFO") == ("NSE_INDEX", "NFO")

    @pytest.mark.parametrize("exchange", sorted(NO_SPOT_EXCHANGES))
    def test_every_no_spot_exchange_is_declarable(self, exchange):
        """These all quote a future rather than a spot and all trade on
        themselves; leaving one out would silently route it to NFO.
        """
        assert resolve_option_exchanges("ANYTHING", exchange) == (exchange, exchange)


class TestBothOptionsNodesShareOneResolver:
    def test_neither_node_keeps_a_private_exchange_table(self):
        """They carried two copies of the BSE branch. Adding MCX to only one
        would have left the multi-leg node placing commodity legs on NFO.
        """
        import inspect

        import services.flow_executor_service as fes

        source = inspect.getsource(fes)
        assert 'underlying in ["SENSEX", "BANKEX", "SENSEX50"]' not in source
        assert source.count("resolve_option_exchanges(") >= 3  # the def plus both nodes


class TestAtmReferenceForNoSpotExchanges:
    def test_a_bare_commodity_is_quoted_as_its_near_month_future(self, monkeypatch):
        """Without this the LTP lookup asked MCX for "CRUDEOIL", a symbol that
        cannot exist, and the order failed with "Could not determine LTP".
        """
        import services.option_symbol_service as oss

        asked = []

        def fake_quotes(symbol, exchange, api_key=None):
            asked.append((symbol, exchange))
            return True, {"data": {"ltp": 7500.0}}, 200

        monkeypatch.setattr(oss, "get_quotes", fake_quotes)
        monkeypatch.setattr(
            oss, "resolve_underlying_quote", lambda base, exch: ("CRUDEOIL21SEP26FUT", "MCX")
        )
        monkeypatch.setattr(oss, "get_available_strikes", lambda *a, **k: [7400.0, 7500.0, 7600.0])
        # Stubbed so the assertion is about routing, not about which contracts
        # this machine happens to have downloaded.
        monkeypatch.setattr(
            oss,
            "find_option_in_database",
            lambda symbol, exchange: {
                "symbol": symbol,
                "exchange": exchange,
                "brexchange": exchange,
                "token": "1",
                "lotsize": 1,
                "strike": 7500.0,
                "expiry": "15-OCT-26",
                "tick_size": 1.0,
            },
        )

        success, response, _ = oss.get_option_symbol(
            "CRUDEOIL", "MCX", "15OCT26", None, "ATM", "CE", api_key="x"
        )

        assert asked == [("CRUDEOIL21SEP26FUT", "MCX")]
        assert success
        assert response["exchange"] == "MCX"

    def test_an_index_underlying_is_still_quoted_directly(self, monkeypatch):
        import services.option_symbol_service as oss

        asked = []

        def fake_quotes(symbol, exchange, api_key=None):
            asked.append((symbol, exchange))
            return True, {"data": {"ltp": 24500.0}}, 200

        monkeypatch.setattr(oss, "get_quotes", fake_quotes)
        monkeypatch.setattr(oss, "get_available_strikes", lambda *a, **k: [24400.0, 24500.0])
        monkeypatch.setattr(oss, "find_option_in_database", lambda symbol, exchange: None)

        oss.get_option_symbol("NIFTY", "NSE_INDEX", "30SEP26", None, "ATM", "CE", api_key="x")

        assert asked == [("NIFTY", "NSE_INDEX")]

    def test_a_commodity_with_no_live_future_is_refused_not_guessed(self, monkeypatch):
        """An expired product has no reference price. Sizing an order off a
        guessed one is worse than not placing it.
        """
        import services.option_symbol_service as oss

        monkeypatch.setattr(oss, "resolve_underlying_quote", lambda base, exch: None)
        monkeypatch.setattr(
            oss,
            "get_quotes",
            lambda *a, **k: pytest.fail("must not quote without a reference contract"),
        )

        success, response, status = oss.get_option_symbol(
            "CRUDEOIL", "MCX", "15OCT26", None, "ATM", "CE", api_key="x"
        )

        assert not success
        assert status == 404
        assert "futures" in response["message"].lower()


def _offered_underlyings(exchange: str) -> set[str]:
    """The values the Options Order dropdown shows for one exchange."""
    path = os.path.join(REPO_ROOT, "frontend", "src", "lib", "flow", "constants.ts")
    with open(path, encoding="utf-8") as handle:
        source = handle.read()

    block = source.split("export const INDEX_SYMBOLS = [", 1)[1].split("] as const", 1)[0]
    pattern = r"\{\s*value:\s*'([^']+)'[^}]*?exchange:\s*'" + exchange + r"'"
    return {match.group(1) for match in re.finditer(pattern, block)}


class TestTheEditorOffersWhatTheExecutorAccepts:
    """The dropdown and the resolver are two lists that have to agree."""

    def test_every_mcx_underlying_offered_resolves_to_mcx(self):
        offered = _offered_underlyings("MCX")
        assert offered, "the dropdown offers no MCX underlyings"
        for underlying in offered:
            assert resolve_option_exchanges(underlying) == ("MCX", "MCX"), underlying

    def test_the_dropdown_and_the_resolver_list_the_same_commodities(self):
        assert _offered_underlyings("MCX") == set(MCX_OPTION_UNDERLYINGS)

    def test_the_index_underlyings_are_untouched(self):
        assert _offered_underlyings("BFO") == {"SENSEX", "BANKEX", "SENSEX50"}
        assert _offered_underlyings("NFO") == {
            "NIFTY",
            "BANKNIFTY",
            "FINNIFTY",
            "MIDCPNIFTY",
            "NIFTYNXT50",
        }
