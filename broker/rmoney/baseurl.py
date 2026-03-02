"""RMoney broker base URLs configuration."""

# HostLookup URL for RMoney (Symphony XTS)
HOSTLOOKUP_URL = "https://xts.rmoneyindia.co.in:4000/hostlookup"

# Base URL for RMoney XTS API endpoints
BASE_URL = "https://xts.rmoneyindia.co.in:3000"

# Derived URLs for specific API endpoints
MARKET_DATA_URL = f"{BASE_URL}/apimarketdata"
INTERACTIVE_URL = f"{BASE_URL}/interactive"
