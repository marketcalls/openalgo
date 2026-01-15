import sys
import os
# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from openalgo import api
import pandas as pd
from datetime import datetime, timedelta

# Test the history API to see the response format
client = api(api_key="56c3dc6ba7d9c9df478e4f19ffc5d3e15e1dd91b5aa11e91c910f202c91eff9d", host="http://127.0.0.1:5000")

# Get history data
end_date = datetime.now()
start_date = end_date - timedelta(days=5)

response = client.history(
    symbol="RELIANCE",
    exchange="NSE",
    interval="5m",
    start_date=start_date.strftime("%Y-%m-%d"),
    end_date=end_date.strftime("%Y-%m-%d")
)

print("History API Response Type:", type(response))

if isinstance(response, pd.DataFrame):
    print("\nResponse is a DataFrame!")
    print("Shape:", response.shape)
    print("Columns:", list(response.columns))
    print("\nFirst 5 rows:")
    print(response.head())
elif isinstance(response, dict):
    print("\nResponse is a dictionary with keys:", response.keys())
    if 'data' in response:
        data = response['data']
        print("Data type:", type(data))
        if isinstance(data, pd.DataFrame):
            print("Data is a DataFrame with columns:", list(data.columns))
else:
    print("Unexpected response type:", type(response))