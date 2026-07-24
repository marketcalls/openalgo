import hmac
import os

from flask import Blueprint, jsonify, request

from limiter import limiter
from services.broker_token_import_service import BrokerTokenImportError, import_broker_token

internal_broker_token_bp = Blueprint("internal_broker_token", __name__)

SECRET_HEADER = "X-OpenAlgo-Token-Service-Secret"


def _configured_secret() -> str:
    return (os.getenv("OPENALGO_TOKEN_SERVICE_SECRET") or "").strip().strip("'\"")


def _error(message: str, status_code: int):
    return jsonify({"status": "error", "message": message}), status_code


@internal_broker_token_bp.route("/broker-token", methods=["POST"])
@limiter.limit("20 per minute")
def broker_token():
    configured_secret = _configured_secret()
    if not configured_secret:
        return _error("not_found", 404)

    provided_secret = request.headers.get(SECRET_HEADER, "")
    if not provided_secret or not hmac.compare_digest(provided_secret, configured_secret):
        return _error("forbidden", 403)

    payload = request.get_json(silent=True) or {}
    try:
        result = import_broker_token(
            apikey=payload.get("apikey"),
            broker=payload.get("broker"),
            access_token=payload.get("access_token"),
        )
    except BrokerTokenImportError as exc:
        return _error(exc.message, exc.status_code)

    return jsonify({"status": "success", "data": result.to_dict()}), 200
