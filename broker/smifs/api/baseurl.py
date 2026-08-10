import os

# SMIFS God Quant REST base. Sandbox and live are the same host; the venue
# is a per-account flag on the SMIFS side, so no URL change is needed to go live.
BASE_URL = os.getenv("SMIFS_BASE_URL", "https://smifsgq.smifs.com").rstrip("/")


def get_url(endpoint):
    if not endpoint.startswith("/"):
        endpoint = "/" + endpoint
    return BASE_URL + endpoint
