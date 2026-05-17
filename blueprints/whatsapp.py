"""
WhatsApp blueprint — session-authenticated control endpoints consumed by the
React frontend.

Mirrors blueprints/telegram.py: the REST namespace at /api/v1/whatsapp serves
external API clients (auth via API key + rate limit), while these routes
serve the logged-in OpenAlgo admin user (auth via Flask session cookie).
The two share the same underlying service and database modules.
"""

from __future__ import annotations

import os

from flask import Blueprint, jsonify, request, session

from database.whatsapp_db import (
    delete_whatsapp_user,
    get_all_whatsapp_users,
    get_bot_config,
    get_command_stats,
    get_whatsapp_user_by_username,
    update_bot_config,
)
from limiter import limiter
from services.whatsapp_alert_service import alert_executor, whatsapp_alert_service
from services.whatsapp_bot_service import (
    WarsNotInstalled,
    normalize_phone,
    phone_to_jid,
    validate_attachment_path,
    whatsapp_bot_service,
)
from utils.logging import get_logger
from utils.session import check_session_validity

logger = get_logger(__name__)

WHATSAPP_MESSAGE_RATE_LIMIT = os.getenv("WHATSAPP_MESSAGE_RATE_LIMIT", "10 per minute")

whatsapp_bp = Blueprint("whatsapp_bp", __name__, url_prefix="/whatsapp")


# -------------------------------------------------------------------------
# Config
# -------------------------------------------------------------------------


@whatsapp_bp.route("/config", methods=["GET"])
@check_session_validity
def get_config():
    """Read bot config + runtime + pairing state in a single call so the
    React /whatsapp page can render everything from one fetch."""
    try:
        cfg = get_bot_config()
        cfg["is_running"] = whatsapp_bot_service.is_running
        return jsonify(
            {
                "status": "success",
                "data": {
                    "config": cfg,
                    "pair_state": whatsapp_bot_service.get_pair_state(),
                },
            }
        )
    except Exception:
        logger.exception("Failed to get WhatsApp config")
        return jsonify({"status": "error", "message": "Failed to get config"}), 500


@whatsapp_bp.route("/config", methods=["POST"])
@check_session_validity
def update_config():
    """Update non-secret config fields. Session blob is updated only via /pair."""
    try:
        data = request.json or {}
        updates: dict = {}
        for key in ("broadcast_enabled", "rate_limit_per_minute", "max_message_length"):
            if key in data:
                updates[key] = data[key]
        ok = update_bot_config(updates)
        return jsonify(
            {
                "status": "success" if ok else "error",
                "message": "Configuration updated" if ok else "Failed to update",
            }
        )
    except Exception as e:
        logger.exception("Failed to update WhatsApp config")
        return jsonify({"status": "error", "message": str(e)}), 500


# -------------------------------------------------------------------------
# Pair / unpair
# -------------------------------------------------------------------------


@whatsapp_bp.route("/pair", methods=["POST"])
@check_session_validity
def start_pair():
    """Kick off pairing. The QR code (and any pair-code) stream back to the
    frontend over SocketIO ('whatsapp_qr', 'whatsapp_pair_code',
    'whatsapp_paired', 'whatsapp_pair_status').

    Captures the logged-in OpenAlgo admin's identity (user_id + username) and
    stores it with the encrypted session blob. The bot uses owner_user_id
    at command-dispatch time to look up the api_key for SDK calls — there
    is no /link flow because there is no second user to authorize."""
    try:
        data = request.json or {}
        phone = normalize_phone(data.get("phone") or "") or None

        owner_username = session.get("user")
        owner_user_id = None
        if owner_username:
            try:
                from database.user_db import find_user_by_exact_username

                u = find_user_by_exact_username(owner_username)
                if u is not None:
                    owner_user_id = getattr(u, "id", None)
            except Exception:
                logger.exception("WhatsApp pair: owner lookup failed")

        ok, message = whatsapp_bot_service.start_pair(
            phone=phone,
            owner_user_id=owner_user_id,
            owner_username=owner_username,
        )
        return jsonify(
            {
                "status": "success" if ok else "error",
                "message": message,
                "data": whatsapp_bot_service.get_pair_state(),
            }
        ), (200 if ok else 400)
    except WarsNotInstalled as e:
        return jsonify({"status": "error", "message": str(e)}), 500
    except Exception as e:
        logger.exception("WhatsApp pair start failed")
        return jsonify({"status": "error", "message": str(e)}), 500


@whatsapp_bp.route("/pair/status", methods=["GET"])
@check_session_validity
def pair_status():
    """Polling endpoint for clients that can't use SocketIO."""
    return jsonify({"status": "success", "data": whatsapp_bot_service.get_pair_state()})


@whatsapp_bp.route("/unlink", methods=["POST"])
@check_session_validity
def unlink_device():
    ok, message = whatsapp_bot_service.unlink()
    return jsonify({"status": "success" if ok else "error", "message": message}), (
        200 if ok else 500
    )


# -------------------------------------------------------------------------
# Bot lifecycle
# -------------------------------------------------------------------------


@whatsapp_bp.route("/bot/start", methods=["POST"])
@check_session_validity
def start_bot():
    try:
        ok, message = whatsapp_bot_service.start_bot()
        return jsonify({"status": "success" if ok else "error", "message": message}), (
            200 if ok else 400
        )
    except WarsNotInstalled as e:
        return jsonify({"status": "error", "message": str(e)}), 500
    except Exception as e:
        logger.exception("WhatsApp bot start failed")
        return jsonify({"status": "error", "message": str(e)}), 500


@whatsapp_bp.route("/bot/stop", methods=["POST"])
@check_session_validity
def stop_bot():
    ok, message = whatsapp_bot_service.stop_bot()
    return jsonify({"status": "success" if ok else "error", "message": message}), (
        200 if ok else 500
    )


@whatsapp_bp.route("/bot/status", methods=["GET"])
@check_session_validity
def bot_status():
    try:
        cfg = get_bot_config()
        return jsonify(
            {
                "status": "success",
                "data": {
                    "is_running": whatsapp_bot_service.is_running,
                    "is_paired": cfg.get("is_paired", False),
                    "is_active": cfg.get("is_active", False),
                    "own_jid": cfg.get("own_jid"),
                    "own_phone": cfg.get("own_phone"),
                    "bot_username": cfg.get("bot_username"),
                    "paired_at": cfg.get("paired_at"),
                },
            }
        )
    except Exception as e:
        logger.exception("WhatsApp status failed")
        return jsonify({"status": "error", "message": str(e)}), 500


# -------------------------------------------------------------------------
# Linked users
# -------------------------------------------------------------------------


@whatsapp_bp.route("/users", methods=["GET"])
@check_session_validity
def list_users():
    try:
        users = get_all_whatsapp_users()
        return jsonify({"status": "success", "data": users, "count": len(users)})
    except Exception:
        logger.exception("Failed to list WhatsApp users")
        return jsonify({"status": "error", "message": "Failed to list users"}), 500


@whatsapp_bp.route("/user/<path:whatsapp_jid>/unlink", methods=["POST"])
@check_session_validity
def unlink_user(whatsapp_jid):
    """Soft-delete a linked recipient. JID is in URL because it contains '@'."""
    try:
        ok = delete_whatsapp_user(whatsapp_jid)
        return jsonify(
            {
                "status": "success" if ok else "error",
                "message": "User unlinked" if ok else "User not found",
            }
        ), (200 if ok else 404)
    except Exception as e:
        logger.exception("Failed to unlink WhatsApp user")
        return jsonify({"status": "error", "message": str(e)}), 500


# -------------------------------------------------------------------------
# Send / test
# -------------------------------------------------------------------------


@whatsapp_bp.route("/broadcast", methods=["POST"])
@check_session_validity
@limiter.limit(WHATSAPP_MESSAGE_RATE_LIMIT)
def broadcast():
    try:
        if not whatsapp_bot_service.is_ready():
            return jsonify(
                {
                    "status": "error",
                    "message": "WhatsApp is not paired. Pair the device first to send messages.",
                }
            ), 409
        data = request.json or {}
        message = data.get("message")
        filters = data.get("filters", {})
        if not message:
            return jsonify({"status": "error", "message": "Message is required"}), 400
        cfg = get_bot_config()
        if not cfg.get("broadcast_enabled", True):
            return jsonify({"status": "error", "message": "Broadcast is disabled"}), 403
        queued, skipped = whatsapp_alert_service.send_broadcast_alert(message, filters)
        return jsonify(
            {
                "status": "success",
                "message": f"Queued for {queued} users, skipped {skipped}",
                "queued": queued,
                "skipped": skipped,
            }
        )
    except Exception as e:
        logger.exception("WhatsApp broadcast failed")
        return jsonify({"status": "error", "message": str(e)}), 500


@whatsapp_bp.route("/test-message", methods=["POST"])
@check_session_validity
@limiter.limit(WHATSAPP_MESSAGE_RATE_LIMIT)
def test_message():
    """Send a test message — to the linked-user for the logged-in OpenAlgo
    admin if one exists, else to the first available user. Mirrors the
    telegram test-message UX so the React 'Send Test' button works the
    same way on both channels."""
    try:
        if not whatsapp_bot_service.is_ready():
            return jsonify(
                {
                    "status": "error",
                    "message": "WhatsApp is not paired. Pair the device first to send messages.",
                }
            ), 409
        username = session.get("user")
        if not username:
            return jsonify({"status": "error", "message": "Not logged in"}), 401

        target_jid: str | None = None
        wa_user = get_whatsapp_user_by_username(username)
        if wa_user:
            target_jid = wa_user["whatsapp_jid"]
            test_msg = "*Test from OpenAlgo*\nYour WhatsApp integration is working."
        else:
            all_users = get_all_whatsapp_users()
            if not all_users:
                return jsonify(
                    {
                        "status": "error",
                        "message": (
                            "No linked WhatsApp users. Ask a user to send /link <api_key> "
                            "to the bot first, or pair this number to receive admin alerts."
                        ),
                    }
                ), 404
            target_jid = all_users[0]["whatsapp_jid"]
            test_msg = (
                f"*Test from OpenAlgo (admin: {username})*\n"
                "Your WhatsApp integration is working."
            )

        alert_executor.submit(whatsapp_alert_service.send_alert_sync, target_jid, test_msg)
        return jsonify({"status": "success", "message": f"Test queued to {target_jid}"})
    except Exception as e:
        logger.exception("WhatsApp test-message failed")
        return jsonify({"status": "error", "message": str(e)}), 500


@whatsapp_bp.route("/send", methods=["POST"])
@check_session_validity
@limiter.limit(WHATSAPP_MESSAGE_RATE_LIMIT)
def send_to_phone():
    """Send a one-off message to any phone number (E.164 digits). Used by
    the React UI's 'send to number' input — doesn't require the recipient
    to be linked."""
    try:
        if not whatsapp_bot_service.is_ready():
            return jsonify(
                {
                    "status": "error",
                    "message": "WhatsApp is not paired. Pair the device first to send messages.",
                }
            ), 409
        data = request.json or {}
        phone = normalize_phone(data.get("phone") or "")
        message = data.get("message")
        raw_image_path = data.get("image_path")
        raw_document_path = data.get("document_path")
        if not phone:
            return jsonify({"status": "error", "message": "Phone number is required"}), 400
        if not message:
            return jsonify({"status": "error", "message": "Message is required"}), 400

        image_path = validate_attachment_path(raw_image_path)
        document_path = validate_attachment_path(raw_document_path)
        if raw_image_path and not image_path:
            return jsonify({"status": "error", "message": "image_path is not allowed"}), 400
        if raw_document_path and not document_path:
            return jsonify({"status": "error", "message": "document_path is not allowed"}), 400

        target_jid = phone_to_jid(phone)
        alert_executor.submit(
            whatsapp_alert_service.send_alert_sync,
            target_jid,
            message,
            image_path,
            document_path,
        )
        return jsonify({"status": "success", "message": f"Queued to {target_jid}"})
    except Exception as e:
        logger.exception("WhatsApp send-to-phone failed")
        return jsonify({"status": "error", "message": str(e)}), 500


# -------------------------------------------------------------------------
# Stats
# -------------------------------------------------------------------------


@whatsapp_bp.route("/stats", methods=["GET"])
@check_session_validity
def stats():
    try:
        days = min(max(int(request.args.get("days", 7)), 1), 365)
    except (TypeError, ValueError):
        days = 7
    return jsonify({"status": "success", "data": get_command_stats(days)})
