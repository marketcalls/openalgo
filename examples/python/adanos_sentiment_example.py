"""
Example: fetch optional Adanos market sentiment through your OpenAlgo instance.
"""

from __future__ import annotations

import requests

OPENALGO_HOST = "http://127.0.0.1:5000"
OPENALGO_API_KEY = "replace-with-your-openalgo-apikey"

payload = {
    "apikey": OPENALGO_API_KEY,
    "tickers": ["AAPL", "TSLA", "NVDA"],
    "source": "all",
    "days": 7,
}

response = requests.post(
    f"{OPENALGO_HOST}/api/v1/market/sentiment",
    json=payload,
    timeout=15,
)
response.raise_for_status()

data = response.json()
print("Status:", data["status"])
print("Enabled:", data["data"]["enabled"])
print("Summary:")
print(data["data"]["summary"])
