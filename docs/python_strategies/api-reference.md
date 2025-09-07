# Python Strategies API Reference

## Base URL
```
http://127.0.0.1:5000/python
```

## Authentication
All API endpoints require CSRF token for POST requests.

### Getting CSRF Token
```javascript
const token = document.querySelector('meta[name="csrf-token"]').content;
```

## Endpoints

### 1. Dashboard
**GET** `/python`

Returns the main dashboard HTML page.

**Response:**
- HTML page with strategy list

---

### 2. Upload Strategy
**POST** `/python/upload`

Upload a new Python strategy file.

**Request:**
```http
POST /python/upload
Content-Type: multipart/form-data
X-CSRFToken: <token>

file: <binary>
name: "Strategy Name"
```

**Parameters:**
| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| file | File | Yes | Python file (.py) |
| name | String | Yes | Display name for strategy |

**Response:**
```json
{
  "success": true,
  "message": "Strategy uploaded successfully",
  "strategy_id": "uuid-string"
}
```

**Error Codes:**
- `400` - Invalid file or missing parameters
- `413` - File too large
- `415` - Invalid file type

---

### 3. Start Strategy
**POST** `/python/start/<strategy_id>`

Start a strategy process.

**Request:**
```http
POST /python/start/abc123
X-CSRFToken: <token>
```

**Response:**
```json
{
  "success": true,
  "message": "Strategy started with PID 12345 at 09:15:00 IST"
}
```

**Error Codes:**
- `404` - Strategy not found
- `409` - Strategy already running

---

### 4. Stop Strategy
**POST** `/python/stop/<strategy_id>`

Stop a running strategy.

**Request:**
```http
POST /python/stop/abc123
X-CSRFToken: <token>
```

**Response:**
```json
{
  "success": true,
  "message": "Strategy stopped at 15:30:00 IST"
}
```

**Error Codes:**
- `404` - Strategy not found
- `400` - Strategy not running

---

### 5. Delete Strategy
**POST** `/python/delete/<strategy_id>`

Delete a strategy (must be stopped first).

**Request:**
```http
POST /python/delete/abc123
X-CSRFToken: <token>
```

**Response:**
```json
{
  "success": true,
  "message": "Strategy deleted successfully"
}
```

**Error Codes:**
- `404` - Strategy not found
- `409` - Strategy is running

---

### 6. Schedule Strategy
**POST** `/python/schedule/<strategy_id>`

Set automatic schedule for strategy.

**Request:**
```http
POST /python/schedule/abc123
Content-Type: application/json
X-CSRFToken: <token>

{
  "start_time": "09:15",
  "stop_time": "15:30",
  "days": ["mon", "tue", "wed", "thu", "fri"]
}
```

**Parameters:**
| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| start_time | String | Yes | Start time in HH:MM format (IST) |
| stop_time | String | No | Stop time in HH:MM format (IST) |
| days | Array | Yes | Days of week (mon-sun) |

**Response:**
```json
{
  "success": true,
  "message": "Strategy scheduled successfully"
}
```

**Error Codes:**
- `400` - Invalid time format, missing days, or strategy is running
- `404` - Strategy not found

**Safety Restriction:**
- Cannot modify schedules while strategy is running
- Returns `STRATEGY_RUNNING` error code if attempted

---

### 7. Unschedule Strategy
**POST** `/python/unschedule/<strategy_id>`

Remove automatic schedule.

**Request:**
```http
POST /python/unschedule/abc123
X-CSRFToken: <token>
```

**Response:**
```json
{
  "success": true,
  "message": "Schedule removed successfully"
}
```

---

### 8. Edit Strategy
**GET** `/python/edit/<strategy_id>`

Get strategy editor page.

**Response:**
- HTML page with code editor
- Read-only if strategy is running

---

### 9. Save Strategy
**POST** `/python/save/<strategy_id>`

Save edited strategy content.

**Request:**
```http
POST /python/save/abc123
Content-Type: application/json
X-CSRFToken: <token>

{
  "content": "# Python code here\nimport time\n..."
}
```

**Response:**
```json
{
  "success": true,
  "message": "Strategy saved successfully",
  "timestamp": "2024-01-01 12:00:00 IST"
}
```

**Error Codes:**
- `400` - Strategy is running (cannot edit)
- `404` - Strategy not found

---

### 10. Export Strategy
**GET** `/python/export/<strategy_id>`

Download strategy file.

**Request:**
```http
GET /python/export/abc123
```

**Response:**
- Binary file download
- Content-Type: text/x-python
- Content-Disposition: attachment

---

### 11. View Logs
**GET** `/python/logs/<strategy_id>`

View strategy execution logs.

**Query Parameters:**
| Parameter | Type | Description |
|-----------|------|-------------|
| latest | Integer | Show latest log (1) |

**Response:**
- HTML page with log viewer

---

### 12. Clear Logs
**POST** `/python/logs/<strategy_id>/clear`

Clear all log files for a strategy.

**Request:**
```http
POST /python/logs/abc123/clear
X-CSRFToken: <token>
```

**Response:**
```json
{
  "success": true,
  "message": "Cleared 3 log files (1.25 MB)",
  "cleared_count": 3,
  "total_size_mb": 1.25
}
```

**Behavior:**
- **Running strategies**: Active log file is truncated (not deleted)
- **Stopped strategies**: All log files are deleted
- **Smart handling**: Preserves active logs while clearing historical ones

**Error Codes:**
- `404` - Strategy not found
- `500` - File system error

---

### 13. System Status
**GET** `/python/status`

Get system status and running strategies.

**Request:**
```http
GET /python/status
```

**Response:**
```json
{
  "running": 2,
  "total": 5,
  "scheduler_running": true,
  "current_ist_time": "14:30:15 IST",
  "platform": "windows",
  "strategies": [
    {
      "id": "abc123",
      "name": "EMA Crossover",
      "is_running": true,
      "is_scheduled": true
    }
  ]
}
```

---

### 14. Manage Environment Variables
**GET/POST** `/python/env/<strategy_id>`

Manage environment variables for a strategy.

#### Get Environment Variables
**GET** `/python/env/<strategy_id>`

**Response:**
```json
{
  "success": true,
  "regular_vars": {
    "DEBUG": "true",
    "LOG_LEVEL": "INFO",
    "SYMBOL": "RELIANCE"
  },
  "secure_vars": ["API_KEY", "SECRET_KEY"]
}
```

#### Set Environment Variables
**POST** `/python/env/<strategy_id>`

**Request:**
```http
POST /python/env/abc123
Content-Type: application/json
X-CSRFToken: <token>

{
  "regular_vars": {
    "DEBUG": "true",
    "LOG_LEVEL": "INFO",
    "SYMBOL": "RELIANCE"
  },
  "secure_vars": {
    "API_KEY": "your_api_key_here",
    "SECRET_KEY": "your_secret_key_here"
  }
}
```

**Response:**
```json
{
  "success": true,
  "message": "Environment variables saved successfully",
  "regular_count": 3,
  "secure_count": 2
}
```

**Error Codes:**
- `404` - Strategy not found
- `400` - Invalid data provided or strategy is running

**Safety Restrictions:**
- **Running strategies**: Environment variables are read-only
- Cannot modify while strategy is active
- Returns `STRATEGY_RUNNING` error code if modification attempted
- Must stop strategy first to make changes

**Security Notes:**
- Regular variables stored in `strategies/strategy_env.json` (git-ignored)
- Secure variables encrypted and stored in `strategies/.secure_env` (git-ignored)  
- Encryption key auto-generated per installation (git-ignored)
- All environment variable files protected from version control commits

## Data Models

### Strategy Configuration
```json
{
  "id": "uuid-string",
  "name": "Strategy Name",
  "file_path": "strategies/scripts/file.py",
  "is_running": false,
  "is_scheduled": false,
  "schedule_start": "09:15",
  "schedule_stop": "15:30",
  "schedule_days": ["mon", "tue", "wed", "thu", "fri"],
  "last_started": "2024-01-01T09:15:00+05:30",
  "last_stopped": "2024-01-01T15:30:00+05:30",
  "last_modified": "2024-01-01T12:00:00+05:30",
  "pid": 12345
}
```

### Log File Format
```
=== Strategy Started at 2024-01-01 09:15:00 IST ===
=== Platform: windows ===

[Strategy Output]
2024-01-01 09:15:01 INFO: Strategy initialized
2024-01-01 09:15:02 INFO: Connecting to market...
...
```

## Error Handling

### Standard Error Response
```json
{
  "success": false,
  "message": "Error description",
  "error_code": "ERROR_CODE"
}
```

### Common Error Codes
| Code | Description |
|------|-------------|
| `STRATEGY_NOT_FOUND` | Strategy ID doesn't exist |
| `STRATEGY_RUNNING` | Cannot modify running strategy |
| `STRATEGY_NOT_RUNNING` | Strategy is not running |
| `INVALID_FILE` | Invalid Python file |
| `SCHEDULE_ERROR` | Scheduling error |
| `PROCESS_ERROR` | Process management error |

## WebSocket Events (Future)

### Events
```javascript
// Connect to WebSocket
const ws = new WebSocket('ws://127.0.0.1:5000/python/ws');

// Listen for events
ws.on('strategy_started', (data) => {
  console.log(`Strategy ${data.id} started`);
});

ws.on('strategy_stopped', (data) => {
  console.log(`Strategy ${data.id} stopped`);
});

ws.on('strategy_log', (data) => {
  console.log(`Log: ${data.message}`);
});
```

## Rate Limiting

- Upload: 10 files per minute
- Start/Stop: 30 requests per minute
- Save: 20 requests per minute
- Status: 60 requests per minute

## Examples

### JavaScript Client
```javascript
class StrategyClient {
  constructor(baseUrl = '/python') {
    this.baseUrl = baseUrl;
  }

  getCSRFToken() {
    return document.querySelector('meta[name="csrf-token"]').content;
  }

  async uploadStrategy(file, name) {
    const formData = new FormData();
    formData.append('file', file);
    formData.append('name', name);

    const response = await fetch(`${this.baseUrl}/upload`, {
      method: 'POST',
      headers: {
        'X-CSRFToken': this.getCSRFToken()
      },
      body: formData
    });

    return response.json();
  }

  async startStrategy(strategyId) {
    const response = await fetch(`${this.baseUrl}/start/${strategyId}`, {
      method: 'POST',
      headers: {
        'X-CSRFToken': this.getCSRFToken()
      }
    });

    return response.json();
  }

  async stopStrategy(strategyId) {
    const response = await fetch(`${this.baseUrl}/stop/${strategyId}`, {
      method: 'POST',
      headers: {
        'X-CSRFToken': this.getCSRFToken()
      }
    });

    return response.json();
  }

  async getStatus() {
    const response = await fetch(`${this.baseUrl}/status`);
    return response.json();
  }
}

// Usage
const client = new StrategyClient();

// Upload strategy
const file = document.getElementById('file-input').files[0];
const result = await client.uploadStrategy(file, 'My Strategy');

// Start strategy
await client.startStrategy(result.strategy_id);

// Check status
const status = await client.getStatus();
console.log(`Running strategies: ${status.running}`);
```

### Python Client
```python
import requests
import json

class StrategyAPIClient:
    def __init__(self, base_url='http://127.0.0.1:5000/python'):
        self.base_url = base_url
        self.session = requests.Session()
        
    def get_csrf_token(self):
        # Get CSRF token from main page
        response = self.session.get(f'{self.base_url}/')
        # Parse token from response
        return 'token-here'
    
    def upload_strategy(self, file_path, name):
        with open(file_path, 'rb') as f:
            files = {'file': f}
            data = {'name': name}
            headers = {'X-CSRFToken': self.get_csrf_token()}
            
            response = self.session.post(
                f'{self.base_url}/upload',
                files=files,
                data=data,
                headers=headers
            )
            
        return response.json()
    
    def start_strategy(self, strategy_id):
        headers = {'X-CSRFToken': self.get_csrf_token()}
        response = self.session.post(
            f'{self.base_url}/start/{strategy_id}',
            headers=headers
        )
        return response.json()
    
    def stop_strategy(self, strategy_id):
        headers = {'X-CSRFToken': self.get_csrf_token()}
        response = self.session.post(
            f'{self.base_url}/stop/{strategy_id}',
            headers=headers
        )
        return response.json()
    
    def get_status(self):
        response = self.session.get(f'{self.base_url}/status')
        return response.json()

# Usage
client = StrategyAPIClient()

# Upload and start strategy
result = client.upload_strategy('my_strategy.py', 'Test Strategy')
strategy_id = result['strategy_id']

client.start_strategy(strategy_id)
print(f"Strategy {strategy_id} started")

# Check status
status = client.get_status()
print(f"Running: {status['running']} strategies")
```

## Changelog

### Version 1.0.0 (September 2024)
- Initial release
- Process isolation
- Scheduling system
- Code editor
- Export functionality
- Cross-platform support

---

*API Reference v1.0.0*
*Last Updated: September 2024*