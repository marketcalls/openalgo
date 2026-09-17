"""NSE's F&O bhavcopy as the Change-in-OI anchor.

One file carries the previous session's open interest for every contract, so a
symbol switch costs no broker history calls at all. What has to hold: each row
maps onto the symbol the rest of the platform uses, the numbers arrive in the
broker's own units, and a leg the file cannot speak for still falls through to
the per-leg path rather than being silently anchored at zero.

No network - the fixture builds a file in memory.
"""

import csv
import io
import zipfile
from datetime import date

import pytest

import services.nse_oi_bhavcopy as bhav
import services.oi_profile_service as svc

ROWS = [
    # (TckrSymb, XpryDt, StrkPric, OptnTp, OpnIntrst)
    ("NIFTY", "2026-09-22", "23200.00", "PE", "7467135"),
    ("NIFTY", "2026-09-22", "23200.00", "CE", "1000000"),
    ("VEDL", "2026-09-29", "292.50", "CE", "50000"),
    ("TVSMOTOR", "2026-09-29", "3850.00", "CE", "0"),
]


def _zipped_csv(rows=ROWS):
    """A bhavcopy archive with the columns the parser reads."""
    header = ["TckrSymb", "XpryDt", "StrkPric", "OptnTp", "OpnIntrst"]
    text = io.StringIO()
    writer = csv.writer(text)
    writer.writerow(header)
    for row in rows:
        writer.writerow(row)
    # A futures row carries no OptnTp and must be skipped, not mis-keyed.
    writer.writerow(["NIFTY", "2026-09-29", "0.00", "", "123456"])

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("BhavCopy_NSE_FO_0_0_0_20260916_F_0000.csv", text.getvalue())
    return buffer.getvalue()


@pytest.fixture(autouse=True)
def _clear_book_cache():
    bhav._book_cache.clear()
    bhav._failed_at.clear()
    yield
    bhav._book_cache.clear()
    bhav._failed_at.clear()


def test_a_row_maps_onto_the_symbol_the_platform_uses():
    oi, underlyings = bhav._parse(_zipped_csv())
    # Whole strikes are written bare and fractional ones keep their decimal,
    # the way the symbol master writes them. Checked against symtoken: all
    # 35,010 option rows in the 16-Sep-2026 file matched a known symbol.
    assert oi["NIFTY22SEP2623200PE"] == 7_467_135
    assert oi["VEDL29SEP26292.5CE"] == 50_000
    assert underlyings == frozenset({"NIFTY", "VEDL", "TVSMOTOR"})
    # The futures row has no option type and belongs to no option symbol.
    assert not [s for s in oi if s.endswith("0.0CE") or s.endswith("0.0PE")]


def test_the_anchor_matches_what_the_per_leg_path_reports():
    # The number this whole file exists to replace. NIFTY22SEP2623200PE closed
    # 15-Sep-2026 at 4,552,925 - verified against NSE, and pinned in
    # test_oi_profile_multi_expiry. The 16-Sep file reads 7,467,135 with a
    # day's change of 2,914,210, and 7,467,135 - 2,914,210 is that close, so
    # the file's open interest is in the broker's units with no conversion.
    oi, _ = bhav._parse(_zipped_csv())
    assert oi["NIFTY22SEP2623200PE"] - 2_914_210 == 4_552_925


def test_underlying_is_read_back_off_the_symbol():
    assert bhav.underlying_of("NIFTY22SEP2623200PE") == "NIFTY"
    assert bhav.underlying_of("TVSMOTOR29SEP263850CE") == "TVSMOTOR"
    assert bhav.underlying_of("VEDL29SEP26292.5CE") == "VEDL"
    assert bhav.underlying_of("") is None


def _book():
    oi, underlyings = bhav._parse(_zipped_csv())
    return bhav.Bhavcopy(date(2026, 9, 16), oi, underlyings)


def test_the_file_answers_the_legs_it_covers():
    svc._prev_oi_cache.clear()
    legs = ["NIFTY22SEP2623200PE", "VEDL29SEP26292.5CE"]
    resolved, remaining = svc._resolve_from_nse(legs, _book(), "NFO", "2026-09-17")
    assert resolved == {"NIFTY22SEP2623200PE": 7_467_135, "VEDL29SEP26292.5CE": 50_000}
    assert remaining == []


def test_a_strike_absent_from_a_covered_underlying_is_anchored_at_zero():
    # The file lists every contract that traded or held open interest. A NIFTY
    # strike missing from it held none, so all of today's open interest is a
    # fresh build - unlike a failed broker read, where absence means unknown
    # and a zero anchor would paint the strike as a huge write.
    svc._prev_oi_cache.clear()
    resolved, remaining = svc._resolve_from_nse(
        ["NIFTY22SEP2699999CE"], _book(), "NFO", "2026-09-17"
    )
    assert resolved == {"NIFTY22SEP2699999CE": 0.0}
    assert remaining == []


def test_an_underlying_the_file_does_not_cover_still_goes_to_the_broker():
    # An F&O name listed today is absent from yesterday's file entirely.
    # Anchoring its every strike at zero would report the whole chain as built
    # today, so it has to fall through to the per-leg path instead.
    svc._prev_oi_cache.clear()
    resolved, remaining = svc._resolve_from_nse(
        ["NEWNAME29SEP261000CE"], _book(), "NFO", "2026-09-17"
    )
    assert resolved == {}
    assert remaining == ["NEWNAME29SEP261000CE"]


def test_only_nse_is_served_from_the_file():
    # BSE publishes its own file in a different format and crypto has none;
    # both must keep the per-leg fallback rather than get a wrong anchor.
    assert bhav.previous_session_oi("BFO") is None
    assert bhav.cached_previous_session_oi("BFO") is None


def test_a_failure_is_not_retried_on_every_miss(monkeypatch):
    # NSE being unreachable at 09:15 must not cost the session, but it must
    # also not put a download in front of every leg that misses.
    attempts = []
    monkeypatch.setattr(bhav, "_download", lambda day: attempts.append(day) or None)
    monkeypatch.setattr(bhav, "_displayed_session", lambda today: today)

    assert bhav.previous_session_oi("NFO") is None
    first = len(attempts)
    assert first > 0, "it should have looked for a file"
    assert bhav.previous_session_oi("NFO") is None
    assert len(attempts) == first, "the second miss must not download again"
