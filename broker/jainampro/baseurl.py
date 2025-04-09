"""Jainam Pro broker base URLs configuration."""
import json
import requests
from utils.httpx_client import get_httpx_client

# Constants for hostlookup
HOSTLOOKUP_URL = "http://ctrade.jainam.in:4000/hostlookup"
ACCESS_PASSWORD = "2021HostLookUpAccess"
VERSION = "interactive_1.0.1"

# Function to get hostlookup response with connectionString and uniqueKey
def get_hostlookup_response():
    try:
        client = get_httpx_client()
        payload = {
            "AccessPassword": ACCESS_PASSWORD,
            "version": VERSION
        }
        headers = {"Content-Type": "application/json"}
        
        response = client.post(HOSTLOOKUP_URL, json=payload, headers=headers)
        print(f"Hostlookup response code: {response.status_code}")
        
        if response.status_code == 200:
            result = response.json()
            print(f"Hostlookup result: {result}")
            if result.get("type") == True and "result" in result:
                connection_string = result["result"]["connectionString"]
                unique_key = result["result"]["uniqueKey"]
                return connection_string, unique_key, None
        # Return fallback values if fetch fails
        print("Failed to fetch from hostlookup endpoint, using fallback values")
        return "http://ctrade.jainam.in:4100", None, "Hostlookup failed"
    except Exception as e:
        print(f"Error in hostlookup: {str(e)}")
        return "http://ctrade.jainam.in:4100", None, f"Error: {str(e)}"

# Get connection string and unique key from hostlookup
BASE_URL, UNIQUE_KEY, HOSTLOOKUP_ERROR = get_hostlookup_response()

# Print for debugging
print(f"Base URL set to: {BASE_URL}")
print(f"Unique Key available: {UNIQUE_KEY is not None}")

# Define URLs for different API endpoints
MARKET_DATA_URL = BASE_URL  # Used for market data endpoints
INTERACTIVE_URL = BASE_URL   # Used for interactive endpoints like user/session
