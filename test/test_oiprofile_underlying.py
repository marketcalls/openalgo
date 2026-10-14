"""The OI Profile endpoint must accept every underlying OpenAlgo actually names.

Letters and digits alone refused M&M and BAJAJ-AUTO with "Invalid input format",
so the /trading overlay and the /oiprofile page could not profile them at all.
Found live on 14-Oct-2026, after the overlay itself was fixed to send the name
intact: its tests stubbed this endpoint, so they passed while the server
refused every request.
"""

import pytest

from blueprints.oiprofile import UNDERLYING_RE


@pytest.mark.parametrize("name", ["NIFTY", "BANKNIFTY", "M&M", "M&MFIN", "BAJAJ-AUTO", "NIFTYNXT50", "CRUDEOIL"])
def test_real_underlyings_are_accepted(name):
    assert UNDERLYING_RE.match(name), name


@pytest.mark.parametrize("name", ["", "&M", "-NIFTY", "nifty", "NIFTY 50", "NIFTY;", "NIFTY'", "M&M<script>"])
def test_anything_else_is_still_refused(name):
    assert not UNDERLYING_RE.match(name), name
