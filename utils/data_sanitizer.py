"""
Data sanitization utility for redacting sensitive information before storage.

This module provides functions to redact sensitive fields like API keys, passwords,
tokens, and secrets from data structures before they are persisted to databases or logs.
"""

import copy


def redact_sensitive_data(data):
    """
    Redact sensitive fields from data before storage.

    This function recursively searches through dictionaries and lists to find
    and redact sensitive fields. It creates a deep copy of the data structure
    to avoid modifying the original.

    Sensitive fields that are redacted:
    - apikey
    - password
    - token
    - secret
    - authorization
    - auth

    Args:
        data: The data structure to sanitize (dict, list, or other)

    Returns:
        A sanitized copy of the data with sensitive fields redacted
    """
    # Handle None/empty cases
    if data is None:
        return None

    # Define sensitive field names (case-insensitive matching)
    sensitive_fields = {'apikey', 'password', 'token', 'secret', 'authorization', 'auth'}

    # Create a deep copy to avoid modifying the original
    sanitized = copy.deepcopy(data)

    # Recursively redact sensitive fields
    return _redact_recursive(sanitized, sensitive_fields)


def _redact_recursive(obj, sensitive_fields):
    """
    Recursively redact sensitive fields in nested data structures.

    Args:
        obj: The object to sanitize (modified in place)
        sensitive_fields: Set of field names to redact

    Returns:
        The sanitized object
    """
    if isinstance(obj, dict):
        for key, value in obj.items():
            # Check if this key is sensitive (case-insensitive)
            if key.lower() in sensitive_fields:
                obj[key] = "[REDACTED]"
            # Recursively process nested structures
            elif isinstance(value, (dict, list)):
                obj[key] = _redact_recursive(value, sensitive_fields)

    elif isinstance(obj, list):
        for i, item in enumerate(obj):
            if isinstance(item, (dict, list)):
                obj[i] = _redact_recursive(item, sensitive_fields)

    return obj
