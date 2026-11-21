import re
from urllib.parse import unquote, urlsplit

# C0 controls and DEL. A CR/LF here could smuggle an extra header into the
# redirect response; none of them belong in a same-origin path.
_CONTROL_CHARS = re.compile(r"[\x00-\x1f\x7f]")

_ALLOWED_ABSOLUTE_SCHEMES = {"http", "https"}


def safe_local_redirect_target(candidate: str | None, fallback: str, host: str) -> str:
    """Resolve an untrusted redirect target to a safe, same-origin path.

    The CSRF and admin rate-limit error handlers redirect back to
    ``request.referrer`` on the assumption that the referrer is always a
    same-origin page the user just came from. That assumption doesn't hold:
    the Referer header is attacker-controlled on any request the attacker
    crafts directly, so redirecting to it unchecked turns an error path into
    an open redirect that can support phishing.

    A real browser's Referer is always a full absolute URL, so this accepts
    one whose host matches ``host`` (scheme differences are not treated as
    cross-origin here) as well as a bare same-origin path. Anything else - a
    different host, a protocol-relative ``//host`` target, a backslash
    variant of one (``/\\host``, which several browsers still normalize to
    ``//host``), or a percent-encoded form of any of those - falls back to
    ``fallback``.

    Args:
        candidate: The untrusted target, typically ``request.referrer``.
        fallback: The internal URL to use when ``candidate`` is missing or
            isn't a safe same-origin target.
        host: The current request's host (``request.host``), used to decide
            whether an absolute ``candidate`` is same-origin.

    Returns:
        A same-origin absolute path (scheme and host stripped) derived from
        ``candidate``, or ``fallback``.
    """
    if not candidate:
        return fallback

    # The Referer header can itself be percent-encoded, so a bypass like
    # "/%2F%2Fevil.com" must be judged on what it decodes to, not on its
    # encoded shape.
    decoded = unquote(candidate.strip())
    if not decoded or _CONTROL_CHARS.search(decoded):
        return fallback

    # Normalize backslashes to forward slashes before parsing, closing the
    # "/\evil.com" bypass some browsers still treat like "//evil.com". A real
    # Referer is never protocol-relative, so treat any leading "//" as unsafe
    # outright rather than trying to resolve it against `host`.
    normalized = decoded.replace("\\", "/")
    if normalized.startswith("//"):
        return fallback

    try:
        parts = urlsplit(normalized)
    except ValueError:
        return fallback

    scheme = parts.scheme.lower()
    if scheme:
        # An absolute URL must both use http(s) and explicitly name our own
        # host - "https:///evil.com" (empty authority) is rejected here too,
        # not treated as schemeless. `netloc` never carries userinfo for a
        # genuine same-origin URL, so a trick like "http://host@evil.com/"
        # (netloc "host@evil.com") also fails this comparison.
        if scheme not in _ALLOWED_ABSOLUTE_SCHEMES or parts.netloc.lower() != host.lower():
            return fallback
    elif parts.netloc:
        # Reachable only for a malformed edge case the "//" check above
        # didn't already catch; treat as unsafe rather than guess.
        return fallback

    path = parts.path or "/"
    if not path.startswith("/"):
        return fallback

    local = path
    if parts.query:
        local += f"?{parts.query}"
    if parts.fragment:
        local += f"#{parts.fragment}"
    return local
