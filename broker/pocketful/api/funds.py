"""Pocketful funds mapped onto OpenAlgo's funds response.

GET /api/v2/funds/view?client_id=<client_id>&type=all (Pocketful docs,
"Funds"; the SDK's ``api.funds`` route) answers a label and value table:

    {"data": {"client_id": "...", "headers": ["Description", ""],
              "values": [["Available", "39.99"], ["Cash Deposit", "39.99"],
                         ...]},
     "message": "", "status": "success"}

The rows read, by the label the docs give them:

    availablecash   "Available": funds currently available in the account
    collateral      "DP Pledge Collateral" + "Pool Pledge Collateral": funds
                    obtained against pledged securities, which is what
                    OpenAlgo's collateral means (margin from pledged holdings).
                    The "... Collateral Benefit" rows describe the same pledge
                    from another angle, so they are not added on top.
    utiliseddebits  "Net Margin": the docs define it as the balance required
                    after accounting for all open positions, the margin in use.

The answer carries no M2M figure. Realised and unrealised M2M come from the
position book, through the same functions the position book service calls
(``order_api.get_positions``, ``order_data.map_position_data`` and
``transform_positions_data``), so the dashboard and the position book agree:
closed rows (quantity 0) are realised, open rows unrealised. A position book
that cannot be read leaves both at 0.00 and the funds figures still stand.

Every value is a 2 decimal string. Any failure to read funds returns {}, which
is what the dashboard and the session resume read as a dead session.
"""

from broker.pocketful.api.baseurl import client_id, pocketful_request
from utils.logging import get_logger

logger = get_logger(__name__)

FUNDS_PATH = "/api/v2/funds/view"

AVAILABLE = "Available"
COLLATERAL_ROWS = ("DP Pledge Collateral", "Pool Pledge Collateral")
USED = "Net Margin"


def _to_float(value):
    try:
        return float(str(value).replace(",", "").strip())
    except (TypeError, ValueError):
        return 0.0


def _rows(values):
    """{label: amount} from the ``values`` table of [label, amount] pairs."""
    table = {}
    for row in values:
        if isinstance(row, (list, tuple)) and len(row) >= 2:
            table[str(row[0]).strip()] = _to_float(row[1])
    return table


def _position_m2m(auth_token):
    """(realised, unrealised) across the position book; (0.0, 0.0) if unreadable."""
    try:
        from broker.pocketful.api.order_api import get_positions
        from broker.pocketful.mapping.order_data import map_position_data, position_pnl_split

        book = get_positions(auth_token)
        if isinstance(book, dict) and book.get("status") == "error":
            logger.warning("Pocketful position book could not be read for M2M")
            return 0.0, 0.0
        rows = map_position_data(book) or []
    except Exception:
        logger.exception("Could not read the Pocketful position book for M2M")
        return 0.0, 0.0

    # Split within each row: a position closed in part has booked profit on
    # the matched quantity and open profit on the rest.
    realised = 0.0
    unrealised = 0.0
    for row in rows:
        if not isinstance(row, dict):
            continue
        booked, open_pnl = position_pnl_split(row)
        realised += booked
        unrealised += open_pnl
    return realised, unrealised


def get_margin_data(auth_token):
    """OpenAlgo funds dict (2 decimal strings), or {} when Pocketful cannot be read."""
    account = client_id(auth_token)
    if not account:
        logger.error("Pocketful funds not requested: the session carries no client id")
        return {}

    try:
        response = pocketful_request(
            "GET", FUNDS_PATH, auth_token, params={"client_id": account, "type": "all"}
        )
    except Exception:
        logger.exception("Pocketful funds request failed")
        return {}

    if not response.ok:
        logger.error(
            f"Pocketful funds answered {response.status_code}: {response.message or 'no message'}"
        )
        return {}

    payload = response.payload
    values = payload.get("values") if isinstance(payload, dict) else None
    if not isinstance(values, list):
        logger.error("Pocketful funds answer has no values table")
        return {}

    table = _rows(values)
    expected = (AVAILABLE, USED, *COLLATERAL_ROWS)
    missing = [label for label in expected if label not in table]
    if missing:
        # Labels only, never amounts: this is what a first live run needs to
        # see if Pocketful's labels differ from its documentation.
        logger.warning(f"Pocketful funds rows missing {missing}; rows received: {sorted(table)}")

    realised, unrealised = _position_m2m(auth_token)

    return {
        "availablecash": f"{table.get(AVAILABLE, 0.0):.2f}",
        "collateral": f"{sum(table.get(label, 0.0) for label in COLLATERAL_ROWS):.2f}",
        "m2munrealized": f"{unrealised:.2f}",
        "m2mrealized": f"{realised:.2f}",
        "utiliseddebits": f"{table.get(USED, 0.0):.2f}",
    }
