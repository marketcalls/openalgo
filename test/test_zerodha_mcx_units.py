"""Zerodha MCX quantity convention: OpenAlgo units in, Kite contracts out.

Kite denominates MCX order quantity in contracts and reports lot_size = 1 for
every MCX instrument; every other Indian broker uses units and ships the real
market lot. OpenAlgo standardises on units so one request body works on any
broker, and broker/zerodha translates at each boundary with api.kite.trade --
the same way it already translates symbol, product and price type.

The failure this pins is asymmetric and expensive. A missing outbound divide
sends 100 crude contracts where the user asked for one lot. A missing inbound
multiply understates a position by the same factor, and that number then feeds
smart-order sizing and square-off. Both directions are asserted here, along with
the round trip, because either half alone looks correct in isolation.
"""

import pytest

from broker.zerodha.mapping.mcx_contract_size import (
    MCX_CONTRACT_SIZES,
    McxQuantityError,
    from_kite_quantity,
    get_contract_size,
    to_kite_quantity,
    units_per_contract,
)


class TestUnitsPerContract:
    @pytest.mark.parametrize(
        "symbol,expected",
        [
            ("CRUDEOIL21SEP26FUT", 100),
            ("CRUDEOIL26SEPFUT", 100),
            ("CRUDEOIL17SEP268650CE", 100),
            ("COPPER26SEPFUT", 2500),
            ("NATURALGAS26SEPFUT", 1250),
            ("GOLD26OCTFUT", 1),
        ],
        ids=["oa-fut", "kite-fut", "option", "copper", "natgas", "gold"],
    )
    def test_resolves_both_symbol_formats(self, symbol, expected):
        assert units_per_contract(symbol, "MCX") == expected

    @pytest.mark.parametrize(
        "symbol,expected",
        [
            ("CRUDEOIL26SEPFUT", 100),
            ("CRUDEOILM26SEPFUT", 10),
            ("SILVER26SEPFUT", 30),
            ("SILVERM26SEPFUT", 5),
            ("SILVERMIC26SEPFUT", 1),
            ("SILVER10026SEPFUT", 100),
            ("GOLD26OCTFUT", 1),
            ("GOLDM26OCTFUT", 100),
            ("GOLDTEN26OCTFUT", 10),
            ("GOLDGUINEA26OCTFUT", 8),
            ("GOLDPETAL26OCTFUT", 1),
            ("ZINC26SEPFUT", 5),
            ("ZINCMINI26SEPFUT", 1),
            ("LEAD26SEPFUT", 5),
            ("LEADMINI26SEPFUT", 1),
            ("ALUMINIUM26SEPFUT", 5),
            ("ALUMINI26SEPFUT", 1),
        ],
    )
    def test_longest_prefix_wins_over_shorter_root(self, symbol, expected):
        """The mini contracts share a prefix with their full-size parent.

        Matching "SILVER" against SILVERMIC would size it 30x too large and
        CRUDEOILM against CRUDEOIL 10x. Every colliding family is listed.
        """
        assert units_per_contract(symbol, "MCX") == expected

    @pytest.mark.parametrize("exchange", ["NFO", "NSE", "BFO", "CDS", "BSE", "NCDEX"])
    def test_no_conversion_off_mcx(self, exchange):
        assert units_per_contract("CRUDEOIL26SEPFUT", exchange) == 1

    def test_unmapped_underlying_passes_through(self):
        """CARDAMOM trades but is absent from the table.

        A factor of 1 keeps Kite's own contract count, which is what shipped
        before the table existed. Guessing a size here would mis-size a live
        order; reading one lot as one unit merely looks inconsistent.
        """
        assert units_per_contract("CARDAMOM26OCTFUT", "MCX") == 1

    def test_missing_symbol_is_not_an_error(self):
        assert units_per_contract(None, "MCX") == 1
        assert units_per_contract("", "MCX") == 1
        assert units_per_contract("CRUDEOIL26SEPFUT", None) == 1

    def test_a_null_name_does_not_raise(self):
        """NaN is truthy, so a falsiness check lets it reach .strip().

        Kite ships blank names in the thousands on other segments; one on MCX
        would abort the whole master contract download rather than leaving a
        single row unmapped.
        """
        assert get_contract_size(float("nan")) is None
        assert get_contract_size(None) is None
        assert units_per_contract(float("nan"), "MCX") == 1
        assert units_per_contract("CRUDEOIL26SEPFUT", float("nan")) == 1


class TestOutboundToKite:
    def test_one_lot_of_crude_leaves_as_one_contract(self):
        assert to_kite_quantity(100, "CRUDEOIL26SEPFUT", "MCX") == 1

    def test_multiple_lots(self):
        assert to_kite_quantity(300, "CRUDEOIL26SEPFUT", "MCX") == 3
        assert to_kite_quantity(12500, "COPPER26SEPFUT", "MCX") == 5

    def test_non_multiple_is_refused_not_rounded(self):
        """150 barrels is one and a half contracts.

        Rounding down halves the order and rounding up doubles it, and both
        report success. The order is refused instead.
        """
        with pytest.raises(McxQuantityError) as exc:
            to_kite_quantity(150, "CRUDEOIL26SEPFUT", "MCX")
        assert "multiples of lot size 100" in str(exc.value)

    def test_a_bare_one_is_refused(self):
        """The old Zerodha habit. It now means one barrel, not one lot."""
        with pytest.raises(McxQuantityError):
            to_kite_quantity(1, "CRUDEOIL17SEP268650CE", "MCX")

    def test_sign_is_preserved(self):
        assert to_kite_quantity(-200, "CRUDEOIL26SEPFUT", "MCX") == -2

    def test_zero_converts_without_raising(self):
        # disclosed_quantity defaults to 0 on nearly every order.
        assert to_kite_quantity(0, "CRUDEOIL26SEPFUT", "MCX") == 0

    def test_nfo_quantity_is_untouched(self):
        assert to_kite_quantity(75, "NIFTY28MAR2420800CE", "NFO") == 75

    def test_string_quantity_accepted(self):
        assert to_kite_quantity("100", "CRUDEOIL26SEPFUT", "MCX") == 1


class TestInboundFromKite:
    def test_one_contract_arrives_as_one_lot(self):
        assert from_kite_quantity(1, "CRUDEOIL26SEPFUT", "MCX") == 100

    def test_short_position_keeps_its_sign(self):
        assert from_kite_quantity(-1, "CRUDEOIL26SEPFUT", "MCX") == -100

    def test_nfo_is_untouched(self):
        assert from_kite_quantity(75, "NIFTY28MAR2420800CE", "NFO") == 75

    def test_unparseable_value_degrades_to_passthrough(self):
        """One malformed field must not take down the whole orderbook."""
        assert from_kite_quantity(None, "CRUDEOIL26SEPFUT", "MCX") is None
        assert from_kite_quantity("", "CRUDEOIL26SEPFUT", "MCX") == ""


class TestRoundTrip:
    @pytest.mark.parametrize("root,size", sorted(MCX_CONTRACT_SIZES.items()))
    def test_every_mapped_underlying_survives_a_round_trip(self, root, size):
        symbol = f"{root}26SEPFUT"
        units = size * 3
        assert from_kite_quantity(to_kite_quantity(units, symbol, "MCX"), symbol, "MCX") == units

    def test_table_matches_the_source_csv_row_count(self):
        # 29 rows scraped from zerodha.com/margin-calculator/Commodity/.
        assert len(MCX_CONTRACT_SIZES) == 29
        assert all(isinstance(v, int) and v > 0 for v in MCX_CONTRACT_SIZES.values())


class TestOrderPayloadBoundary:
    """The conversion where it matters: the payload posted to api.kite.trade."""

    @pytest.fixture(autouse=True)
    def _stub_symbol_lookup(self, monkeypatch):
        # get_br_symbol hits symtoken; the payload's quantity is what is under
        # test, so the symbol translation is stubbed to an identity.
        import broker.zerodha.mapping.transform_data as td

        monkeypatch.setattr(td, "get_br_symbol", lambda symbol, exchange: symbol)

    def _order(self, **over):
        base = {
            "symbol": "CRUDEOIL17SEP268650CE",
            "exchange": "MCX",
            "action": "BUY",
            "pricetype": "MARKET",
            "product": "NRML",
            "quantity": "100",
        }
        base.update(over)
        return base

    def test_the_angel_request_body_now_works_on_zerodha(self):
        """quantity 100 -> one crude lot, exactly as it means on Angel."""
        from broker.zerodha.mapping.transform_data import transform_data

        assert transform_data(self._order())["quantity"] == 1

    def test_nfo_order_is_unchanged(self):
        from broker.zerodha.mapping.transform_data import transform_data

        payload = transform_data(
            self._order(symbol="NIFTY28MAR2420800CE", exchange="NFO", quantity="75")
        )
        assert payload["quantity"] == 75

    def test_absent_disclosed_quantity_does_not_raise(self):
        from broker.zerodha.mapping.transform_data import transform_data

        assert transform_data(self._order())["disclosed_quantity"] == 0

    def test_present_disclosed_quantity_is_converted_too(self):
        from broker.zerodha.mapping.transform_data import transform_data

        payload = transform_data(self._order(quantity="300", disclosed_quantity="100"))
        assert payload["quantity"] == 3
        assert payload["disclosed_quantity"] == 1

    def test_a_bad_disclosed_quantity_names_itself_in_the_error(self):
        """Not "Quantity": the order quantity here is a clean 3 contracts."""
        from broker.zerodha.mapping.transform_data import transform_data

        with pytest.raises(McxQuantityError) as exc:
            transform_data(self._order(quantity="300", disclosed_quantity="50"))
        assert "Disclosed quantity must be in multiples of lot size 100" in str(exc.value)

    def test_modify_names_disclosed_quantity_too(self):
        from broker.zerodha.mapping.transform_data import transform_modify_order_data

        with pytest.raises(McxQuantityError) as exc:
            transform_modify_order_data(
                {
                    "symbol": "CRUDEOIL17SEP268650CE",
                    "exchange": "MCX",
                    "pricetype": "LIMIT",
                    "price": 340.0,
                    "quantity": 200,
                    "disclosed_quantity": 50,
                }
            )
        assert "Disclosed quantity" in str(exc.value)

    def test_modify_converts_using_the_symbol_on_the_request(self):
        from broker.zerodha.mapping.transform_data import transform_modify_order_data

        payload = transform_modify_order_data(
            {
                "symbol": "CRUDEOIL17SEP268650CE",
                "exchange": "MCX",
                "pricetype": "LIMIT",
                "price": 340.0,
                "quantity": 200,
            }
        )
        assert payload["quantity"] == 2


class TestResponseBoundary:
    """Kite responses normalised into OpenAlgo units before anything reads them."""

    @pytest.fixture(autouse=True)
    def _stub_symbol_lookup(self, monkeypatch):
        import broker.zerodha.mapping.order_data as od

        monkeypatch.setattr(od, "get_oa_symbol", lambda brsymbol, exchange: brsymbol)

    def test_positionbook_reports_units(self):
        from broker.zerodha.mapping.order_data import (
            map_position_data,
            transform_positions_data,
        )

        raw = {
            "data": {
                "net": [
                    {
                        "tradingsymbol": "CRUDEOIL26SEP8650CE",
                        "exchange": "MCX",
                        "product": "NRML",
                        "quantity": -1,
                        "buy_quantity": 1,
                        "sell_quantity": 2,
                        "overnight_quantity": 3,
                        "day_buy_quantity": 1,
                        "day_sell_quantity": 2,
                        "average_price": 323.10,
                        "last_price": 323.50,
                        "pnl": -2578.0,
                    },
                    {
                        "tradingsymbol": "NIFTY26SEP24800CE",
                        "exchange": "NFO",
                        "product": "NRML",
                        "quantity": 75,
                        "average_price": 100.0,
                        "last_price": 101.0,
                        "pnl": 75.0,
                    },
                ]
            }
        }
        mapped = map_position_data(raw)
        # Every field in _POSITION_QTY_FIELDS, so a member added to that tuple
        # without a conversion, or one dropped from it, fails here.
        assert mapped[0]["quantity"] == -100
        assert mapped[0]["buy_quantity"] == 100
        assert mapped[0]["sell_quantity"] == 200
        assert mapped[0]["overnight_quantity"] == 300
        assert mapped[0]["day_buy_quantity"] == 100
        assert mapped[0]["day_sell_quantity"] == 200
        # Kite reports P&L and per-unit prices in rupees already; scaling those
        # too would double-count the lot size.
        assert mapped[0]["pnl"] == -2578.0
        assert mapped[0]["average_price"] == 323.10
        assert mapped[1]["quantity"] == 75

        assert transform_positions_data(mapped)[0]["quantity"] == -100

    def test_orderbook_reports_units(self):
        from broker.zerodha.mapping.order_data import map_order_data, transform_order_data

        raw = {
            "data": [
                {
                    "tradingsymbol": "CRUDEOIL26SEP8650CE",
                    "exchange": "MCX",
                    "transaction_type": "BUY",
                    "status": "COMPLETE",
                    "quantity": 3,
                    "filled_quantity": 1,
                    "pending_quantity": 2,
                    "disclosed_quantity": 1,
                    "cancelled_quantity": 0,
                    "order_type": "MARKET",
                    "product": "NRML",
                    "order_id": "26090407046951",
                    "price": 0.0,
                    "trigger_price": 0.0,
                }
            ]
        }
        # Every field in _ORDER_QTY_FIELDS. filled + pending must still add up
        # to quantity after conversion, which a per-field slip would break.
        mapped = map_order_data(raw)
        assert mapped[0]["quantity"] == 300
        assert mapped[0]["filled_quantity"] == 100
        assert mapped[0]["pending_quantity"] == 200
        assert mapped[0]["filled_quantity"] + mapped[0]["pending_quantity"] == 300
        assert mapped[0]["disclosed_quantity"] == 100
        assert mapped[0]["cancelled_quantity"] == 0
        assert transform_order_data(mapped)[0]["quantity"] == 300

    def test_absent_quantity_fields_are_not_invented(self):
        """The mapper converts in place; it must not add keys Kite did not send."""
        from broker.zerodha.mapping.order_data import map_order_data

        raw = {
            "data": [
                {
                    "tradingsymbol": "CRUDEOIL26SEP8650CE",
                    "exchange": "MCX",
                    "transaction_type": "BUY",
                    "status": "COMPLETE",
                    "quantity": 1,
                    "order_id": "1",
                }
            ]
        }
        mapped = map_order_data(raw)
        assert mapped[0]["quantity"] == 100
        assert "disclosed_quantity" not in mapped[0]
        assert "cancelled_quantity" not in mapped[0]

    def test_non_mcx_order_fields_are_all_untouched(self):
        from broker.zerodha.mapping.order_data import map_order_data

        raw = {
            "data": [
                {
                    "tradingsymbol": "NIFTY26SEP24800CE",
                    "exchange": "NFO",
                    "transaction_type": "BUY",
                    "status": "OPEN",
                    "quantity": 150,
                    "filled_quantity": 75,
                    "pending_quantity": 75,
                    "disclosed_quantity": 75,
                    "cancelled_quantity": 0,
                    "order_id": "1",
                }
            ]
        }
        mapped = map_order_data(raw)
        assert mapped[0]["quantity"] == 150
        assert mapped[0]["filled_quantity"] == 75
        assert mapped[0]["pending_quantity"] == 75
        assert mapped[0]["disclosed_quantity"] == 75
        assert mapped[0]["cancelled_quantity"] == 0

    def test_tradebook_value_uses_converted_quantity(self):
        from broker.zerodha.mapping.order_data import map_trade_data, transform_tradebook_data

        raw = {
            "data": [
                {
                    "tradingsymbol": "CRUDEOIL26SEP8650CE",
                    "exchange": "MCX",
                    "transaction_type": "BUY",
                    "product": "NRML",
                    "quantity": 1,
                    "average_price": 340.40,
                    "order_id": "26090407046951",
                }
            ]
        }
        trade = transform_tradebook_data(map_trade_data(raw))[0]
        assert trade["quantity"] == 100
        assert trade["trade_value"] == pytest.approx(34040.0)


class TestSquareOffRoundTrip:
    """The double-conversion trap.

    close_all_positions reads a raw Kite positionbook and feeds the quantity
    back into place_order_api, which divides. Without the multiply on the way
    in, a one-contract crude position squares off as quantity 0.
    """

    def test_a_one_contract_position_squares_off_as_one_contract(self):
        raw_kite_qty = -1
        symbol, exchange = "CRUDEOIL26SEP8650CE", "MCX"

        # What close_all_positions computes before building the payload.
        units = abs(int(from_kite_quantity(raw_kite_qty, symbol, exchange)))
        assert units == 100

        # What place_order_api then sends back to Kite.
        assert to_kite_quantity(units, symbol, exchange) == abs(raw_kite_qty)
