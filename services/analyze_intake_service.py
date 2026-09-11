"""Decision-telemetry intake service (ADR-006 Amendment 5 counterpart).

Records a routed strategy decision (producer: LOATS ``route_to_analyzer``)
into the analyzer log and acknowledges receipt. Pure receive-and-record:
no broker calls, no order state, no mode toggles — the ANALYZE-mode read-only
semantic is untouched. The apikey never reaches storage: the resource strips
it before calling this service, and this service re-strips defensively.
"""

from concurrent.futures import ThreadPoolExecutor
from typing import Any

from database.analyzer_db import async_log_analyzer
from utils.logging import get_logger

# Initialize logger
logger = get_logger(__name__)

# Single-thread executor for the audit write: acknowledgement must not wait
# on database I/O, matching the fire-and-forget audit pattern used by the
# order/data endpoints (log_executor.submit).
_log_executor = ThreadPoolExecutor(max_workers=1)

# api_type under which decision-telemetry rows are stored in analyzer_logs.
DECISION_INTAKE_API_TYPE = "analyze_intake"


def record_decision_intake(
    intake_data: dict[str, Any],
    original_data: dict[str, Any],
) -> tuple[bool, dict[str, Any], int]:
    """Record one routed decision and return the acknowledgement.

    Args:
        intake_data: Validated decision payload (apikey already removed).
        original_data: Raw request body (apikey removed) kept for the audit log.

    Returns:
        Tuple of (success, response_data, http_status_code). The acknowledgement
        precedes the audit write: the log task is submitted fire-and-forget and
        its failures are contained inside ``async_log_analyzer``.
    """
    try:
        decision_id = str(intake_data.get("decision_id", "unknown"))
        # Defensive re-strip: audit rows must never carry the credential.
        safe_request = {k: v for k, v in original_data.items() if k != "apikey"}

        _log_executor.submit(
            async_log_analyzer, safe_request, {"status": "success"}, DECISION_INTAKE_API_TYPE
        )

        response_data = {
            "status": "success",
            "data": {
                "decision_id": decision_id,
                "recorded": True,
            },
        }
        return True, response_data, 200

    except Exception as e:
        logger.exception(f"Error recording decision intake: {e}")
        error_response = {"status": "error", "message": "Failed to record decision"}
        return False, error_response, 500
