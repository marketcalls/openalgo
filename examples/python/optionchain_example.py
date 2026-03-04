import time

from openalgo import api

# Initialize client
client = api(
    api_key="fb77b2df614f43f607c3cd7543200a3d0b7f8e133701ed40bebeceb901b4d440",
    host="http://127.0.0.1:3300",
)

# -------------------------------------------------------
# Get available expiry dates for NIFTY
# Note: strike_count is NOT a valid parameter for expiry()
#       it belongs to optionchain() only.
# -------------------------------------------------------
t0 = time.perf_counter()
expiry_result = client.expiry(
    symbol="NIFTY", exchange="NFO", instrumenttype="options"
)
expiry_elapsed = time.perf_counter() - t0

if expiry_result["status"] == "success":
    print(f"Available NIFTY Expiries: (fetched in {expiry_elapsed:.3f}s)")
    for exp in expiry_result["data"]:
        print(f"  {exp}")
else:
    print("Failed to fetch expiries :", expiry_result.get("message"))

print()

# -------------------------------------------------------
# Get option chain (strikes around ATM)
# -------------------------------------------------------
t1 = time.perf_counter()
chain = client.optionchain(
    underlying="NIFTY", exchange="NSE_INDEX", expiry_date="10MAR26", strike_count=15
)
chain_elapsed = time.perf_counter() - t1

print(f"NIFTY Option Chain fetched in {chain_elapsed:.3f}s")
print("-" * 50)

if chain["status"] == "success":
    print(f"Underlying LTP: {chain['underlying_ltp']}")
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

# -------------------------------------------------------
# Summary
# -------------------------------------------------------
total_elapsed = expiry_elapsed + chain_elapsed
print()
print("=" * 50)
print(f"  Expiry fetch : {expiry_elapsed:.3f}s")
print(f"  Chain fetch  : {chain_elapsed:.3f}s")
print(f"  Total        : {total_elapsed:.3f}s")
print("=" * 50)
