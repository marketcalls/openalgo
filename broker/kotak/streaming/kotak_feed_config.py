"""Resolve which market-data feed host this account's data centre is routed to.

Kotak no longer publishes one fixed market-data URL. The host is looked up per
data centre from a config service, and the answer has changed underneath
clients at least once already - the legacy HSM host at mlhsm.kotaksecurities.com
is still serving but no data centre selects it any more, and Kotak's own SDK
removed every code path to it in 2.2.0.

The lookup is two steps:

    {data_center}_broadcast_source            -> "hs" | "sh" | "ks"
    {data_center}_{source}_broadcast_endpoint -> market data host
    {data_center}_{source}_interactive_endpoint -> order feed host

Best effort throughout. A network failure, an unparseable response, an unknown
data centre or a missing key all resolve to the hardcoded SFeed default rather
than raising, which is the same thing Kotak's SDK does on every one of those
paths. The one case worth failing loudly on is a data centre that genuinely
selects "hs", because that answer contradicts everything observed since
September 2026 and we would want to know rather than quietly dial a dead host.
"""

from utils.httpx_client import get_httpx_client
from utils.logging import get_logger

logger = get_logger(__name__)

CONFIG_SERVICE_URL = "https://lapi.kotaksecurities.com/5config/config"

# What the SDK falls back to when its own config lookup fails, and what six of
# the ten live data centres resolve to anyway.
DEFAULT_SFEED_URL = "wss://sfeed.kotaksecurities.com/apifeed"

# Sent as appVersion. Kotak keys nothing off this today; it exists so a future
# server-side version gate has something to read.
CONFIG_APP_VERSION = "1.0.0"
CONFIG_PLATFORM = "api"
CONFIG_ENVIRONMENT = "prod"

CONFIG_TIMEOUT_SECONDS = 5

# Feed sources, in the vocabulary the config service uses.
SOURCE_HSM = "hs"
SOURCE_SFEED = "sh"
SOURCE_CDTSTREAM = "ks"


def _to_websocket_scheme(url):
    """Normalize an https/http endpoint to wss/ws, leaving the rest intact.

    The config service returns endpoints as https URLs, and two of them come
    back with no scheme at all (the hs entries are bare hostnames), so a plain
    string replace is not enough.
    """
    if not url:
        return url
    url = url.strip()
    if url.startswith("https://"):
        return "wss://" + url[len("https://") :]
    if url.startswith("http://"):
        return "ws://" + url[len("http://") :]
    if url.startswith(("wss://", "ws://")):
        return url
    return "wss://" + url


def fetch_feed_config(data_center, timeout=CONFIG_TIMEOUT_SECONDS):
    """Look up the market-data and order-feed hosts for one data centre.

    Args:
        data_center: the "dataCenter" value from tradeApiValidate, e.g. "E43".
            Falsy (an older stored token predates us capturing it) short
            circuits straight to the default.
        timeout: seconds to allow the config call.

    Returns:
        dict with "source", "market_data_url" and "order_feed_url". Any value
        that could not be resolved is None except market_data_url, which always
        carries at least DEFAULT_SFEED_URL so a caller can dial something.
    """
    result = {
        "source": None,
        "market_data_url": DEFAULT_SFEED_URL,
        "order_feed_url": None,
    }

    if not data_center:
        logger.info(
            "No Kotak dataCenter recorded for this session (token predates it being "
            f"captured); using the default market-data feed {DEFAULT_SFEED_URL}"
        )
        return result

    try:
        # Shared client, per the FD conventions in CLAUDE.md - a per-call
        # httpx.Client would open its own connection pool and leak it. The
        # explicit timeout matters more than usual here: this runs on the path
        # that builds the feed client, so a hung config service would stall
        # streaming startup rather than just this lookup.
        response = get_httpx_client().get(
            CONFIG_SERVICE_URL,
            params={
                "appVersion": CONFIG_APP_VERSION,
                "platform": CONFIG_PLATFORM,
                "environment": CONFIG_ENVIRONMENT,
            },
            timeout=timeout,
        )
        response.raise_for_status()
        payload = response.json()
        configs = ((payload.get("data") or {}).get("configs")) or {}
    except Exception as e:
        logger.warning(
            f"Kotak feed config lookup failed for data centre {data_center} ({e}); "
            f"falling back to {DEFAULT_SFEED_URL}"
        )
        return result

    source = configs.get(f"{data_center}_broadcast_source")
    if not source:
        logger.warning(
            f"Kotak config service lists no broadcast_source for data centre "
            f"{data_center}; falling back to {DEFAULT_SFEED_URL}"
        )
        return result

    result["source"] = source

    market_data = configs.get(f"{data_center}_{source}_broadcast_endpoint")
    order_feed = configs.get(f"{data_center}_{source}_interactive_endpoint")

    if order_feed:
        result["order_feed_url"] = _to_websocket_scheme(order_feed)

    if not market_data:
        logger.warning(
            f"Kotak data centre {data_center} selects source '{source}' but the config "
            f"service carries no {data_center}_{source}_broadcast_endpoint key; "
            f"falling back to {DEFAULT_SFEED_URL}"
        )
        return result

    if source == SOURCE_HSM:
        # Nothing has selected hs since at least September 2026, and the SDK
        # dropped its HSM client entirely in 2.2.0. If this ever fires, the
        # binary decoder in sfeed_protocol.py is the wrong one for the host we
        # are about to dial - big-endian HSM framing, not little-endian SFeed -
        # so say so instead of connecting and decoding garbage.
        logger.error(
            f"Kotak data centre {data_center} selects the legacy HSM feed "
            f"({market_data}). OpenAlgo's SFeed decoder cannot read that protocol. "
            "Falling back to SFeed; if quotes do not arrive, this is why."
        )
        return result

    result["market_data_url"] = _to_websocket_scheme(market_data)
    logger.info(
        f"Kotak data centre {data_center} routes market data to "
        f"{result['market_data_url']} (source '{source}')"
    )
    return result
