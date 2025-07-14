# Database Schema Design for Zero-Config Broker Setup

## Overview

This document details the database schema changes required to implement the zero-config broker setup system in OpenAlgo. The new schema will store encrypted broker credentials per user, replacing the need for manual `.env` configuration.

## Current Database Structure

### Existing Tables

#### `users` table
```sql
CREATE TABLE users (
    id INTEGER PRIMARY KEY,
    username VARCHAR(80) UNIQUE NOT NULL,
    email VARCHAR(120) UNIQUE NOT NULL,
    password_hash VARCHAR(255) NOT NULL,
    totp_secret VARCHAR(32) NOT NULL,
    is_admin BOOLEAN DEFAULT FALSE
);
```

#### `auth` table
```sql
CREATE TABLE auth (
    id INTEGER PRIMARY KEY,
    name VARCHAR(255) UNIQUE NOT NULL,
    auth TEXT NOT NULL,
    feed_token TEXT,
    broker VARCHAR(20) NOT NULL,
    user_id VARCHAR(255),
    is_revoked BOOLEAN DEFAULT FALSE
);
```

## New Database Schema

### Primary Table: `broker_configs`

```sql
CREATE TABLE broker_configs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id VARCHAR(255) NOT NULL,
    broker_name VARCHAR(20) NOT NULL,
    display_name VARCHAR(100),
    api_key_encrypted TEXT NOT NULL,
    api_secret_encrypted TEXT NOT NULL,
    market_api_key_encrypted TEXT,
    market_api_secret_encrypted TEXT,
    redirect_url VARCHAR(500),
    additional_config TEXT,  -- JSON field for broker-specific configs
    is_active BOOLEAN DEFAULT TRUE,
    is_default BOOLEAN DEFAULT FALSE,
    connection_status VARCHAR(20) DEFAULT 'untested',  -- untested, valid, invalid, expired
    last_validated TIMESTAMP,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    
    -- Constraints
    UNIQUE(user_id, broker_name),
    FOREIGN KEY(user_id) REFERENCES users(username) ON DELETE CASCADE,
    
    -- Ensure only one default broker per user
    UNIQUE(user_id, is_default) WHERE is_default = TRUE
);
```

### Supporting Table: `broker_templates`

```sql
CREATE TABLE broker_templates (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    broker_name VARCHAR(20) UNIQUE NOT NULL,
    display_name VARCHAR(100) NOT NULL,
    description TEXT,
    logo_url VARCHAR(255),
    redirect_url_template VARCHAR(500),
    required_fields TEXT NOT NULL,  -- JSON array of required field definitions
    optional_fields TEXT,           -- JSON array of optional field definitions
    documentation_url VARCHAR(255),
    is_active BOOLEAN DEFAULT TRUE,
    supports_market_data BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

### Audit Table: `broker_config_audit`

```sql
CREATE TABLE broker_config_audit (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    broker_config_id INTEGER NOT NULL,
    user_id VARCHAR(255) NOT NULL,
    action VARCHAR(20) NOT NULL,  -- create, update, delete, activate, deactivate
    old_values TEXT,              -- JSON of previous values
    new_values TEXT,              -- JSON of new values
    ip_address VARCHAR(45),
    user_agent TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    
    FOREIGN KEY(broker_config_id) REFERENCES broker_configs(id) ON DELETE CASCADE,
    FOREIGN KEY(user_id) REFERENCES users(username) ON DELETE CASCADE
);
```

## Field Definitions and Constraints

### `broker_configs` Table Fields

| Field | Type | Constraints | Description |
|-------|------|-------------|-------------|
| `id` | INTEGER | PRIMARY KEY | Auto-incrementing unique identifier |
| `user_id` | VARCHAR(255) | NOT NULL, FK | References users.username |
| `broker_name` | VARCHAR(20) | NOT NULL | Broker identifier (dhan, angel, etc.) |
| `display_name` | VARCHAR(100) | NULL | User-friendly broker name |
| `api_key_encrypted` | TEXT | NOT NULL | Encrypted API key |
| `api_secret_encrypted` | TEXT | NOT NULL | Encrypted API secret |
| `market_api_key_encrypted` | TEXT | NULL | Encrypted market data API key |
| `market_api_secret_encrypted` | TEXT | NULL | Encrypted market data API secret |
| `redirect_url` | VARCHAR(500) | NULL | OAuth redirect URL |
| `additional_config` | TEXT | NULL | JSON for broker-specific configuration |
| `is_active` | BOOLEAN | DEFAULT TRUE | Whether config is active |
| `is_default` | BOOLEAN | DEFAULT FALSE | Default broker for user |
| `connection_status` | VARCHAR(20) | DEFAULT 'untested' | Last connection test result |
| `last_validated` | TIMESTAMP | NULL | Last successful validation |
| `created_at` | TIMESTAMP | DEFAULT NOW | Creation timestamp |
| `updated_at` | TIMESTAMP | DEFAULT NOW | Last update timestamp |

### `broker_templates` Table Fields

| Field | Type | Constraints | Description |
|-------|------|-------------|-------------|
| `id` | INTEGER | PRIMARY KEY | Auto-incrementing unique identifier |
| `broker_name` | VARCHAR(20) | UNIQUE NOT NULL | Broker identifier |
| `display_name` | VARCHAR(100) | NOT NULL | Display name for UI |
| `description` | TEXT | NULL | Broker description |
| `logo_url` | VARCHAR(255) | NULL | Broker logo image URL |
| `redirect_url_template` | VARCHAR(500) | NULL | Template for redirect URL |
| `required_fields` | TEXT | NOT NULL | JSON array of required fields |
| `optional_fields` | TEXT | NULL | JSON array of optional fields |
| `documentation_url` | VARCHAR(255) | NULL | Link to broker API docs |
| `is_active` | BOOLEAN | DEFAULT TRUE | Whether broker is supported |
| `supports_market_data` | BOOLEAN | DEFAULT FALSE | Market data API support |
| `is_xts_broker` | BOOLEAN | DEFAULT FALSE | Whether broker uses XTS API |

## JSON Schema Definitions

### `required_fields` and `optional_fields` JSON Schema

```json
{
  "type": "array",
  "items": {
    "type": "object",
    "properties": {
      "name": {
        "type": "string",
        "description": "Field name for database storage"
      },
      "label": {
        "type": "string",
        "description": "Display label for UI"
      },
      "type": {
        "type": "string",
        "enum": ["text", "password", "email", "url", "number"],
        "description": "Input field type"
      },
      "placeholder": {
        "type": "string",
        "description": "Placeholder text"
      },
      "help_text": {
        "type": "string",
        "description": "Help text for users"
      },
      "validation": {
        "type": "object",
        "properties": {
          "min_length": {"type": "integer"},
          "max_length": {"type": "integer"},
          "pattern": {"type": "string"},
          "required": {"type": "boolean"}
        }
      }
    },
    "required": ["name", "label", "type"]
  }
}
```

### `additional_config` JSON Schema

```json
{
  "type": "object",
  "description": "Broker-specific configuration",
  "additionalProperties": true,
  "examples": [
    {
      "client_id": "encrypted_value",
      "environment": "production",
      "timeout": 30,
      "retry_attempts": 3
    }
  ]
}
```

## Encryption Strategy

### Encryption Implementation
```python
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
import base64
import os

def get_encryption_key():
    """Generate Fernet key from existing pepper"""
    pepper = os.getenv('API_KEY_PEPPER', 'default-pepper')
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=b'openalgo_broker_salt',
        iterations=100000,
    )
    key = base64.urlsafe_b64encode(kdf.derive(pepper.encode()))
    return Fernet(key)

def encrypt_credential(value):
    """Encrypt sensitive credential"""
    if not value:
        return None
    fernet = get_encryption_key()
    return fernet.encrypt(value.encode()).decode()

def decrypt_credential(encrypted_value):
    """Decrypt sensitive credential"""
    if not encrypted_value:
        return None
    try:
        fernet = get_encryption_key()
        return fernet.decrypt(encrypted_value.encode()).decode()
    except Exception:
        return None
```

### Fields to Encrypt
- `api_key_encrypted`
- `api_secret_encrypted`
- `market_api_key_encrypted`
- `market_api_secret_encrypted`
- Any sensitive fields in `additional_config`

## Database Indexes

### Performance Indexes
```sql
-- Primary lookups
CREATE INDEX idx_broker_configs_user_id ON broker_configs(user_id);
CREATE INDEX idx_broker_configs_broker_name ON broker_configs(broker_name);
CREATE INDEX idx_broker_configs_user_broker ON broker_configs(user_id, broker_name);

-- Status queries
CREATE INDEX idx_broker_configs_active ON broker_configs(user_id, is_active);
CREATE INDEX idx_broker_configs_default ON broker_configs(user_id, is_default) WHERE is_default = TRUE;

-- Validation queries
CREATE INDEX idx_broker_configs_status ON broker_configs(connection_status, last_validated);

-- Audit queries
CREATE INDEX idx_broker_audit_config_id ON broker_config_audit(broker_config_id);
CREATE INDEX idx_broker_audit_user_id ON broker_config_audit(user_id);
CREATE INDEX idx_broker_audit_created_at ON broker_config_audit(created_at);

-- Template queries
CREATE INDEX idx_broker_templates_name ON broker_templates(broker_name);
CREATE INDEX idx_broker_templates_active ON broker_templates(is_active);
```

## Migration Scripts

### Initial Schema Creation
```sql
-- Migration: 001_create_broker_configs.sql

-- Create broker_templates table
CREATE TABLE broker_templates (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    broker_name VARCHAR(20) UNIQUE NOT NULL,
    display_name VARCHAR(100) NOT NULL,
    description TEXT,
    logo_url VARCHAR(255),
    redirect_url_template VARCHAR(500),
    required_fields TEXT NOT NULL,
    optional_fields TEXT,
    documentation_url VARCHAR(255),
    is_active BOOLEAN DEFAULT TRUE,
    supports_market_data BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Create broker_configs table
CREATE TABLE broker_configs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id VARCHAR(255) NOT NULL,
    broker_name VARCHAR(20) NOT NULL,
    display_name VARCHAR(100),
    api_key_encrypted TEXT NOT NULL,
    api_secret_encrypted TEXT NOT NULL,
    market_api_key_encrypted TEXT,
    market_api_secret_encrypted TEXT,
    redirect_url VARCHAR(500),
    additional_config TEXT,
    is_active BOOLEAN DEFAULT TRUE,
    is_default BOOLEAN DEFAULT FALSE,
    connection_status VARCHAR(20) DEFAULT 'untested',
    last_validated TIMESTAMP,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    
    UNIQUE(user_id, broker_name),
    FOREIGN KEY(user_id) REFERENCES users(username) ON DELETE CASCADE
);

-- Create audit table
CREATE TABLE broker_config_audit (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    broker_config_id INTEGER NOT NULL,
    user_id VARCHAR(255) NOT NULL,
    action VARCHAR(20) NOT NULL,
    old_values TEXT,
    new_values TEXT,
    ip_address VARCHAR(45),
    user_agent TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    
    FOREIGN KEY(broker_config_id) REFERENCES broker_configs(id) ON DELETE CASCADE,
    FOREIGN KEY(user_id) REFERENCES users(username) ON DELETE CASCADE
);

-- Create indexes
CREATE INDEX idx_broker_configs_user_id ON broker_configs(user_id);
CREATE INDEX idx_broker_configs_broker_name ON broker_configs(broker_name);
CREATE INDEX idx_broker_configs_user_broker ON broker_configs(user_id, broker_name);
CREATE INDEX idx_broker_configs_active ON broker_configs(user_id, is_active);
CREATE INDEX idx_broker_configs_default ON broker_configs(user_id, is_default) WHERE is_default = TRUE;
CREATE INDEX idx_broker_configs_status ON broker_configs(connection_status, last_validated);
CREATE INDEX idx_broker_audit_config_id ON broker_config_audit(broker_config_id);
CREATE INDEX idx_broker_audit_user_id ON broker_config_audit(user_id);
CREATE INDEX idx_broker_audit_created_at ON broker_config_audit(created_at);
CREATE INDEX idx_broker_templates_name ON broker_templates(broker_name);
CREATE INDEX idx_broker_templates_active ON broker_templates(is_active);
```

### Default Template Data
```sql
-- Insert default broker templates
INSERT INTO broker_templates (broker_name, display_name, description, required_fields, supports_market_data, is_xts_broker) VALUES
-- Regular brokers
('dhan', 'Dhan', 'Dhan Securities broker integration', 
 '[{"name":"api_key","label":"API Key","type":"text","placeholder":"Enter your Dhan API Key"},{"name":"api_secret","label":"API Secret","type":"password","placeholder":"Enter your Dhan API Secret"}]', 
 true, false),
('angel', 'Angel One', 'Angel One (Angel Broking) integration',
 '[{"name":"api_key","label":"API Key","type":"text","placeholder":"Enter your Angel One API Key"},{"name":"api_secret","label":"API Secret","type":"password","placeholder":"Enter your Angel One API Secret"}]',
 true, false),
('zerodha', 'Zerodha', 'Zerodha Kite Connect integration',
 '[{"name":"api_key","label":"API Key","type":"text","placeholder":"Enter your Kite Connect API Key"},{"name":"api_secret","label":"API Secret","type":"password","placeholder":"Enter your Kite Connect API Secret"}]',
 false, false),

-- XTS-based brokers (require market data credentials)
('fivepaisaxts', '5Paisa XTS', '5Paisa XTS API integration',
 '[{"name":"api_key","label":"Trading API Key","type":"text","placeholder":"Enter your Trading API Key"},{"name":"api_secret","label":"Trading API Secret","type":"password","placeholder":"Enter your Trading API Secret"},{"name":"market_api_key","label":"Market Data API Key","type":"text","placeholder":"Enter your Market Data API Key"},{"name":"market_api_secret","label":"Market Data API Secret","type":"password","placeholder":"Enter your Market Data API Secret"}]',
 true, true),
('compositedge', 'Compositedge', 'Compositedge XTS API integration',
 '[{"name":"api_key","label":"Trading API Key","type":"text","placeholder":"Enter your Trading API Key"},{"name":"api_secret","label":"Trading API Secret","type":"password","placeholder":"Enter your Trading API Secret"},{"name":"market_api_key","label":"Market Data API Key","type":"text","placeholder":"Enter your Market Data API Key"},{"name":"market_api_secret","label":"Market Data API Secret","type":"password","placeholder":"Enter your Market Data API Secret"}]',
 true, true),
('iifl', 'IIFL', 'IIFL XTS API integration',
 '[{"name":"api_key","label":"Trading API Key","type":"text","placeholder":"Enter your Trading API Key"},{"name":"api_secret","label":"Trading API Secret","type":"password","placeholder":"Enter your Trading API Secret"},{"name":"market_api_key","label":"Market Data API Key","type":"text","placeholder":"Enter your Market Data API Key"},{"name":"market_api_secret","label":"Market Data API Secret","type":"password","placeholder":"Enter your Market Data API Secret"}]',
 true, true);
```

## Data Access Patterns

### Common Queries

#### Get User's Active Broker Configurations
```sql
SELECT id, broker_name, display_name, is_default, connection_status, last_validated
FROM broker_configs 
WHERE user_id = ? AND is_active = TRUE
ORDER BY is_default DESC, broker_name ASC;
```

#### Get Default Broker for User
```sql
SELECT * FROM broker_configs 
WHERE user_id = ? AND is_default = TRUE AND is_active = TRUE;
```

#### Get Broker Configuration for Authentication
```sql
SELECT api_key_encrypted, api_secret_encrypted, market_api_key_encrypted, market_api_secret_encrypted
FROM broker_configs 
WHERE user_id = ? AND broker_name = ? AND is_active = TRUE;
```

#### Update Connection Status
```sql
UPDATE broker_configs 
SET connection_status = ?, last_validated = CURRENT_TIMESTAMP, updated_at = CURRENT_TIMESTAMP
WHERE id = ?;
```

### Caching Strategy

#### Cache Keys
- `broker_config:{user_id}:{broker_name}` - Individual config
- `broker_configs:{user_id}` - All user configs
- `broker_default:{user_id}` - Default broker config
- `broker_templates:active` - Active broker templates

#### Cache TTL
- Broker configurations: 300 seconds (5 minutes)
- Broker templates: 3600 seconds (1 hour)
- Connection status: 60 seconds (1 minute)

## Security Considerations

### Data Protection
1. **Encryption at Rest**: All sensitive credentials encrypted using Fernet
2. **Key Management**: Encryption key derived from existing API_KEY_PEPPER
3. **Access Control**: User isolation through foreign key constraints
4. **Audit Trail**: Complete audit log of all configuration changes

### Input Validation
1. **Field Validation**: Validate all inputs against broker template definitions
2. **URL Validation**: Validate redirect URLs for security
3. **Length Limits**: Enforce maximum field lengths
4. **SQL Injection**: Use parameterized queries exclusively

### Rate Limiting
1. **Configuration Changes**: Limit broker configuration updates
2. **Connection Tests**: Limit broker connection test attempts
3. **Validation Requests**: Rate limit credential validation

## Performance Considerations

### Database Performance
1. **Indexes**: Comprehensive indexing strategy for common queries
2. **Connection Pooling**: Reuse database connections
3. **Query Optimization**: Optimized queries for common access patterns

### Application Performance
1. **Caching**: Aggressive caching of frequently accessed data
2. **Lazy Loading**: Load broker configs only when needed
3. **Background Validation**: Asynchronous credential validation

### Scalability
1. **Horizontal Scaling**: Schema supports database sharding by user_id
2. **Read Replicas**: Read-heavy queries can use replica databases
3. **Archival**: Old audit records can be archived

## Maintenance and Operations

### Regular Maintenance
1. **Audit Log Cleanup**: Archive old audit records
2. **Connection Validation**: Periodic validation of stored credentials
3. **Template Updates**: Keep broker templates current

### Monitoring
1. **Configuration Health**: Monitor broker configuration validity
2. **Usage Patterns**: Track which brokers are most used
3. **Error Rates**: Monitor authentication failure rates

### Backup and Recovery
1. **Encrypted Backups**: Ensure backups maintain encryption
2. **Key Recovery**: Secure key backup and recovery procedures
3. **Point-in-Time Recovery**: Support for configuration rollback

## Future Enhancements

### Advanced Features
1. **Configuration Versioning**: Track configuration changes over time
2. **Shared Configurations**: Team-based broker configurations
3. **Configuration Templates**: User-defined configuration templates
4. **Automated Validation**: Scheduled credential validation

### Integration Possibilities
1. **OAuth Integration**: Direct OAuth flows with brokers
2. **API Key Rotation**: Automated API key rotation
3. **Health Monitoring**: Real-time broker connection monitoring
4. **Analytics**: Usage analytics and reporting

This schema design provides a robust foundation for the zero-config broker setup system while maintaining security, performance, and scalability requirements.