# api/funds.py

"""Account funds for Motilal Oswal (MOFSL).

Motilal publishes no dedicated Fund API (FAQ Q41), so funds are derived from
the Margin Detail report (``/rest/report/v3/getreportmargindetail``,
doc 25-margin-detail.md). The response is a flat list of
``{srno, particulars, amount}`` rows; ``srno`` selects the rows we need.

``srno`` is NOT unique in the documented response (507 appears twice, and
"Add: Unrealised (Net)" appears once per segment at 402/422/442/462/482), so
rows that repeat are summed rather than matched once.
"""

from broker.motilal.api.baseurl import get_common_headers, get_url
from utils.httpx_client import get_httpx_client
from utils.logging import get_logger

logger = get_logger(__name__)

# --- Row numbers from doc 25-margin-detail.md -------------------------------
# Comments quote the documented ``particulars`` strings verbatim.
SRNO_NET_AVAILABLE_CASH_SEG = 102  # "Available for Cash / SLBM Segment" (NET, see below)
SRNO_CASH_BALANCE = 201  # "Cash Balance(Cash Margin)"  <- true free cash
SRNO_NON_CASH_BALANCE = 220  # "Non-Cash Balance(Non-Cash Margin)"  <- collateral
SRNO_MARGIN_USAGE_TOTAL = 300  # "Margin Usage Details (B)"
SRNO_MTM_TOTAL = 400  # "Profit / Loss (MTM) Details C"
SRNO_TOTAL_PL_MTM = 600  # "Total Profit and Loss(MTM)"  (== srno 400)
SRNO_TOTAL_PL_BPL = 700  # "Total Profit and Loss(BPL)"  (booked P&L, unused)

# Per-segment margin usage headers, used only to reconstruct srno 300 when the
# response omits it (the Margin SUMMARY report, doc 24, has no srno 300 and its
# srno 301 is the cash segment only). Sub-rows (302-304, 322-325, ...) roll up
# into these, so summing just these does not double count.
#   detail (doc 25): 301 "Equities", 321 "FO", 340 "Currency", 360 "Commodity",
#                    380 "SLBM", 381 "Brokerage"  ->  622432.38 ~= srno 300
#   summary (doc 24): 301/321/340/360/381 "Margin Usage(B) <segment>"
SRNO_MARGIN_USAGE_SEGMENTS = (301, 321, 340, 360, 380, 381)

# "Add: Unrealised (Net)" / "Add: Realised P/L (Net)", one pair per segment.
SRNO_UNREALISED = (402, 422, 442, 462, 482)
SRNO_REALISED = (403, 423, 443, 463, 483)

OUTPUT_KEYS = (
    "availablecash",
    "collateral",
    "m2mrealized",
    "m2munrealized",
    "utiliseddebits",
)


def _to_float(value):
    """Doc samples emit bare JSON numbers; be tolerant of anything else."""
    try:
        return float(value)
    except (ValueError, TypeError):
        return 0.0


def _sum_rows(rows, srnos):
    """Sum every row whose srno is in ``srnos``. Returns (total, matched)."""
    total = 0.0
    matched = 0
    for row in rows:
        if row.get("srno") in srnos:
            total += _to_float(row.get("amount", 0))
            matched += 1
    return total, matched


def _first_row(rows, srno):
    """Amount of the first row with ``srno``, or ``None`` when absent."""
    for row in rows:
        if row.get("srno") == srno:
            return _to_float(row.get("amount", 0))
    return None


def get_margin_data(auth_token):
    """Fetch margin data from Motilal Oswal API using the provided auth token.

    Returns the OpenAlgo funds dict, or ``{}`` on any broker-side failure so
    callers (blueprints/auth.py session resume) can tell an expired token from
    a genuinely empty account.
    """
    client = get_httpx_client()

    response = client.post(
        get_url("getreportmargindetail"),
        headers=get_common_headers(auth_token),
        json={},
    )

    # Add status attribute for compatibility with the existing codebase
    response.status = response.status_code

    try:
        margin_data = response.json()
    except ValueError:
        logger.error(
            f"Motilal margin detail returned non-JSON body (HTTP {response.status_code}): "
            f"{response.text[:200]!r}"
        )
        return {}

    logger.info(f"Margin Data: {margin_data}")

    if margin_data.get("status") != "SUCCESS" or not margin_data.get("data"):
        # MO8001 Invalid Token / MO8002 Token Expired etc. (doc 31-error-codes.md).
        # Return {} — NOT a dict of zeros — so an expired token is not mistaken
        # for a valid session with an empty account.
        errorcode = margin_data.get("errorcode") or margin_data.get("errorCode") or ""
        logger.error(
            "Failed to fetch Motilal margin data: "
            f"status={margin_data.get('status')!r} errorcode={errorcode!r} "
            f"message={margin_data.get('message', 'Unknown error')!r}"
        )
        return {}

    rows = [row for row in margin_data["data"] if isinstance(row, dict)]

    # --- collateral: srno 220 "Non-Cash Balance(Non-Cash Margin)" -----------
    collateral = _first_row(rows, SRNO_NON_CASH_BALANCE) or 0.0

    # --- utiliseddebits: srno 300 "Margin Usage Details (B)" ----------------
    # Fallback sums the per-segment headers rather than picking srno 301, which
    # is the cash/equities segment alone (674.75 vs 622432.4 in doc 25 — off by
    # ~1000x) and would badly understate usage.
    utiliseddebits = _first_row(rows, SRNO_MARGIN_USAGE_TOTAL)
    if utiliseddebits is None:
        utiliseddebits, matched = _sum_rows(rows, SRNO_MARGIN_USAGE_SEGMENTS)
        if not matched:
            utiliseddebits = 0.0

    # --- availablecash: srno 201 "Cash Balance(Cash Margin)" ----------------
    # srno 102 "Available for Cash / SLBM Segment" is a NET figure, identical to
    # srno 100 "Total Available Margin(A-B-C-D)": from the doc-25 sample,
    #   cash 50000000 (201) + non-cash 474919.06 (220)
    #   - usage 622432.4 (300) + MTM -18590 (600) = 49833896.66 (102)
    # Reporting 102 as availablecash while ALSO reporting collateral (220) and
    # utiliseddebits (300) double counts them — the same bug class fixed in
    # broker/angel/api/funds.py:75-94 (GitHub issue #1582). Motilal, unlike
    # Angel, publishes the free-cash row directly, so use srno 201 and fall back
    # to inverting the net identity (cash = net - non-cash + usage - MTM) only
    # when srno 201 is missing.
    availablecash = _first_row(rows, SRNO_CASH_BALANCE)
    if availablecash is None:
        net_available = _first_row(rows, SRNO_NET_AVAILABLE_CASH_SEG)
        if net_available is None:
            availablecash = 0.0
        else:
            mtm_total = _first_row(rows, SRNO_TOTAL_PL_MTM)
            if mtm_total is None:
                mtm_total = _first_row(rows, SRNO_MTM_TOTAL) or 0.0
            availablecash = net_available - collateral + utiliseddebits - mtm_total
            logger.info(
                "Motilal srno 201 (Cash Balance) absent; derived free cash from "
                f"srno 102 net {net_available} - collateral {collateral} "
                f"+ usage {utiliseddebits} - MTM {mtm_total} = {availablecash}"
            )

    # --- m2m: the explicit per-segment split rows ---------------------------
    # srno 600 "Total Profit and Loss(MTM)" is the COMBINED MTM (it equals
    # srno 400 "Profit / Loss (MTM) Details C") and srno 700 is
    # "Total Profit and Loss(BPL)" — booked P&L, a different concept. The real
    # split lives in the per-segment "Add: Unrealised (Net)" / "Add: Realised
    # P/L (Net)" rows, which repeat per segment and so must be summed.
    m2munrealized, unrealised_rows = _sum_rows(rows, SRNO_UNREALISED)
    m2mrealized, realised_rows = _sum_rows(rows, SRNO_REALISED)
    if not unrealised_rows and not realised_rows:
        # Margin SUMMARY-shaped response (doc 24) carries no split rows; the
        # combined MTM is the best available approximation of open-position P&L.
        combined_mtm = _first_row(rows, SRNO_TOTAL_PL_MTM)
        if combined_mtm is None:
            combined_mtm = _first_row(rows, SRNO_MTM_TOTAL)
        if combined_mtm is not None:
            logger.info(
                "Motilal response has no per-segment realised/unrealised rows; "
                f"reporting combined MTM {combined_mtm} as m2munrealized"
            )
            m2munrealized = combined_mtm

    values = {
        "availablecash": availablecash,
        "collateral": collateral,
        "m2mrealized": m2mrealized,
        "m2munrealized": m2munrealized,
        "utiliseddebits": utiliseddebits,
    }
    return {key: f"{_to_float(values.get(key, 0)):.2f}" for key in OUTPUT_KEYS}
