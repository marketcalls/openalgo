# Python Strategies Documentation

Welcome to the Python Strategies Management System documentation for OpenAlgo.

## 📚 Documentation Structure

### Getting Started
- [**README**](README.md) - Complete overview and quick start guide
- [**Installation Guide**](installation-guide.md) - Detailed installation instructions
- [**API Reference**](api-reference.md) - Complete API documentation

### User Guides
- [**Editor Guide**](editor-guide.md) - Using the built-in code editor
- [**Complete Implementation Guide**](complete-implementation-guide.md) - Full technical details
- [**Master Contract & State Management**](master-contract-state-management.md) - Advanced state and dependency management

## 🚀 Quick Links

### For Users
1. [How to Upload a Strategy](README.md#upload-your-first-strategy)
2. [How to Schedule Strategies](README.md#scheduling)
3. [How to Edit Strategies](editor-guide.md)
4. [How to Export Strategies](README.md#export-a-strategy)

### For Developers
1. [API Endpoints](api-reference.md#endpoints)
2. [Data Models](api-reference.md#data-models)
3. [JavaScript Client Example](api-reference.md#javascript-client)
4. [Python Client Example](api-reference.md#python-client)

### For System Administrators
1. [Installation Steps](installation-guide.md#installation-steps)
2. [Configuration Options](installation-guide.md#configuration)
3. [Security Settings](README.md#security)
4. [Troubleshooting](README.md#troubleshooting)

## 📋 Feature Overview

| Feature | Description | Documentation |
|---------|-------------|---------------|
| **Process Isolation** | Each strategy runs in separate process | [Architecture](README.md#architecture) |
| **Scheduling** | Automated execution at specific times | [Scheduling Guide](README.md#scheduling) |
| **Code Editor** | Built-in Python editor with syntax highlighting | [Editor Guide](editor-guide.md) |
| **Logging** | Real-time strategy execution logs | [Logging System](README.md#logging-system) |
| **Export/Import** | Download and backup strategies | [Export Guide](README.md#export-a-strategy) |
| **Environment Variables** | Secure storage for API keys and configuration | [Environment Variables](README.md#environment-variables) |
| **State Management** | Persistent state across restarts | [State Management](master-contract-state-management.md#state-management) |
| **Master Contract Dependency** | Automatic start after contracts download | [Master Contracts](master-contract-state-management.md#master-contract-dependency) |
| **Cross-Platform** | Works on Windows, Linux, macOS | [Platform Notes](README.md#platform-specific-notes) |

## 🔧 System Requirements

### Minimum Requirements
- Python 3.8+
- 2GB RAM
- 1GB disk space
- OpenAlgo installed

### Python Packages
```bash
apscheduler>=3.10.0
psutil>=5.9.0
pytz
cryptography  # For secure environment variables
flask-wtf     # For CSRF protection
```

## 🎯 Common Tasks

### Upload and Run a Strategy
1. Navigate to `/python`
2. Click "Upload New Strategy"
3. Select your `.py` file
4. Click "Start" to run

### Schedule a Strategy
1. Click "Schedule" on strategy card
2. Set start time (e.g., 09:15)
3. Set stop time (e.g., 15:30)
4. Select days (Mon-Fri)
5. Save schedule

### Edit a Strategy
1. Stop the strategy if running
2. Click "Edit" button
3. Modify the code
4. Save changes (Ctrl+S)

### Export a Strategy
1. Click "Export" on strategy card
2. Or in editor, use Export dropdown
3. Choose "Export Saved" or "Export Current"

## 📊 API Quick Reference

### Key Endpoints
```
POST /python/upload          # Upload strategy
POST /python/start/<id>      # Start strategy
POST /python/stop/<id>       # Stop strategy
GET  /python/export/<id>     # Export strategy
POST /python/schedule/<id>   # Schedule strategy
GET  /python/logs/<id>       # View logs
POST /python/logs/<id>/clear # Clear logs
GET  /python/status          # System status
GET  /python/env/<id>        # Get environment variables
POST /python/env/<id>        # Set environment variables
POST /python/check-contracts # Check and start pending strategies
POST /python/clear-error/<id> # Clear error state
```

### Example Request
```javascript
// Start a strategy
fetch('/python/start/strategy_id', {
    method: 'POST',
    headers: {
        'X-CSRFToken': getCSRFToken()
    }
})
.then(response => response.json())
.then(data => console.log(data));
```

## 🛠️ Troubleshooting Quick Fixes

| Issue | Solution |
|-------|----------|
| Strategy won't start | Check master contracts status, Python syntax, view logs |
| "Waiting" status | Master contracts downloading, will auto-start when ready |
| Save returns 400 | Stop strategy first, check CSRF token |
| Editor not loading | Clear browser cache, refresh page |
| Schedule not working | Verify time format (HH:MM), check days selected |
| Export fails | Check file permissions, disk space |
| Strategy in error after restart | Click "Clear Error" then "Restart" |

## 📝 Example Strategy

```python
from openalgo import api
import time

# Initialize
client = api(api_key='YOUR_KEY', host='http://127.0.0.1:5000')

def main():
    while True:
        # Your trading logic here
        print(f"Running at {time.strftime('%Y-%m-%d %H:%M:%S IST')}")
        
        # Fetch market data
        data = client.history(
            symbol="RELIANCE",
            exchange="NSE",
            interval="5m"
        )
        
        # Process and trade
        # ...
        
        time.sleep(60)

if __name__ == "__main__":
    main()
```

## 🔒 Security Best Practices

1. **Never hardcode API keys** - Use secure environment variables instead
2. **Use environment variables** - Regular for config, secure for sensitive data
3. **Git protection** - All sensitive files automatically git-ignored
4. **File permissions** - Encryption keys restricted to owner only (Unix)
5. **Persistent security** - Environment variables survive logout/restart
6. **Encryption** - Secure variables encrypted with unique key in `keys/.encryption_key`
7. **Regular backups** - Export strategies but keep env vars local
8. **Safety restrictions** - Cannot modify running strategies or their environment
9. **Process isolation** - Each strategy runs in separate process
10. **State security** - No sensitive data in state files

## 📞 Support

### Getting Help
1. Check the [Troubleshooting Guide](README.md#troubleshooting)
2. Review [API Documentation](api-reference.md)
3. Check logs in `log/strategies/`
4. Open GitHub issue

### Contact
- GitHub: [OpenAlgo Repository](https://github.com/openalgo/openalgo)
- Documentation: [This folder](.)
- Issues: [GitHub Issues](https://github.com/openalgo/openalgo/issues)

## 🔄 Version History

| Version | Date | Changes |
|---------|------|---------|
| 1.1.1 | Sep 2024 | Security improvements |
| | | - Moved encryption key to `keys/` folder |
| | | - Fixed secure variable persistence in UI |
| | | - Added bullet masking for secure values |
| 1.1.0 | Sep 2024 | Enhanced state management |
| | | - Master contract dependency checking |
| | | - Persistent state across restarts |
| | | - Automatic strategy restoration |
| | | - Improved error handling |
| | | - Safety restrictions for running strategies |
| 1.0.0 | Sep 2024 | Initial release |
| | | - Process isolation |
| | | - Scheduling system |
| | | - Code editor |
| | | - Export functionality |

---

*Python Strategies Documentation*
*Version 1.1.1 - September 2024*
*Part of OpenAlgo Trading Platform*