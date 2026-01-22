# 51 - Broker and System Config

## Overview

The Profile section in OpenAlgo provides configuration interfaces for broker credentials and system settings. These settings are stored in the `.env` file and database, with security measures for sensitive data.

## Architecture Diagram

```
┌──────────────────────────────────────────────────────────────────────────────┐
│                    Broker & System Configuration Architecture                 │
└──────────────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────────────┐
│                           Profile Section                                    │
│                           /profile                                           │
│                                                                              │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │  [Broker Config]  [System Settings]  [Security]  [About]            │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│                                                                              │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │                    Broker Configuration                              │   │
│  │                                                                      │   │
│  │  Select Broker: [Zerodha            ▼]                              │   │
│  │                                                                      │   │
│  │  API Key:      [kite_api_key_xxxx              ]                    │   │
│  │  API Secret:   [••••••••••••••••••             ]                    │   │
│  │  User ID:      [AB1234                         ]                    │   │
│  │  Password:     [••••••••                       ]                    │   │
│  │  TOTP Key:     [••••••••••••                   ]                    │   │
│  │                                                                      │   │
│  │  [Test Connection]  [Save Changes]                                  │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│                                                                              │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │                    System Settings                                   │   │
│  │                                                                      │   │
│  │  App Host:     [127.0.0.1                      ]                    │   │
│  │  App Port:     [5000                           ]                    │   │
│  │  Debug Mode:   [ ] Enabled                                          │   │
│  │  Log Level:    [INFO                  ▼]                            │   │
│  │                                                                      │   │
│  │  WebSocket Host: [127.0.0.1                    ]                    │   │
│  │  WebSocket Port: [8765                         ]                    │   │
│  │                                                                      │   │
│  │  [Save Settings]                                                    │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────────────────┘
                                     │
                                     │ Save
                                     │
                                     ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                         Configuration Storage                                │
│                                                                              │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │                      .env File                                       │   │
│  │                                                                      │   │
│  │  # Broker Configuration                                             │   │
│  │  BROKER_API_KEY=kite_api_key_xxxx                                   │   │
│  │  BROKER_API_SECRET=encrypted_or_masked                              │   │
│  │  BROKER=zerodha                                                     │   │
│  │                                                                      │   │
│  │  # System Configuration                                             │   │
│  │  FLASK_HOST=127.0.0.1                                               │   │
│  │  FLASK_PORT=5000                                                    │   │
│  │  FLASK_DEBUG=False                                                  │   │
│  │                                                                      │   │
│  │  # WebSocket Configuration                                          │   │
│  │  WEBSOCKET_HOST=127.0.0.1                                           │   │
│  │  WEBSOCKET_PORT=8765                                                │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│                                                                              │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │                    Database (Encrypted)                              │   │
│  │                                                                      │   │
│  │  broker_credentials table                                           │   │
│  │  • Sensitive values encrypted with Fernet                           │   │
│  │  • Access tokens refreshed automatically                            │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────────────────┘
```

## Broker Configuration

### Supported Brokers

| Broker | Auth Type | Required Fields |
|--------|-----------|-----------------|
| Zerodha | OAuth2 | API Key, API Secret |
| Dhan | API Key | Client ID, Access Token |
| Angel One | API Key | API Key, Client Code, Password, TOTP |
| 5paisa | OAuth2 | User ID, Password, 2FA |
| Flattrade | API Key | User ID, API Key, API Secret |
| Upstox | OAuth2 | API Key, API Secret |
| Fyers | OAuth2 | App ID, Secret ID |
| IIFL | API Key | API Key, Password |
| ... | ... | ... |

### Broker-Specific Validation

```python
BROKER_FIELD_PATTERNS = {
    'zerodha': {
        'api_key': r'^[a-z0-9]{16}$',  # 16 alphanumeric
        'api_secret': r'^[A-Za-z0-9]{32}$'  # 32 alphanumeric
    },
    'dhan': {
        'client_id': r'^\d{10}$',  # 10 digits
        'access_token': r'^[a-zA-Z0-9]+$'
    },
    '5paisa': {
        'user_id': r'^[A-Z0-9]{8}$',  # 8 alphanumeric uppercase
        'encryption_key': r'^[A-Za-z0-9]{32}$'
    },
    'flattrade': {
        'user_id': r'^[A-Z]{2}\d{6}$',  # 2 letters + 6 digits
        'api_key': r'^[A-Za-z0-9]{32}$'
    }
}

def validate_broker_credentials(broker, credentials):
    """Validate broker credentials format"""
    patterns = BROKER_FIELD_PATTERNS.get(broker, {})
    errors = []

    for field, pattern in patterns.items():
        value = credentials.get(field, '')
        if not re.match(pattern, value):
            errors.append(f"Invalid {field} format for {broker}")

    return len(errors) == 0, errors
```

### Credential Masking

```python
def mask_sensitive_value(value, visible_chars=4):
    """Mask sensitive values for display"""
    if not value:
        return ''
    if len(value) <= visible_chars:
        return '•' * len(value)
    return value[:visible_chars] + '•' * (len(value) - visible_chars)

def get_masked_credentials(broker):
    """Get credentials with sensitive fields masked"""
    creds = get_broker_credentials(broker)

    masked = {}
    sensitive_fields = ['api_secret', 'password', 'totp_key', 'access_token']

    for key, value in creds.items():
        if key in sensitive_fields:
            masked[key] = mask_sensitive_value(value)
        else:
            masked[key] = value

    return masked
```

## System Configuration

### Environment Variables

```
┌────────────────────────────────────────────────────────────────────────────┐
│                    System Configuration Variables                           │
│                                                                             │
│  Flask Application                                                          │
│  ─────────────────                                                          │
│  FLASK_HOST       = 127.0.0.1        # Bind address                        │
│  FLASK_PORT       = 5000             # HTTP port                           │
│  FLASK_DEBUG      = False            # Debug mode                          │
│  SECRET_KEY       = xxxxxx           # Session encryption                   │
│                                                                             │
│  WebSocket Server                                                           │
│  ─────────────────                                                          │
│  WEBSOCKET_HOST   = 127.0.0.1        # WebSocket bind                      │
│  WEBSOCKET_PORT   = 8765             # WebSocket port                      │
│  ZMQ_PORT         = 5555             # ZeroMQ port                         │
│                                                                             │
│  Database                                                                   │
│  ─────────────────                                                          │
│  DATABASE_URL     = sqlite:///db/openalgo.db                               │
│  LOGS_DB_URL      = sqlite:///db/logs.db                                   │
│                                                                             │
│  Logging                                                                    │
│  ─────────────────                                                          │
│  LOG_LEVEL        = INFO             # DEBUG/INFO/WARNING/ERROR            │
│  LOG_FILE         = logs/app.log     # Log file path                       │
│                                                                             │
│  Rate Limiting                                                              │
│  ─────────────────                                                          │
│  RATE_LIMIT_ORDER = 10/second        # Order endpoints                     │
│  RATE_LIMIT_DATA  = 3/second         # Data endpoints                      │
│                                                                             │
└────────────────────────────────────────────────────────────────────────────┘
```

### Configuration Update Service

```python
import os
from dotenv import set_key, dotenv_values

ENV_FILE_PATH = '.env'

def update_env_variable(key, value):
    """Update single environment variable"""
    # Update .env file
    set_key(ENV_FILE_PATH, key, value)

    # Update runtime environment
    os.environ[key] = value

    return True

def update_broker_config(broker, credentials):
    """Update broker configuration"""
    # Validate credentials
    valid, errors = validate_broker_credentials(broker, credentials)
    if not valid:
        return False, errors

    # Update .env
    updates = {
        'BROKER': broker,
        f'{broker.upper()}_API_KEY': credentials.get('api_key', ''),
        f'{broker.upper()}_API_SECRET': credentials.get('api_secret', ''),
    }

    for key, value in updates.items():
        update_env_variable(key, value)

    return True, None

def update_system_config(settings):
    """Update system configuration"""
    allowed_keys = [
        'FLASK_HOST', 'FLASK_PORT', 'FLASK_DEBUG',
        'WEBSOCKET_HOST', 'WEBSOCKET_PORT',
        'LOG_LEVEL'
    ]

    for key, value in settings.items():
        if key in allowed_keys:
            update_env_variable(key, str(value))

    return True
```

## API Endpoints

### Get Broker Config

```
GET /api/settings/broker
Authorization: Bearer ADMIN_TOKEN
```

**Response:**
```json
{
    "status": "success",
    "data": {
        "broker": "zerodha",
        "credentials": {
            "api_key": "kite_xxxx",
            "api_secret": "xxxx••••••••••••••••••••••••",
            "user_id": "AB1234"
        },
        "status": "connected"
    }
}
```

### Update Broker Config

```
POST /api/settings/broker
Content-Type: application/json
Authorization: Bearer ADMIN_TOKEN

{
    "broker": "zerodha",
    "credentials": {
        "api_key": "kite_api_key",
        "api_secret": "kite_api_secret"
    }
}
```

### Get System Config

```
GET /api/settings/system
Authorization: Bearer ADMIN_TOKEN
```

**Response:**
```json
{
    "status": "success",
    "data": {
        "flask_host": "127.0.0.1",
        "flask_port": 5000,
        "flask_debug": false,
        "websocket_host": "127.0.0.1",
        "websocket_port": 8765,
        "log_level": "INFO"
    }
}
```

### Update System Config

```
POST /api/settings/system
Content-Type: application/json
Authorization: Bearer ADMIN_TOKEN

{
    "flask_debug": true,
    "log_level": "DEBUG"
}
```

### Test Broker Connection

```
POST /api/settings/broker/test
Authorization: Bearer ADMIN_TOKEN
```

**Response:**
```json
{
    "status": "success",
    "message": "Connection successful",
    "data": {
        "broker": "zerodha",
        "user_id": "AB1234",
        "user_name": "John Doe"
    }
}
```

## Frontend Components

### Broker Config Form

```typescript
function BrokerConfig() {
  const [broker, setBroker] = useState('');
  const [credentials, setCredentials] = useState<Record<string, string>>({});
  const [testing, setTesting] = useState(false);

  const brokerFields = {
    zerodha: ['api_key', 'api_secret'],
    dhan: ['client_id', 'access_token'],
    angel: ['api_key', 'client_code', 'password', 'totp_key'],
    '5paisa': ['user_id', 'password', 'encryption_key'],
    flattrade: ['user_id', 'api_key', 'api_secret']
  };

  const testConnection = async () => {
    setTesting(true);
    try {
      const result = await api.testBrokerConnection();
      toast.success(`Connected as ${result.user_name}`);
    } catch (e) {
      toast.error('Connection failed');
    }
    setTesting(false);
  };

  const saveConfig = async () => {
    await api.updateBrokerConfig(broker, credentials);
    toast.success('Configuration saved');
  };

  return (
    <div className="card bg-base-200 p-6">
      <h2 className="text-xl font-semibold mb-4">Broker Configuration</h2>

      <div className="form-control mb-4">
        <label className="label">Select Broker</label>
        <select
          value={broker}
          onChange={(e) => setBroker(e.target.value)}
          className="select select-bordered"
        >
          <option value="">Select...</option>
          {Object.keys(brokerFields).map(b => (
            <option key={b} value={b}>{b.charAt(0).toUpperCase() + b.slice(1)}</option>
          ))}
        </select>
      </div>

      {broker && brokerFields[broker]?.map(field => (
        <div key={field} className="form-control mb-4">
          <label className="label">{formatFieldName(field)}</label>
          <input
            type={isSensitiveField(field) ? 'password' : 'text'}
            value={credentials[field] || ''}
            onChange={(e) => setCredentials({...credentials, [field]: e.target.value})}
            className="input input-bordered"
            placeholder={`Enter ${formatFieldName(field)}`}
          />
        </div>
      ))}

      <div className="flex gap-2 mt-4">
        <button
          onClick={testConnection}
          disabled={testing}
          className="btn btn-secondary"
        >
          {testing ? <span className="loading loading-spinner" /> : 'Test Connection'}
        </button>
        <button onClick={saveConfig} className="btn btn-primary">
          Save Changes
        </button>
      </div>
    </div>
  );
}
```

### System Settings Form

```typescript
function SystemSettings() {
  const [settings, setSettings] = useState({
    flask_host: '127.0.0.1',
    flask_port: 5000,
    flask_debug: false,
    websocket_host: '127.0.0.1',
    websocket_port: 8765,
    log_level: 'INFO'
  });

  const saveSettings = async () => {
    await api.updateSystemConfig(settings);
    toast.success('Settings saved. Restart required for some changes.');
  };

  return (
    <div className="card bg-base-200 p-6">
      <h2 className="text-xl font-semibold mb-4">System Settings</h2>

      <div className="grid grid-cols-2 gap-4">
        <div className="form-control">
          <label className="label">App Host</label>
          <input
            type="text"
            value={settings.flask_host}
            onChange={(e) => setSettings({...settings, flask_host: e.target.value})}
            className="input input-bordered"
          />
        </div>

        <div className="form-control">
          <label className="label">App Port</label>
          <input
            type="number"
            value={settings.flask_port}
            onChange={(e) => setSettings({...settings, flask_port: parseInt(e.target.value)})}
            className="input input-bordered"
          />
        </div>

        <div className="form-control">
          <label className="label">WebSocket Host</label>
          <input
            type="text"
            value={settings.websocket_host}
            onChange={(e) => setSettings({...settings, websocket_host: e.target.value})}
            className="input input-bordered"
          />
        </div>

        <div className="form-control">
          <label className="label">WebSocket Port</label>
          <input
            type="number"
            value={settings.websocket_port}
            onChange={(e) => setSettings({...settings, websocket_port: parseInt(e.target.value)})}
            className="input input-bordered"
          />
        </div>

        <div className="form-control">
          <label className="label">Log Level</label>
          <select
            value={settings.log_level}
            onChange={(e) => setSettings({...settings, log_level: e.target.value})}
            className="select select-bordered"
          >
            <option value="DEBUG">DEBUG</option>
            <option value="INFO">INFO</option>
            <option value="WARNING">WARNING</option>
            <option value="ERROR">ERROR</option>
          </select>
        </div>

        <div className="form-control">
          <label className="label cursor-pointer">
            <span className="label-text">Debug Mode</span>
            <input
              type="checkbox"
              checked={settings.flask_debug}
              onChange={(e) => setSettings({...settings, flask_debug: e.target.checked})}
              className="checkbox"
            />
          </label>
        </div>
      </div>

      <div className="mt-4">
        <button onClick={saveSettings} className="btn btn-primary">
          Save Settings
        </button>
      </div>

      <div className="alert alert-warning mt-4">
        <span>Some changes require application restart to take effect.</span>
      </div>
    </div>
  );
}
```

## Security Measures

### Credential Protection

```
┌────────────────────────────────────────────────────────────────────────────┐
│                     Credential Security Measures                            │
│                                                                             │
│  1. Storage                                                                 │
│     • API secrets encrypted with Fernet before database storage            │
│     • .env file permissions restricted (600 on Unix)                       │
│                                                                             │
│  2. Display                                                                 │
│     • Sensitive fields masked in UI (••••)                                 │
│     • Only partial values shown in API responses                           │
│                                                                             │
│  3. Access                                                                  │
│     • Admin-only endpoints for configuration                               │
│     • CSRF protection on all forms                                         │
│     • Rate limiting on config endpoints                                    │
│                                                                             │
│  4. Audit                                                                   │
│     • Configuration changes logged                                         │
│     • Failed authentication attempts tracked                               │
│                                                                             │
└────────────────────────────────────────────────────────────────────────────┘
```

### Permission Checking

```python
def check_config_permissions():
    """Check if config files have secure permissions"""
    import stat

    env_path = '.env'
    if os.path.exists(env_path):
        mode = os.stat(env_path).st_mode
        if mode & stat.S_IROTH or mode & stat.S_IWOTH:
            logger.warning(".env file has insecure permissions")
            return False, "Config file permissions too open"

    return True, None
```

## Key Files Reference

| File | Purpose |
|------|---------|
| `blueprints/settings.py` | Configuration routes |
| `services/config_service.py` | Config management logic |
| `utils/env_utils.py` | .env file utilities |
| `database/broker_db.py` | Broker credentials model |
| `frontend/src/pages/Profile.tsx` | Profile page |
| `frontend/src/components/BrokerConfig.tsx` | Broker settings UI |
| `frontend/src/components/SystemSettings.tsx` | System settings UI |
