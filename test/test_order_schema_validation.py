import pytest
from marshmallow import ValidationError

from restx_api.schemas import OptionsMultiOrderLegSchema, OptionsOrderSchema

OPTION_OFFSET_ERROR = "Offset must be ATM, ITM1-ITM50, or OTM1-OTM50"


def _options_order_payload(offset: str) -> dict:
    return {
        "apikey": "test-api-key",
        "strategy": "test-strategy",
        "underlying": "NIFTY",
        "exchange": "NFO",
        "offset": offset,
        "option_type": "CE",
        "action": "BUY",
        "quantity": 1,
    }


def _options_multi_order_leg_payload(offset: str) -> dict:
    return {
        "offset": offset,
        "option_type": "PE",
        "action": "SELL",
        "quantity": 1,
    }


@pytest.mark.parametrize(
    ("schema", "payload_factory"),
    [
        (OptionsOrderSchema(), _options_order_payload),
        (OptionsMultiOrderLegSchema(), _options_multi_order_leg_payload),
    ],
    ids=["options-order", "options-multi-order-leg"],
)
@pytest.mark.parametrize("offset", ["ATM", "ITM1", "ITM50", "OTM1", "OTM50"])
def test_order_schemas_accept_valid_option_offset_boundaries(schema, payload_factory, offset):
    result = schema.load(payload_factory(offset))

    assert result["offset"] == offset


@pytest.mark.parametrize(
    ("schema", "payload_factory"),
    [
        (OptionsOrderSchema(), _options_order_payload),
        (OptionsMultiOrderLegSchema(), _options_multi_order_leg_payload),
    ],
    ids=["options-order", "options-multi-order-leg"],
)
@pytest.mark.parametrize("offset", ["ITM0", "ITM51", "OTM0", "OTM51", "INVALID"])
def test_order_schemas_reject_invalid_option_offsets(schema, payload_factory, offset):
    with pytest.raises(ValidationError) as exc_info:
        schema.load(payload_factory(offset))

    assert exc_info.value.messages == {"offset": [OPTION_OFFSET_ERROR]}
