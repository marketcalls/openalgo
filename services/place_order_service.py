import copy
import importlib
from typing import Any, Dict, Optional, Tuple

from database.auth_db import get_auth_token_broker
from database.settings_db import get_analyze_mode
from events import AnalyzerErrorEvent, OrderFailedEvent, OrderPlacedEvent
from restx_api.schemas import OrderSchema
from utils.constants import (
    REQUIRED_ORDER_FIELDS,
    VALID_ACTIONS,
    VALID_EXCHANGES,
    VALID_PRICE_TYPES,
    VALID_PRODUCT_TYPES,
)
from utils.event_bus import bus
from utils.logging import get_logger

# Initialize logger
logger = get_logger(__name__)

# Initialize schema
order_schema = OrderSchema()


def import_broker_module(broker_name: str) -> Any | None:
    """
    Dynamically import the broker-specific order API module.

    Args:
        broker_name: Name of the broker

    Returns:
        The imported module or None if import fails
    """
    try:
        module_path = f"broker.{broker_name}.api.order_api"
        broker_module = importlib.import_module(module_path)
        return broker_module
    except ImportError as error:
        logger.error(f"Error importing broker module '{module_path}': {error}")
        return None


def emit_analyzer_error(request_data: dict[str, Any], error_message: str) -> dict[str, Any]:
    """Publish an analyzer error event and return the error response dict."""
    error_response = {"mode": "analyze", "status": "error", "message": error_message}

    analyzer_request = request_data.copy()
    if "apikey" in analyzer_request:
        del analyzer_request["apikey"]
    analyzer_request["api_type"] = "placeorder"

    bus.publish(
        AnalyzerErrorEvent(
            mode="analyze",
            api_type="placeorder",
            request_data=analyzer_request,
            response_data=error_response,
            error_message=error_message,
        )
    )

    return error_response


def validate_order_data(data: dict[str, Any]) -> tuple[bool, dict[str, Any] | None, str | None]:
    """
    Validate order data against required fields and valid values

    Args:
        data: Order data to validate

    Returns:
        Tuple containing:
        - Success status (bool)
        - Validated order data (dict) or None if validation failed
        - Error message (str) or None if validation succeeded
    """
    # Check for missing mandatory fields
    missing_fields = [field for field in REQUIRED_ORDER_FIELDS if field not in data]
    if missing_fields:
        return False, None, f"Missing mandatory field(s): {', '.join(missing_fields)}"

    # Validate exchange
    if "exchange" in data and data["exchange"] not in VALID_EXCHANGES:
        return False, None, f"Invalid exchange. Must be one of: {', '.join(VALID_EXCHANGES)}"

    # Convert action to uppercase and validate
    if "action" in data:
        data["action"] = data["action"].upper()
        if data["action"] not in VALID_ACTIONS:
            return (
                False,
                None,
                f"Invalid action. Must be one of: {', '.join(VALID_ACTIONS)} (case insensitive)",
            )

    # Validate price type if provided
    if "price_type" in data and data["price_type"] not in VALID_PRICE_TYPES:
        return False, None, f"Invalid price type. Must be one of: {', '.join(VALID_PRICE_TYPES)}"

    # Validate product type if provided
    if "product_type" in data and data["product_type"] not in VALID_PRODUCT_TYPES:
        return (
            False,
            None,
            f"Invalid product type. Must be one of: {', '.join(VALID_PRODUCT_TYPES)}",
        )

    # Validate and deserialize input
    try:
        order_data = order_schema.load(data)
        return True, order_data, None
    except Exception as err:
        return False, None, str(err)


# Broker/adapter statuses that prove the order was NOT placed: the request
# was refused before acceptance (validation, auth, rate limit, unknown
# route). Anything else — 5xx (including transport failures converted to
# 500 inside adapters) and unknown codes — is ambiguous: the request may
# have reached the broker and been accepted, so the idempotency reservation
# must stay and the key must be reconciled before another placement.
CONFIRMED_REJECTION_STATUSES = frozenset({400, 401, 403, 404, 405, 409, 422, 429})


def _params_match_reservation(resolution: dict, order_data: dict) -> bool:
    """True when the retry's parameters equal the reservation's originals.

    A retry that changes parameters (a "corrected" order) must never reuse
    an unresolved key: the ambiguous attempt may still be live with the
    original parameters, so releasing or replaying on its behalf would be
    wrong either way.
    """

    def _norm_str(value) -> str:
        return str(value or "").strip().upper()

    if _norm_str(resolution.get("symbol")) != _norm_str(order_data.get("symbol")):
        return False
    if _norm_str(resolution.get("exchange")) != _norm_str(order_data.get("exchange")):
        return False
    if _norm_str(resolution.get("action")) != _norm_str(order_data.get("action")):
        return False
    try:
        if int(resolution.get("quantity") or 0) != int(order_data.get("quantity") or 0):
            return False
    except (TypeError, ValueError):
        return False
    stored_price = resolution.get("price")
    if stored_price is not None:
        try:
            if abs(float(stored_price) - float(order_data.get("price") or 0)) > 1e-9:
                return False
        except (TypeError, ValueError):
            return False
    return True


def _reconcile_unresolved_key(
    auth_token: str, broker: str, api_key: str, client_order_id: str, order_data: dict
):
    """Best-effort broker reconciliation for an unresolved idempotency key.

    Returns ``(ok, response, status_code)`` to answer the retry with, or
    ``None`` when reconciliation proved the original attempt never reached
    the broker (the key is released; the caller may place fresh). The
    outcome is deliberately conservative: replaying a matching order is
    safe (it already exists), while any ambiguity blocks the key instead
    of risking a double placement.
    """
    from database.idempotency_db import (
        get_resolution,
        record_success,
        release_client_order_id,
    )
    from services.orderbook_service import get_orderbook_with_auth

    original = get_resolution(api_key, client_order_id)
    if original is None:
        # Key vanished (TTL prune) since the reserve: nothing to protect.
        return None

    if not _params_match_reservation(original, order_data):
        return False, {
            "status": "error",
            "message": (
                "Previous placement with this client_order_id is unresolved "
                "and the new request parameters differ; verify the order book "
                "and use a new client_order_id"
            ),
        }, 409

    ok, book, _code = get_orderbook_with_auth(auth_token, broker, original_data=None)
    if not ok or not isinstance(book, dict) or book.get("status") != "success":
        return False, {
            "status": "error",
            "message": (
                "Previous placement with this client_order_id is unresolved "
                "and the broker order book is unavailable; verify the order "
                "book before reusing this id"
            ),
        }, 409

    orders = (book.get("data") or {}).get("orders") or []
    candidates = []
    for order in orders:
        if not isinstance(order, dict):
            continue
        status = str(order.get("order_status", "")).strip().upper()
        if status in ("REJECTED", "CANCELLED"):
            continue
        if _params_match_reservation(original, order):
            candidates.append(order)

    if len(candidates) > 1:
        return False, {
            "status": "error",
            "message": (
                "Previous placement with this client_order_id is unresolved "
                "and multiple matching orders were found in the order book; "
                "reconcile manually before reusing this id"
            ),
        }, 409

    if len(candidates) == 1:
        orderid = str(candidates[0].get("orderid", "") or "")
        if not orderid:
            return False, {
                "status": "error",
                "message": (
                    "Previous placement with this client_order_id is "
                    "unresolved; the matching order has no id to replay"
                ),
            }, 409
        record_success(api_key, client_order_id, orderid)
        replay_response = {
            "status": "success",
            "orderid": orderid,
            "client_order_id": client_order_id,
            "duplicate": True,
            "reconciled": True,
        }
        if original.get("tag"):
            replay_response["tag"] = original["tag"]
        return True, replay_response, 200

    # No live candidate: the broker book proves the attempt never placed an
    # order (rejected/cancelled entries are excluded above). Release the key
    # and let the caller place fresh.
    release_client_order_id(api_key, client_order_id)
    return None


def place_order_with_auth(
    order_data: dict[str, Any],
    auth_token: str,
    broker: str,
    original_data: dict[str, Any],
    emit_event: bool = True,
    prefetched_quote: dict[str, Any] | None = None,
    force_live: bool = False,
) -> tuple[bool, dict[str, Any], int]:
    """
    Place an order using provided auth token.

    Args:
        order_data: Validated order data
        auth_token: Authentication token for the broker API
        broker: Name of the broker
        original_data: Original request data for logging
        emit_event: Whether to emit socket event (default True, set False for batch orders)
        prefetched_quote: Pre-fetched quote from batch call (optional, sandbox only)

    Returns:
        Tuple containing:
        - Success status (bool)
        - Response data (dict)
        - HTTP status code (int)
    """
    order_request_data = copy.deepcopy(original_data)
    if "apikey" in order_request_data:
        order_request_data.pop("apikey", None)

    api_key = original_data.get("apikey", "")

    # If in analyze mode, route to sandbox for sandbox trading.
    #
    # force_live opts out, for a caller that already decided the pipe. The
    # strategy module picks live or sandbox per RUN, not per platform: two runs
    # may disagree, and the run's own mode is authoritative. Without this, an
    # operator turning the analyzer on to try something elsewhere would divert
    # a live run's exits into the sandbox, where they report success, so the
    # engine closes the leg and finalises while the real broker position is
    # left open with nothing managing it.
    #
    # The read services already have this escape, spelled `and original_data`
    # (see orderbook_service). This is the same idea made explicit, because a
    # write path should not infer intent from whether a logging argument
    # happens to be None.
    if get_analyze_mode() and not force_live:
        from services.sandbox_service import sandbox_place_order

        if not api_key:
            error_response = {
                "status": "error",
                "message": "API key required for sandbox mode",
                "mode": "analyze",
            }
            return False, error_response, 400

        success, response, status_code = sandbox_place_order(
            order_data, api_key, original_data, prefetched_quote=prefetched_quote
        )

        if emit_event:
            bus.publish(
                OrderPlacedEvent(
                    mode="analyze",
                    api_type="placeorder",
                    strategy=order_data.get("strategy", ""),
                    symbol=order_data.get("symbol", ""),
                    exchange=order_data.get("exchange", ""),
                    action=order_data.get("action", ""),
                    quantity=int(order_data.get("quantity", 0)),
                    pricetype=order_data.get("pricetype", ""),
                    product=order_data.get("product", ""),
                    orderid=response.get("orderid", ""),
                    request_data=order_request_data,
                    response_data=response,
                    api_key=api_key,
                )
            )

        return success, response, status_code

    # Application-level idempotency (live path only): claim the caller-supplied
    # client_order_id BEFORE the broker call, so a network-timeout retry with
    # the same id replays the recorded orderid instead of double-placing.
    # Sandbox placements are simulated, so the field is accepted but not
    # recorded there; the claim is keyed by the apikey hash, never plaintext.
    client_order_id = order_data.get("client_order_id")
    order_tag = order_data.get("tag")
    idempotent = bool(client_order_id and api_key)
    if idempotent:
        from database.idempotency_db import get_resolution, reserve_client_order_id

        # Recorded on the reservation so an unresolved key can be reconciled
        # against the broker order book, and so a corrected retry (different
        # parameters) is refused instead of silently double-placing.
        order_params = {
            "symbol": order_data.get("symbol"),
            "exchange": order_data.get("exchange"),
            "action": order_data.get("action"),
            "quantity": order_data.get("quantity"),
            "price": order_data.get("price"),
        }

        try:
            state, status = reserve_client_order_id(
                api_key, client_order_id, tag=order_tag, order_params=order_params
            )
            if state == "vacated":
                # Reservation vanished (TTL prune) between conflict and re-read:
                # nothing is in flight, so reclaim and fall through on the result.
                state, status = reserve_client_order_id(
                    api_key, client_order_id, tag=order_tag, order_params=order_params
                )
            if state not in ("reserved", "existing"):
                # Could not obtain a reservation after retry — refuse placement
                # rather than proceeding without duplicate protection.
                error_response = {
                    "status": "error",
                    "message": "Could not reserve idempotency key; please retry",
                }
                return False, error_response, 503
            if state == "existing":
                if status == "placed":
                    resolution = get_resolution(api_key, client_order_id)
                    if resolution and resolution["orderid"]:
                        replay_response = {
                            "status": "success",
                            "orderid": resolution["orderid"],
                            "client_order_id": client_order_id,
                            "duplicate": True,
                        }
                        if resolution.get("tag"):
                            replay_response["tag"] = resolution["tag"]
                        return True, replay_response, 200
                if status == "unresolved":
                    # A previous attempt ended ambiguously: ask the broker
                    # order book what actually happened before re-placing.
                    # Reconciliation must never surface as a store failure —
                    # any error means the key stays blocked, never released.
                    try:
                        reconciled = _reconcile_unresolved_key(
                            auth_token, broker, api_key, client_order_id, order_data
                        )
                    except Exception:
                        logger.exception(
                            "Reconciliation failed for client_order_id %s", client_order_id
                        )
                        reconciled = False, {
                            "status": "error",
                            "message": (
                                "Previous placement with this client_order_id "
                                "is unresolved and could not be reconciled with "
                                "the broker; verify the order book before "
                                "reusing this id"
                            ),
                        }, 409
                    if reconciled is not None:
                        return reconciled
                    # Reconciliation proved the order never reached the broker
                    # and released the key: fall through to a fresh placement.
                else:
                    # in_flight, or placed without a recorded orderid: never
                    # re-place.
                    error_response = {
                        "status": "error",
                        "message": "Order placement with this client_order_id is already in progress",
                    }
                    return False, error_response, 409
        except Exception:
            # Store unavailable (SQLite locked/IO error): nothing was committed,
            # so there is no reservation to release. Proceeding would place the
            # order without duplicate protection — the caller explicitly opted
            # in via client_order_id, so refuse the placement instead.
            logger.exception(
                "Idempotency store failure while reserving client_order_id %s",
                client_order_id,
            )
            error_response = {
                "status": "error",
                "message": "Order idempotency store unavailable; order not placed",
            }
            bus.publish(
                OrderFailedEvent(
                    mode="live",
                    api_type="placeorder",
                    request_data=order_request_data,
                    response_data=error_response,
                    api_key=api_key,
                    symbol=order_data.get("symbol", ""),
                    exchange=order_data.get("exchange", ""),
                    error_message="idempotency store unavailable",
                )
            )
            return False, error_response, 503

    # If not in analyze mode, proceed with actual order placement
    broker_module = import_broker_module(broker)
    if broker_module is None:
        if idempotent:
            from database.idempotency_db import release_client_order_id

            release_client_order_id(api_key, client_order_id)
        error_response = {"status": "error", "message": "Broker-specific module not found"}
        bus.publish(
            OrderFailedEvent(
                mode="live",
                api_type="placeorder",
                request_data=order_request_data,
                response_data=error_response,
                api_key=api_key,
                symbol=order_data.get("symbol", ""),
                exchange=order_data.get("exchange", ""),
                error_message="Broker-specific module not found",
            )
        )
        return False, error_response, 404

    try:
        # client_order_id is an application-level idempotency key, never a
        # broker field: hand the broker a payload without it. (Broker mappers
        # build explicit payloads and would ignore it, but stripping keeps the
        # contract explicit.)
        broker_order_data = (
            {k: v for k, v in order_data.items() if k != "client_order_id"}
            if "client_order_id" in order_data
            else order_data
        )
        res, response_data, order_id = broker_module.place_order_api(broker_order_data, auth_token)
    except Exception as e:
        logger.exception(f"Error in broker_module.place_order_api: {e}")
        if idempotent:
            # Ambiguous outcome: the exception may have hit mid-call, after
            # the broker accepted the order. Releasing the reservation would
            # let a retry double-place, so the key is kept as unresolved.
            from database.idempotency_db import mark_unresolved

            mark_unresolved(api_key, client_order_id)
        error_response = {
            "status": "error",
            "message": (
                "Failed to place order due to internal error; placement "
                "unresolved — retries with this client_order_id are blocked "
                "until the order is reconciled"
            ),
        }
        bus.publish(
            OrderFailedEvent(
                mode="live",
                api_type="placeorder",
                request_data=order_request_data,
                response_data=error_response,
                api_key=api_key,
                symbol=order_data.get("symbol", ""),
                exchange=order_data.get("exchange", ""),
                error_message=str(e),
            )
        )
        return False, error_response, 500

    if res.status == 200:
        if idempotent and not order_id:
            # Broker ACKed but named no order — unknown at the broker. Not a
            # failure (a retry could double-place) and not a success (there is
            # no orderid to report or record). The reservation moves to the
            # unresolved state: retries of this id keep getting 409 instead
            # of re-placing, and reconciliation can resolve the true orderid.
            error_response = {
                "status": "error",
                "message": (
                    "Order accepted by broker but no order id was returned; "
                    "placement unresolved, retries with this client_order_id "
                    "are blocked"
                ),
            }
            if emit_event:
                bus.publish(
                    OrderFailedEvent(
                        mode="live",
                        api_type="placeorder",
                        request_data=order_request_data,
                        response_data=error_response,
                        api_key=api_key,
                        symbol=order_data.get("symbol", ""),
                        exchange=order_data.get("exchange", ""),
                        error_message="broker returned 200 without an order id",
                    )
                )
            if idempotent:
                from database.idempotency_db import mark_unresolved

                mark_unresolved(api_key, client_order_id)
            return False, error_response, 500

        order_response_data = {"status": "success", "orderid": order_id}
        if client_order_id:
            order_response_data["client_order_id"] = client_order_id
            if order_tag:
                order_response_data["tag"] = order_tag
        if idempotent:
            try:
                from database.idempotency_db import record_success

                record_success(api_key, client_order_id, str(order_id))
            except Exception:
                logger.exception(
                    "CRITICAL: Order %s placed at broker but idempotency DB "
                    "write failed for client_order_id=%s — row will remain "
                    "in_flight until TTL expiry",
                    order_id,
                    client_order_id,
                )

        if emit_event:
            bus.publish(
                OrderPlacedEvent(
                    mode="live",
                    api_type="placeorder",
                    strategy=order_data.get("strategy", ""),
                    symbol=order_data.get("symbol", ""),
                    exchange=order_data.get("exchange", ""),
                    action=order_data.get("action", ""),
                    quantity=int(order_data.get("quantity", 0)),
                    pricetype=order_data.get("pricetype", ""),
                    product=order_data.get("product", ""),
                    orderid=str(order_id),
                    request_data=order_request_data,
                    response_data=order_response_data,
                    api_key=api_key,
                )
            )

        return True, order_response_data, 200
    else:
        # Release only when the broker/adapter provably refused the order;
        # for inconclusive statuses the key stays reserved (see
        # CONFIRMED_REJECTION_STATUSES) so a retry cannot double-place.
        unresolved = idempotent and res.status not in CONFIRMED_REJECTION_STATUSES
        if idempotent:
            if unresolved:
                from database.idempotency_db import mark_unresolved

                mark_unresolved(api_key, client_order_id)
            else:
                from database.idempotency_db import release_client_order_id

                release_client_order_id(api_key, client_order_id)
        message = (
            response_data.get("message", "Failed to place order")
            if isinstance(response_data, dict)
            else "Failed to place order"
        )
        if unresolved:
            message = (
                f"{message}; placement unresolved — the broker response was "
                "inconclusive, so retries with this client_order_id are "
                "blocked until the order is reconciled"
            )
        error_response = {"status": "error", "message": message}
        bus.publish(
            OrderFailedEvent(
                mode="live",
                api_type="placeorder",
                request_data=order_request_data,
                response_data=error_response,
                api_key=api_key,
                symbol=order_data.get("symbol", ""),
                exchange=order_data.get("exchange", ""),
                error_message=message,
            )
        )
        return False, error_response, res.status if res.status != 200 else 500


def place_order(
    order_data: dict[str, Any],
    api_key: str | None = None,
    auth_token: str | None = None,
    broker: str | None = None,
    emit_event: bool = True,
    prefetched_quote: dict[str, Any] | None = None,
) -> tuple[bool, dict[str, Any], int]:
    """
    Place an order with the broker.
    Supports both API-based authentication and direct internal calls.

    Args:
        order_data: Order data containing all required fields
        api_key: OpenAlgo API key (for API-based calls)
        auth_token: Direct broker authentication token (for internal calls)
        broker: Direct broker name (for internal calls)
        emit_event: Whether to emit socket event (default True, set False for batch orders)
        prefetched_quote: Pre-fetched quote from batch call (optional, sandbox only).
            Skips per-order REST API quote fetch when provided.

    Returns:
        Tuple containing:
        - Success status (bool)
        - Response data (dict)
        - HTTP status code (int)
    """
    original_data = copy.deepcopy(order_data)
    if api_key:
        original_data["apikey"] = api_key
        # Also add apikey to order_data for validation
        order_data["apikey"] = api_key

    # Check if order should be routed to Action Center (semi-auto mode)
    # Only check for API-based calls, not internal calls
    if api_key and not (auth_token and broker):
        from services.order_router_service import queue_order, should_route_to_pending

        if should_route_to_pending(api_key, "placeorder"):
            return queue_order(api_key, original_data, "placeorder")

    # Validate the order data
    is_valid, _, error_message = validate_order_data(order_data)
    if not is_valid:
        if get_analyze_mode():
            return False, emit_analyzer_error(original_data, error_message), 400
        error_response = {"status": "error", "message": error_message}
        safe_request = {k: v for k, v in original_data.items() if k != "apikey"}
        bus.publish(
            OrderFailedEvent(
                mode="live",
                api_type="placeorder",
                request_data=safe_request,
                response_data=error_response,
                error_message=error_message,
                api_key=api_key or "",
            )
        )
        return False, error_response, 400

    # Case 1: API-based authentication
    if api_key and not (auth_token and broker):
        AUTH_TOKEN, broker_name = get_auth_token_broker(api_key)
        if AUTH_TOKEN is None:
            error_response = {"status": "error", "message": "Invalid openalgo apikey"}
            # Skip logging for invalid API keys to prevent database flooding
            return False, error_response, 403

        return place_order_with_auth(
            order_data, AUTH_TOKEN, broker_name, original_data, emit_event, prefetched_quote
        )

    # Case 2: Direct internal call with auth_token and broker
    elif auth_token and broker:
        return place_order_with_auth(
            order_data, auth_token, broker, original_data, emit_event, prefetched_quote
        )

    # Case 3: Invalid parameters
    else:
        error_response = {
            "status": "error",
            "message": "Either api_key or both auth_token and broker must be provided",
        }
        return False, error_response, 400
