# Secrets Management Assessment

## Overview

This assessment covers how OpenAlgo protects your sensitive data: broker credentials, API keys, and encryption secrets.

**Risk Level**: Critical (data sensitivity)
**Status**: Good

## What Secrets Does OpenAlgo Store?

| Secret | Where Stored | Protection | Why It Matters |
|--------|--------------|------------|----------------|
| Broker access token | Database | Fernet encryption | Access to your brokerage |
| Broker refresh token | Database | Fernet encryption | Token renewal |
| Your API key | Database | Hash + Encrypted | Webhook authentication |
| Login password | Database | Argon2 hash | Dashboard access |
| 2FA secret | Database | Fernet encryption | Two-factor auth |
| SMTP password | Database | AES encryption | Email notifications |

## Broker Credential Security

### This Is the Most Important Part

Your broker tokens allow:
- Placing orders
- Viewing positions
- Accessing funds
- Managing portfolio

### How Tokens Are Protected

**Location**: `database/auth_db.py`

```
Broker Login (OAuth)
        ↓
Access token received
        ↓
Token encrypted with Fernet
        ↓
Encrypted token stored in database
        ↓
Decrypted only when needed for API calls
```

**Fernet Encryption**:
- AES-128-CBC encryption
- HMAC-SHA256 authentication
- Based on your `APP_KEY`

### Token Lifecycle

1. **Login**: OAuth flow with broker
2. **Storage**: Encrypted immediately
3. **Usage**: Decrypted for broker API calls
4. **Refresh**: Auto-refreshed when expired
5. **Logout**: Tokens cleared from database

## Environment Secrets

### Critical Environment Variables

**Location**: `.env` file

| Variable | Purpose | How to Generate |
|----------|---------|-----------------|
| `APP_KEY` | Encryption key for Fernet | `python -c "import secrets; print(secrets.token_hex(32))"` |
| `API_KEY_PEPPER` | Additional hash input | `python -c "import secrets; print(secrets.token_hex(32))"` |

### Keeping `.env` Secure

**Already Protected**:
- `.env` is in `.gitignore`
- Won't be committed to git

**Your Responsibilities**:
1. Don't share `.env` file
2. Back up securely (encrypted backup recommended)
3. Use strong random values (not "password123")

### If You Lose Your APP_KEY

**Impact**:
- Can't decrypt stored broker tokens
- Can't decrypt stored API keys
- Need to re-login to brokers
- Need to regenerate API keys

**Recovery**:
1. Set new `APP_KEY` in `.env`
2. Login to brokers again (new OAuth flow)
3. Generate new API key
4. Update webhooks with new API key

## API Key Protection

### Dual Storage System

Your API key is stored twice:

1. **Hashed Version** (for authentication)
   ```python
   hashed = SHA256(api_key + pepper)
   ```
   - Used to verify incoming requests
   - Cannot be reversed

2. **Encrypted Version** (for display/broker ops)
   ```python
   encrypted = Fernet.encrypt(api_key)
   ```
   - Used when you need the actual key
   - Decryptable with APP_KEY

### Why Dual Storage?

- Hash provides fast, secure verification
- Encrypted version allows key recovery/display
- Compromise of hash doesn't expose key
- Pepper prevents rainbow table attacks

## SMTP Credentials (If Configured)

### For Email Notifications

If you've configured email alerts:

**Storage**: `database/settings_db.py`
**Protection**: AES encryption

### Current Implementation

```python
# Key derivation (current)
key = SHA256(APP_KEY)
```

**Note**: This is simpler than ideal key derivation, but acceptable for single-user where:
- Only you access the database
- APP_KEY is already high-entropy
- SMTP credentials have limited scope

### Recommendation

If concerned about SMTP security:
1. Use app-specific passwords (Gmail, etc.)
2. Use email services that support API keys
3. Limit SMTP account permissions

## Database Security

### SQLite Files

Your databases in `db/` directory:

| File | Contains | Sensitivity |
|------|----------|-------------|
| `openalgo.db` | Users, orders, settings | High |
| `logs.db` | API request logs | Medium |
| `sandbox.db` | Paper trading data | Low |
| `latency.db` | Performance metrics | Low |
| `historify.duckdb` | Historical prices | Low |

### Protection Layers

1. **Encryption at field level** - Sensitive fields encrypted
2. **Hashing for passwords** - Can't be reversed
3. **File system permissions** - OS-level protection

### Recommendations

1. **Enable disk encryption** on your machine (BitLocker, FileVault)
2. **Regular backups** of `.env` and `db/` folder
3. **Secure backup storage** - Encrypted cloud or offline

## What's Stored in Plaintext?

For transparency, these are NOT encrypted:

| Data | Why Plaintext | Risk |
|------|---------------|------|
| Symbol names | Need for queries | None |
| Order history | Need for display | Low |
| Exchange codes | Configuration | None |
| Webhook URLs | Need for requests | Low |
| SMTP host/port | Configuration | Low |

This is appropriate - encrypting everything would impact performance without security benefit.

## Security Checklist

### Your Setup

- [ ] Generated unique `APP_KEY` (not default)
- [ ] Generated unique `API_KEY_PEPPER` (not default)
- [ ] `.env` file is secure (not shared)
- [ ] Backup of `.env` exists (secure location)

### Best Practices

- [ ] Using disk encryption on host machine
- [ ] Regular backups of database folder
- [ ] Strong password for OS account
- [ ] Strong password for OpenAlgo login

## Recovery Scenarios

### Scenario 1: Lost `.env` File

**Impact**: Can't decrypt broker tokens or API keys
**Recovery**:
1. Create new `.env` with fresh secrets
2. Re-authenticate with all brokers
3. Generate new API key
4. Update all webhook configurations

### Scenario 2: Database Corrupted

**Impact**: Lose order history, need to re-login
**Recovery**:
1. Restore from backup, or
2. Delete `db/` folder, restart app
3. Re-authenticate with brokers
4. Generate new API key

### Scenario 3: Suspect Compromise

**Actions**:
1. Logout from OpenAlgo
2. Revoke broker tokens (in broker dashboard)
3. Generate new API key in OpenAlgo
4. Rotate `APP_KEY` and `API_KEY_PEPPER`
5. Re-authenticate with brokers

## Summary

**Good Security Practices Already Implemented**:
- Broker tokens encrypted at rest
- Passwords hashed with Argon2
- API keys hashed with pepper
- Sensitive data not logged

**Your Responsibilities**:
- Keep `.env` file secure
- Use strong secrets (not defaults)
- Enable disk encryption
- Maintain secure backups

---

**Back to**: [Security Audit Overview](./README.md)
