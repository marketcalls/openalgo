from openalgo import api

print("🔁 OpenAlgo Python Bot is running.")

# ------------------------------------------
# Initialize API client
# ------------------------------------------
client = api(
    api_key="83ad96143dd5081d033abcfd20e9108daee5708fbea404121a762bed1e498dd0",
    host="http://127.0.0.1:5000"
)

# ------------------------------------------
# Fetch NIFTY Spot (must print immediately)
# ------------------------------------------
quote = client.quotes(symbol="NIFTY", exchange="NSE_INDEX")
print("NIFTY QUOTE:", quote)

# ------------------------------------------
# Place NIFTY ATM Option Order - 09DEC25
# ------------------------------------------
response = client.optionsorder(
      strategy="python",
      underlying="NIFTY",          # Underlying Index
      exchange="NSE_INDEX",        # Index exchange
      expiry_date="09DEC25",       # Correct expiry
      offset="OTM2",                # Auto-select ATM strike
      option_type="CE",            # CE or PE
      action="BUY",                # BUY or SELL
      quantity=75,                 # 1 Lot = 75
      pricetype="MARKET",          # MARKET or LIMIT
      product="NRML",              # NRML or MIS
      splitsize=0                  # 0 = no split
)

print("ORDER RESPONSE:", response)
