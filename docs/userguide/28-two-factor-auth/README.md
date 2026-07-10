# 28 - Two-Factor Authentication

## Overview

OpenAlgo supports time-based one-time passwords (TOTP) for the application account. TOTP can be required independently for web login, Remote MCP authorization, and password reset.

OpenAlgo TOTP is separate from any TOTP or PIN required by a broker adapter.

## Configure TOTP

1. Sign in and open **Profile**.
2. Select the **TOTP** tab.
3. Scan the displayed QR code with a compatible authenticator, or enter the displayed secret manually.
4. Enter the current six-digit code to verify the authenticator.
5. Enable TOTP and choose the purposes that should require it.

The user record receives a random TOTP secret when it is created. That secret is encrypted at rest with the installation's token-encryption key. The Profile route decrypts it only for the authenticated setup view.

## Purpose Controls

| Purpose | Effect when enabled |
|---|---|
| Login | Password authentication pauses until a valid TOTP code is submitted |
| Remote MCP | OAuth authorization for requested write scope requires a fresh TOTP verification |
| Password reset | The reset flow can require the account's TOTP code |

The master TOTP switch must be enabled for any purpose switch to take effect. Updating the preferences requires a valid current code.

## Login Flow

1. Submit the username and password.
2. When the server returns `totp_required`, enter the current six-digit code.
3. After verification, OpenAlgo resumes the normal broker-session check and dashboard flow.

The pending TOTP login state has a short lifetime. If it expires, restart the password step instead of repeatedly submitting an old code.

## API and MCP Behavior

OpenAlgo REST API keys authenticate independently of web-login TOTP. Protect the API key as a trading credential; enabling login TOTP does not add a TOTP prompt to each `/api/v1` request.

Remote MCP uses OAuth. When MCP TOTP is enabled and a client requests `write:orders`, the authorization page requires a fresh code before granting that scope. Read-only OAuth scopes follow the configured MCP approval policy without an order-write grant.

## Recovery and Device Changes

The current application does **not** generate one-time recovery codes. Do not rely on a recovery-code screen or support workflow that is not implemented.

Before replacing or wiping an authenticator device, transfer the OpenAlgo TOTP entry or retain the secret in a protected password manager. If no valid authenticator or secret remains, account recovery requires operator access to the self-hosted installation and should be handled as a privileged database/configuration recovery procedure.

## Troubleshooting

| Symptom | Check |
|---|---|
| Code rejected | Correct OpenAlgo entry, six digits, and automatic device time |
| Login returns to password | Pending TOTP state may have expired; start again |
| MCP write scope prompts again | Fresh-TOTP window expired or a new authorization began |
| Broker asks for another code | Broker authentication is a separate TOTP flow |

TOTP codes depend on synchronized clocks. Enable automatic network time on the server and authenticator device.

## Security Practices

- Lock and encrypt the authenticator device.
- Store the setup secret only in a protected secret manager when recovery is required.
- Never place the QR code or secret in logs, screenshots, or tickets.
- Enable login TOTP for publicly reachable deployments.
- Enable MCP TOTP before granting `write:orders` to hosted AI clients.
- Keep the application password, OpenAlgo TOTP, broker TOTP, and REST API key as distinct credentials.

---

**Previous**: [27 - Security Settings](../27-security-settings/README.md)

**Next**: [29 - Troubleshooting](../29-troubleshooting/README.md)
