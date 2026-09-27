"""Which product a Flow node sends when its author never picked one.

MIS squares a position off at the end of the session; NRML carries it. For a
cash segment MIS is the sane default -- a Flow order on NSE is almost always
intraday. For a derivative it is not: an NFO or MCX position taken NRML is the
ordinary case, and MIS on the same contract is an auto-square-off the author
never asked for. Every order node shipped MIS regardless of segment, so a
workflow built on NFO had to be corrected by hand node by node, and any node
missed silently traded intraday.

The fix is a *default*, not an override. A product the author actually chose is
stored on the node and always wins, which is what keeps a deliberately intraday
NFO order intraday and, more importantly, keeps every already-saved workflow
sending exactly what it sent before -- those nodes all carry an explicit
product from the editor that wrote them.

Two rules, one copy of each:

* the exchange decides, for anything that names a symbol; and
* an option is a derivative whatever its underlying's exchange field reads,
  because that field names where the *underlying* is quoted (NSE_INDEX), not
  where the option trades.
"""

import os
import re
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import services.flow_executor_service as fes  # noqa: E402
from services.flow_node_contracts import (  # noqa: E402
    DERIVATIVE_EXCHANGES,
    default_product_for_exchange,
)

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

CASH_AND_INDEX = ("NSE", "BSE", "NSE_INDEX", "BSE_INDEX", "MCX_INDEX", "GLOBAL_INDEX", "CRYPTO")


def read(*parts):
    with open(os.path.join(REPO_ROOT, *parts), encoding="utf-8") as handle:
        return handle.read()


class _RecordingClient:
    """Captures what would have reached the broker."""

    def __init__(self):
        self.orders = []
        self.smart_orders = []
        self.split_orders = []
        self.baskets = []
        self.closed = []
        self.positions = []
        self.margins = []

    def place_order(self, **kwargs):
        self.orders.append(kwargs)
        return {"status": "success", "orderid": "X1"}

    def place_smart_order(self, **kwargs):
        self.smart_orders.append(kwargs)
        return {"status": "success", "orderid": "S1"}

    def split_order(self, **kwargs):
        self.split_orders.append(kwargs)
        return {"status": "success", "orderid": "SP1"}

    def basket_order(self, **kwargs):
        self.baskets.append(kwargs)
        return {"status": "success", "orderids": ["B1"]}

    def close_position(self, **kwargs):
        self.closed.append(kwargs)
        return {"status": "success"}

    def get_open_position(self, **kwargs):
        self.positions.append(kwargs)
        return {"status": "success", "quantity": 0}

    def margin(self, **kwargs):
        self.margins.append(kwargs)
        return {"status": "success", "data": {}}


@pytest.fixture
def executor():
    client = _RecordingClient()
    return fes.NodeExecutor(client, fes.WorkflowContext(), [])


class TestTheRuleItself:
    @pytest.mark.parametrize("exchange", sorted(DERIVATIVE_EXCHANGES))
    def test_a_derivative_segment_carries(self, exchange):
        assert default_product_for_exchange(exchange) == "NRML"

    @pytest.mark.parametrize("exchange", CASH_AND_INDEX)
    def test_cash_and_index_stay_intraday(self, exchange):
        assert default_product_for_exchange(exchange) == "MIS"

    def test_every_segment_that_trades_options_is_covered(self):
        """The MCX/CDS underlyings the options nodes accept trade on segments
        that must be in the set, or an options basket routed there would default
        to intraday."""
        for _underlying, (_quote, option_exchange) in fes.OPTION_UNDERLYING_EXCHANGES.items():
            assert option_exchange in DERIVATIVE_EXCHANGES

    @pytest.mark.parametrize("value", ["nfo", " NFO ", "NfO"])
    def test_the_exchange_is_read_case_and_space_insensitively(self, value):
        assert default_product_for_exchange(value) == "NRML"

    @pytest.mark.parametrize("value", ["", None, "   ", "NOTANEXCHANGE"])
    def test_an_unusable_exchange_falls_back_to_intraday(self, value):
        """Never guess NRML from a value that names no segment: carrying a
        position the author expected squared off is the costlier mistake."""
        assert default_product_for_exchange(value) == "MIS"

    def test_index_pseudo_exchanges_are_absent(self):
        """No order is ever placed on one, so listing them would only make the
        options nodes look as if they followed their `exchange` field."""
        assert not DERIVATIVE_EXCHANGES & {
            "NSE_INDEX",
            "BSE_INDEX",
            "MCX_INDEX",
            "GLOBAL_INDEX",
        }


class TestOneCopyOfTheRule:
    """A second copy would drift, and the editor's Product box would then
    promise a product the run does not send."""

    def test_the_editor_imports_the_rule_rather_than_restating_it(self):
        panel = read("frontend", "src", "components", "flow", "panels", "ConfigPanel.tsx")
        assert "defaultProductForExchange" in panel
        assert not re.search(r"nodeData\.product as string\) \|\| 'MIS'", panel)

    def test_the_editor_and_the_executor_agree_on_the_segment_list(self):
        """The two homes of the set are in different languages, which is exactly
        where a drift would hide: the panel would show NRML on a segment the run
        sends MIS for, or the reverse."""
        constants = read("frontend", "src", "lib", "flow", "constants.ts")
        block = constants.split("export const DERIVATIVE_EXCHANGES = new Set<string>([", 1)[1]
        block = block.split("])", 1)[0]
        listed = set(re.findall(r"'([A-Z_]+)'", block))

        assert listed == set(DERIVATIVE_EXCHANGES)

    def test_the_editor_derives_the_product_rather_than_hardcoding_one(self):
        """Every Product control read `nodeData.product || 'MIS'`, which is the
        shape that made the segment invisible in the first place."""
        for parts in (
            ("frontend", "src", "components", "flow", "panels", "ConfigPanel.tsx"),
            ("frontend", "src", "components", "flow", "nodes", "PlaceOrderNode.tsx"),
            ("frontend", "src", "components", "flow", "nodes", "SmartOrderNode.tsx"),
            ("frontend", "src", "components", "flow", "nodes", "OpenPositionNode.tsx"),
        ):
            body = read(*parts)
            assert "product || 'MIS'" not in body, parts[-1]
            assert "defaultProductForExchange" in body, parts[-1]


class TestAnOrderNodeFollowsItsExchange:
    @pytest.mark.parametrize(
        ("exchange", "expected"),
        [("NSE", "MIS"), ("BSE", "MIS"), ("NFO", "NRML"), ("MCX", "NRML"), ("CDS", "NRML")],
    )
    def test_place_order(self, executor, exchange, expected):
        executor.execute_place_order({"symbol": "X", "exchange": exchange, "quantity": 1})

        assert executor.client.orders[0]["product_type"] == expected

    def test_smart_order(self, executor):
        executor.execute_smart_order(
            {"symbol": "NIFTY28AUG2624000CE", "exchange": "NFO", "quantity": 1, "positionSize": 1}
        )

        assert executor.client.smart_orders[0]["product_type"] == "NRML"

    def test_split_order(self, executor):
        executor.execute_split_order(
            {"symbol": "CRUDEOIL", "exchange": "MCX", "quantity": 2, "splitSize": 1}
        )

        assert executor.client.split_orders[0]["product_type"] == "NRML"

    @pytest.mark.parametrize("method", ["execute_place_order", "execute_smart_order"])
    def test_a_chosen_product_is_never_overridden(self, executor, method):
        """Intraday on a derivative is a legitimate thing to ask for, and the
        editor stores it the moment it is picked."""
        getattr(executor, method)(
            {"symbol": "X", "exchange": "NFO", "quantity": 1, "positionSize": 1, "product": "MIS"}
        )

        sent = executor.client.orders or executor.client.smart_orders
        assert sent[0]["product_type"] == "MIS"

    def test_an_already_saved_workflow_sends_what_it_always_sent(self, executor):
        """Every node the old editor wrote carries an explicit product, so this
        change cannot move a live workflow onto a different one."""
        executor.execute_place_order(
            {"symbol": "NIFTY28AUG2624000CE", "exchange": "NFO", "quantity": 1, "product": "MIS"}
        )

        assert executor.client.orders[0]["product_type"] == "MIS"

    def test_a_templated_exchange_is_resolved_before_the_product_is_decided(self, executor):
        """The default is read off the exchange the run actually uses, not off
        the `{{...}}` text sitting in the node."""
        executor.context.set_variable("webhook", {"exchange": "NFO"})

        executor.execute_place_order(
            {"symbol": "X", "exchange": "{{webhook.exchange}}", "quantity": 1}
        )

        assert executor.client.orders[0]["product_type"] == "NRML"


class TestPositionNodesFollowTheirExchange:
    def test_close_positions(self, executor):
        executor.execute_close_positions({"symbol": "GOLDM", "exchange": "MCX"})

        assert executor.client.closed[0]["product_type"] == "NRML"

    def test_close_positions_on_cash(self, executor):
        executor.execute_close_positions({"symbol": "SBIN", "exchange": "NSE"})

        assert executor.client.closed[0]["product_type"] == "MIS"

    def test_open_position(self, executor):
        executor.execute_open_position({"symbol": "GOLDM", "exchange": "MCX"})

        assert executor.client.positions[0]["product_type"] == "NRML"

    def test_position_check_reads_the_position_it_is_guarding(self, executor):
        """A guard that looked up MIS while the order below it took NRML would
        never see the position it was meant to gate on."""
        executor.execute_position_check(
            {"symbol": "NIFTY28AUG2624000CE", "exchange": "NFO", "condition": "exists"}
        )

        assert executor.client.positions[0]["product_type"] == "NRML"

    def test_margin(self, executor):
        executor.execute_margin({"symbol": "NIFTY28AUG26FUT", "exchange": "NFO", "quantity": 1})

        assert executor.client.margins[0]["product_type"] == "NRML"


class TestABasketDecidesPerRow:
    """One basket can hold rows from several segments, so a single blanket
    product would be wrong for at least one of them."""

    def test_each_row_follows_its_own_exchange(self, executor):
        executor.execute_basket_order({"orders": "SBIN,NSE,BUY,1\nGOLDM,MCX,BUY,1"})

        sent = executor.client.baskets[0]["orders"]
        assert [row["product"] for row in sent] == ["MIS", "NRML"]

    def test_a_product_on_the_node_still_covers_every_row(self, executor):
        executor.execute_basket_order(
            {"orders": "SBIN,NSE,BUY,1\nGOLDM,MCX,BUY,1", "product": "NRML"}
        )

        sent = executor.client.baskets[0]["orders"]
        assert [row["product"] for row in sent] == ["NRML", "NRML"]

    def test_a_row_that_names_its_own_product_wins(self, executor):
        executor.execute_basket_order(
            {
                "orders": [
                    {"symbol": "X", "exchange": "NFO", "action": "BUY", "quantity": 1},
                    {
                        "symbol": "Y",
                        "exchange": "NFO",
                        "action": "BUY",
                        "quantity": 1,
                        "product": "MIS",
                    },
                ]
            }
        )

        sent = executor.client.baskets[0]["orders"]
        assert [row["product"] for row in sent] == ["NRML", "MIS"]

    def test_a_blank_product_on_the_node_is_still_refused(self, executor):
        """Absent means "let each row decide"; present-but-empty is a template
        that resolved to nothing, and guessing there would place the order the
        author's data failed to describe."""
        result = executor.execute_basket_order({"orders": "SBIN,NSE,BUY,1", "product": ""})

        assert result["status"] == "error"
        assert executor.client.baskets == []


class TestOptionsAreAlwaysADerivative:
    def test_the_editor_defaults_both_options_nodes_to_nrml(self):
        constants = read("frontend", "src", "lib", "flow", "constants.ts")
        for node in ("optionsOrder", "optionsMultiOrder"):
            block = constants.split(f"\n  {node}: {{\n", 1)[1].split("\n  },\n", 1)[0]
            assert "product: 'NRML'" in block, node

    def test_the_underlying_exchange_field_does_not_decide_the_product(self):
        """`exchange` on an options node names where the *underlying* is quoted
        -- NSE_INDEX -- so following it would default every index option to
        intraday."""
        assert default_product_for_exchange("NSE_INDEX") == "MIS"
        source = read("services", "flow_executor_service.py")
        options_order = source.split("def execute_options_order", 1)[1].split("\n    def ", 1)[0]
        assert 'default="NRML"' in options_order

    def test_a_multi_leg_basket_carries(self):
        source = read("services", "flow_executor_service.py")
        multi = source.split("def execute_options_multi_order", 1)[1].split("\n    def ", 1)[0]
        assert 'values.enum("product", VALID_PRODUCT_TYPES, default="NRML")' in multi

    def test_a_leg_the_service_receives_without_a_product_carries(self):
        """The legs reaching options_multiorder_service are option contracts on
        NFO/BFO/MCX; nothing cash-settled ever arrives there."""
        source = read("services", "options_multiorder_service.py")
        assert 'leg_data.get("product", "MIS")' not in source
        assert source.count('leg_data.get("product", "NRML")') == 3
