"""Strategy v2 blueprint — phase-0 scaffold.

Phase 0 ships only the audit-chain verifier endpoint. Subsequent phases add
strategy/leg CRUD, run management, orderbook/tradebook/positionbook endpoints,
webhook security endpoints, etc.

URL prefix: /strategy/api/v2  (REST/JSON only — UI routes still served by the
React frontend under /strategy/v2 once the SPA pages land in Phase 1).
"""

from flask import Blueprint, jsonify

from subscribers.strategy_audit_subscriber import verify_chain
from utils.logging import get_logger

logger = get_logger(__name__)

strategy_v2_bp = Blueprint("strategy_v2", __name__, url_prefix="/strategy/api/v2")


@strategy_v2_bp.route("/audit/verify/<int:run_id>", methods=["GET"])
def audit_verify(run_id: int):
    """Walk the chained-hash audit log for a run and report integrity.

    Returns:
      200 {"status": "ok", "events_verified": N}                — chain intact
      200 {"status": "tampered", "first_bad_event_id": ID, ...} — divergence
      404 {"status": "error", "message": "no events for run"}   — empty
    """
    try:
        result = verify_chain(run_id)
    except Exception as exc:  # noqa: BLE001
        logger.exception("audit verify failed for run_id=%s", run_id)
        return (
            jsonify({"status": "error", "message": f"verifier crashed: {exc}"}),
            500,
        )

    if result.get("events_verified", 0) == 0 and result.get("status") == "ok":
        return (
            jsonify({"status": "error", "message": "no events for run"}),
            404,
        )
    return jsonify(result), 200
