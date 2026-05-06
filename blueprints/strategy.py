"""Webhook entrypoint for strategy v2.

Phase 8 — the legacy v1 surface (HTML routes, JSON CRUD, queue-based
order processor, squareoff scheduler, ~1000 lines) has been removed.
The only thing that remains here is the public webhook URL that
external integrators (TradingView / Amibroker / Chartink / Python SDK)
post to. The URL contract is preserved verbatim:

    POST /strategy/webhook/<webhook_id>

is dispatched into services.strategy.ingestion_service.handle_webhook
which validates signing, runs account/strategy preflight, and creates
a strategy run.

Why this file still exists at all (rather than folding into
blueprints/strategy_v2.py):
  - app.py:370 has `csrf.exempt(app.view_functions["strategy_bp.webhook"])`.
    Existing operator config and the rate-limit decorator
    (`limiter.limit(WEBHOOK_RATE_LIMIT)`) are tied to the
    `strategy_bp.webhook` view-function name. Keeping the blueprint
    name and the view name avoids a touch on every operator's running
    deployment.
  - The webhook URL lives at /strategy/webhook/<id> (url_prefix='/strategy'
    on this blueprint). Existing TradingView alert URLs, Amibroker
    AFLs, and Chartink scanner configs all post here. Renaming the
    prefix would break all of them.
"""

import os

from flask import Blueprint, jsonify, request

from limiter import limiter
from utils.logging import get_logger

logger = get_logger(__name__)

# Webhook rate limit — applied per-IP by Flask-Limiter. Same env var as
# the old v1 path so existing operators don't have to update their .env.
WEBHOOK_RATE_LIMIT = os.getenv("WEBHOOK_RATE_LIMIT", "100 per minute")

strategy_bp = Blueprint("strategy_bp", __name__, url_prefix="/strategy")


@strategy_bp.route("/webhook/<webhook_id>", methods=["POST"])
@limiter.limit(WEBHOOK_RATE_LIMIT)
def webhook(webhook_id):
    """Strategy v2 webhook endpoint.

    Capture raw bytes BEFORE any JSON parsing — required for HMAC over
    body signing (services.strategy.webhook_guard.verify_hmac computes
    the digest over `request.get_data()`, not over the parsed JSON).
    """
    raw_body = request.get_data()

    # Late import keeps the heavy v2 stack out of the cold-start path of
    # operators who never call /strategy/webhook/* (e.g. someone using
    # OpenAlgo only for /api/v1 manual orders).
    from services.strategy.ingestion_service import handle_webhook

    try:
        status, body = handle_webhook(
            webhook_id=webhook_id,
            raw_body=raw_body,
            headers=dict(request.headers),
            request=request,
        )
    except Exception:  # pragma: no cover — defensive guard
        logger.exception(f"Strategy v2 webhook handler crashed for {webhook_id}")
        return jsonify({"status": "error", "message": "Internal server error"}), 500

    return jsonify(body), status
