# services/pending_order_execution_service.py

import json
from typing import Any

from database.action_center_db import (
    NO_ACTION,
    SUBMITTING,
    claim_pending_order_for_execution,
    get_pending_order_by_id,
    return_approved_order_to_pending,
    update_broker_status,
)
from database.auth_db import get_api_key_for_tradingview, get_auth_token
from utils.broker_backpressure import BrokerBusyError, RefusalRecorder
from utils.logging import get_logger

# Initialize logger
logger = get_logger(__name__)

#: HTTP status for an approved order that another request is already sending.
ALREADY_SUBMITTING_STATUS = 409

#: What the operator reads when an approval loses the execution claim.
ALREADY_SUBMITTING_MESSAGE = (
    "This order is already being sent to your broker. Check the order book "
    "before approving it again."
)

#: Set on the response of an approval whose order was never sent and is back in
#: the pending list, so the route can say so and refresh the page.
RETURNED_TO_PENDING = "returned_to_pending"

#: What the operator reads when the approval could not be recorded as sending.
CLAIM_FAILED_MESSAGE = (
    "The order was not sent to your broker, because OpenAlgo could not record it "
    "as being sent. It is back in the pending list: approve it again in a moment."
)

#: The same, when it could not even be put back in the pending list.
CLAIM_FAILED_STUCK_MESSAGE = (
    "The order was not sent to your broker, because OpenAlgo could not record it "
    "as being sent. Place it again from your trading platform."
)

#: What the operator reads when the broker pacer refused the order (gthread only).
REFUSED_BACK_TO_PENDING_MESSAGE = (
    "The order was not sent: OpenAlgo is pacing requests to stay within your "
    "broker's rate limit, and its turn was too far away. It is back in the "
    "pending list, so approve it again in a few seconds."
)

#: Order types that send at most one order, so a refusal means nothing was sent.
_SINGLE_ORDER_TYPES = frozenset({"placeorder", "smartorder", "optionsorder", "placegttorder"})


def _refused_single_order(pending_order_id: int, api_type: str) -> tuple[bool, dict, int] | None:
    """Offer a single order the pacer refused back for approval.

    Only for an order type that sends one order, whose refusal therefore proves
    nothing reached the broker. Returns the response to give, or None when the
    order could not be put back (the caller then records it as rejected).
    """
    if api_type not in _SINGLE_ORDER_TYPES:
        return None
    if not return_approved_order_to_pending(pending_order_id, SUBMITTING):
        return None
    return (
        False,
        {"status": "error", "message": REFUSED_BACK_TO_PENDING_MESSAGE, RETURNED_TO_PENDING: True},
        429,
    )


def _flatten_execution_results(results: Any) -> list[dict[str, Any]]:
    """Return leaf order results from batch and split-order responses."""
    flattened = []
    if not isinstance(results, list):
        return flattened

    for result in results:
        if not isinstance(result, dict):
            continue
        split_results = result.get("split_results")
        if isinstance(split_results, list):
            flattened.extend(_flatten_execution_results(split_results))
        else:
            flattened.append(result)

    return flattened


def _summarize_order_ids(order_ids: list[str]) -> str:
    """Fit one or more broker order IDs into the Action Center DB column."""
    combined = ",".join(order_ids)
    if len(combined) <= 255:
        return combined
    return f"{order_ids[0]} (+{len(order_ids) - 1} more)"[:255]


def execute_approved_order(pending_order_id: int) -> tuple[bool, dict[str, Any], int]:
    """
    Execute an approved pending order

    Args:
        pending_order_id: ID of the pending order to execute

    Returns:
        Tuple containing:
        - Success status (bool)
        - Response data (dict)
        - HTTP status code (int)
    """
    claimed = False
    try:
        # Get the pending order
        pending_order = get_pending_order_by_id(pending_order_id)

        if not pending_order:
            logger.error(f"Pending order {pending_order_id} not found")
            return False, {"status": "error", "message": "Pending order not found"}, 404

        if pending_order.status != "approved":
            logger.error(
                f"Cannot execute pending order {pending_order_id}: status is '{pending_order.status}', not 'approved'"
            )
            return (
                False,
                {
                    "status": "error",
                    "message": f"Order cannot be executed (status: {pending_order.status})",
                },
                400,
            )

        # Claim before anything can reach the broker. An approved order is
        # sent at most once: two approvals racing (a double click, Approve on
        # one device and Approve All on another) could both pass the status
        # check above and both place the order. The claim is one conditional
        # UPDATE that moves broker_status from empty to "submitting", so only
        # one caller gets True. Every path after it writes a final status, and
        # an order left in "submitting" (a crash mid-send) is never resent
        # automatically: the operator checks the broker's order book.
        claim = claim_pending_order_for_execution(pending_order_id)
        if claim is None:
            # The database could not answer, so nothing was claimed and nothing
            # was sent. Saying "already being sent" here would be wrong: put the
            # approval back so the order can be approved again.
            if return_approved_order_to_pending(pending_order_id, None):
                return (
                    False,
                    {"status": "error", "message": CLAIM_FAILED_MESSAGE, RETURNED_TO_PENDING: True},
                    500,
                )
            return False, {"status": "error", "message": CLAIM_FAILED_STUCK_MESSAGE}, 500

        if not claim:
            logger.warning(
                f"Pending order {pending_order_id} is already being executed; not sending it again"
            )
            return (
                False,
                {"status": "error", "message": ALREADY_SUBMITTING_MESSAGE},
                ALREADY_SUBMITTING_STATUS,
            )

        claimed = True

        # Parse order data
        order_data = json.loads(pending_order.order_data)
        api_type = pending_order.api_type
        user_id = pending_order.user_id

        # Get the user's API key (needed for order_data validation and broker functions)
        api_key = get_api_key_for_tradingview(user_id)

        # Get auth token and broker (to skip routing check and authenticate)
        auth_token = get_auth_token(user_id)

        # Get broker from auth table
        from database.auth_db import Auth

        auth_obj = Auth.query.filter_by(name=user_id).first()
        broker = auth_obj.broker if auth_obj else None

        if not api_key or not auth_token or not broker:
            logger.error(
                f"Cannot execute pending order {pending_order_id}: missing api_key, auth_token, or broker"
            )
            update_broker_status(pending_order_id, None, "rejected")
            return False, {"status": "error", "message": "Authentication failed"}, 403

        # Route to appropriate service based on api_type
        success = False
        response_data = {}
        status_code = 500

        logger.info(
            f"Executing approved order: pending_order_id={pending_order_id}, api_type={api_type}, user={user_id}"
        )
        logger.debug(f"Order data keys: {list(order_data.keys())}")
        logger.debug(f"Has apikey in order_data: {'apikey' in order_data}")

        # Knows whether a refusal (gthread only) happened while the order was
        # being placed, which proves a single order never reached the broker.
        refusals = RefusalRecorder().start()
        try:
            # Pass api_key, auth_token, and broker to:
            # 1. Include apikey in order_data for validation and broker functions
            # 2. Skip routing check (because auth_token and broker are present)
            # 3. Execute order with proper authentication

            if api_type == "placeorder":
                from services.place_order_service import place_order

                success, response_data, status_code = place_order(
                    order_data=order_data, api_key=api_key, auth_token=auth_token, broker=broker
                )

            elif api_type == "smartorder":
                from services.place_smart_order_service import place_smart_order

                success, response_data, status_code = place_smart_order(
                    order_data=order_data, api_key=api_key, auth_token=auth_token, broker=broker
                )

            elif api_type == "basketorder":
                from services.basket_order_service import place_basket_order

                success, response_data, status_code = place_basket_order(
                    basket_data=order_data, api_key=api_key, auth_token=auth_token, broker=broker
                )

            elif api_type == "splitorder":
                from services.split_order_service import split_order

                logger.info(f"Calling split_order for broker={broker}")
                success, response_data, status_code = split_order(
                    split_data=order_data, api_key=api_key, auth_token=auth_token, broker=broker
                )
                logger.info(
                    f"Split order result: success={success}, status={status_code}, response={response_data}"
                )

            elif api_type == "optionsorder":
                from services.place_options_order_service import place_options_order

                logger.info(f"Calling place_options_order for broker={broker}")
                success, response_data, status_code = place_options_order(
                    options_data=order_data, api_key=api_key, auth_token=auth_token, broker=broker
                )
                logger.info(
                    f"Options order result: success={success}, status={status_code}, response={response_data}"
                )

            elif api_type == "optionsmultiorder":
                from services.options_multiorder_service import place_options_multiorder

                logger.info(f"Calling place_options_multiorder for broker={broker}")
                success, response_data, status_code = place_options_multiorder(
                    multiorder_data=order_data,
                    api_key=api_key,
                    auth_token=auth_token,
                    broker=broker,
                )

            elif api_type == "placegttorder":
                from services.place_gtt_order_service import place_gtt_order

                logger.info(f"Calling place_gtt_order for broker={broker}")
                success, response_data, status_code = place_gtt_order(
                    order_data=order_data,
                    api_key=api_key,
                    auth_token=auth_token,
                    broker=broker,
                )

            else:
                logger.error(f"Unknown api_type: {api_type}")
                update_broker_status(pending_order_id, None, "rejected")
                return False, {"status": "error", "message": f"Unknown order type: {api_type}"}, 400

            # Update pending order with broker response
            if not success:
                if status_code == 429 and refusals.refused:
                    offered_back = _refused_single_order(pending_order_id, api_type)
                    if offered_back is not None:
                        logger.warning(
                            f"Pending order {pending_order_id} refused before it was sent; "
                            "back in the pending list"
                        )
                        return offered_back
                update_broker_status(pending_order_id, None, "rejected")
                logger.warning(f"Order rejected by broker: pending_order_id={pending_order_id}")

            elif api_type == "placegttorder":
                trigger_id = response_data.get("trigger_id")
                if not trigger_id:
                    update_broker_status(pending_order_id, None, "rejected")
                    response_data = {
                        **response_data,
                        "status": "error",
                        "message": "GTT placement succeeded without a trigger ID",
                    }
                    return False, response_data, 502

                trigger_id = str(trigger_id)
                update_broker_status(pending_order_id, trigger_id, "open")
                response_data["broker_order_id"] = trigger_id
                logger.info(
                    f"GTT executed: pending_order_id={pending_order_id}, trigger_id={trigger_id}"
                )

            elif isinstance(response_data.get("results"), list):
                leaf_results = _flatten_execution_results(response_data["results"])
                order_ids = [
                    str(result["orderid"])
                    for result in leaf_results
                    if result.get("status") == "success" and result.get("orderid")
                ]

                if not order_ids:
                    update_broker_status(pending_order_id, None, "rejected")
                    response_data = {
                        **response_data,
                        "status": "error",
                        "message": "No child orders were submitted successfully",
                    }
                    return False, response_data, 502

                has_failures = any(
                    result.get("status") != "success" or not result.get("orderid")
                    for result in leaf_results
                )
                broker_order_id = _summarize_order_ids(order_ids)
                broker_status = "partial" if has_failures else "open"
                update_broker_status(pending_order_id, broker_order_id, broker_status)
                response_data["broker_order_id"] = broker_order_id
                response_data["broker_order_ids"] = order_ids
                logger.info(
                    f"Batch order executed: pending_order_id={pending_order_id}, "
                    f"submitted={len(order_ids)}, status={broker_status}"
                )

            elif "orderid" in response_data:
                broker_order_id = response_data["orderid"]

                # Get actual order status from broker
                try:
                    from services.orderstatus_service import get_order_status

                    status_success, status_response, _ = get_order_status(
                        status_data={"orderid": broker_order_id},
                        api_key=api_key,
                        auth_token=auth_token,
                        broker=broker,
                    )

                    # Extract broker status from response
                    if status_success and "data" in status_response:
                        actual_status = status_response["data"].get("status", "open")
                        update_broker_status(pending_order_id, broker_order_id, actual_status)
                        logger.info(
                            f"Order executed: pending_order_id={pending_order_id}, broker_order_id={broker_order_id}, status={actual_status}"
                        )
                    else:
                        # Fallback to 'open' if status check fails
                        update_broker_status(pending_order_id, broker_order_id, "open")
                        logger.info(
                            f"Order executed successfully: pending_order_id={pending_order_id}, broker_order_id={broker_order_id}"
                        )
                except Exception as e:
                    logger.exception(f"Error checking order status: {e}")
                    # Fallback to 'open' on error
                    update_broker_status(pending_order_id, broker_order_id, "open")
                    logger.info(
                        f"Order executed successfully: pending_order_id={pending_order_id}, broker_order_id={broker_order_id}"
                    )

            else:
                # A success that carries no order id: a smart order whose
                # position already matched sends nothing. The claim must still
                # be replaced by a final status, or the row reads as a send
                # that never finished.
                final = NO_ACTION if api_type == "smartorder" else "open"
                update_broker_status(pending_order_id, None, final)

            return success, response_data, status_code

        except BrokerBusyError as e:
            # Refused before it was sent: the broker's request queue was too
            # long to wait in (only under the gthread worker).
            logger.warning(f"Pending order {pending_order_id} not sent, broker busy: {e}")
            offered_back = _refused_single_order(pending_order_id, api_type)
            if offered_back is not None:
                return offered_back
            update_broker_status(pending_order_id, None, "rejected")
            return False, {"status": "error", "message": str(e)}, 429

        except Exception as e:
            logger.exception(f"Error executing order via service: {e}")
            update_broker_status(pending_order_id, None, "rejected")
            return False, {"status": "error", "message": f"Order execution failed: {str(e)}"}, 500

        finally:
            refusals.stop()

    except Exception as e:
        logger.exception(f"Error in execute_approved_order: {e}")
        if claimed:
            # Failed after the claim and before any order was sent (reading
            # the order or its credentials): the row must not be left reading
            # as on its way to the broker.
            update_broker_status(pending_order_id, None, "rejected")
        return False, {"status": "error", "message": f"Failed to execute order: {str(e)}"}, 500
