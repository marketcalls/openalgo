import pandas as pd
import logging
import os
import time
import gc
from openalgo import api
from datetime import datetime, timedelta

# Initialize the API client
client = api(api_key='your_api_key_here', host='http://127.0.0.1:5000')

# Path to the CSV file
symbols_file = "symbols.csv"
output_folder = "symbols"
checkpoint_file = "checkpoint.txt"

# Create the output folder if it doesn't exist
os.makedirs(output_folder, exist_ok=True)

# Set up logging
logging.basicConfig(
    filename="data_download.log",
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)

# Function to get start date based on user selection
def get_date_range(option):
    today = datetime.now()
    if option == 1:
        return today.strftime("%Y-%m-%d"), today.strftime("%Y-%m-%d")
    elif option == 2:
        return (today - timedelta(days=5)).strftime("%Y-%m-%d"), today.strftime("%Y-%m-%d")
    elif option == 3:
        return (today - timedelta(days=30)).strftime("%Y-%m-%d"), today.strftime("%Y-%m-%d")
    elif option == 4:
        return (today - timedelta(days=90)).strftime("%Y-%m-%d"), today.strftime("%Y-%m-%d")
    elif option == 5:
        return (today - timedelta(days=365)).strftime("%Y-%m-%d"), today.strftime("%Y-%m-%d")
    elif option == 6:
        return (today - timedelta(days=365 * 2)).strftime("%Y-%m-%d"), today.strftime("%Y-%m-%d")
    elif option == 7:
        return (today - timedelta(days=365 * 5)).strftime("%Y-%m-%d"), today.strftime("%Y-%m-%d")
    elif option == 8:
        return (today - timedelta(days=365 * 10)).strftime("%Y-%m-%d"), today.strftime("%Y-%m-%d")
    else:
        raise ValueError("Invalid selection")

# Prompt user for fresh download or continuation
print("Select download mode:")
print("1) Fresh download")
print("2) Continue from the last checkpoint")

try:
    mode_choice = int(input("Enter your choice (1-2): "))
    if mode_choice not in [1, 2]:
        raise ValueError("Invalid selection")
except ValueError:
    print("Invalid input. Please restart the script and select a valid option.")
    exit()

# Prompt user for time period
print("Select the time period for data download:")
print("1) Download Today's Data")
print("2) Download Last 5 Days Data")
print("3) Download Last 30 Days Data")
print("4) Download Last 90 Days Data")
print("5) Download Last 1 Year Data")
print("6) Download Last 2 Years Data")
print("7) Download Last 5 Years Data")
print("8) Download Last 10 Years Data")

try:
    user_choice = int(input("Enter your choice (1-8): "))
    start_date, end_date = get_date_range(user_choice)
except ValueError as e:
    print("Invalid input. Please restart the script and select a valid option.")
    exit()

# Read symbols from CSV
symbols = pd.read_csv(symbols_file, header=None)[0].tolist()

# Handle checkpoint logic
if mode_choice == 2 and os.path.exists(checkpoint_file):
    with open(checkpoint_file, "r") as f:
        last_processed = f.read().strip()
    # Skip symbols up to the last processed one
    if last_processed in symbols:
        symbols = symbols[symbols.index(last_processed) + 1:]
elif mode_choice == 1:
    # Remove existing checkpoint for fresh download
    if os.path.exists(checkpoint_file):
        os.remove(checkpoint_file)

# Process symbols in batches
batch_size = 10  # Adjust this value based on your memory availability
for i in range(0, len(symbols), batch_size):
    batch = symbols[i:i + batch_size]
    for symbol in batch:
        logging.info(f"Starting download for {symbol}")
        try:
            # Skip already downloaded symbols
            output_file = os.path.join(output_folder, f"{symbol}.csv")
            if os.path.exists(output_file):
                logging.info(f"Skipping {symbol}, already downloaded")
                continue

            # Fetch historical data for the symbol
            for attempt in range(3):  # Retry up to 3 times
                try:
                    response = client.history(
                        symbol=symbol,
                        exchange="NSE",
                        interval="1m",
                        start_date=start_date,
                        end_date=end_date
                    )
                    break
                except Exception as e:
                    logging.warning(f"Retry {attempt + 1} for {symbol} due to error: {e}")
                    time.sleep(5)  # Wait before retrying
            else:
                logging.error(f"Failed to download data for {symbol} after 3 attempts")
                continue

            # Convert the response to a DataFrame if it's a dictionary
            if isinstance(response, dict):
                if "timestamp" in response:
                    df = pd.DataFrame(response)
                else:
                    logging.error(f"Response for {symbol} missing 'timestamp' key: {response}")
                    continue
            else:
                df = response

            # Ensure the DataFrame is not empty
            if df.empty:
                logging.warning(f"No data available for {symbol}")
                continue

            # Reset the index to extract the timestamp
            df.reset_index(inplace=True)

            # Rename and split the timestamp column
            df['DATE'] = pd.to_datetime(df['timestamp']).dt.date
            df['TIME'] = pd.to_datetime(df['timestamp']).dt.time

            # Add SYMBOL column and rearrange columns
            df['SYMBOL'] = symbol
            df = df[['SYMBOL', 'DATE', 'TIME', 'open', 'high', 'low', 'close', 'volume']]
            df.columns = ['SYMBOL', 'DATE', 'TIME', 'OPEN', 'HIGH', 'LOW', 'CLOSE', 'VOLUME']

            # Save to CSV file
            df.to_csv(output_file, index=False)
            logging.info(f"Data for {symbol} saved to {output_file}")

            # Save checkpoint after successfully processing the symbol
            with open(checkpoint_file, "w") as f:
                f.write(symbol)

            # Clear DataFrame and force garbage collection
            del df
            gc.collect()

        except Exception as e:
            logging.error(f"Failed to download data for {symbol}: {e}")

        # Delay to avoid rate limiting
        time.sleep(3)

    logging.info(f"Batch of {batch_size} symbols completed.")

logging.info("All data downloaded.")