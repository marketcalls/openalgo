# OpenAlgo Centralized Logging Guide

## **Overview**

OpenAlgo uses a centralized logging system to ensure consistent, secure, and configurable log management across the entire codebase. All logs are handled by the `utils/logging.py` module. The logging configuration is validated at startup by `utils/env_check.py` to ensure proper setup.

---

## **Features**

* Console logging by default
* Optional file logging with daily rotation (controlled by `.env`)
* Configurable log levels and format
* Sensitive data filtering (API keys, passwords, tokens automatically redacted)
* Automatic log retention and cleanup
* Environment validation at startup
* Modular usage—one logger per module

---

## **.env Logging Options**

| Variable       | Description                                       | Default                                                 |
| -------------- | ------------------------------------------------- | ------------------------------------------------------- |
| LOG_TO_FILE    | Enable log file writing (True/False)              | False                                                   |
| LOG_LEVEL      | Log level (DEBUG, INFO, WARNING, ERROR, CRITICAL) | INFO                                                    |
| LOG_DIR        | Directory for log files                           | log                                                     |
| LOG_FORMAT     | Log message format                                | [%(asctime)s] %(levelname)s in %(module)s: %(message)s |
| LOG_RETENTION  | Days to keep log files                            | 14                                                      |

---

## **How to Use the Logger in Your Module**

Import and get a logger instance at the top of any module:

```python
from utils.logging import get_logger

logger = get_logger(__name__)
```

### **Logging Levels & Examples**

*   **Informational Messages:** Use `logger.info()` for general operational messages.
    ```python
    logger.info("Service started successfully.")
    ```

*   **Debug Messages:** Use `logger.debug()` for detailed diagnostic information useful during development.
    ```python
    logger.debug(f"Received payload: {payload}")
    ```

*   **Error Handling with Stack Traces:** Use `logger.exception()` inside a `try...except` block to log an error with its full stack trace. This is the **required** method for capturing exceptions.
    ```python
    try:
        result = 1 / 0
    except Exception as e:
        logger.exception("An error occurred during calculation.")
    ```
*   **Warning Messages:** Use `logger.warning()` to indicate a potential issue that doesn't prevent the operation from continuing.
    ```python
    logger.warning("API response time is higher than expected.")
    ```

---

## **Best Practices**

*   **Always use `logger.exception()` for Errors:** When catching exceptions, use `logger.exception()` instead of `logger.error()` to automatically include the full stack trace in the log. This is critical for effective debugging.
*   **Instantiate the Logger Once Per Module:** Define `logger = get_logger(__name__)` at the top of the file, not inside functions or classes.
*   **Never Use `print()`:** All diagnostic output must go through the logger.
*   **Avoid Logging Sensitive Data Directly:** While the system has filters, it is best practice to avoid logging raw API keys, tokens, or passwords.
*   **Use F-Strings for Dynamic Messages:** Construct log messages using f-strings for clarity and performance (e.g., `logger.info(f"Processing user {user_id}")`).

---

## **FAQ**

**Q: How do I enable log files?**
A: Set `LOG_TO_FILE=True` in your `.env` file.

**Q: How do I change log levels?**
A: Set `LOG_LEVEL=DEBUG` (or another level) in your `.env` file.

**Q: Where are log files stored?**
A: In the directory specified by `LOG_DIR` (default is `/log`).

**Q: How can I keep logs clean and secure?**
A: Avoid logging raw request payloads. The system automatically redacts sensitive data matching patterns in `SENSITIVE_PATTERNS`, but you should not rely on it as a primary security measure.

---

## **Codebase Compliance**

As of June 2025, the centralized logging system has been fully implemented across all major directories of the OpenAlgo project, including `/services`, `/blueprints`, `/restx_api`, `/websocket_proxy`, and `/broker`.

All modules adhere to the following standards:
*   A single logger instance is created per module using `get_logger(__name__)`.
*   All `print()` statements and legacy `logging` calls have been removed.
*   Error handling uses `logger.exception()` to provide full stack traces.

Maintaining this standard is crucial for the stability and maintainability of the application.

---

## **Environment Validation**

The logging configuration is automatically validated when the application starts through `utils/env_check.py`. The validation ensures:

* `LOG_TO_FILE` is either 'True' or 'False'
* `LOG_LEVEL` is one of: DEBUG, INFO, WARNING, ERROR, CRITICAL
* `LOG_RETENTION` is a positive integer
* `LOG_DIR` is not empty
* `LOG_FORMAT` is not empty

If any validation fails, the application will not start and will display helpful error messages.

---

## **Example Logging Configuration in `.env`**

```env
LOG_TO_FILE=True
LOG_LEVEL=DEBUG
LOG_DIR=log
LOG_FORMAT=[%(asctime)s] %(levelname)s in %(module)s: %(message)s
LOG_RETENTION=14
```

---

## **Need Help?**

Open an issue in the repo or contact the OpenAlgo dev team.