import pytest
from marshmallow import ValidationError

from restx_api.data_schemas import OptionSymbolSchema, validate_option_expiry
from restx_api.schemas import (
    OptionsMultiOrderLegSchema,
    OptionsMultiOrderSchema,
    OptionsOrderSchema,
)

SCHEMA_PAYLOADS = [
    (
        OptionSymbolSchema,
        {
            "apikey": "test-key",
            "underlying": "NIFTY",
            "exchange": "NSE_INDEX",
            "offset": "ATM",
            "option_type": "CE",
        },
    ),
    (
        OptionsOrderSchema,
        {
            "apikey": "test-key",
            "strategy": "test-strategy",
            "underlying": "NIFTY",
            "exchange": "NSE_INDEX",
            "offset": "ATM",
            "option_type": "CE",
            "action": "BUY",
            "quantity": 1,
        },
    ),
    (
        OptionsMultiOrderLegSchema,
        {
            "offset": "ATM",
            "option_type": "CE",
            "action": "BUY",
            "quantity": 1,
        },
    ),
    (
        OptionsMultiOrderSchema,
        {
            "apikey": "test-key",
            "strategy": "test-strategy",
            "underlying": "NIFTY",
            "exchange": "NSE_INDEX",
            "legs": [
                {
                    "offset": "ATM",
                    "option_type": "CE",
                    "action": "BUY",
                    "quantity": 1,
                }
            ],
        },
    ),
]


@pytest.mark.parametrize("expiry_date", ["28AUG26", "29FEB24"])
def test_option_expiry_validator_accepts_valid_dates(expiry_date):
    assert validate_option_expiry(expiry_date) is None


def test_option_expiry_validator_allows_empty_value():
    assert validate_option_expiry("") is None


@pytest.mark.parametrize(
    "expiry_date",
    ["29FEB25", "31APR26", "28aug26", "28AUG2026", "28-AUG-26", "1AUG26"],
)
def test_option_expiry_validator_rejects_invalid_dates(expiry_date):
    with pytest.raises(ValidationError):
        validate_option_expiry(expiry_date)


@pytest.mark.parametrize("schema_class,payload", SCHEMA_PAYLOADS)
def test_matching_schemas_reuse_option_expiry_validator(schema_class, payload):
    assert schema_class().load({**payload, "expiry_date": "28AUG26"})["expiry_date"] == "28AUG26"


@pytest.mark.parametrize("schema_class,payload", SCHEMA_PAYLOADS)
@pytest.mark.parametrize("expiry_date", ["29FEB25", "28aug26", "28-AUG-26"])
def test_matching_schemas_reject_invalid_expiry_dates(schema_class, payload, expiry_date):
    with pytest.raises(ValidationError, match="expiry_date"):
        schema_class().load({**payload, "expiry_date": expiry_date})


def test_options_order_allows_omitted_expiry_with_embedded_underlying():
    order_data = OptionsOrderSchema().load(
        {
            "apikey": "test-key",
            "strategy": "test-strategy",
            "underlying": "NIFTY28OCT25FUT",
            "exchange": "NSE_INDEX",
            "offset": "ATM",
            "option_type": "CE",
            "action": "BUY",
            "quantity": 1,
        }
    )

    assert "expiry_date" not in order_data


def test_options_order_allows_empty_expiry_with_embedded_underlying():
    order_data = OptionsOrderSchema().load(
        {
            "apikey": "test-key",
            "strategy": "test-strategy",
            "underlying": "NIFTY28OCT25FUT",
            "exchange": "NSE_INDEX",
            "offset": "ATM",
            "option_type": "CE",
            "action": "BUY",
            "quantity": 1,
            "expiry_date": "",
        }
    )

    assert order_data["expiry_date"] == ""
