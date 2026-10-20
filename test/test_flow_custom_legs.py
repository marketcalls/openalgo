"""Manually built legs on the Multi-Leg Options node.

The readymade strategies cover the baskets whose legs share one expiry and sit
at an offset from the money. A calendar spread, a diagonal, a ratio, or a basket
pinned to strikes the trader already chose cannot be said that way -- each leg
has to name its own strike, expiry and side.

The executor has accepted all of that for a while. Two things did not:

* the validator required `offset` on every leg, so a leg naming an absolute
  strike was rejected before it could be saved; and
* the editor said "Configure custom legs via API", so the only way in was to
  hand-write the workflow JSON.

A leg accepted by the validator must not fail at run time, because a multi-leg
basket fails leg by leg: by the time leg three is refused, legs one and two are
already filled and the position is not the one anybody chose.
"""

import io
import os
import re
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.flow_node_contracts import (  # noqa: E402
    EXPIRY_DATE_PATTERN,
    OPTION_OFFSET_PATTERN,
    VALID_EXPIRY_TYPES,
    VALID_LEG_STRIKE_MODES,
)
from services.flow_workflow_validator import validate_workflow  # noqa: E402

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
POSITION = {"x": 0, "y": 0}

BASE_LEG = {"optionType": "CE", "action": "BUY", "quantity": 1}


def validate_legs(*legs, strict=True, **node_overrides):
    """Codes raised for a custom multi-leg node carrying these legs."""
    data = {
        "strategy": "custom",
        "underlying": "NIFTY",
        "quantity": 1,
        "legs": list(legs),
        **node_overrides,
    }
    workflow = {
        "name": "t",
        "nodes": [
            {"id": "n1", "type": "start", "position": POSITION, "data": {}},
            {"id": "n2", "type": "optionsMultiOrder", "position": POSITION, "data": data},
        ],
        "edges": [{"id": "e1", "source": "n1", "target": "n2"}],
    }
    return [error["code"] for error in validate_workflow(workflow, require_name=False, strict=strict)]


class TestALegPicksItsStrikeEitherWay:
    def test_an_offset_leg_is_accepted(self):
        assert validate_legs({**BASE_LEG, "offset": "ATM"}) == []

    def test_a_leg_naming_an_absolute_strike_is_accepted(self):
        """This was rejected outright: the validator demanded `offset`, so the
        strike path the executor implements could not be saved."""
        assert validate_legs({**BASE_LEG, "strikeMode": "STRIKE", "strike": 24500}) == []

    def test_a_strike_leg_needs_no_offset(self):
        assert "missing_required_field" not in validate_legs(
            {**BASE_LEG, "strikeMode": "STRIKE", "strike": 24500}
        )

    def test_a_leg_naming_neither_cannot_execute(self):
        assert "missing_required_field" in validate_legs(BASE_LEG)

    def test_a_leg_naming_neither_still_saves_while_being_built(self):
        """Presence is a strict-only check, or a half-built leg blocks the save."""
        assert validate_legs(BASE_LEG, strict=False) == []

    @pytest.mark.parametrize("strike", [0, -100, "0", "abc", True])
    def test_a_strike_that_names_no_contract_is_refused(self, strike):
        """bool is an int subclass, so True would otherwise pass as strike 1."""
        assert "invalid_strike" in validate_legs(
            {**BASE_LEG, "strikeMode": "STRIKE", "strike": strike}
        )

    @pytest.mark.parametrize("strike", [24500, 24500.5, "24500"])
    def test_a_usable_strike_is_accepted_in_either_type(self, strike):
        assert validate_legs({**BASE_LEG, "strikeMode": "STRIKE", "strike": strike}) == []

    @pytest.mark.parametrize("offset", ["ATM", "ITM1", "ITM50", "OTM1", "OTM50"])
    def test_the_offset_range_the_executor_accepts(self, offset):
        assert validate_legs({**BASE_LEG, "offset": offset}) == []

    @pytest.mark.parametrize("offset", ["OTM99", "ATM1", "DEEP", "ITM0"])
    def test_an_offset_outside_that_range_is_refused(self, offset):
        assert "invalid_constant" in validate_legs({**BASE_LEG, "offset": offset})

    @pytest.mark.parametrize("mode", ["OFFSET", "STRIKE"])
    def test_both_strike_modes_are_known(self, mode):
        assert mode in VALID_LEG_STRIKE_MODES

    def test_an_unknown_strike_mode_is_refused(self):
        assert "invalid_constant" in validate_legs(
            {**BASE_LEG, "strikeMode": "NEAREST", "strike": 100}
        )


class TestALegMayOverrideTheNodeExpiry:
    """What makes a calendar or diagonal spread expressible."""

    def test_an_exact_expiry_is_accepted(self):
        assert validate_legs({**BASE_LEG, "offset": "ATM", "expiry": "28OCT25"}) == []

    @pytest.mark.parametrize("expiry_type", sorted(VALID_EXPIRY_TYPES))
    def test_every_relative_expiry_is_accepted(self, expiry_type):
        assert validate_legs({**BASE_LEG, "offset": "ATM", "expiryType": expiry_type}) == []

    @pytest.mark.parametrize("expiry", ["2025-10-28", "28-OCT-25", "OCT2825", "28OCTOBER25"])
    def test_a_malformed_expiry_is_caught_before_the_run(self, expiry):
        """It used to save cleanly and fail mid-basket, after earlier legs filled."""
        assert "invalid_expiry" in validate_legs({**BASE_LEG, "offset": "ATM", "expiry": expiry})

    def test_an_unknown_relative_expiry_is_refused(self):
        assert "invalid_constant" in validate_legs(
            {**BASE_LEG, "offset": "ATM", "expiryType": "next_year"}
        )

    def test_a_leg_that_names_no_expiry_inherits_the_node(self):
        assert validate_legs({**BASE_LEG, "offset": "ATM"}) == []

    def test_a_calendar_spread_validates(self):
        """Same strike, two expiries -- the shape no readymade strategy covers."""
        assert (
            validate_legs(
                {**BASE_LEG, "strikeMode": "STRIKE", "strike": 24500, "expiry": "28OCT25"},
                {
                    "optionType": "CE",
                    "action": "SELL",
                    "quantity": 1,
                    "strikeMode": "STRIKE",
                    "strike": 24500,
                    "expiry": "25NOV25",
                },
            )
            == []
        )


class TestRunTimeValuesAreLeftToTheExecutor:
    @pytest.mark.parametrize(
        "field,value",
        [
            ("strike", "{{webhook.strike}}"),
            ("offset", "{{webhook.offset}}"),
            ("expiry", "{{webhook.expiry}}"),
            ("expiryType", "{{webhook.expiryType}}"),
            ("strikeMode", "{{webhook.mode}}"),
        ],
    )
    def test_a_variable_reference_is_not_checked_for_shape(self, field, value):
        """Only the resolved value can be checked, and the executor does that
        before it calls the broker."""
        leg = {**BASE_LEG, "offset": "ATM", field: value}
        assert validate_legs(leg) == []


class TestTheValidatorAndTheExecutorAgree:
    """Both read the same contracts, so neither can drift on its own."""

    def test_the_shared_patterns_are_the_ones_the_executor_uses(self):
        import services.flow_executor_service as fes

        assert fes._OPTION_OFFSET_PATTERN is OPTION_OFFSET_PATTERN
        assert fes._EXPIRY_DATE_PATTERN is EXPIRY_DATE_PATTERN
        assert fes.VALID_EXPIRY_TYPES is VALID_EXPIRY_TYPES
        assert fes.VALID_LEG_STRIKE_MODES is VALID_LEG_STRIKE_MODES

    def test_neither_module_redefines_them(self):
        """Two copies of a rule is how the two halves stop agreeing."""
        for path in (
            "services/flow_executor_service.py",
            "services/flow_workflow_validator.py",
        ):
            with open(os.path.join(REPO_ROOT, path), encoding="utf-8") as handle:
                source = handle.read()
            assert "ATM|(?:ITM|OTM)" not in source, path
            assert '"current_week", "next_week"' not in source, path


#: A seeded leg is written either with a literal side -- leg('OTM2', 'CE',
#: 'SELL') -- or with the node's common action, leg('ATM', 'CE', action). Both
#: forms have to be read, or a strategy written the second way silently
#: compares as an empty list and the parity assertion passes vacuously.
_SEEDED_LEG = re.compile(r"leg\((width|'[^']+'), '([^']+)', (action|'[^']+')\)")


def _seeded_legs_from_frontend(
    strategy: str, *, action: str = "BUY", strangle_width: str = "OTM2"
) -> list[tuple[str, str, str]]:
    """The (offset, optionType, action) triples the editor's template emits.

    Read from the source so the assertion is about the shipped behaviour rather
    than a restatement of it here. The two identifiers the seeding function uses
    are substituted with the values the caller would have passed.
    """
    path = os.path.join(REPO_ROOT, "frontend", "src", "lib", "flow", "customLegs.ts")
    with open(path, encoding="utf-8") as handle:
        source = handle.read()

    body = source.split("export function seedLegsFromStrategy", 1)[1]
    case = body.split(f"case '{strategy}':", 1)[1].split("case '", 1)[0]

    def resolve(token: str, identifiers: dict[str, str]) -> str:
        return identifiers[token] if token in identifiers else token.strip("'")

    legs = [
        (
            resolve(match.group(1), {"width": strangle_width}),
            match.group(2),
            resolve(match.group(3), {"action": action}),
        )
        for match in _SEEDED_LEG.finditer(case)
    ]
    assert legs, f"no seeded legs parsed for {strategy}; the seeding source changed shape"
    return legs


class TestTemplatesSeedWhatTheGeneratorBuilds:
    """Load a readymade strategy, save it untouched, and it has to trade what
    the generated strategy would have traded. If the two lists drift, "start
    from a template" quietly becomes a different position than the preview.
    """

    @pytest.mark.parametrize(
        "strategy", ["iron_condor", "bull_call_spread", "bear_put_spread"]
    )
    def test_the_fixed_side_strategies_match_leg_for_leg(self, strategy):
        from services.flow_executor_service import NodeExecutor, WorkflowContext

        executor = NodeExecutor(None, WorkflowContext(), [])
        generated = executor._generate_strategy_legs(strategy, "BUY", 1, "MIS")
        backend = [(leg["offset"], leg["option_type"], leg["action"]) for leg in generated]

        assert backend == _seeded_legs_from_frontend(strategy)

    @pytest.mark.parametrize("action", ["BUY", "SELL"])
    def test_a_straddle_follows_the_common_action_on_both_sides(self, action):
        from services.flow_executor_service import NodeExecutor, WorkflowContext

        executor = NodeExecutor(None, WorkflowContext(), [])
        generated = executor._generate_strategy_legs("straddle", action, 1, "MIS")
        backend = [(leg["offset"], leg["option_type"], leg["action"]) for leg in generated]

        assert backend == _seeded_legs_from_frontend("straddle", action=action)

    @pytest.mark.parametrize("width", ["OTM2", "OTM5"])
    def test_a_strangle_matches_at_whatever_width_is_configured(self, width):
        from services.flow_executor_service import NodeExecutor, WorkflowContext

        executor = NodeExecutor(None, WorkflowContext(), [])
        generated = executor._generate_strategy_legs("strangle", "SELL", 1, "MIS", width)
        backend = [(leg["offset"], leg["option_type"], leg["action"]) for leg in generated]

        assert backend == _seeded_legs_from_frontend(
            "strangle", action="SELL", strangle_width=width
        )

    def test_every_seeded_template_is_a_basket_the_validator_accepts(self):
        """Loading a template must never produce a basket that cannot be saved."""
        for strategy in ("iron_condor", "bull_call_spread", "bear_put_spread"):
            legs = [
                {
                    "offset": offset,
                    "optionType": option_type,
                    "action": action,
                    "quantity": 1,
                    "strikeMode": "OFFSET",
                }
                for offset, option_type, action in _seeded_legs_from_frontend(strategy)
            ]
            assert legs, strategy
            assert validate_legs(*legs) == [], strategy


class TestTheEditorNoLongerSendsUsersToTheApi:
    def test_the_panel_builds_legs_itself(self):
        path = os.path.join(
            REPO_ROOT, "frontend", "src", "components", "flow", "panels", "ConfigPanel.tsx"
        )
        with open(path, encoding="utf-8") as handle:
            source = handle.read()

        assert "Configure custom legs via API" not in source
        assert "CustomLegsFields" in source


class _FakeClient:
    """Records what the multi-order service would have been asked to place."""

    def __init__(self, expiries):
        self.expiries = expiries
        self.sent = {}

    def get_expiry(self, **kwargs):
        return {"status": "success", "data": self.expiries}

    def options_multi_order(self, **kwargs):
        self.sent = kwargs
        return {"status": "success", "results": []}


class TestALegReachesTheBrokerAsBuilt:
    """The end of the chain: what the editor builds is what gets placed.

    Every layer in between has its own checks, but only this proves the four
    selectors survive together - strike, expiry, side and size - which is the
    whole point of building a leg by hand.
    """

    def _place(self, legs, expiries=("28-AUG-26", "25-SEP-26", "30-OCT-26")):
        from services.flow_executor_service import NodeExecutor, WorkflowContext

        client = _FakeClient(list(expiries))
        executor = NodeExecutor(client, WorkflowContext(), [])
        # The lot size is the master contract's business and is covered
        # elsewhere; fixing it keeps this about the leg fields.
        executor._resolve_lot_size = lambda underlying, exchange: 75

        result = executor.execute_options_multi_order(
            {
                "strategy": "custom",
                "underlying": "NIFTY",
                "quantity": 1,
                "expiryType": "current_week",
                "priceType": "MARKET",
                "product": "NRML",
                "action": "SELL",
                "legs": legs,
            }
        )
        return result, client.sent

    def test_a_calendar_spread_is_placed_with_two_different_expiries(self):
        result, sent = self._place(
            [
                {
                    "strikeMode": "STRIKE",
                    "strike": 24500,
                    "expiry": "28OCT25",
                    "optionType": "CE",
                    "action": "SELL",
                    "quantity": 1,
                },
                {
                    "strikeMode": "STRIKE",
                    "strike": 24500,
                    "expiry": "25NOV25",
                    "optionType": "CE",
                    "action": "BUY",
                    "quantity": 2,
                },
            ]
        )

        assert result["status"] == "success"
        assert [leg["expiry_date"] for leg in sent["legs"]] == ["28OCT25", "25NOV25"]
        assert [leg["strike"] for leg in sent["legs"]] == [24500.0, 24500.0]
        assert [leg["action"] for leg in sent["legs"]] == ["SELL", "BUY"]

    def test_a_relative_leg_expiry_is_resolved_to_a_date(self):
        _, sent = self._place(
            [{"offset": "OTM2", "expiryType": "next_month", "optionType": "PE", "action": "BUY", "quantity": 1}]
        )

        assert sent["legs"][0]["expiry_date"] == "25SEP26"

    def test_a_leg_naming_no_expiry_carries_none_and_inherits_the_basket(self):
        """The service falls back to the common expiry when the key is absent,
        so sending an empty one would override the node with nothing."""
        _, sent = self._place(
            [{"offset": "ATM", "optionType": "PE", "action": "SELL", "quantity": 1}]
        )

        assert "expiry_date" not in sent["legs"][0]
        assert sent["expiry_date"] == "28AUG26"

    def test_exactly_one_strike_selector_is_sent_per_leg(self):
        """Sending both would leave the service resolving a precedence rule
        rather than doing what the leg says."""
        _, sent = self._place(
            [
                {"strikeMode": "STRIKE", "strike": 24500, "optionType": "CE", "action": "BUY", "quantity": 1},
                {"strikeMode": "OFFSET", "offset": "OTM2", "optionType": "PE", "action": "BUY", "quantity": 1},
            ]
        )

        assert "offset" not in sent["legs"][0]
        assert "strike" not in sent["legs"][1]

    def test_leg_quantity_is_in_lots_like_the_node(self):
        _, sent = self._place(
            [{"offset": "ATM", "optionType": "CE", "action": "BUY", "quantity": 3}]
        )

        assert sent["legs"][0]["quantity"] == 3 * 75

    def test_a_leg_with_an_unusable_expiry_stops_the_basket_before_anything_fills(self):
        """A multi-leg basket fills leg by leg, so a leg that cannot resolve has
        to stop the whole thing rather than leave half a position on."""
        result, sent = self._place(
            [
                {"offset": "ATM", "optionType": "CE", "action": "BUY", "quantity": 1},
                {"offset": "ATM", "expiry": "not-a-date", "optionType": "PE", "action": "BUY", "quantity": 1},
            ]
        )

        assert result["status"] == "error"
        assert sent == {}


class TestOneExpiryRuleForTheRunAndThePicker:
    """The panel tells the author which contract a relative expiry names, and
    the run has to use that same one. Two copies of the rule would drift, and
    the panel's promise would quietly go stale.
    """

    WEEKLY = ["28-AUG-26", "04-SEP-26", "11-SEP-26", "25-SEP-26", "30-OCT-26"]
    MONTHLY = ["28-AUG-26", "25-SEP-26", "29-OCT-26"]

    def _at(self, day="2026-08-24"):
        from datetime import datetime

        return datetime.strptime(day, "%Y-%m-%d")

    def test_current_week_is_the_nearest_listed_expiry(self):
        from services.flow_node_contracts import select_expiry

        assert select_expiry(self.WEEKLY, "current_week", now=self._at()) == "28AUG26"

    def test_next_week_is_the_second(self):
        from services.flow_node_contracts import select_expiry

        assert select_expiry(self.WEEKLY, "next_week", now=self._at()) == "04SEP26"

    def test_the_monthly_types_take_the_last_expiry_in_the_month(self):
        """On a weekly-listed underlying the monthly contract is the last one
        of the month, not the first."""
        from services.flow_node_contracts import select_expiry

        assert select_expiry(self.WEEKLY, "next_month", now=self._at()) == "25SEP26"

    def test_a_monthly_only_product_reads_current_week_as_nearest(self):
        """MCX lists no weeklies. The type still resolves rather than failing,
        which is why the editor hides the weekly choices there instead of
        letting them silently mean something else."""
        from services.flow_node_contracts import select_expiry

        assert select_expiry(self.MONTHLY, "current_week", now=self._at()) == "28AUG26"
        assert select_expiry(self.MONTHLY, "next_week", now=self._at()) == "25SEP26"

    def test_it_rolls_into_the_next_year_in_december(self):
        from services.flow_node_contracts import select_expiry

        expiries = ["31-DEC-26", "28-JAN-27"]
        assert select_expiry(expiries, "next_month", now=self._at("2026-12-10")) == "28JAN27"

    def test_an_unsatisfiable_type_resolves_to_nothing(self):
        from services.flow_node_contracts import select_expiry

        assert select_expiry(["28-AUG-26"], "next_week", now=self._at()) is None
        assert select_expiry(self.WEEKLY, "next_year", now=self._at()) is None
        assert select_expiry([], "current_week", now=self._at()) is None

    def test_unparseable_entries_are_ignored_not_fatal(self):
        from services.flow_node_contracts import select_expiry

        assert select_expiry(["junk", "28-AUG-26"], "current_week", now=self._at()) == "28AUG26"

    @pytest.mark.parametrize(
        "raw,expected",
        [("28-AUG-26", "28AUG26"), ("28AUG26", "28AUG26"), ("28-August-2026", "28AUGUST2026")],
    )
    def test_every_broker_format_normalizes_to_the_api_form(self, raw, expected):
        from services.flow_node_contracts import format_expiry_for_api

        assert format_expiry_for_api(raw) == expected

    def test_the_executor_uses_this_selector_rather_than_its_own_copy(self):
        import inspect

        import services.flow_executor_service as fes

        source = inspect.getsource(fes.NodeExecutor._resolve_expiry_date)
        assert "select_expiry(" in source
        # The inlined parse/sort/branch it replaced.
        assert "current_month" not in source
        assert "sorted_expiries" not in source


@pytest.fixture
def leg_contracts_client(monkeypatch):
    """The /flow/api/option-strikes endpoint with the broker calls stubbed.

    Auth and live market data are not what these check; the endpoint's job is
    picking the right expiry and shaping the listing the panel reads.
    """
    import utils.session as us

    monkeypatch.setattr(us, "check_session_validity", lambda f: f)
    for module in list(sys.modules):
        if module == "blueprints.flow":
            del sys.modules[module]

    from flask import Flask

    import blueprints.flow as flow_bp_module

    monkeypatch.setattr(flow_bp_module, "get_current_api_key", lambda: "key")

    calls = {}

    def fake_expiry_dates(symbol, exchange, instrumenttype, api_key):
        calls["expiry"] = {"symbol": symbol, "exchange": exchange}
        return True, {"status": "success", "data": ["28-AUG-26", "25-SEP-26", "29-OCT-26"]}, 200

    def fake_option_chain(**kwargs):
        calls["chain"] = kwargs
        return (
            True,
            {
                "status": "success",
                "expiry_date": kwargs["expiry_date"],
                "atm_strike": 163000.0,
                "underlying_ltp": 162945,
                "underlying_symbol": "GOLDM04SEP26FUT",
                "chain": [
                    {
                        "strike": 162500.0,
                        "ce": {"symbol": "GOLDM28AUG26162500CE", "label": "ITM1"},
                        "pe": {"symbol": "GOLDM28AUG26162500PE", "label": "OTM1"},
                    },
                    {
                        "strike": 163000.0,
                        "ce": {"symbol": "GOLDM28AUG26163000CE", "label": "ATM"},
                        "pe": {"symbol": "GOLDM28AUG26163000PE", "label": "ATM"},
                    },
                ],
            },
            200,
        )

    import services.expiry_service as expiry_service
    import services.option_chain_service as option_chain_service

    monkeypatch.setattr(expiry_service, "get_expiry_dates", fake_expiry_dates)
    monkeypatch.setattr(option_chain_service, "get_option_chain", fake_option_chain)

    app = Flask(__name__)
    app.secret_key = "t"
    app.register_blueprint(flow_bp_module.flow_bp)
    client = app.test_client()
    client.calls = calls
    return client


class TestTheLegBuilderOffersListedContracts:
    def _get(self, client, query):
        response = client.get(f"/flow/api/option-strikes?{query}")
        assert response.status_code == 200, response.get_json()
        return response.get_json()["data"]

    def test_a_strike_carries_the_contract_it_resolves_to(self, leg_contracts_client):
        """A typed number is not a contract. The panel shows the symbol the leg
        will place, which is what makes a hand-built basket checkable."""
        data = self._get(leg_contracts_client, "underlying=GOLDM&optionType=CE")

        assert data["strikes"][1]["symbol"] == "GOLDM28AUG26163000CE"
        assert data["strikes"][1]["label"] == "ATM"
        assert data["atm"] == 163000.0

    def test_the_moneyness_label_follows_the_side(self, leg_contracts_client):
        """The same strike is ITM for a call and OTM for a put."""
        calls = self._get(leg_contracts_client, "underlying=GOLDM&optionType=CE")
        puts = self._get(leg_contracts_client, "underlying=GOLDM&optionType=PE")

        assert calls["strikes"][0]["label"] == "ITM1"
        assert puts["strikes"][0]["label"] == "OTM1"
        assert puts["strikes"][0]["symbol"].endswith("PE")

    def test_every_relative_type_reports_the_date_it_currently_picks(self, leg_contracts_client):
        """So the panel can say "Same as node - 28AUG26" instead of leaving the
        author to discover it at run time."""
        data = self._get(leg_contracts_client, "underlying=GOLDM&optionType=CE")

        assert data["resolved"]["current_week"] == "28AUG26"
        assert data["resolved"]["next_month"] == "25SEP26"

    def test_an_explicit_expiry_wins_over_a_relative_type(self, leg_contracts_client):
        data = self._get(
            leg_contracts_client,
            "underlying=GOLDM&optionType=CE&expiry=29OCT26&expiryType=current_week",
        )

        assert data["expiry"] == "29OCT26"

    def test_a_relative_type_is_resolved_when_no_date_is_given(self, leg_contracts_client):
        data = self._get(
            leg_contracts_client, "underlying=GOLDM&optionType=CE&expiryType=next_month"
        )

        assert data["expiry"] == "25SEP26"

    def test_an_unlisted_expiry_falls_back_to_the_nearest(self, leg_contracts_client):
        """Answering with an empty strike list would look like a product with no
        contracts rather than a bad date."""
        data = self._get(leg_contracts_client, "underlying=GOLDM&optionType=CE&expiry=01JAN99")

        assert data["expiry"] == "28AUG26"
        assert data["strikes"]

    def test_the_underlying_decides_the_exchange(self, leg_contracts_client):
        """A commodity resolves to MCX without the panel having to say so."""
        data = self._get(leg_contracts_client, "underlying=GOLDM&optionType=CE")
        assert data["exchange"] == "MCX"

        data = self._get(leg_contracts_client, "underlying=NIFTY&optionType=CE")
        assert data["exchange"] == "NFO"

    def test_the_chain_is_fetched_without_per_strike_quotes(self, leg_contracts_client):
        """A quoted chain costs a broker multiquote every time a dropdown opens,
        and the builder needs the contract, not its price."""
        self._get(leg_contracts_client, "underlying=GOLDM&optionType=CE")

        assert leg_contracts_client.calls["chain"]["with_quotes"] is False

    def test_an_unknown_side_is_refused(self, leg_contracts_client):
        response = leg_contracts_client.get(
            "/flow/api/option-strikes?underlying=GOLDM&optionType=XX"
        )
        assert response.status_code == 400

    def test_the_underlying_is_required(self, leg_contracts_client):
        assert leg_contracts_client.get("/flow/api/option-strikes").status_code == 400
