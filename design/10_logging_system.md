# Centralized Logging System

## Overview

OpenAlgo implements a sophisticated centralized logging system that provides colored console output, sensitive data protection, and comprehensive monitoring capabilities across all application components.

## Architecture Components

### 1. Core Logging Infrastructure

Located in `utils/logging.py`, the logging system provides:

- **Centralized Configuration**: Single point of configuration for all logging
- **Environment-based Setup**: Configuration via environment variables
- **Color Support Detection**: Automatic detection of terminal color capabilities
- **Sensitive Data Protection**: Automatic redaction of sensitive information
- **File Rotation**: Automatic log file rotation and cleanup

### 2. Enhanced Formatter Classes

#### ColoredFormatter

Provides intelligent color formatting for console output:

```python
class ColoredFormatter(logging.Formatter):
    - Color-coded log levels (DEBUG: Cyan, INFO: Green, WARNING: Yellow, ERROR: Red)
    - Component highlighting (timestamps, module names)
    - Cross-platform color support detection
    - Graceful fallback for non-color terminals
```

#### SensitiveDataFilter

Automatic redaction of sensitive information:

```python
class SensitiveDataFilter(logging.Filter):
    - API key redaction
    - Password masking
    - Token protection
    - Authorization header sanitization
    - Bearer token filtering
```

### 3. Utility Functions

#### highlight_url()
Creates visually prominent URL displays:
- Bright cyan coloring for URLs
- Support for custom display text
- Fallback for non-color environments

#### log_startup_banner()
Generates colored startup banners:
- Service title highlighting
- URL prominence
- Configurable separator characters
- Professional startup messaging

#### get_logger()
Factory function for module-specific loggers:
- Consistent logger configuration
- Module name tracking
- Automatic color support

## Configuration System

### Environment Variables

```bash
# Logging Level Configuration
LOG_LEVEL=INFO                    # DEBUG, INFO, WARNING, ERROR, CRITICAL

# File Logging
LOG_TO_FILE=True                  # Enable/disable file logging
LOG_DIR=logs                      # Directory for log files
LOG_RETENTION=14                  # Days to retain log files

# Output Formatting
LOG_FORMAT="[%(asctime)s] %(levelname)s in %(module)s: %(message)s"
LOG_COLORS=True                   # Enable/disable colored output

# Color Control
FORCE_COLOR=True                  # Force color output
NO_COLOR=1                        # Disable color output (standard)
```

### Dynamic Configuration

The system automatically detects:
- **Terminal Capabilities**: Color support, ANSI compatibility
- **CI/CD Environments**: GitHub Actions, GitLab CI, Jenkins
- **Platform Differences**: Windows, Linux, macOS compatibility
- **Virtual Environments**: Docker, WSL, virtual terminals

## Color System

### Log Level Colors

```python
LOG_COLORS = {
    'DEBUG': Fore.CYAN,
    'INFO': Fore.GREEN,
    'WARNING': Fore.YELLOW,
    'ERROR': Fore.RED,
    'CRITICAL': Fore.RED + Style.BRIGHT,
}
```

### Component Colors

```python
COMPONENT_COLORS = {
    'timestamp': Fore.BLUE,          # Timestamp highlighting
    'module': Fore.MAGENTA,          # Module name highlighting
    'reset': Style.RESET_ALL,        # Color reset
}
```

### URL Highlighting

URLs are displayed with bright cyan colors and optional text labels:
```python
highlight_url("http://localhost:5000", "Main Application")
# Output: Main Application -> http://localhost:5000 (in bright colors)
```

## Sensitive Data Protection

### Pattern-Based Filtering

The system automatically redacts sensitive information using regex patterns:

```python
SENSITIVE_PATTERNS = [
    (r'(api[_-]?key[\s]*[=:]\s*)[\w\-]+', r'\1[REDACTED]'),
    (r'(password[\s]*[=:]\s*)[\w\-]+', r'\1[REDACTED]'),
    (r'(token[\s]*[=:]\s*)[\w\-]+', r'\1[REDACTED]'),
    (r'(secret[\s]*[=:]\s*)[\w\-]+', r'\1[REDACTED]'),
    (r'(authorization[\s]*[=:]\s*)[\w\-]+', r'\1[REDACTED]'),
    (r'(Bearer\s+)[\w\-\.]+', r'\1[REDACTED]'),
]
```

### Protection Coverage

- **API Keys**: All variations of API key fields
- **Passwords**: Password fields in various formats
- **Tokens**: JWT tokens, session tokens, access tokens
- **Secrets**: API secrets, client secrets
- **Authorization Headers**: Bearer tokens, basic auth
- **Custom Patterns**: Extensible pattern system

## File Logging System

### Rotation Strategy

```python
TimedRotatingFileHandler(
    filename=log_file,
    when='midnight',        # Rotate at midnight
    interval=1,             # Daily rotation
    backupCount=14,         # Keep 14 days of logs
    encoding='utf-8'        # UTF-8 encoding
)
```

### File Organization

```
logs/
├── openalgo_2024-01-15.log      # Current day log
├── openalgo_2024-01-14.log      # Previous day log
├── openalgo_2024-01-13.log      # Older logs
└── ...                          # Automatic cleanup after retention period
```

### Cleanup Process

Automatic cleanup removes logs older than the retention period:
- **Daily Execution**: Runs during log rotation
- **Configurable Retention**: Environment variable controlled
- **Safe Deletion**: Error handling for file system issues

## Integration Points

### Application Startup

```python
# In app.py or main application
from utils.logging import get_logger, log_startup_banner, highlight_url

logger = get_logger(__name__)
log_startup_banner(logger, "OpenAlgo API Server", "http://localhost:5000")
```

### Module Usage

```python
# In any module
from utils.logging import get_logger

logger = get_logger(__name__)
logger.info("Module initialized successfully")
logger.error("Error occurred during processing")
```

### WebSocket Server

```python
# In websocket_proxy/server.py
from utils.logging import get_logger, highlight_url

logger = get_logger("websocket_proxy")
highlighted_address = highlight_url(f"{self.host}:{self.port}")
logger.info(f"WebSocket server started on {highlighted_address}")
```

## Third-Party Logger Management

The system automatically configures third-party loggers to reduce noise:

```python
# Suppress verbose third-party loggers
logging.getLogger('werkzeug').setLevel(logging.WARNING)
logging.getLogger('urllib3').setLevel(logging.WARNING)
logging.getLogger('requests').setLevel(logging.WARNING)
logging.getLogger('httpx').setLevel(logging.WARNING)
logging.getLogger('httpcore').setLevel(logging.WARNING)
```

## Performance Considerations

### Efficient Processing

- **Lazy Evaluation**: Color detection only when needed
- **Pattern Caching**: Compiled regex patterns for performance
- **Minimal Overhead**: Efficient filtering with early returns
- **Memory Management**: Automatic cleanup of log handlers

### Scalability Features

- **Asynchronous Logging**: Non-blocking log operations
- **Buffer Management**: Efficient handling of high-volume logs
- **Resource Limits**: Automatic file size and count management
- **Thread Safety**: Safe for multi-threaded applications

## Error Handling

### Graceful Degradation

The logging system continues to function even when:
- **Color Libraries Missing**: Falls back to plain text
- **File System Issues**: Continues with console logging
- **Permission Problems**: Graceful handling of write failures
- **Configuration Errors**: Uses sensible defaults

### Error Recovery

```python
try:
    # Logging operation
    logger.info("Operation completed")
except Exception:
    # Fallback to basic logging
    print("Fallback log message")
```

## Monitoring and Debugging

### Log Analysis Features

- **Structured Format**: Consistent log format for parsing
- **Timestamp Precision**: Millisecond precision for debugging
- **Module Tracking**: Clear identification of log sources
- **Level Filtering**: Easy filtering by log level

### Debug Support

```python
# Debug mode logging
logger.debug(f"Variable state: {variable}")
logger.debug(f"Function entered with args: {args}")
```

### Performance Metrics

- **Log Volume**: Track log message frequency
- **Error Rates**: Monitor error log frequency
- **File Sizes**: Monitor log file growth
- **Rotation Success**: Track file rotation operations

## Security Features

### Information Disclosure Prevention

- **Automatic Redaction**: No manual intervention required
- **Pattern Matching**: Comprehensive coverage of sensitive patterns
- **Case Insensitive**: Handles various case combinations
- **Context Preservation**: Maintains log readability while protecting data

### Audit Trail

- **Tamper Resistance**: File-based logs for audit purposes
- **Retention Policy**: Configurable retention for compliance
- **Access Control**: File system permissions for log security

## Best Practices

### Developer Guidelines

1. **Use Module Loggers**: Always use `get_logger(__name__)`
2. **Appropriate Levels**: Use correct log levels (DEBUG, INFO, WARNING, ERROR)
3. **Sensitive Data**: Be aware of data that might be logged
4. **Context Information**: Include relevant context in log messages
5. **Exception Logging**: Use `logger.exception()` for stack traces

### Configuration Guidelines

1. **Environment Specific**: Different configs for dev/staging/prod
2. **Log Levels**: Appropriate levels for each environment
3. **File Retention**: Balance storage vs. audit requirements
4. **Color Settings**: Disable colors in production logs
5. **Sensitive Patterns**: Extend patterns for custom sensitive data

## Future Enhancements

### Planned Features

1. **Structured Logging**: JSON format support for log aggregation
2. **Remote Logging**: Integration with centralized logging services
3. **Log Aggregation**: ELK stack integration
4. **Metrics Integration**: Prometheus metrics from logs
5. **Alert Integration**: Automatic alerting on error patterns

### Extensibility

- **Custom Filters**: Plugin system for custom log filters
- **Custom Formatters**: Support for custom log formats
- **Handler Plugins**: Additional log output destinations
- **Pattern Extensions**: Easy addition of new sensitive data patterns