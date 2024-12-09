from openalgo import api

# Initialize the API client
client = api(api_key='38f99d7d226cc0c3baa19dcacf0b1f049d2f68371da1dda2c97b1b63a3a9ca2e', host='http://127.0.0.1:5000')

# Fetch historical data for BHEL
df = client.history(
    symbol="BHEL",
    exchange="NSE",
    interval="5m",
    start_date="2024-11-01",
    end_date="2024-12-31"
)

# Display the fetched data
print(df)

# print(type(df))
# print(df.shape)
# print(df.index)

# print(df.head())
# print(df.columns)
