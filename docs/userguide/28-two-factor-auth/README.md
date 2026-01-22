# 28 - Two-Factor Authentication

## Introduction

Two-Factor Authentication (2FA) adds an extra layer of security to your OpenAlgo account. Even if someone knows your password, they can't access your account without the second factor - a time-based code from your authenticator app.

## How 2FA Works

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                        Two-Factor Authentication                            │
│                                                                              │
│  Normal Login:                                                              │
│  ┌──────────────┐                                                           │
│  │  Password    │────────────────────────────────▶ Access Granted          │
│  └──────────────┘                                                           │
│                                                                              │
│  With 2FA:                                                                  │
│  ┌──────────────┐     ┌──────────────┐                                     │
│  │  Password    │────▶│  TOTP Code   │─────────────▶ Access Granted        │
│  └──────────────┘     └──────────────┘                                     │
│         │                    │                                              │
│   Something you          Something you                                      │
│      KNOW                   HAVE                                            │
│                        (Authenticator App)                                  │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

## Why Enable 2FA?

| Threat | Without 2FA | With 2FA |
|--------|-------------|----------|
| Password stolen | ❌ Account compromised | ✅ Still protected |
| Phishing attack | ❌ Login possible | ✅ Code also needed |
| Credential reuse | ❌ If breached elsewhere | ✅ Code is unique |
| Keylogger | ❌ Password captured | ✅ Code changes every 30s |

## Setting Up 2FA

### Prerequisites

Install an authenticator app:

| App | Platform | Download |
|-----|----------|----------|
| Google Authenticator | iOS, Android | App Store / Play Store |
| Microsoft Authenticator | iOS, Android | App Store / Play Store |
| Authy | iOS, Android, Desktop | authy.com |
| 1Password | All platforms | 1password.com |

### Step 1: Access TOTP Settings

1. Go to **Settings** → **Security**
2. Find **Two-Factor Authentication**
3. Click **Enable 2FA**

### Step 2: Scan QR Code

```
┌─────────────────────────────────────────────────────────────────────────────┐
│  Enable Two-Factor Authentication                                           │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  Step 1: Scan QR Code                                                       │
│                                                                              │
│  ┌─────────────────────────────────────┐                                    │
│  │  ██████████████████████████████    │                                    │
│  │  ██                          ██    │                                    │
│  │  ██  ████████████████████    ██    │                                    │
│  │  ██  ██              ██      ██    │                                    │
│  │  ██  ██  ██████████  ██      ██    │ ← Scan with authenticator app     │
│  │  ██  ██              ██      ██    │                                    │
│  │  ██  ████████████████████    ██    │                                    │
│  │  ██                          ██    │                                    │
│  │  ██████████████████████████████    │                                    │
│  └─────────────────────────────────────┘                                    │
│                                                                              │
│  Can't scan? Enter this code manually:                                      │
│  JBSWY3DPEHPK3PXP                                                          │
│                                                                              │
│  Step 2: Enter Verification Code                                            │
│                                                                              │
│  ┌────┐ ┌────┐ ┌────┐ ┌────┐ ┌────┐ ┌────┐                                │
│  │    │ │    │ │    │ │    │ │    │ │    │                                │
│  └────┘ └────┘ └────┘ └────┘ └────┘ └────┘                                │
│                                                                              │
│  ┌──────────────────┐                                                       │
│  │  Verify & Enable │                                                       │
│  └──────────────────┘                                                       │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

### Step 3: Verify Code

1. Open authenticator app
2. Find the OpenAlgo entry
3. Enter the 6-digit code
4. Click **Verify & Enable**

### Step 4: Save Recovery Codes

```
┌─────────────────────────────────────────────────────────────────────────────┐
│  ⚠️ Save Your Recovery Codes                                                │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  These codes can be used to access your account if you lose your           │
│  authenticator device. Each code can only be used once.                    │
│                                                                              │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │  1. 8f4k-2m9n-7p3q                                                   │   │
│  │  2. 5t6y-1u2i-3o4p                                                   │   │
│  │  3. 9a8s-7d6f-5g4h                                                   │   │
│  │  4. 2z3x-4c5v-6b7n                                                   │   │
│  │  5. 1q2w-3e4r-5t6y                                                   │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│                                                                              │
│  ┌────────────────┐  ┌────────────────┐                                    │
│  │  Download PDF  │  │  Copy to Clip  │                                    │
│  └────────────────┘  └────────────────┘                                    │
│                                                                              │
│  ☑ I have saved my recovery codes in a safe place                          │
│                                                                              │
│  ┌──────────────────┐                                                       │
│  │  Continue        │                                                       │
│  └──────────────────┘                                                       │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

**Important**: Store recovery codes safely:
- Print and store securely
- Save in password manager
- Don't store on the same device

## Logging In with 2FA

### Login Flow

1. Enter username and password
2. Click **Login**
3. Enter 6-digit code from authenticator
4. Click **Verify**

```
┌─────────────────────────────────────────────────────────────────────────────┐
│  Two-Factor Verification                                                    │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  Enter the 6-digit code from your authenticator app                        │
│                                                                              │
│  ┌────┐ ┌────┐ ┌────┐ ┌────┐ ┌────┐ ┌────┐                                │
│  │ 1  │ │ 2  │ │ 3  │ │ 4  │ │ 5  │ │ 6  │                                │
│  └────┘ └────┘ └────┘ └────┘ └────┘ └────┘                                │
│                                                                              │
│  Code expires in: 18 seconds                                                │
│                                                                              │
│  ┌──────────────────┐                                                       │
│  │     Verify       │                                                       │
│  └──────────────────┘                                                       │
│                                                                              │
│  Lost access to authenticator? Use recovery code                           │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

### Using Recovery Code

If you lose access to your authenticator:

1. Click **Use recovery code**
2. Enter one of your recovery codes
3. Access granted
4. Set up new authenticator immediately

## Managing 2FA

### Viewing 2FA Status

```
┌─────────────────────────────────────────────────────────────────────────────┐
│  Two-Factor Authentication                                                  │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  Status: ✅ Enabled                                                         │
│  Enabled on: 2025-01-15                                                     │
│  Authenticator: Google Authenticator                                        │
│                                                                              │
│  Recovery codes remaining: 4 of 5                                           │
│                                                                              │
│  ┌────────────────────────┐  ┌────────────────────────┐                    │
│  │  Regenerate Codes      │  │  Disable 2FA           │                    │
│  └────────────────────────┘  └────────────────────────┘                    │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

### Regenerating Recovery Codes

1. Go to **Settings** → **Security**
2. Click **Regenerate Codes**
3. Enter your 2FA code to confirm
4. New codes are generated
5. Old codes are invalidated
6. Save new codes securely

### Changing Authenticator App

1. Disable 2FA (requires current code)
2. Re-enable 2FA
3. Scan new QR code with new app
4. Save new recovery codes

### Disabling 2FA

1. Go to **Settings** → **Security**
2. Click **Disable 2FA**
3. Enter your password
4. Enter current 2FA code
5. Confirm action

**Warning**: Disabling 2FA reduces your account security.

## Troubleshooting

### Code Not Working

| Issue | Solution |
|-------|----------|
| Code expired | Wait for new code (30 seconds) |
| Time sync issue | Sync phone time to network |
| Wrong account | Verify you're using OpenAlgo entry |
| Typo | Re-enter code carefully |

### Lost Authenticator Access

1. Use recovery code
2. If no recovery codes, contact support
3. Identity verification required
4. Account recovery process initiated

### Time Sync Issue

TOTP codes depend on time synchronization:

**Android:**
1. Settings → Date & Time
2. Enable "Automatic date & time"

**iOS:**
1. Settings → General → Date & Time
2. Enable "Set Automatically"

**Authenticator App:**
- Google Authenticator: Settings → Time correction for codes → Sync now

## Security Best Practices

### 1. Protect Your Authenticator

- Use device lock (PIN, fingerprint, Face ID)
- Don't root/jailbreak device
- Keep app updated

### 2. Backup Your Codes

- Store recovery codes offline
- Use secure password manager
- Don't store on same device as authenticator

### 3. Multiple Devices (Authy)

If using Authy:
- Enable multi-device temporarily
- Add to backup device
- Disable multi-device after setup

### 4. Account Recovery Plan

Know your recovery options:
- Recovery codes location
- Support contact information
- Alternative verification methods

## 2FA for API Access

API keys work independently of 2FA:
- API key authentication doesn't require 2FA
- Protect API keys separately
- Consider IP whitelisting for API

```
Web Login: Password + 2FA Code
API Access: API Key only (2FA not required)
```

## Frequently Asked Questions

### Q: Is 2FA required?

A: No, but strongly recommended for account security.

### Q: What if I get a new phone?

A:
1. Set up authenticator on new phone
2. Use recovery code if needed
3. Re-enable 2FA with new device

### Q: Can I use SMS instead?

A: No, OpenAlgo uses TOTP apps only (more secure than SMS).

### Q: Will 2FA slow down my login?

A: Adds ~5 seconds for code entry. Worth it for security.

### Q: What authenticator apps work?

A: Any TOTP-compatible app (Google Authenticator, Authy, 1Password, etc.)

---

**Previous**: [27 - Security Settings](../27-security-settings/README.md)

**Next**: [29 - Troubleshooting](../29-troubleshooting/README.md)
