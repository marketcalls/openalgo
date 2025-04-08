# Trading Strategies

The `strategies` directory houses the logic for the various automated trading strategies that can be executed by the OpenAlgo platform.

## Strategy Definition

Based on the files present (e.g., `ema_crossover.py`, `supertrend.py`), trading strategies are likely defined as:

*   **Python Modules/Classes:** Each `.py` file could represent a distinct strategy, possibly implemented as a class inheriting from a base strategy class or following a specific functional convention.
*   **Core Logic:** These modules contain the algorithms that analyze market data, identify trading opportunities (entry/exit signals), and determine order parameters (symbol, quantity, price, order type).
*   **Indicators:** Strategies often rely on technical indicators. These might be calculated within the strategy code itself using libraries like `pandas-ta` (listed in `requirements.txt`) or potentially fetched from external sources or pre-calculated data stores.
*   **Configuration:** Strategies might be configurable via parameters stored in the database (`strategy_db.py`) or passed during initialization.

## Strategy Execution

The exact mechanism for strategy execution isn't fully evident from the file structure alone, but common patterns include:

*   **Scheduled Execution:** An external scheduler (like APScheduler, found in `requirements.txt`) or a background task runner (like Celery, if used) might periodically trigger the execution of active strategies (e.g., every minute, hour, or on specific market events).
*   **Event-Driven Execution:** Strategies might subscribe to real-time market data streams (potentially via WebSockets handled by broker adapters or Flask-SocketIO) and react to incoming ticks or price changes.
*   **Webhook Triggers:** The presence of `webhook.ipynb` and the `chartink_bp` blueprint suggests that strategies might also be triggered by external signals received via webhooks (e.g., from TradingView alerts or ChartInk scans).

## Interaction with Other Components

*   **Broker Interface:** When a strategy generates a trading signal, it interacts with the Broker Interface (`broker` directory) to place, modify, or cancel orders.
*   **Database:** Strategies likely read configuration from and write state information (e.g., active status, current positions held by the strategy) to the database (`strategy_db.py`). They might also query historical data or instrument details.
*   **API Layer:** The API layer (`blueprints/strategy.py`) allows users to manage (create, configure, activate, deactivate) strategies via the UI or API.

## Loading and Management

*   Strategies might be discovered and loaded dynamically at runtime.
*   The platform needs a mechanism to instantiate and manage the lifecycle of active strategy instances, potentially linking them to specific user accounts and broker connections.

*(Further details would require inspecting the code within `strategies/*.py`, `blueprints/strategy.py`, and potentially task scheduling configurations.)*
