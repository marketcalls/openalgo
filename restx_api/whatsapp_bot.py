"""
WhatsApp REST namespace — deliberately minimal.

The only thing an external API-key holder can do is **send a WhatsApp
message**. Everything else — pairing, unpairing, starting / stopping the
bot, reading or mutating config, listing linked recipients, broadcasting
to all of them, reading stats, editing preferences — is admin-only and
lives behind the session-authed blueprint at /whatsapp.

Why so restrictive: the paired-device session blob is functionally a
credential to the operator's WhatsApp account. A leaked API key should
never be enough to re-pair, wipe, or reconfigure the bot, or to enumerate
the operator's contact list. The narrow `/notify` surface lets strategies
and external dashboards fire alerts without ever exposing that admin
control plane.

Mounted at /api/v1/whatsapp.
"""

import os

from flask import jsonify, make_response, request
from flask_restx import Namespace, Resource, fields

from database.auth_db import verify_api_key
from database.whatsapp_db import get_whatsapp_user_by_username
from limiter import limiter
from services.whatsapp_alert_service import alert_executor, whatsapp_alert_service
from services.whatsapp_bot_service import (
    normalize_phone,
    phone_to_jid,
    validate_attachment_path,
    whatsapp_bot_service,
)
from utils.logging import get_logger

logger = get_logger(__name__)

WHATSAPP_RATE_LIMIT = os.getenv("WHATSAPP_RATE_LIMIT", "30 per minute")

api = Namespace("whatsapp", description="WhatsApp send API")

notify_model = api.model(
    "WhatsAppNotification",
    {
        "apikey": fields.String(required=True),
        "self": fields.Boolean(
            default=False,
            description="If true, send to the paired device's own number (the operator).",
        ),
        "username": fields.String(
            description="OpenAlgo username — resolves to that user's linked WhatsApp number."
        ),
        "phone": fields.String(
            description="Single E.164 digit string to message directly (e.g. 919876543210)."
        ),
        "phones": fields.List(
            fields.String,
            description="Up to 5 E.164 digit strings for a small broadcast. "
            "Anything beyond 5 is dropped — WhatsApp ToS-safe usage.",
        ),
        "message": fields.String(description="Text body. Optional if image/document set."),
        "image_path": fields.String(description="Server-local path to an image file"),
        "document_path": fields.String(description="Server-local path to a document file"),
        "caption": fields.String(description="Caption for image / follow-up for document"),
        "filename": fields.String(description="Override document display name"),
        "wait_for_delivery": fields.Boolean(default=True),
    },
)


def _resolve_api_key(data: dict | None = None) -> str | None:
    if data is None:
        data = {}
    return data.get("apikey") or request.headers.get("X-API-KEY") or request.args.get("apikey")


def _auth_or_401(data: dict | None = None):
    api_key = _resolve_api_key(data)
    if not api_key or not verify_api_key(api_key):
        return make_response(
            jsonify({"status": "error", "message": "Invalid or missing API key"}), 401
        )
    return None


@api.route("/notify", strict_slashes=False)
class WhatsAppNotify(Resource):
    @limiter.limit(WHATSAPP_RATE_LIMIT)
    @api.doc(security="apikey")
    @api.expect(notify_model)
    def post(self):
        """Send a WhatsApp message — the single trader-facing send entry.

        Recipient (exactly one of):
            "self": true                — send to the paired device's own number
            "username": "<openalgo>"    — resolve via linked-users table
            "phone": "919876543210"     — direct E.164 digits
            "phones": ["a", "b", ...]   — small broadcast (up to 5 recipients)

        Payload — combine freely:
            "message": "..."            text body
            "image_path": "/path/png"   image attachment (caption falls back to message)
            "document_path": "/path/pdf"
            "caption": "..."
            "filename": "..."

        Fire-and-forget by default; set "wait_for_delivery": true to block
        and receive a per-recipient delivery report.
        """
        data = request.json or {}
        err = _auth_or_401(data)
        if err:
            return err

        # Hard precheck: refuse the send entirely if WhatsApp isn't ready.
        # We do NOT queue on not-paired — a caller is better off seeing a
        # clear "pair first" error than discovering hours later that their
        # alerts never went out. The /whatsapp admin UI is the only place
        # pairing happens.
        if not whatsapp_bot_service.is_ready():
            return make_response(
                jsonify(
                    {
                        "status": "error",
                        "message": (
                            "WhatsApp is not paired or not connected. Pair the device "
                            "first from the /whatsapp page in OpenAlgo before sending."
                        ),
                    }
                ),
                409,  # Conflict: server is in the wrong state for this operation
            )

        message = data.get("message")
        if message and len(message) > 4096:
            return make_response(
                jsonify({"status": "error", "message": "Message must not exceed 4096 characters"}),
                400,
            )

        raw_image_path = data.get("image_path")
        raw_document_path = data.get("document_path")
        caption = data.get("caption")
        filename = data.get("filename")
        # Default to synchronous delivery so the trader sees a real success /
        # failure report instead of a "Queued" lie. wars.send blocks <1s on
        # a connected session, well inside the 30s alert pool timeout. Set
        # wait_for_delivery=false explicitly for true fire-and-forget.
        wait_for_delivery = bool(data.get("wait_for_delivery", True))

        if not message and not raw_image_path and not raw_document_path:
            return make_response(
                jsonify(
                    {
                        "status": "error",
                        "message": "Provide at least one of: message, image_path, document_path",
                    }
                ),
                400,
            )

        # Resolve attachment paths against the configured allowlist. A bare
        # 400 with a generic message — we deliberately do NOT echo back why
        # a path was rejected (path leakage), nor the original path.
        image_path = validate_attachment_path(raw_image_path)
        document_path = validate_attachment_path(raw_document_path)
        if raw_image_path and not image_path:
            return make_response(
                jsonify({"status": "error", "message": "image_path is not allowed"}), 400
            )
        if raw_document_path and not document_path:
            return make_response(
                jsonify({"status": "error", "message": "document_path is not allowed"}), 400
            )

        targets: list[str] = []
        if data.get("self"):
            targets = []  # empty -> send_sync uses own_jid
        elif data.get("phones"):
            raw = data["phones"]
            if not isinstance(raw, list):
                return make_response(
                    jsonify({"status": "error", "message": "'phones' must be a list"}), 400
                )
            for p in raw[:5]:
                digits = normalize_phone(str(p))
                if digits:
                    targets.append(phone_to_jid(digits))
            if not targets:
                return make_response(
                    jsonify({"status": "error", "message": "No valid phones in list"}), 400
                )
        elif data.get("phone"):
            digits = normalize_phone(data["phone"])
            if not digits:
                return make_response(
                    jsonify({"status": "error", "message": "Invalid phone number"}), 400
                )
            targets = [phone_to_jid(digits)]
        elif data.get("username"):
            user = get_whatsapp_user_by_username(data["username"])
            if not user:
                return make_response(
                    jsonify(
                        {
                            "status": "error",
                            "message": "Username not found or not linked to WhatsApp",
                        }
                    ),
                    404,
                )
            targets = [user["whatsapp_jid"]]
        else:
            return make_response(
                jsonify(
                    {
                        "status": "error",
                        "message": (
                            "Specify one of: 'self', 'username', 'phone', or 'phones'"
                        ),
                    }
                ),
                400,
            )

        if wait_for_delivery:
            report = whatsapp_bot_service.send_sync(
                to=targets if targets else None,
                text=message,
                image=image_path,
                document=document_path,
                caption=caption,
                filename=filename,
            )
            return make_response(
                jsonify(
                    {
                        "status": "success",
                        "message": (
                            f"Delivered to {len(report['sent'])}, failed {len(report['failed'])}"
                        ),
                        "data": report,
                    }
                ),
                200,
            )

        recipients = targets or [""]  # empty -> self in send_alert_sync
        for jid in recipients:
            alert_executor.submit(
                whatsapp_alert_service.send_alert_sync,
                jid,
                message or caption or "",
                image_path,
                document_path,
            )
        return make_response(
            jsonify(
                {
                    "status": "success",
                    "message": f"Queued for {len(recipients)} recipient(s)",
                    "queued": len(recipients),
                }
            ),
            200,
        )
