"""
Broker-custom RESTX endpoint.
Accepts a JSON payload that specifies broker, endpoint, method, and payload,
then forwards the call to the selected broker via execute_custom.
"""
from flask_restx import Namespace, Resource
from flask import request, jsonify, make_response
from marshmallow import ValidationError

from restx_api.data_schemas import CustomBrokerSchema
from services.get_token_service import get_auth_token_brokers
from services.broker_custom_service import execute_custom
from utils.logging import get_logger

api = Namespace('broker_custom', description='Execute custom broker API requests')
logger = get_logger(__name__)
schema = CustomBrokerSchema()


def _build_error_response(message: str, status_code: int):
    """Helper to create a consistent error payload."""
    return make_response(jsonify({'status': 'error', 'message': message}), status_code)


@api.route('/', strict_slashes=False)
class CustomBroker(Resource):
    @api.doc('execute_custom_broker_request')
    def post(self):
        """Execute custom broker API request."""
        try:
            payload = schema.load(request.json)
        except ValidationError as err:
            return _build_error_response(err.messages, 400)

        api_key = payload['apikey']
        endpoint = payload['endpoint']
        method = payload['method']
        body = payload['payload']

        auth_token, _, broker_name = get_auth_token_brokers(api_key=api_key)
        if auth_token is None:
            # Skip logging to avoid DB flooding from bad keys
            return _build_error_response('Invalid openalgo apikey', 403)

        try:
            data = execute_custom(
                auth_token=auth_token,
                broker_name=broker_name,
                endpoint=endpoint,
                method=method,
                payload=body,
            )
        except Exception as exc:  # noqa: BLE001  # service already logs internals
            logger.exception('Custom broker request failed: %s', exc)
            return _build_error_response('An unexpected error occurred', 500)

        return make_response(data, 200)
