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
from database.whatsapp_db import get_bot_config, get_whatsapp_user_by_username
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


def _is_paired_owner(username: str) -> bool:
    """Whether this username is the operator who paired the device.

    Read from ``whatsapp_config``, which records ``owner_username`` at pair
    time, rather than from the linked-users table, which is a different fact:
    that table says who has messaged the bot, and the operator of a single
    user install has no reason to have done so.
    """
    if not username:
        return False
    try:
        config = get_bot_config() or {}
    except Exception:
        logger.exception("Could not read the WhatsApp bot config")
        return False
    owner = (config.get("owner_username") or "").strip()
    return bool(owner) and owner.casefold() == str(username).strip().casefold()


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
            if user:
                targets = [user["whatsapp_jid"]]
            elif _is_paired_owner(data["username"]):
                # The operator who paired this device, asking for themselves.
                #
                # OpenAlgo is single user, and the rest of this bot already
                # treats the paired operator as the identity: the command
                # handlers look their api_key up from the owner recorded at
                # pair time precisely "so the operator never has to /link or
                # paste credentials from the phone"
                # (whatsapp_bot_service._sdk_client_for_owner).
                #
                # This route did not follow that rule. It resolved a username
                # only through the linked-users table, which is filled by a
                # phone sending /link, so an operator who had paired their
                # device and never messaged the bot was told their own
                # username was "not found or not linked" while the /whatsapp
                # page showed the device paired. A chart alert asking for the
                # logged-in user hit exactly that.
                #
                # An empty target list is the self recipient, the same one
                # "self": true uses.
                targets = []
            else:
                return make_response(
                    jsonify(
                        {
                            "status": "error",
                            "message": "Username not found or not linked to WhatsApp",
                        }
                    ),
                    404,
                )
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
            # **A send that reached nobody is not a success.**
            #
            # This answered "status": "success" whatever the report said, so
            # "Delivered to 0, failed 1" went back under the same status as a
            # message that arrived. Every caller keys on the status: the chart
            # alert in /trading records the channel as accepted and the trader
            # is told the alert went out, which is the one outcome worse than a
            # refusal. The failure text is already written for a trader, so it
            # is carried up as the message rather than summarised away.
            delivered = len(report["sent"])
            refused = len(report["failed"])
            if delivered == 0 and refused > 0:
                first = report["failed"][0]
                said = first.get("error") if isinstance(first, dict) else None
                return make_response(
                    jsonify(
                        {
                            "status": "error",
                            "message": said or "The message could not be delivered.",
                            "data": report,
                        }
                    ),
                    # **200, deliberately, and this is the compatibility line.**
                    #
                    # The lie worth fixing is the `status` field: a report of
                    # "Delivered to 0, failed 1" came back as "success", and
                    # every caller branches on that, including the chart alert
                    # in /trading which then recorded the channel as accepted.
                    # That field is now truthful.
                    #
                    # The HTTP code is left alone. This endpoint is public and
                    # has a large installed base of callers nobody here can
                    # survey, and a code they have never seen from this path is
                    # a new failure mode for anything that raises on non-2xx or
                    # retries on 5xx. Those callers were mishandling a wrong
                    # `status`; they should not also have to handle a new
                    # transport error to keep working. The request itself was
                    # accepted and processed, which is what 200 says, and what
                    # happened to it is in the body, which is where this API
                    # puts every other outcome.
                    200,
                )
            return make_response(
                jsonify(
                    {
                        # Some arrived and some did not: still a success for the
                        # ones that did, and the report names the rest.
                        "status": "success",
                        "message": f"Delivered to {delivered}, failed {refused}",
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
