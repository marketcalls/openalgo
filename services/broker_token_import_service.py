import hashlib
from dataclasses import dataclass

from broker.zerodha.api.auth_api import format_auth_token, validate_access_token
from database.auth_db import get_auth_token, verify_api_key
from utils.auth_utils import activate_broker_auth_token
from utils.logging import get_logger

logger = get_logger(__name__)


class BrokerTokenImportError(Exception):
    status_code = 400

    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


class InvalidApiKeyError(BrokerTokenImportError):
    status_code = 403


class UnsupportedBrokerError(BrokerTokenImportError):
    status_code = 400


class InvalidAccessTokenError(BrokerTokenImportError):
    status_code = 400


class BrokerTokenPersistenceError(BrokerTokenImportError):
    status_code = 500


@dataclass(frozen=True)
class BrokerTokenImportResult:
    broker: str
    user_id: str
    updated: bool

    def to_dict(self) -> dict[str, object]:
        return {
            "broker": self.broker,
            "user_id": self.user_id,
            "updated": self.updated,
        }


def _fingerprint(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()[:12]


def _log_import_result(broker: str, user_id: str, access_token: str, updated: bool) -> None:
    logger.info(
        "Broker token import broker=%s user_id=%s token_len=%s token_fp=%s updated=%s",
        broker,
        user_id,
        len(access_token),
        _fingerprint(access_token),
        updated,
    )


def import_broker_token(apikey: str | None, broker: str | None, access_token: str | None):
    cleaned_broker = (broker or "").strip().lower()
    if cleaned_broker != "zerodha":
        raise UnsupportedBrokerError("unsupported_broker")

    cleaned_access_token = (access_token or "").strip().strip("'\"")
    if not cleaned_access_token:
        raise InvalidAccessTokenError("zerodha_access_token_missing")

    cleaned_apikey = (apikey or "").strip()
    if not cleaned_apikey:
        raise InvalidApiKeyError("invalid_openalgo_apikey")

    user_id = verify_api_key(cleaned_apikey)
    if not user_id:
        raise InvalidApiKeyError("invalid_openalgo_apikey")

    try:
        formatted_token = format_auth_token(cleaned_access_token)
    except ValueError as exc:
        raise InvalidAccessTokenError(str(exc)) from exc

    is_valid, validation_reason = validate_access_token(cleaned_access_token)
    if not is_valid:
        raise InvalidAccessTokenError(validation_reason or "zerodha_profile_rejected")

    existing_token = get_auth_token(user_id, bypass_cache=True)
    if existing_token == formatted_token:
        _log_import_result(cleaned_broker, user_id, cleaned_access_token, updated=False)
        return BrokerTokenImportResult(
            broker=cleaned_broker,
            user_id=user_id,
            updated=False,
        )

    inserted_id = activate_broker_auth_token(formatted_token, user_id, cleaned_broker)
    if not inserted_id:
        raise BrokerTokenPersistenceError("broker_token_persist_failed")

    _log_import_result(cleaned_broker, user_id, cleaned_access_token, updated=True)
    return BrokerTokenImportResult(
        broker=cleaned_broker,
        user_id=user_id,
        updated=True,
    )
