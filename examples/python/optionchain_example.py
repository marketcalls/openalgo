from openalgo import api

# Initialize client
client = api(
    api_key="83ad96143dd5081d033abcfd20e9108daee5708fbea404121a762bed1e498dd0",
    host="http://127.0.0.1:5000"
)

# -------------------------------------------------------
# Get available expiry dates for NIFTY
# -------------------------------------------------------
expiry_result = client.expiry(
    symbol="NIFTY",
    exchange="NFO",
    instrumenttype="options",
    strike_count= 10
)

if expiry_result["status"] == "success":
    print("Available NIFTY Expiries:")
    for exp in expiry_result["data"]:
        print(f"  {exp}")
else:
    print("Failed to fetch expiries :", expiry_result.get("message"))

# -------------------------------------------------------
# Get option chain (5 strikes around ATM)
# -------------------------------------------------------
chain = client.optionchain(
    underlying="NIFTY",
    exchange="NSE_INDEX",
    expiry_date="30DEC25",
    strike_count=5
)

print("\nNIFTY Option Chain (5 strikes around ATM):")
print("-" * 50)
print(chain)
print("-" * 50)
print("Strike  | CE LTP (Label) | PE LTP (Label)")

if chain["status"] == "success":
    print(f"\nUnderlying LTP: {chain['underlying_ltp']}")
    print(f"ATM Strike: {chain['atm_strike']}")

    print("\nStrike  | CE LTP (Label) | PE LTP (Label)")
    print("-" * 50)

    for item in chain["chain"]:
        ce = item.get("ce") or {}
        pe = item.get("pe") or {}

        print(
            f"{item['strike']:>7} | "
            f"{ce.get('ltp', '-'):>6} ({ce.get('label', '-'):>4}) | "
            f"{pe.get('ltp', '-'):>6} ({pe.get('label', '-'):>4})"
        )
else:
    print("Failed to fetch option chain :", chain.get("message"))
