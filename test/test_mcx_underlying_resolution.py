"""MCX options price against the near-month future, not a spot.

MCX lists no tradable spot instrument: there is a CRUDEOIL19AUG26FUT but no
plain CRUDEOIL. Every options tool that fetched a quote or history for the bare
base symbol therefore got nothing back and rendered empty, which is why MCX
worked in OpenBull and not here.

The resolution has to match the base exactly. MCX carries several products
sharing a prefix but in different contract sizes - GOLD (10g), GOLDM (100g),
GOLDGUINEA (8g), GOLDPETAL (1g), GOLDTEN (10g) - so a prefix match would price
a GOLD chain against GOLDPETAL, a number an order of magnitude out.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.option_symbol_service import (  # noqa: E402
    NO_SPOT_EXCHANGES,
    find_near_month_futures,
    resolve_underlying_quote,
)


class TestExchangeClassification:
    @pytest.mark.parametrize("exchange", ["MCX", "CDS", "BCD", "NCDEX", "NCO"])
    def test_commodity_and_currency_have_no_spot(self, exchange):
        assert exchange in NO_SPOT_EXCHANGES

    @pytest.mark.parametrize("exchange", ["NFO", "BFO", "NSE", "BSE", "NSE_INDEX"])
    def test_equity_segments_are_unaffected(self, exchange):
        """The equity path must keep quoting the underlying it always did."""
        assert exchange not in NO_SPOT_EXCHANGES


class TestQuoteResolution:
    def test_equity_underlying_passes_through_untouched(self):
        assert resolve_underlying_quote("NIFTY", "NFO") == ("NIFTY", "NFO")
        assert resolve_underlying_quote("SENSEX", "BFO") == ("SENSEX", "BFO")

    def test_lowercase_exchange_is_handled(self):
        assert resolve_underlying_quote("NIFTY", "nfo") == ("NIFTY", "NFO")

    def test_unknown_base_on_a_no_spot_exchange_returns_none(self):
        """None rather than a bad symbol, so the caller can say why."""
        assert resolve_underlying_quote("NOTAPRODUCT", "MCX") is None

    @pytest.mark.parametrize("bad", [("", "MCX"), ("GOLD", ""), (None, "MCX")])
    def test_missing_input_is_refused(self, bad):
        assert find_near_month_futures(*bad) is None


#: The collision-prone family, seeded so the exact-match protection is actually
#: exercised. Relying on a downloaded master meant these could only ever skip:
#: conftest pins the suite to a test database, so the real symbol table is never
#: reachable and the tests looked like coverage while proving nothing.
#: %y maps 00-68 to 2000-2068, so "30" is 2030 and "20" is 2020. The far-future
#: dates keep these rows unexpired for the life of the codebase; the 2020 row is
#: there to prove an expired contract is passed over.
_SEED_FUTURES = [
    # (symbol, expiry) - deliberately out of order, so "nearest" has work to do
    ("CRUDEOIL21SEP31FUT", "21-SEP-31"),
    ("CRUDEOIL19AUG30FUT", "19-AUG-30"),  # the nearest unexpired one
    ("CRUDEOIL15JAN20FUT", "15-JAN-20"),  # already expired; must be ignored
    ("CRUDEOILM01JUL30FUT", "01-JUL-30"),
    # The variants expire EARLIER than GOLD on purpose. Give them the same
    # expiry and a naive prefix match still lands on GOLD by luck, so the test
    # passes against the very bug it exists to catch. With GOLDPETAL nearest,
    # anything but an exact base match picks the 1g contract to price a 10g
    # chain.
    ("GOLDPETAL02JUN30FUT", "02-JUN-30"),
    ("GOLDGUINEA03JUN30FUT", "03-JUN-30"),
    ("GOLDM04JUN30FUT", "04-JUN-30"),
    ("GOLDTEN05JUN30FUT", "05-JUN-30"),
    ("GOLD05AUG30FUT", "05-AUG-30"),
    ("SILVERM04SEP30FUT", "04-SEP-30"),
]


@pytest.fixture(scope="module", autouse=True)
def seed_mcx_futures():
    """Put the MCX family into the test database, idempotently."""
    from database.symbol import SymToken, db_session, init_db

    try:
        init_db()
    except Exception:
        pass

    try:
        for symbol, expiry in _SEED_FUTURES:
            existing = SymToken.query.filter_by(symbol=symbol, exchange="MCX").first()
            if existing is None:
                db_session.add(
                    SymToken(
                        symbol=symbol,
                        brsymbol=symbol,
                        name=symbol,
                        exchange="MCX",
                        brexchange="MCX",
                        token=symbol,
                        expiry=expiry,
                        strike=-1.0,
                        lotsize=1,
                        instrumenttype="FUT",
                        tick_size=1.0,
                    )
                )
        db_session.commit()
    except Exception as exc:  # pragma: no cover - environment problem
        db_session.rollback()
        pytest.skip(f"Could not seed MCX futures: {exc}")

    yield

    try:
        for symbol, _ in _SEED_FUTURES:
            SymToken.query.filter_by(symbol=symbol, exchange="MCX").delete()
        db_session.commit()
    except Exception:
        db_session.rollback()


class TestAgainstTheMasterContract:
    """Exercised against seeded symbols covering the real collision family."""

    def _futures(self, base):
        return find_near_month_futures(base, "MCX")

    @pytest.mark.parametrize(
        "base", ["CRUDEOIL", "GOLD", "SILVERM", "GOLDM", "CRUDEOILM"]
    )
    def test_each_product_resolves_to_its_own_future(self, base):
        fut = self._futures(base)
        if fut is None:
            pytest.skip(f"{base} has no unexpired future in this master")
        symbol = fut["symbol"]
        assert symbol.startswith(base), f"{base} resolved to {symbol}"
        assert symbol.endswith("FUT")
        # The character straight after the base must start the DDMMMYY block.
        # This is what separates GOLD from GOLDM and CRUDEOIL from CRUDEOILM.
        assert symbol[len(base)].isdigit(), (
            f"{base} resolved to {symbol}, which is a different product"
        )

    def test_gold_does_not_resolve_to_a_gold_variant(self):
        """The expensive mistake: GOLDPETAL is 1g against GOLD's 10g."""
        fut = self._futures("GOLD")
        if fut is None:
            pytest.skip("GOLD has no unexpired future in this master")
        for variant in ("GOLDM", "GOLDPETAL", "GOLDGUINEA", "GOLDTEN"):
            assert not fut["symbol"].startswith(variant), (
                f"GOLD resolved to {fut['symbol']}"
            )

    def test_variants_resolve_to_themselves(self):
        for base in ("GOLDM", "SILVERM", "CRUDEOILM"):
            fut = self._futures(base)
            if fut is None:
                continue
            assert fut["symbol"].startswith(base)
            assert fut["symbol"][len(base)].isdigit()

    def test_the_resolved_contract_has_not_expired(self):
        from datetime import datetime

        fut = self._futures("CRUDEOIL")
        if fut is None:
            pytest.skip("CRUDEOIL has no unexpired future in this master")
        expiry = datetime.strptime(fut["expiry"], "%d-%b-%y").date()
        assert expiry >= datetime.now().date(), "resolved an expired contract"

    def test_the_nearest_expiry_is_chosen(self):
        from datetime import datetime

        from database.symbol import SymToken

        fut = find_near_month_futures("CRUDEOIL", "MCX")
        if fut is None:
            pytest.skip("CRUDEOIL has no unexpired future in this master")

        today = datetime.now().date()
        unexpired = []
        for row in SymToken.query.filter(
            SymToken.symbol.like("CRUDEOIL%FUT"), SymToken.exchange == "MCX"
        ).all():
            if not row.symbol.startswith("CRUDEOIL") or not row.symbol[8].isdigit():
                continue
            try:
                exp = datetime.strptime(row.expiry, "%d-%b-%y").date()
            except (ValueError, TypeError):
                continue
            if exp >= today:
                unexpired.append(exp)

        assert unexpired
        chosen = datetime.strptime(fut["expiry"], "%d-%b-%y").date()
        assert chosen == min(unexpired), "did not pick the nearest expiry"
