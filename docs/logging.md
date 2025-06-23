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

Import and get a logger in any file:

```python
from utils.logging import get_logger

logger = get_logger(__name__)

logger.info("Informational message")
logger.debug("Detailed debug info")
logger.error("An error occurred")
```

---

## **Best Practices**

* **Never use `print()` for debug/info/error messages.**
* **Do not log sensitive information** such as passwords, tokens, or API keys.
* **Set log levels via `.env` as needed for production, staging, or local debugging.**
* **Check log files in the `/log` directory if file logging is enabled.**

---

## **FAQ**

**Q: How do I enable log files?**
A: Set `LOG_TO_FILE=True` in your `.env` file.

**Q: How do I change log levels?**
A: Set `LOG_LEVEL=DEBUG` (or another level) in your `.env` file.

**Q: Where are log files stored?**
A: In the directory specified by `LOG_DIR` (default is `/log`).

**Q: How can I keep logs clean and secure?**
A: Avoid logging raw request payloads, and use logger filters to redact sensitive fields.

---

## **Migration Steps**

1. Remove all `print()` calls across the codebase.
2. Replace with the centralized logger from `utils/logging.py`.
3. Set up `.env` with the new logging options.
4. Validate that logs behave as expected in both console and file mode.

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