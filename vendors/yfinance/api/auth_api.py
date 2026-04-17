def authenticate_vendor(api_key: str | None = None, api_secret: str | None = None):
    """yfinance is a public data source; no authentication required.

    Returns a constant sentinel token so callers that expect (token, error) tuples
    continue to work without special-casing anonymous vendors.
    """
    return "public", None
