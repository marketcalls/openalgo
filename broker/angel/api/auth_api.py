import json
import os

import httpx

from utils.httpx_client import get_httpx_client


def authenticate_broker(clientcode, broker_pin, totp_code):
    """
    Authenticate with the broker and return the auth token.
    """
    api_key = os.getenv("BROKER_API_KEY")

    try:
        # Get the shared httpx client
        client = get_httpx_client()

        payload = json.dumps({"clientcode": clientcode, "password": broker_pin, "totp": totp_code})
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
            "X-UserType": "USER",
            "X-SourceID": "WEB",
            "X-ClientLocalIP": "CLIENT_LOCAL_IP",  # Ensure these are handled or replaced appropriately
            "X-ClientPublicIP": "CLIENT_PUBLIC_IP",
            "X-MACAddress": "MAC_ADDRESS",
            "X-PrivateKey": api_key,
        }

        response = client.post(
            "https://apiconnect.angelone.in/rest/auth/angelbroking/user/v1/loginByPassword",
            headers=headers,
            content=payload,
        )

        # Add status attribute for compatibility with the existing codebase
        response.status = response.status_code

        data = response.text
        # Angel can return a NON-JSON body on some errors — e.g. an HTTP 403
        # rate-limit ("Access denied because of exceeding access rate"), or an F5
        # Web Application Firewall page ("Request Rejected … Your support ID is: …")
        # / a bare "not found" (HTTP 404) when the gateway blocks the caller's IP. A
        # bare json.loads() on that raises JSONDecodeError, which the caller surfaces
        # as the cryptic "Expecting value: line 1 column 1 (char 0)" — making a
        # broker-side block look like a credentials bug. Guard the parse and return a
        # clear, actionable message instead.
        try:
            data_dict = json.loads(data)
        except json.JSONDecodeError:
            body = (data or "").strip()
            waf = "request rejected" in body.lower() or "support id" in body.lower()
            if waf or response.status_code in (403, 404):
                msg = (
                    f"Angel rejected the login request (HTTP {response.status_code}) with a "
                    "non-JSON response — this is a gateway block (WAF / rate-limit / IP block), "
                    "not a credentials error. The server's public IP may be temporarily blocked "
                    "(often from repeated automated logins); try again from a different IP, the "
                    "block usually clears within a few hours."
                )
            else:
                msg = (
                    f"Angel returned a non-JSON login response (HTTP {response.status_code}): "
                    f"{body[:200]}"
                )
            return None, None, msg

        if "data" in data_dict and "jwtToken" in data_dict["data"]:
            # Return both JWT token and feed token if available (None if not)
            auth_token = data_dict["data"]["jwtToken"]
            feed_token = data_dict["data"].get("feedToken", None)
            return auth_token, feed_token, None
        else:
            return None, None, data_dict.get("message", "Authentication failed. Please try again.")
    except Exception as e:
        return None, None, str(e)
