from openalgo import api
from apscheduler.schedulers.background import BackgroundScheduler
import pytz
import time

print("🔁 OpenAlgo Python Bot is running.")

# ===============================
# OpenAlgo Client
# ===============================
client = api(
    api_key="83ad96143dd5081d033abcfd20e9108daee5708fbea404121a762bed1e498dd0",
    host="http://127.0.0.1:5000"
)

NIFTY_LOT = 75    # NSE Index lot size
LOTS = 1          # Number of lots


# ===============================
# Function to Place Straddle
# ===============================
def place_nifty_straddle_0920():
    try:
        # Fetch NIFTY INDEX Quote (must print immediately)
        quote = client.quotes(symbol="NIFTY", exchange="NSE_INDEX")
        print("NIFTY QUOTE:", quote)

        qty = LOTS * NIFTY_LOT

        # Place optionsmultiorder short straddle
        response = client.optionsmultiorder(
            strategy="NIFTY_09DEC25_STRADDLE_0920",
            underlying="NIFTY",
            exchange="NSE_INDEX",
            expiry_date="09DEC25",    # FIXED EXPIRY
            legs=[
                {"offset": "ATM", "option_type": "CE", "action": "SELL", "quantity": qty, "product": "NRML"},
                {"offset": "ATM", "option_type": "PE", "action": "SELL", "quantity": qty, "product": "NRML"}
            ]
        )

        print("ORDER RESPONSE:", response)

    except Exception as e:
        print("Error:", e)


# ===============================
# Schedule the Job at 09:20 IST
# ===============================
def schedule_straddle():
    ist = pytz.timezone("Asia/Kolkata")

    scheduler = BackgroundScheduler(timezone=ist)

    scheduler.add_job(
        place_nifty_straddle_0920,
        trigger="cron",
        day_of_week="mon-sun",
        hour=09,
        minute=20,
        id="nifty_0920_straddle"
    )

    scheduler.start()
    print("✅ Scheduled NIFTY 09DEC25 ATM Straddle for 09:20 IST (Mon–Sun).")

    return scheduler


if __name__ == "__main__":
    scheduler = schedule_straddle()

    # Keep script alive
    try:
        while True:
            time.sleep(1)
    except (KeyboardInterrupt, SystemExit):
        scheduler.shutdown()
