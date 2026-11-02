"""INDmoney history requests are split into date chunks, and the last day counts.

The split looped while the chunk start was before the end date, so a one-day
request (start == end, e.g. today's 1minute candles) produced no chunk and
returned 0 candles, and a range one day past a whole chunk lost its last day.
"""

from broker.indmoney.api.data import BrokerData


def split(start, end, max_days):
    # _split_date_range uses no instance state.
    return BrokerData._split_date_range(None, start, end, max_days)


def test_a_single_day_is_one_chunk():
    assert split("2026-11-02", "2026-11-02", 7) == [("2026-11-02", "2026-11-02")]


def test_a_range_one_day_past_a_chunk_keeps_its_last_day():
    assert split("2026-10-27", "2026-11-03", 7) == [
        ("2026-10-27", "2026-11-02"),
        ("2026-11-03", "2026-11-03"),
    ]


def test_a_range_of_whole_chunks_is_unchanged():
    assert split("2026-10-20", "2026-11-02", 7) == [
        ("2026-10-20", "2026-10-26"),
        ("2026-10-27", "2026-11-02"),
    ]
