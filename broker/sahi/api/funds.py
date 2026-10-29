"""Sahi funds mapped onto OpenAlgo's funds response.

GET /v1/funds (broker-api-docs/sahi-api-docs, Funds) reports one available
figure per order kind plus the components behind them, all in paise:

    available.intraday_and_fno_selling  spendable for intraday, futures and
                                        option selling (collateral included)
    balance.collateral                  margin from pledged holdings
    utilised.*                          span, exposure, delivery_margin,
                                        intraday_margin, delivery_buy,
                                        charges, mtm_loss

OpenAlgo's ``availablecash`` is the cash left after everything blocked
against it, so it is the intraday figure with the pledge collateral taken
back out (collateral is reported on its own). ``utiliseddebits`` is the sum of
the utilised block plus net option premium paid. Realised and unrealised M2M
come from the position book, since /v1/funds carries only a net loss figure.
"""

from broker.sahi.api.baseurl import get_headers, get_url
from broker.sahi.api.order_api import get_positions
from broker.sahi.api.rate_limiter import sahi_request
from broker.sahi.mapping.order_data import map_position_data
from broker.sahi.mapping.transform_data import from_paise
from utils.broker_backpressure import BrokerBusyError
from utils.httpx_client import get_httpx_client
from utils.logging import get_logger

logger = get_logger(__name__)

UTILISED_FIELDS = (
    "span",
    "exposure",
    "delivery_margin",
    "intraday_margin",
    "delivery_buy",
    "charges",
    "mtm_loss",
)


def _position_pnl(auth_token):
    """(realised, unrealised) rupees across today's positions; (0, 0) if unreadable."""
    book = get_positions(auth_token)
    if not isinstance(book, dict) or book.get("status") == "error":
        return 0.0, 0.0
    realised = 0.0
    total = 0.0
    for raw in book.get("positions") or []:
        realised += from_paise(raw.get("realised_pnl"))
    for position in map_position_data(book):
        total += position.get("pnl", 0.0)
    return realised, total - realised


def get_margin_data(auth_token):
    """OpenAlgo funds dict (2-dp strings), or {} when Sahi cannot be read."""
    client = get_httpx_client()
    try:
        response = sahi_request(
            client,
            "GET",
            get_url("/v1/funds"),
            "funds",
            headers=get_headers(auth_token),
            timeout=30,
        )
    except BrokerBusyError:
        raise
    except Exception:
        logger.exception("Sahi funds request failed")
        return {}

    try:
        funds = response.json()
    except ValueError:
        funds = {}
    if response.status_code != 200 or not isinstance(funds, dict) or "available" not in funds:
        logger.error(f"Sahi funds returned HTTP {response.status_code}: {funds}")
        return {}

    try:
        available = funds.get("available") or {}
        balance = funds.get("balance") or {}
        utilised = funds.get("utilised") or {}
        premium = funds.get("option_premium") or {}

        collateral = from_paise(balance.get("collateral"))
        available_cash = from_paise(available.get("intraday_and_fno_selling")) - collateral
        used = sum(from_paise(utilised.get(field)) for field in UTILISED_FIELDS)
        used += from_paise(premium.get("paid"))

        try:
            realised, unrealised = _position_pnl(auth_token)
        except BrokerBusyError:
            raise
        except Exception:
            logger.exception("Could not read Sahi positions for M2M")
            realised, unrealised = 0.0, 0.0

        return {
            "availablecash": f"{available_cash:.2f}",
            "collateral": f"{collateral:.2f}",
            "m2munrealized": f"{unrealised:.2f}",
            "m2mrealized": f"{realised:.2f}",
            "utiliseddebits": f"{used:.2f}",
        }
    except Exception:
        logger.exception("Could not map Sahi funds")
        return {}
