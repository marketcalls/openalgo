"""Kotak HSM market-data decoding.

The HSM feed marks a field it has no value for this tick with 0x80000000.
HSWebSocketLib is meant to drop those, but its reader is unsigned while the
sentinel constant was signed, so the guard never fired and an absent price
decoded to 21474836.48 - a plausible-looking number that reached the quote
path unfiltered. These pin the guard and the price scaling around it.
"""

import importlib.util
from pathlib import Path

import pytest

# Loaded by path, not as broker.kotak.streaming.HSWebSocketLib: that package's
# __init__ pulls in the adapter, which imports websocket_proxy, which imports
# the adapter back. The decoder itself has no such dependency, and a protocol
# unit test has no business dragging the proxy in to get at it.
_spec = importlib.util.spec_from_file_location(
    "kotak_hswebsocketlib",
    Path(__file__).resolve().parents[1] / "broker" / "kotak" / "streaming" / "HSWebSocketLib.py",
)
hs = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(hs)

SCRIP_INDEX = hs.SCRIP_INDEX
TRASH_VAL = hs.TRASH_VAL
TRASH_VAL_UNSIGNED = hs.TRASH_VAL_UNSIGNED
ScripTopicData = hs.ScripTopicData
buf2long = hs.buf2long

# What the wire actually carries for "this field has no value right now".
SENTINEL_BYTES = bytes([0x80, 0x00, 0x00, 0x00])


def scrip(precision=2, multiplier=1):
    """A scrip topic with the broker's scaling terms already applied."""
    data = ScripTopicData()
    data.setLongValues(SCRIP_INDEX["PRECISION"], precision)
    data.setLongValues(SCRIP_INDEX["MULTIPLIER"], multiplier)
    data.setMultiplierAndPrec()
    return data


# --- the sentinel itself ------------------------------------------------------


def test_the_reader_is_unsigned_so_the_sentinel_arrives_positive():
    """The reason the signed constant alone could never match."""
    assert buf2long(SENTINEL_BYTES) == TRASH_VAL_UNSIGNED == 2147483648
    assert buf2long(SENTINEL_BYTES) != TRASH_VAL


@pytest.mark.parametrize("sentinel", [TRASH_VAL, TRASH_VAL_UNSIGNED])
def test_an_unavailable_field_is_not_recorded(sentinel):
    data = scrip()

    data.setLongValues(SCRIP_INDEX["LTP"], sentinel)

    assert data.fieldDataArray[SCRIP_INDEX["LTP"]] is None
    assert not data.updatedFieldsArray[SCRIP_INDEX["LTP"]]


def test_an_unavailable_tick_leaves_the_last_good_price_alone():
    """A "no value this tick" packet must not overwrite a real price."""
    data = scrip()
    data.setLongValues(SCRIP_INDEX["LTP"], 213500)  # 21.35

    data.setLongValues(SCRIP_INDEX["LTP"], buf2long(SENTINEL_BYTES))

    assert data.fieldDataArray[SCRIP_INDEX["LTP"]] == 213500


def test_the_sentinel_never_reaches_the_quote_as_a_price():
    """21474836.48 is what the quote path used to publish for an absent field.

    kotak_websocket.py reads bp/sp/op/h/lo/ltp/c with a bare float(), with no
    filter of its own, so anything emitted here is what a consumer sees.
    """
    data = scrip()
    data.setLongValues(SCRIP_INDEX["CLOSE"], buf2long(SENTINEL_BYTES))

    emitted = data.prepareData()

    assert "21474836.48" not in str(emitted.values())


# --- scaling ------------------------------------------------------------------


def test_a_price_is_scaled_by_the_declared_precision():
    data = scrip(precision=2)
    data.setLongValues(SCRIP_INDEX["LTP"], 2135)

    assert data.prepareData()["ltp"] == "21.35"


def test_four_decimal_instruments_keep_their_four_decimals():
    """USDINR ticks at 0.0025, so 2dp is a real loss on a currency contract.

    The depth and index decoders in this same file already round to the
    broker-declared precision; the scrip decoder used to hardcode 2.
    """
    data = scrip(precision=4)
    data.setLongValues(SCRIP_INDEX["LTP"], 872350)  # 87.2350

    assert data.prepareData()["ltp"] == "87.2350"


def test_a_multiplier_scales_on_top_of_precision():
    data = scrip(precision=2, multiplier=2)
    data.setLongValues(SCRIP_INDEX["LTP"], 4270)

    assert data.prepareData()["ltp"] == "21.35"


def test_a_quantity_is_never_divided():
    """Volume is a LONG. Dividing it would be the mirror-image defect."""
    data = scrip()
    data.setLongValues(SCRIP_INDEX["VOLUME"], 1500000)

    assert data.prepareData()["v"] == "1500000"
