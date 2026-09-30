import ipaddress
import logging
import os

from flask import request

logger = logging.getLogger(__name__)


def is_infrastructure_ip(ip_string):
    """Return True if *ip_string* is loopback, link-local, unspecified, or RFC1918/ULA.

    Banning these addresses from a Docker or reverse-proxy deployment can lock
    out every request that arrives via the container gateway (typically
    172.16/12) rather than the public client IP. Callers should refuse or
    require an explicit confirmation before writing such a ban.
    """
    if not ip_string:
        return False
    try:
        ip = ipaddress.ip_address(ip_string.strip())
    except ValueError:
        return False
    return bool(
        ip.is_loopback
        or ip.is_link_local
        or ip.is_unspecified
        or ip.is_private
        or ip.is_reserved
        or ip.is_multicast
    )
