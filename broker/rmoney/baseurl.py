"""RMoney broker base URLs configuration."""

# HostLookup URL for RMoney XTS
HOSTLOOKUP_URL = "https://xts.rmoneyindia.co.in:4000/hostlookup"

# Base URL for RMoney XTS Interactive API endpoints
BASE_URL = "https://xts.rmoneyindia.co.in:3000"

# Base URL for RMoney XTS Market Data API (binary market data)
# Uses the same host but the market data API path is /apibinarymarketdata
MARKET_DATA_BASE_URL = BASE_URL

# Derived URLs for specific API endpoints
MARKET_DATA_URL = f"{MARKET_DATA_BASE_URL}/apibinarymarketdata"
INTERACTIVE_URL = f"{BASE_URL}/interactive"
