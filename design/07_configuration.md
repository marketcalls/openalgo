# Configuration Management

OpenAlgo uses environment variables as the primary method for configuration. This allows for flexibility in different deployment environments (development, testing, production) without modifying the codebase.

## Mechanism

*   **.env File:** Configuration variables are typically defined in a `.env` file located in the project root directory.
*   **python-dotenv:** The `python-dotenv` library (listed in `requirements.txt`) is used to load these variables from the `.env` file into the application's environment when it starts.
*   **Loading and Validation:** The custom function `utils.env_check.load_and_check_env_variables()` is called at the very beginning of `app.py`. This function likely handles:
    *   Loading variables from the `.env` file.
    *   Checking for the presence of essential variables.
    *   Potentially validating the format or values of certain variables.
*   **Access:** Throughout the application code, configuration values are accessed using `os.getenv('VARIABLE_NAME', 'default_value')`.
*   **Sample:** A `.sample.env` file provides a template listing the available configuration variables and their purpose.

## Key Configuration Variables

Based on `.sample.env`, key configuration categories and variables include:

*   **Broker Configuration:**
    *   `BROKER_API_KEY`: API Key for the primary broker.
    *   `BROKER_API_SECRET`: API Secret for the primary broker.
    *   `BROKER_API_KEY_MARKET`: Market data API Key (for specific brokers like XTS).
    *   `BROKER_API_SECRET_MARKET`: Market data API Secret (for specific brokers like XTS).
    *   `REDIRECT_URL`: OAuth callback URL for broker authentication.
    *   `VALID_BROKERS`: Comma-separated list of enabled broker integrations.

*   **Security Configuration:**
    *   `APP_KEY`: Secret key used by Flask for session signing and other security functions. **Must be changed for production.**
    *   `API_KEY_PEPPER`: A secret random string added before hashing/encrypting sensitive data like API keys, passwords, and broker tokens. **Must be changed for production.**

*   **Database Configuration:**
    *   `DATABASE_URL`: SQLAlchemy database connection string (e.g., `sqlite:///db/openalgo.db`, `postgresql://user:pass@host/db`).
    *   `DB_POOL_SIZE`, `DB_MAX_OVERFLOW`, `DB_POOL_TIMEOUT`, `DB_POOL_RECYCLE`: Parameters controlling the SQLAlchemy connection pool (as noted in memory). These might be added to the `.env` file for customization.

*   **Server Configuration:**
    *   `FLASK_HOST_IP`: IP address the Flask development server binds to (e.g., `127.0.0.1`, `0.0.0.0`).
    *   `FLASK_PORT`: Port the Flask development server listens on.
    *   `FLASK_DEBUG`: Enables/disables Flask debug mode.
    *   `FLASK_ENV`: Sets the Flask environment (`development` or `production`).
    *   `NGROK_ALLOW`: Set to `TRUE` to enable ngrok tunneling in development.
    *   `HOST_SERVER`: The public-facing base URL of the application (used for constructing URLs like `REDIRECT_URL`).

*   **Rate Limiting:**
    *   `LOGIN_RATE_LIMIT_MIN`: Rate limit for login attempts per minute.
    *   `LOGIN_RATE_LIMIT_HOUR`: Rate limit for login attempts per hour.
    *   `API_RATE_LIMIT`: Default rate limit for API endpoints.

*   **API Behavior:**
    *   `SMART_ORDER_DELAY`: Delay (in seconds) between legs of multi-legged orders.
    *   `SESSION_EXPIRY_TIME`: Daily time (IST) when all web UI sessions expire.

## Environment Specificity

It is crucial to maintain separate `.env` files or use environment variable management tools (like Docker secrets, system environment variables) for different environments (development, staging, production) to ensure correct settings and security.
