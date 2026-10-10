"""Security response headers for credential-bearing endpoints."""

from flask import make_response


def no_store_response(*args, **kwargs):
    """Build a Flask JSON response that prevents intermediary caching.

    Use this for responses that carry decrypted API keys, tokens, or other
    credential material that must never be stored by browsers, proxies, or
    debugging caches.

    Accepts the same arguments as ``flask.jsonify``.
    """
    resp = make_response(*args, **kwargs)
    resp.headers["Cache-Control"] = "no-store, max-age=0"
    resp.headers["Pragma"] = "no-cache"
    return resp
