import os

from broker.nubra.api.baseurl import get_base_url, get_device_id, get_nubra_headers
from utils.httpx_client import get_httpx_client
from utils.logging import get_logger

logger = get_logger(__name__)

# Re-exported so existing importers of these names keep working; the hosts and
# the device id themselves live in baseurl.py.
__all__ = ["get_base_url", "get_device_id"]


def _error_message(data, fallback):
    """
    Extract the human-readable failure reason from a Nubra V3 error payload.

    V3's error shape is ``{"error": "...", "nubra_error_code": ""}`` and the
    docs say to surface the ``error`` string directly. Older/other responses
    use ``message``, so check both before falling back -- otherwise a precise
    server diagnosis ("TOTP is not enabled") gets replaced by a generic one.
    """
    if isinstance(data, dict):
        for key in ("error", "message"):
            value = data.get(key)
            if value:
                return str(value)
    return fallback


def _session_headers(session_token, device_id=None):
    """Authenticated V3 REST headers: Authorization + x-device-id."""
    return get_nubra_headers(session_token, device_id=device_id)


def _normalize_totp(totp_code):
    """
    Normalize a TOTP code to a clean, zero-padded 6-digit string.

    TOTP codes are 6-digit strings where a leading zero is significant
    (e.g. "012345"). Returns None if the input is not 1-6 digits.
    """
    s = str(totp_code).strip()
    if not s.isdigit() or not 1 <= len(s) <= 6:
        return None
    return s.zfill(6)


def _totp_login(client, base_url, device_id, phone, totp_str):
    """
    Call POST /totp/login, hedging the int-vs-string ambiguity for leading-zero
    codes.

    Nubra's docs show ``totp`` as a JSON integer, but ``int("012345")`` drops the
    leading zero -- which fails if the server compares the code as a string. For
    a leading-zero code we therefore try the documented integer first, then fall
    back to the zero-padded string (which is correct whether the server compares
    numerically or as a string). The TOTP stays valid within its 30s window, so
    the retry reuses the same live code.

    Returns:
        (response, data) for the first attempt that yields an auth_token, or the
        last attempt if none succeeded.
    """
    headers = {"Content-Type": "application/json", "x-device-id": device_id}

    candidates = [int(totp_str)]
    # Only a leading-zero code needs the string fallback (int repr differs).
    if totp_str != str(int(totp_str)):
        candidates.append(totp_str)

    last = None
    for totp_val in candidates:
        response = client.post(
            f"{base_url}/totp/login",
            # The V3 docs show an empty "otp" alongside the TOTP code.
            json={"phone": phone, "totp": totp_val, "otp": ""},
            headers=headers,
        )
        try:
            data = response.json()
        except ValueError:
            data = {}
        last = (response, data)
        if data.get("auth_token"):
            return response, data
    return last


def _verify_pin(client, base_url, device_id, auth_token, mpin):
    """
    POST /verifypin -- exchange the login auth_token for a session token.

    This final step is shared by the TOTP login flow and the phone-OTP flow.
    Do NOT send x-temp-token on this request.

    Returns:
        (session_token, error_message)
    """
    response = client.post(
        f"{base_url}/verifypin",
        json={"pin": mpin},
        headers=_session_headers(auth_token, device_id),
    )

    try:
        data = response.json()
    except ValueError:
        data = {}

    logger.debug(f"Nubra PIN verification response: {data}")

    if response.status_code != 200:
        return None, _error_message(data, "PIN verification failed")

    session_token = data.get("session_token")
    if not session_token:
        return None, "No session_token received from PIN verification"

    return session_token, None


def _get_credentials():
    """
    Read the Nubra login credentials from the environment.

    Returns:
        (phone, mpin, error_message)
    """
    phone = os.getenv("BROKER_API_KEY")  # Mobile number
    mpin = os.getenv("BROKER_API_SECRET")  # MPIN

    if not phone or not mpin:
        return None, None, (
            "Missing BROKER_API_KEY (phone) or BROKER_API_SECRET (mpin) in environment"
        )
    return phone, mpin, None


def request_login_otp():
    """
    Start a Nubra login by sending an OTP to the registered mobile number.

    This is the first half of the phone-OTP login: it runs both /sendphoneotp
    calls (the first mints a temp_token, the second actually dispatches the
    OTP) and hands back the final temp_token. Pass that token to
    authenticate_broker() together with the code the user received.

    OpenAlgo uses this rather than the TOTP flow because TOTP has to be
    enrolled on the Nubra account first, which their web terminal does not
    reliably expose.

    Returns:
        (temp_token, masked_phone, error_message)
    """
    phone, _mpin, error = _get_credentials()
    if error:
        return None, None, error

    masked = f"{phone[:5]}***{phone[-2:]}" if len(phone) > 7 else "***"

    try:
        # Step 1: open the login flow. For an account without TOTP this already
        # dispatches the SMS and comes back with next=VERIFY_MOBILE.
        data, error = send_phone_otp(phone, skip_totp=False)
        if error:
            logger.error(f"Nubra OTP request failed at step 1: {error}")
            return None, masked, error

        next_step = str(data.get("next", "")).upper()

        # Step 2 is ONLY for a TOTP-enrolled account (next=VERIFY_TOTP), where
        # skip_totp=true forces the SMS path instead. This mirrors the official
        # SDK's __send_otp branch. Calling it unconditionally replaces a token
        # bound to a live OTP challenge with one that is not, which
        # /verifyphoneotp then rejects as "unauthorized".
        if next_step == "VERIFY_TOTP":
            logger.info("Nubra account is TOTP-enrolled; forcing the SMS path (skip_totp=true)")
            data, error = send_phone_otp(phone, temp_token=data["temp_token"], skip_totp=True)
            if error:
                logger.error(f"Nubra OTP request failed at step 2: {error}")
                return None, masked, error
        elif next_step != "VERIFY_MOBILE":
            # The SDK treats any other next value as a hard error rather than
            # guessing at the flow.
            logger.error(f"Nubra returned an unexpected login step: {next_step!r}")
            return None, masked, f"Unexpected Nubra login step: {data.get('next')!r}"

        logger.info(f"Nubra login OTP sent to {masked} (next={data.get('next')!r})")
        return data["temp_token"], masked, None

    except Exception as e:
        logger.error(f"Nubra OTP request error: {str(e)}")
        return None, masked, str(e)


def authenticate_broker(otp_code, temp_token=None):
    """
    Authenticate with Nubra using the phone-OTP flow.

    Second half of the login started by request_login_otp():
    1. Verify the SMS OTP (/verifyphoneotp) to get an auth_token
    2. Verify the MPIN (/verifypin) to get the session token

    Args:
        otp_code: The OTP the user received by SMS
        temp_token: The temp_token returned by request_login_otp()

    Returns:
        tuple: (auth_token, feed_token, error_message)
               - auth_token: The session token for API calls
               - feed_token: None (Nubra doesn't return a separate feed token)
               - error_message: Error message if authentication failed
    """
    phone, mpin, error = _get_credentials()
    if error:
        return None, None, error

    if not temp_token:
        return None, None, (
            "Login session expired before the OTP was submitted. "
            "Start the Nubra login again from the broker page to request a new OTP."
        )

    otp_str = str(otp_code or "").strip()
    if not otp_str.isdigit():
        return None, None, "Invalid OTP: expected a numeric code"

    base_url = get_base_url()
    device_id = get_device_id()

    try:
        client = get_httpx_client()

        # Step 1: verify the OTP the user received by SMS
        logger.info(f"Nubra OTP login initiated for phone: {phone[:5]}***")

        auth_token, error_msg = verify_phone_otp(phone, otp_str, temp_token, device_id)
        if not auth_token:
            logger.error(f"Nubra OTP verification failed: {error_msg}")
            return None, None, error_msg

        # Step 2: verify the MPIN to get the session token
        logger.info("Nubra OTP verified, verifying PIN...")

        session_token, error_msg = _verify_pin(client, base_url, device_id, auth_token, mpin)
        if not session_token:
            logger.error(f"Nubra PIN verification failed: {error_msg}")
            return None, None, error_msg

        logger.info("Nubra authentication successful")

        # Return session_token as auth_token, no separate feed_token for Nubra
        return session_token, None, None

    except Exception as e:
        logger.error(f"Nubra authentication error: {str(e)}")
        return None, None, str(e)


def authenticate_broker_totp(totp_code):
    """
    Authenticate with Nubra using the TOTP flow.

    Not the default login path -- OpenAlgo logs in with phone-OTP via
    authenticate_broker() because TOTP must first be enrolled on the account.
    Enrolment is a one-time exchange of generate_totp_secret() followed by
    enable_totp(), both of which need a session token from a completed login.
    Once enrolled, this is the non-interactive alternative:

    1. Login via TOTP (/totp/login) with phone + TOTP code
    2. Verify PIN (/verifypin) with MPIN to get session token

    Args:
        totp_code: The TOTP code from authenticator app

    Returns:
        tuple: (auth_token, feed_token, error_message)
    """
    phone, mpin, error = _get_credentials()
    if error:
        return None, None, error

    # Normalize the TOTP up front so a leading-zero code (e.g. "012345") is not
    # silently mangled by int() later in the flow.
    totp_str = _normalize_totp(totp_code)
    if totp_str is None:
        return None, None, "Invalid TOTP code: expected a 6-digit numeric code"

    base_url = get_base_url()
    device_id = get_device_id()

    try:
        client = get_httpx_client()

        # Step 1: Login via TOTP (int per docs, with a string fallback for
        # leading-zero codes).
        logger.info(f"Nubra TOTP login initiated for phone: {phone[:5]}***")

        totp_response, totp_data = _totp_login(client, base_url, device_id, phone, totp_str)
        logger.info(f"Nubra TOTP login response status: {totp_response.status_code}")
        logger.info(f"Nubra TOTP login response data: {totp_data}")

        # Check for auth_token in response (success indicator)
        auth_token = totp_data.get("auth_token")
        if not auth_token:
            error_msg = _error_message(totp_data, "TOTP login failed")
            logger.error(f"Nubra TOTP login failed: {error_msg}")
            return None, None, error_msg

        logger.info(f"Nubra TOTP login successful, next step: {totp_data.get('next')}")

        # Step 2: Verify PIN to get session token
        logger.info("Nubra TOTP login successful, verifying PIN...")

        session_token, error_msg = _verify_pin(client, base_url, device_id, auth_token, mpin)
        if not session_token:
            logger.error(f"Nubra PIN verification failed: {error_msg}")
            return None, None, error_msg

        logger.info("Nubra authentication successful")

        # Return session_token as auth_token, no separate feed_token for Nubra
        return session_token, None, None

    except Exception as e:
        logger.error(f"Nubra authentication error: {str(e)}")
        return None, None, str(e)


# --- Phone-OTP login primitives ---------------------------------------------
#
# The four-step flow from the V3 "Nubra Auth Flow" section. This is OpenAlgo's
# default Nubra login: request_login_otp() drives the /sendphoneotp half and
# authenticate_broker() redeems the result.


def send_phone_otp(phone, temp_token=None, skip_totp=False, device_id=None):
    """
    POST /sendphoneotp -- steps 1 and 2 of the phone login flow.

    Call once with no ``temp_token`` to start the flow. Each call returns a
    fresh ``temp_token`` that supersedes the previous one.

    Matches Nubra's official Python SDK (``NubraSDK.__send_otp``): this
    endpoint is called with NO ``x-device-id`` -- the device id is only
    introduced at /verifyphoneotp -- and the payload carries a ``flow`` key
    alongside phone and skip_totp. ``device_id`` is accepted for signature
    symmetry with the other helpers but deliberately not sent.

    Returns:
        (data, error_message) -- ``data`` is the full response, whose useful
        fields are ``temp_token``, ``next``, ``message``, ``expiry`` and
        ``attempts_left``.
    """
    client = get_httpx_client()

    headers = {"Content-Type": "application/json"}
    if temp_token:
        headers["x-temp-token"] = temp_token

    response = client.post(
        f"{get_base_url()}/sendphoneotp",
        json={"phone": phone, "flow": "", "skip_totp": bool(skip_totp)},
        headers=headers,
    )

    try:
        data = response.json()
    except ValueError:
        data = {}

    if not data.get("temp_token"):
        return None, _error_message(data, f"sendphoneotp failed (HTTP {response.status_code})")

    logger.info(
        f"Nubra sendphoneotp(skip_totp={bool(skip_totp)}): message={data.get('message')!r} "
        f"next={data.get('next')!r} expiry={data.get('expiry')} "
        f"attempts_left={data.get('attempts_left')}"
    )
    return data, None


def verify_phone_otp(phone, otp, temp_token, device_id=None):
    """
    POST /verifyphoneotp -- step 3, exchange the SMS OTP for an auth_token.

    Returns:
        (auth_token, error_message)
    """
    client = get_httpx_client()

    response = client.post(
        f"{get_base_url()}/verifyphoneotp",
        json={"phone": phone, "otp": str(otp)},
        headers={
            "Content-Type": "application/json",
            "x-temp-token": temp_token,
            "x-device-id": device_id or get_device_id(),
        },
    )

    try:
        data = response.json()
    except ValueError:
        data = {}

    auth_token = data.get("auth_token")
    if not auth_token:
        # Log the raw payload: "unauthorized" here means the temp_token was
        # rejected (stale, superseded, or issued under a different device id),
        # which is a different fix from a plain wrong-OTP rejection.
        logger.error(
            f"Nubra verifyphoneotp rejected (HTTP {response.status_code}), "
            f"device_id={device_id or get_device_id()!r}, "
            f"temp_token={'...' + str(temp_token)[-8:] if temp_token else None}, "
            f"payload={data}"
        )
        return None, _error_message(data, f"verifyphoneotp failed (HTTP {response.status_code})")

    return auth_token, None


def login_with_phone_otp(phone, mpin, otp_prompt, device_id=None):
    """
    Run the full phone-OTP login and return a session token.

    ``otp_prompt`` is a zero-argument callable returning the OTP the user
    received by SMS -- kept as a callback so this function stays usable from a
    CLI, a web handler, or a test.

    Returns:
        (session_token, error_message)
    """
    base_url = get_base_url()
    device_id = device_id or get_device_id()
    client = get_httpx_client()

    # Steps 1-2: dispatch the OTP and get the token to redeem it with
    temp_token, _masked, error = request_login_otp()
    if error:
        return None, error

    # Step 3: verify the OTP the user received
    auth_token, error = verify_phone_otp(phone, otp_prompt(), temp_token, device_id)
    if error:
        return None, error

    # Step 4: verify the MPIN to get the final session token
    return _verify_pin(client, base_url, device_id, auth_token, mpin)


# --- TOTP management --------------------------------------------------------


def generate_totp_secret(session_token, device_id=None):
    """
    GET /totp/generate-secret -- create a TOTP secret for the logged-in account.

    Returns:
        (data, error_message) where data is {"secret_key": ..., "qr_image": ...}.
        ``qr_image`` is a ``data:image/png;base64,...`` URI.

    The secret must be added to an authenticator app before calling
    enable_totp() with a live code from that app.
    """
    client = get_httpx_client()

    response = client.get(
        f"{get_base_url()}/totp/generate-secret",
        headers=_session_headers(session_token, device_id),
    )

    try:
        payload = response.json()
    except ValueError:
        payload = {}

    data = payload.get("data")
    if not isinstance(data, dict) or not data.get("secret_key"):
        return None, _error_message(payload, f"generate-secret failed (HTTP {response.status_code})")

    return data, None


def enable_totp(session_token, mpin, totp_code, device_id=None):
    """
    POST /totp/enable -- turn on TOTP login for the account.

    Requires a session token from a completed login plus the MPIN and a live
    code from the authenticator app the secret was added to.

    Returns:
        (True, None) on success, or (False, error_message).
    """
    totp_str = _normalize_totp(totp_code)
    if totp_str is None:
        return False, "Invalid TOTP code: expected a 6-digit numeric code"

    client = get_httpx_client()

    response = client.post(
        f"{get_base_url()}/totp/enable",
        json={"mpin": str(mpin), "totp": totp_str},
        headers=_session_headers(session_token, device_id),
    )

    try:
        data = response.json()
    except ValueError:
        data = {}

    if response.status_code in (200, 201):
        logger.info(f"Nubra TOTP enable: {data.get('message')}")
        return True, None

    return False, _error_message(data, f"totp/enable failed (HTTP {response.status_code})")


def disable_totp(session_token, mpin, device_id=None):
    """
    POST /totp/disable -- turn off TOTP login for the account.

    Returns:
        (True, None) on success, or (False, error_message).
    """
    client = get_httpx_client()

    response = client.post(
        f"{get_base_url()}/totp/disable",
        json={"mpin": str(mpin)},
        headers=_session_headers(session_token, device_id),
    )

    try:
        data = response.json()
    except ValueError:
        data = {}

    if response.status_code in (200, 201):
        logger.info(f"Nubra TOTP disable: {data.get('message')}")
        return True, None

    return False, _error_message(data, f"totp/disable failed (HTTP {response.status_code})")


# --- Session metadata -------------------------------------------------------


def get_user_info(session_token, device_id=None):
    """
    GET /userinfo -- session metadata including the realtime WebSocket URLs.

    ``env_info.user_ws_url`` is the order-update stream and
    ``env_info.market_ws_url`` the market-data stream. These are environment
    specific, so they must be read from here rather than hardcoded.

    Returns:
        (payload, error_message)
    """
    client = get_httpx_client()

    # A transport failure here must not escape: the order-update adapter calls
    # this at startup purely to discover its WebSocket URL, and an unreachable
    # /userinfo should fall back to the configured default rather than stop the
    # stream from starting at all.
    try:
        response = client.get(
            f"{get_base_url()}/userinfo",
            headers=_session_headers(session_token, device_id),
        )
    except Exception as e:
        logger.warning(f"Nubra /userinfo request failed: {e}")
        return None, f"userinfo request failed: {e}"

    try:
        payload = response.json()
    except ValueError:
        payload = {}

    if response.status_code != 200 or not isinstance(payload, dict):
        return None, _error_message(payload, f"userinfo failed (HTTP {response.status_code})")

    return payload, None


def validate_static_ip(session_token, device_id=None):
    """
    GET /ipaddress/validate -- check the outbound IP against the account's
    registered static IPs.

    This only *verifies*; there is no V3 endpoint to register a static IP --
    that is done on Nubra's side. Accounts with no registered IPs get an error
    payload instead of a match result, which is itself the signal that static
    IP access is not configured.

    Requires a session token from either login path (TOTP or phone-OTP) -- the
    endpoint does not care which produced it.

    Returns:
        (payload, error_message) where payload includes ``is_matched``,
        ``current_ip_address``, ``primary_ip_address`` and
        ``secondary_ip_address``.
    """
    client = get_httpx_client()

    response = client.get(
        f"{get_base_url()}/ipaddress/validate",
        headers=get_nubra_headers(session_token, with_json=False, device_id=device_id),
    )

    try:
        payload = response.json()
    except ValueError:
        payload = {}

    if not isinstance(payload, dict):
        return None, f"ipaddress/validate failed (HTTP {response.status_code})"

    # No static IPs registered -> {"error": "...", "nubra_error_code": ""}
    if payload.get("error"):
        return None, payload["error"]

    if "is_matched" not in payload:
        return None, _error_message(payload, f"ipaddress/validate failed (HTTP {response.status_code})")

    if not payload.get("is_matched"):
        logger.warning(
            f"Nubra static IP mismatch: outbound {payload.get('current_ip_address')} "
            f"is not the registered primary/secondary IP"
        )

    return payload, None


def get_ws_urls(session_token, device_id=None):
    """
    Resolve (user_ws_url, market_ws_url) for the current session.

    Returns (None, None) if /userinfo is unavailable so callers can fall back
    to their configured default.
    """
    payload, error = get_user_info(session_token, device_id)
    if error or not payload:
        logger.warning(f"Nubra /userinfo unavailable: {error}")
        return None, None

    env_info = payload.get("env_info") or {}
    return env_info.get("user_ws_url"), env_info.get("market_ws_url")
