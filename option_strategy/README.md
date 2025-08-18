# Standalone Options Strategy Framework

This folder contains a framework for running standalone, time-driven options trading strategies. The strategies in this folder are designed to be self-contained and run independently from the main Flask application, communicating with it only through its public API.

## Core Concepts

- **`base_strategy.py`**: A reusable base class that contains all the common logic needed for any strategy, such as API communication, logging, and paper trading. Future strategies should inherit from this class to ensure consistency and reduce code duplication.
- **`strangle.py`**: An implementation of the Strangle strategy, inheriting from `BaseStrategy`. It contains only the logic specific to entering, managing, and exiting a Strangle.
- **`config.json`**: A configuration file for all strategy parameters. You can edit this file to change how the strategy behaves without modifying the Python code.
- **`run_strangle.py`**: The main entry point to execute the Strangle strategy.

## How to Run the Strangle Strategy

1.  **Set Up Environment:**
    *   Ensure you have a `.env` file in the root directory of the main application.
    *   This `.env` file must contain your `APP_KEY` and the correct `HOST_SERVER` URL for the running OpenAlgo application.

2.  **Configure the Strategy:**
    *   Open the `config.json` file in this directory.
    *   Adjust the parameters as needed:
        *   `mode`: Set to `PAPER` to log trades to a CSV file or `LIVE` to attempt to place real orders.
        *   `start_time` / `end_time`: Define the trading window for the strategy in `HH:MM` format.
        *   `index`, `quantity_in_lots`, etc.: Configure the specific parameters for your trade.

3.  **Execute the Script:**
    *   Run the strategy from the **root directory** of the project using the following command:
        ```bash
        python -m option_strategy.run_strangle
        ```
    *   This will start the script, which will wait until the configured `start_time` to begin placing trades.

4.  **Monitor Output:**
    *   The script will print log messages to your console.
    *   If running in `PAPER` mode, all simulated trades will be logged to a `paper_trades.csv` file created inside this `option_strategy` directory.