"""The four defects found in review of PR #1998, each pinned by a test.

1. MCXBULLDEX is 30 for the Sep/Oct 2026 contracts and 15 from November, both
   live simultaneously. A single number per underlying cannot express that.
2. Physical contract size is not the P&L multiplier. A commodity quoted in a
   different unit from the one it trades in diverges: GOLDGUINEA is 8 grams
   quoted per 8 grams, GOLDM is 100 grams quoted per 10 grams.
3. A quantity that will not convert must not be dropped from a margin basket
   and the remainder priced as though it were the basket asked for.
4. That same rejection must reach the caller as a 400 naming the reason, not a
   generic 500 from the service layer's blanket handler.
"""

from datetime import date
from types import SimpleNamespace

import pytest

from broker.zerodha.mapping.mcx_contract_size import (
    MCX_SIZE_REVISIONS,
    McxQuantityError,
    get_contract_size,
)


class TestExpiryTransition:
    """Defect 1. Verified against Angel One's live scrip master, which carries
    MCXBULLDEX at 30 for 25SEP2026 and 28OCT2026, and 15 for 27NOV2026 and
    30DEC2026."""

    @pytest.mark.parametrize(
        "expiry,expected",
        [
            (date(2026, 9, 25), 30),
            (date(2026, 10, 28), 30),
            (date(2026, 10, 31), 30),
            (date(2026, 11, 1), 15),
            (date(2026, 11, 27), 15),
            (date(2026, 12, 30), 15),
            (date(2027, 3, 1), 15),
        ],
    )
    def test_mcxbulldex_size_depends_on_expiry(self, expiry, expected):
        assert get_contract_size("MCXBULLDEX", expiry) == expected

    def test_without_an_expiry_the_unrevised_size_is_returned(self):
        """Right for the near months, wrong for the far ones.

        Which is why the master contract, the one caller that always has an
        expiry, always passes it.
        """
        assert get_contract_size("MCXBULLDEX") == 30

    def test_an_unrevised_root_ignores_expiry_entirely(self):
        for expiry in (None, date(2026, 9, 25), date(2027, 6, 1)):
            assert get_contract_size("CRUDEOIL", expiry) == 100
            assert get_contract_size("MCXMETLDEX", expiry) == 40

    def test_revisions_are_ordered_so_the_latest_wins(self):
        """A second revision appended out of order would silently not apply."""
        for root, revisions in MCX_SIZE_REVISIONS.items():
            dates = [d for d, _ in revisions]
            assert dates == sorted(dates), f"{root} revisions must ascend by date"
            assert all(size > 0 for _, size in revisions)

    def test_an_unknown_root_is_still_unknown_with_an_expiry(self):
        assert get_contract_size("NOTACOMMODITY", date(2026, 11, 1)) is None

    def test_cardamom_is_mapped_and_expiry_independent(self):
        """Angel carries 100 on all five live expiries, so no revision applies."""
        assert get_contract_size("CARDAMOM") == 100
        assert get_contract_size("CARDAMOM", date(2027, 1, 29)) == 100


class TestMasterContractIsAuthoritative:
    """The conversion factor must equal the lotsize the quantity was built from.

    OpenAlgo computes an order as lots * symtoken.lotsize, and the adapter
    divides that back to contracts. Any other number turns a correct request
    into a wrong order, so the row wins over the static table.
    """

    def test_the_master_contract_row_overrides_the_static_table(self, monkeypatch):
        import broker.zerodha.mapping.mcx_contract_size as mcx

        # The table says 30 for MCXBULLDEX; a November row says 15.
        monkeypatch.setattr(mcx, "_master_contract_lot_size", lambda s, e: 15)
        assert mcx.units_per_contract("MCXBULLDEX27NOV26FUT", "MCX") == 15
        assert mcx.to_kite_quantity(30, "MCXBULLDEX27NOV26FUT", "MCX") == 2

    def test_november_quantity_15_is_one_contract_not_a_rejection(self, monkeypatch):
        """Reproduces the reported failure: 15 was refused, 30 sent one
        contract where the user meant two."""
        import broker.zerodha.mapping.mcx_contract_size as mcx

        monkeypatch.setattr(mcx, "_master_contract_lot_size", lambda s, e: 15)
        assert mcx.to_kite_quantity(15, "MCXBULLDEX27NOV26FUT", "MCX") == 1

    def test_falls_back_to_the_table_when_there_is_no_row(self, monkeypatch):
        import broker.zerodha.mapping.mcx_contract_size as mcx

        monkeypatch.setattr(mcx, "_master_contract_lot_size", lambda s, e: None)
        assert mcx.units_per_contract("CRUDEOIL26SEPFUT", "MCX") == 100

    def test_a_lookup_failure_never_breaks_the_order_path(self, monkeypatch):
        """An unseeded table or a missing app context degrades, never raises."""
        import broker.zerodha.mapping.mcx_contract_size as mcx

        def boom(symbol, exchange):
            raise RuntimeError("no application context")

        monkeypatch.setattr(mcx, "get_contract_size", get_contract_size)
        monkeypatch.setattr(
            "database.token_db_enhanced.get_symbol_info",
            lambda *a, **k: (_ for _ in ()).throw(RuntimeError("no app context")),
        )
        assert mcx.units_per_contract("CRUDEOIL26SEPFUT", "MCX") == 100

    def test_a_stale_lotsize_of_one_keeps_the_old_behaviour(self, monkeypatch):
        """Before the master contract is rebuilt, lotsize is Kite's 1.

        quantity = lots * 1 = 1, and dividing by 1 sends 1 contract. The old
        contract-denominated behaviour, exactly -- no 100x order from a
        half-upgraded install.
        """
        import broker.zerodha.mapping.mcx_contract_size as mcx

        monkeypatch.setattr(mcx, "_master_contract_lot_size", lambda s, e: 1)
        assert mcx.units_per_contract("CRUDEOIL26SEPFUT", "MCX") == 1
        assert mcx.to_kite_quantity(1, "CRUDEOIL26SEPFUT", "MCX") == 1


class TestValuationUsesKiteMultiplier:
    """Defect 2. Contract size and P&L multiplier are different numbers."""

    @pytest.fixture
    def margin_data(self, monkeypatch):
        """Drive get_margin_data against mocked Kite responses."""
        import broker.zerodha.api.funds as funds

        def run(tradingsymbol, quantity, multiplier, avg_price, ltp):
            class Resp:
                def __init__(self, payload):
                    self._payload = payload

                def raise_for_status(self):
                    return None

                def json(self):
                    return self._payload

            def get(url, headers=None, **kw):
                if "user/margins" in url:
                    return Resp(
                        {
                            "status": "success",
                            "data": {
                                "equity": {
                                    "net": 0,
                                    "available": {"live_balance": 0, "collateral": 0},
                                    "utilised": {"debits": 0},
                                },
                                "commodity": {
                                    "net": 0,
                                    "available": {"live_balance": 0, "collateral": 0},
                                    "utilised": {"debits": 0},
                                },
                            },
                        }
                    )
                if "portfolio/positions" in url:
                    return Resp(
                        {
                            "status": "success",
                            "data": {
                                "net": [
                                    {
                                        "tradingsymbol": tradingsymbol,
                                        "exchange": "MCX",
                                        "quantity": quantity,
                                        "multiplier": multiplier,
                                        "average_price": avg_price,
                                        "last_price": ltp,
                                        "buy_value": 0,
                                        "sell_value": 0,
                                    }
                                ]
                            },
                        }
                    )
                if "quote/ltp" in url:
                    return Resp({"status": "success", "data": {f"MCX:{tradingsymbol}": {"last_price": ltp}}})
                raise AssertionError(f"unexpected url {url}")

            monkeypatch.setattr(funds, "get_httpx_client", lambda: SimpleNamespace(get=get))
            return float(funds.get_margin_data("k:t")["m2munrealized"])

        return run

    @pytest.mark.parametrize(
        "symbol,multiplier,expected,why",
        [
            ("CRUDEOIL26SEPFUT", 100, 100.0, "100 barrels quoted per barrel"),
            ("GOLDGUINEA26OCTFUT", 1, 1.0, "8 grams quoted per 8 grams"),
            ("GOLDM26OCTFUT", 10, 10.0, "100 grams quoted per 10 grams"),
            ("GOLD26OCTFUT", 100, 100.0, "1 kg quoted per 10 grams"),
            ("SILVER26SEPFUT", 30, 30.0, "30 kg quoted per kg"),
        ],
    )
    def test_one_rupee_move_on_one_contract(
        self, margin_data, symbol, multiplier, expected, why
    ):
        """A one rupee move on a single contract is worth Kite's multiplier.

        Scaling by physical contract size instead reports GOLDGUINEA as 8 and
        GOLDM as 100 -- the former a regression on behaviour that was correct
        before the units conversion existed.
        """
        got = margin_data(symbol, quantity=1, multiplier=multiplier, avg_price=100.0, ltp=101.0)
        assert got == pytest.approx(expected), why

    def test_a_missing_multiplier_does_not_zero_the_pnl(self, margin_data):
        """Absent or null, it must behave as 1, never as 0."""
        assert margin_data(
            "CRUDEOIL26SEPFUT", quantity=5, multiplier=None, avg_price=100.0, ltp=101.0
        ) == pytest.approx(5.0)


class TestMarginBasketIsNotSilentlyTruncated:
    """Defect 3. A dropped leg prices a basket nobody asked for."""

    @pytest.fixture(autouse=True)
    def _stub_symbol_lookup(self, monkeypatch):
        import broker.zerodha.mapping.margin_data as md

        monkeypatch.setattr(md, "get_br_symbol", lambda symbol, exchange: symbol)
        monkeypatch.setattr(
            "broker.zerodha.mapping.mcx_contract_size._master_contract_lot_size",
            lambda s, e: None,
        )

    def _basket(self):
        return [
            {
                "symbol": "CRUDEOIL26SEPFUT",
                "exchange": "MCX",
                "action": "BUY",
                "product": "NRML",
                "pricetype": "MARKET",
                "quantity": 150,  # not a whole number of 100-barrel contracts
                "price": 0,
            },
            {
                "symbol": "NIFTY28MAR2420800CE",
                "exchange": "NFO",
                "action": "BUY",
                "product": "NRML",
                "pricetype": "MARKET",
                "quantity": 75,
                "price": 0,
            },
        ]

    def test_the_bad_leg_is_raised_not_skipped(self):
        from broker.zerodha.mapping.margin_data import transform_margin_positions

        with pytest.raises(McxQuantityError) as exc:
            transform_margin_positions(self._basket())
        assert "multiples of lot size 100" in str(exc.value)

    def test_a_clean_basket_still_transforms(self):
        from broker.zerodha.mapping.margin_data import transform_margin_positions

        basket = self._basket()
        basket[0]["quantity"] = 200
        out = transform_margin_positions(basket)
        assert len(out) == 2
        assert out[0]["quantity"] == 2  # 200 barrels -> 2 contracts
        assert out[1]["quantity"] == 75  # NFO untouched


class TestQuantityErrorsReachTheCallerAs400:
    """Defect 4. The service layer's blanket handler turns a raised exception
    into 'internal error' with a 500 and an order-failed event. The reason the
    order was refused has to survive that."""

    @pytest.fixture(autouse=True)
    def _stub_symbol_lookup(self, monkeypatch):
        import broker.zerodha.mapping.transform_data as td

        monkeypatch.setattr(td, "get_br_symbol", lambda symbol, exchange: symbol)
        monkeypatch.setattr(
            "broker.zerodha.mapping.mcx_contract_size._master_contract_lot_size",
            lambda s, e: None,
        )

    def _order(self, **over):
        base = {
            "symbol": "CRUDEOIL26SEPFUT",
            "exchange": "MCX",
            "action": "BUY",
            "pricetype": "MARKET",
            "product": "NRML",
            "quantity": "150",
            "price": "0",
            "trigger_price": "0",
        }
        base.update(over)
        return base

    def test_place_order_returns_400_with_the_reason(self):
        from broker.zerodha.api.order_api import place_order_api

        res, data, orderid = place_order_api(self._order(), "token")

        assert res.status == 400, "the service reads res.status; 500 would be a lie"
        assert orderid is None
        assert "multiples of lot size 100" in data["message"]
        assert data["status"] == "error"

    def test_a_bad_disclosed_quantity_names_itself(self):
        from broker.zerodha.api.order_api import place_order_api

        _, data, _ = place_order_api(
            self._order(quantity="300", disclosed_quantity="50"), "token"
        )
        assert "Disclosed quantity" in data["message"]

    def test_modify_order_returns_400_with_the_reason(self):
        from broker.zerodha.api.order_api import modify_order

        data, status = modify_order(
            {
                "orderid": "1",
                "symbol": "CRUDEOIL26SEPFUT",
                "exchange": "MCX",
                "pricetype": "LIMIT",
                "price": 100.0,
                "quantity": 150,
            },
            "token",
        )
        assert status == 400
        assert "multiples of lot size 100" in data["message"]


class TestRevisedSizeIsNeverGuessed:
    """Second-round defect 1. The static table is keyed by root alone, so for an
    underlying MCX has revised it cannot answer without an expiry -- and the
    symbol does not carry one unambiguously (Kite writes year-month, OpenAlgo
    writes day-month-year). Guessing the pre-revision size halves the order or
    doubles it."""

    @pytest.fixture(autouse=True)
    def _no_master_row(self, monkeypatch):
        monkeypatch.setattr(
            "broker.zerodha.mapping.mcx_contract_size._master_contract_lot_size",
            lambda s, e: None,
        )

    def test_an_outbound_conversion_refuses_rather_than_guessing(self):
        import broker.zerodha.mapping.mcx_contract_size as mcx

        with pytest.raises(McxQuantityError) as exc:
            mcx.to_kite_quantity(30, "MCXBULLDEX27NOV26FUT", "MCX")
        assert "revised its contract size" in str(exc.value)
        assert "master contract" in str(exc.value)

    def test_an_inbound_conversion_passes_through_rather_than_raising(self):
        """An orderbook read must never raise, and must not invent 60 from 2."""
        import broker.zerodha.mapping.mcx_contract_size as mcx

        assert mcx.from_kite_quantity(2, "MCXBULLDEX27NOV26FUT", "MCX") == 2

    def test_an_unrevised_root_still_uses_the_table(self):
        import broker.zerodha.mapping.mcx_contract_size as mcx

        assert mcx.to_kite_quantity(300, "CRUDEOIL26SEPFUT", "MCX") == 3
        assert mcx.from_kite_quantity(3, "CRUDEOIL26SEPFUT", "MCX") == 300

    def test_with_a_master_row_the_revised_root_converts_normally(self, monkeypatch):
        import broker.zerodha.mapping.mcx_contract_size as mcx

        monkeypatch.setattr(mcx, "_master_contract_lot_size", lambda s, e: 15)
        assert mcx.to_kite_quantity(30, "MCXBULLDEX27NOV26FUT", "MCX") == 2


class TestTradeValuation:
    """Second-round defect 2. Quantity times price only values a trade where the
    instrument is quoted in the unit it trades in."""

    @pytest.fixture(autouse=True)
    def _stub(self, monkeypatch):
        import broker.zerodha.mapping.order_data as od

        monkeypatch.setattr(od, "get_oa_symbol", lambda brsymbol, exchange: brsymbol)
        monkeypatch.setattr(
            "broker.zerodha.mapping.mcx_contract_size._master_contract_lot_size",
            lambda s, e: {
                "GOLDGUINEA26OCTFUT": 8,
                "GOLDM26OCTFUT": 100,
                "GOLD26OCTFUT": 1,
                "CRUDEOIL26SEPFUT": 100,
                "SILVER26SEPFUT": 30,
                "ZINC26SEPFUT": 5,
            }.get(s),
        )

    def _value(self, symbol, exchange, kite_quantity, price):
        from broker.zerodha.mapping.order_data import map_trade_data, transform_tradebook_data

        raw = {
            "data": [
                {
                    "tradingsymbol": symbol,
                    "exchange": exchange,
                    "transaction_type": "BUY",
                    "product": "NRML",
                    "quantity": kite_quantity,
                    "average_price": price,
                    "order_id": "1",
                }
            ]
        }
        return transform_tradebook_data(map_trade_data(raw))[0]["trade_value"]

    @pytest.mark.parametrize(
        "symbol,price,expected,why",
        [
            ("CRUDEOIL26SEPFUT", 8566.0, 856600.0, "100 bbl quoted per bbl"),
            ("SILVER26SEPFUT", 150000.0, 4500000.0, "30 kg quoted per kg"),
            ("GOLDGUINEA26OCTFUT", 120000.0, 120000.0, "8 g quoted per 8 g"),
            ("GOLDM26OCTFUT", 150000.0, 1500000.0, "100 g quoted per 10 g"),
            ("GOLD26OCTFUT", 150000.0, 15000000.0, "1 kg quoted per 10 g"),
            ("ZINC26SEPFUT", 300.0, 1500000.0, "5 MT quoted per kg"),
        ],
    )
    def test_one_contract_is_valued_by_its_quotation_basis(
        self, symbol, price, expected, why
    ):
        assert self._value(symbol, "MCX", 1, price) == pytest.approx(expected), why

    def test_non_mcx_is_quantity_times_price_exactly_as_before(self):
        assert self._value("NIFTY26SEP24800CE", "NFO", 75, 100.0) == pytest.approx(7500.0)

    def test_multiple_contracts_scale(self):
        assert self._value("GOLDGUINEA26OCTFUT", "MCX", 3, 120000.0) == pytest.approx(360000.0)


class TestGttQuantityErrors:
    """Second-round defect 3. Zerodha supports MCX GTT, so this path is live."""

    @pytest.fixture(autouse=True)
    def _stub(self, monkeypatch):
        import broker.zerodha.mapping.gtt_data as gd

        monkeypatch.setattr(gd, "get_br_symbol", lambda symbol, exchange: symbol)
        monkeypatch.setattr(
            "broker.zerodha.mapping.mcx_contract_size._master_contract_lot_size",
            lambda s, e: 100 if s.startswith("CRUDEOIL") else None,
        )

    def _gtt(self, quantity):
        return {
            "symbol": "CRUDEOIL26SEPFUT",
            "exchange": "MCX",
            "action": "BUY",
            "product": "NRML",
            "pricetype": "LIMIT",
            "quantity": quantity,
            "trigger_type": "SINGLE",
            "trigger_price": 8500.0,
            "price": 8500.0,
            "last_price": 8566.0,
        }

    def test_place_gtt_returns_400_with_the_reason(self):
        from broker.zerodha.api.gtt_api import place_gtt_order

        res, data, trigger_id = place_gtt_order(self._gtt(150), "token")
        assert res.status == 400
        assert trigger_id is None
        assert "multiples of lot size 100" in data["message"]

    def test_modify_gtt_returns_400_with_the_reason(self):
        """Unpacked exactly as services/modify_gtt_order_service.py:87 does.

        The previous version of this test unpacked three values because that is
        what the implementation happened to return, so it passed while the
        service raised ValueError on the same call and reported a generic 500.
        Asserting the caller's contract is the whole point.
        """
        from broker.zerodha.api.gtt_api import modify_gtt_order

        payload = self._gtt(150)
        payload["trigger_id"] = "1"
        response_message, status_code = modify_gtt_order(payload, "token")
        assert status_code == 400
        assert "multiples of lot size 100" in response_message["message"]

    def test_place_and_modify_keep_their_different_arities(self):
        """place returns 3, modify returns 2. Swapping them is a 500."""
        from broker.zerodha.api.gtt_api import modify_gtt_order, place_gtt_order

        payload = self._gtt(150)
        payload["trigger_id"] = "1"
        assert len(place_gtt_order(self._gtt(150), "token")) == 3
        assert len(modify_gtt_order(payload, "token")) == 2


class TestTradingDecisionsRefuseUnresolvedSizes:
    """Third-round defect 1. Passing an unresolved size through as factor 1 is
    safe for display and dangerous for a decision."""

    @pytest.fixture(autouse=True)
    def _no_master_row(self, monkeypatch):
        import broker.zerodha.api.order_api as oa

        monkeypatch.setattr(oa, "get_br_symbol", lambda symbol, exchange: symbol)
        monkeypatch.setattr(
            "broker.zerodha.mapping.mcx_contract_size._master_contract_lot_size",
            lambda s, e: None,
        )
        monkeypatch.setattr(
            oa,
            "_get_cached_positions",
            lambda auth: {
                "status": True,
                "data": {
                    "net": [
                        {
                            "tradingsymbol": "MCXBULLDEX27NOV26FUT",
                            "exchange": "MCX",
                            "product": "NRML",
                            "quantity": 30,
                        }
                    ]
                },
            },
        )

    def test_reading_the_open_position_refuses(self):
        from broker.zerodha.api.order_api import get_open_position

        with pytest.raises(McxQuantityError) as exc:
            get_open_position("MCXBULLDEX27NOV26FUT", "MCX", "NRML", "token")
        assert "revised its contract size" in str(exc.value)

    def test_the_smart_order_refuses_instead_of_matching(self, monkeypatch):
        """30 contracts is 450 units. Read as 30 it equals a 30 unit target and
        the smart order reports success having placed nothing, leaving 450
        units open."""
        import broker.zerodha.api.order_api as oa

        called = []
        monkeypatch.setattr(
            oa, "place_order_api", lambda *a, **k: called.append(a) or (None, {}, "1")
        )

        res, data, orderid = oa.place_smartorder_api(
            {
                "symbol": "MCXBULLDEX27NOV26FUT",
                "exchange": "MCX",
                "product": "NRML",
                "position_size": "30",
                "action": "BUY",
                "quantity": "30",
                "pricetype": "MARKET",
            },
            "token",
        )
        assert res.status == 400, "must not be a 500 from the generic handler"
        assert orderid is None
        assert "revised its contract size" in data["message"]
        assert called == [], "no order should reach Kite"
        assert "already matched" not in data["message"].lower()


class TestCloseAllReportsRefusedExits:
    """Third-round defect 2. A refused exit leaves the position open, so
    reporting it as squared off stops anyone watching it."""

    @pytest.fixture(autouse=True)
    def _positions(self, monkeypatch):
        import broker.zerodha.api.order_api as oa

        monkeypatch.setattr(oa, "get_oa_symbol", lambda sym, exch: sym)
        monkeypatch.setattr(
            oa,
            "get_positions",
            lambda auth: {
                "status": True,
                "data": {
                    "net": [
                        {
                            "tradingsymbol": "MCXBULLDEX27NOV26FUT",
                            "exchange": "MCX",
                            "product": "NRML",
                            "quantity": 2,
                        }
                    ]
                },
            },
        )

    def test_a_refused_exit_is_reported_not_swallowed(self, monkeypatch):
        import broker.zerodha.api.order_api as oa

        class Refused:
            status = 400

        monkeypatch.setattr(
            oa,
            "place_order_api",
            lambda payload, auth: (Refused(), {"status": "error", "message": "nope"}, None),
        )

        body, code = oa.close_all_positions("key", "token")
        assert code == 500
        assert body["status"] == "error"
        assert "still open" in body["message"]
        assert "MCXBULLDEX27NOV26FUT" in body["message"]

    def test_a_clean_square_off_still_reports_success(self, monkeypatch):
        import broker.zerodha.api.order_api as oa

        class Ok:
            status = 200

        monkeypatch.setattr(
            oa, "place_order_api", lambda payload, auth: (Ok(), {"status": "success"}, "250101")
        )

        body, code = oa.close_all_positions("key", "token")
        assert code == 200
        assert body["status"] == "success"


class TestQuotationMultiplierResolvesTheFullRoot:
    """Third-round defect 4. A prefix match against the override table alone
    reads GOLDPETAL as GOLD."""

    @pytest.fixture(autouse=True)
    def _no_master_row(self, monkeypatch):
        monkeypatch.setattr(
            "broker.zerodha.mapping.mcx_contract_size._master_contract_lot_size",
            lambda s, e: None,
        )

    @pytest.mark.parametrize(
        "symbol,expected",
        [
            ("GOLDPETAL26OCTFUT", 1),
            ("GOLD26OCTFUT", 100),
            ("GOLDM26OCTFUT", 10),
            ("GOLDTEN26OCTFUT", 1),
            ("GOLDGUINEA26OCTFUT", 1),
            ("SILVER26SEPFUT", 30),
            ("SILVERM26SEPFUT", 5),
            ("SILVERMIC26SEPFUT", 1),
            ("ZINC26SEPFUT", 5000),
            ("ZINCMINI26SEPFUT", 1000),
            ("ALUMINIUM26SEPFUT", 5000),
            ("ALUMINI26SEPFUT", 1000),
            ("KAPAS26APRFUT", 200),
            ("COTTONOIL26SEPFUT", 500),
            ("CRUDEOIL26SEPFUT", 100),
            ("CRUDEOILM26SEPFUT", 10),
        ],
    )
    def test_each_family_member_gets_its_own_multiplier(self, symbol, expected):
        from broker.zerodha.mapping.mcx_contract_size import price_multiplier

        assert price_multiplier(symbol, "MCX") == expected

    def test_off_mcx_is_always_one(self):
        from broker.zerodha.mapping.mcx_contract_size import price_multiplier

        assert price_multiplier("NIFTY28MAR2420800CE", "NFO") == 1

    def test_every_override_names_a_real_underlying(self):
        """An override for a root that does not exist can never fire."""
        from broker.zerodha.mapping.mcx_contract_size import (
            MCX_CONTRACT_SIZES,
            MCX_QUOTATION_MULTIPLIERS,
        )

        unknown = set(MCX_QUOTATION_MULTIPLIERS) - set(MCX_CONTRACT_SIZES)
        assert not unknown, f"quotation multipliers for unknown roots: {sorted(unknown)}"

    def test_a_one_gram_contract_is_not_valued_as_a_kilo(self):
        """GOLDPETAL at 15,000 was reporting 15,00,000."""
        from broker.zerodha.mapping.mcx_contract_size import price_multiplier

        assert 1 * price_multiplier("GOLDPETAL26OCTFUT", "MCX") * 15000 == 15000


class TestMultiplierCommentsMatchTheirValues:
    """Each override is annotated `contract size / quotation unit`. This parses
    that annotation and re-derives the number.

    It exists because the review caught a comment saying SILVER100 was quoted
    per kg while the value was built on 10 g. The value was right, so nothing
    failed -- but a reader trusting the prose over the number would have
    "corrected" a correct multiplier. A comment that cannot drift from its
    value is worth more than one that is merely right today.
    """

    _UNITS = {"g": 1.0, "kg": 1000.0, "MT": 1_000_000.0}

    @staticmethod
    def _grams(text):
        import re

        count, unit = re.match(r"([\d,]+(?:\.\d+)?)?\s*(g|kg|MT)", text.strip()).groups()
        return float((count or "1").replace(",", "")) * TestMultiplierCommentsMatchTheirValues._UNITS[unit]

    def _annotations(self):
        import pathlib
        import re

        src = pathlib.Path(
            "broker/zerodha/mapping/mcx_contract_size.py"
        ).read_text(encoding="utf-8")
        block = src.split("MCX_QUOTATION_MULTIPLIERS: dict[str, int] = {")[1].split("}")[0]
        rows = []
        for line in block.strip().splitlines():
            m = re.match(r'\s*"(\w+)":\s*(\d+),\s*#\s*(.+?)\s*/\s*(.+)$', line)
            assert m, f"every override needs a 'size / unit' comment: {line.strip()!r}"
            rows.append((m.group(1), int(m.group(2)), m.group(3), m.group(4)))
        return rows

    def test_every_override_is_annotated(self):
        from broker.zerodha.mapping.mcx_contract_size import MCX_QUOTATION_MULTIPLIERS

        assert len(self._annotations()) == len(MCX_QUOTATION_MULTIPLIERS)

    def test_every_annotation_derives_its_own_value(self):
        for root, value, size, unit in self._annotations():
            derived = self._grams(size) / self._grams(unit)
            assert derived == pytest.approx(value), (
                f"{root}: comment says {size} / {unit} = {derived:g}, "
                f"but the table says {value}"
            )
