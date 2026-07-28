# 27 - Security Settings

## Overview

OpenAlgo combines application authentication, hashed API keys, request rate limits, IP-ban middleware, and optional TOTP. The Security dashboard manages abuse thresholds and IP bans; it is not a general firewall or CIDR whitelist.

Open **Logs > Security** or visit `/logs/security` after signing in.

## Security Dashboard

The dashboard displays active bans, 404 attempts, invalid API-key attempts, login activity, active application sessions, and aggregate security statistics. It can:

- ban or unban one validated IPv4 or IPv6 address;
- resolve a recently observed host and ban matching addresses;
- clear an IP's 404 tracker;
- update automatic-ban thresholds;
- clear login activity records.

All supporting routes under `/security` require a valid application session and are rate limited.

## Automatic Ban Defaults

Security thresholds are persisted in the settings database. Current defaults are:

| Setting | Default |
|---|---:|
| Automatic banning | Off |
| 404 attempts in 24 hours | 100 |
| 404 ban duration | 0 hours (permanent) |
| Invalid API-key attempts in 24 hours | 100 |
| Invalid API-key ban duration | 0 hours (permanent) |
| Repeat-offender limit | 2 bans |

When automatic banning is enabled, localhost addresses are excluded. A zero-hour duration means permanent. Reaching the repeat-offender limit also makes the ban permanent.

The invalid-key tracker stores hashes, not raw API keys. A 404 tracker retains a bounded set of attempted paths for investigation.

## Client IP Trust

By default, OpenAlgo uses the immediate network peer as the client IP. Set `TRUST_PROXY_HEADERS=True` only when a controlled reverse proxy is the sole route to the application. In that mode OpenAlgo can use headers such as `CF-Connecting-IP`, `True-Client-IP`, `X-Real-IP`, and `X-Forwarded-For`.

Exposing Flask directly while trusting proxy headers allows clients to spoof the address used by rate limits and bans.

## API Keys and Credentials

- OpenAlgo API keys are stored as hashes with the installation's pepper.
- Broker configuration values live in `.env`; protect that file and never commit it.
- Broker session tokens use the application's encrypted token store.
- Regenerate an OpenAlgo API key if it is exposed, then update every client that used it.

API keys do not have per-key permission checkboxes in the current application. Possession of a valid key authorizes the REST operations exposed by that instance, subject to endpoint validation, mode, Action Center policy, and rate limits.

## Network Controls

Production installers configure the reverse proxy, TLS, and host firewall for their supported deployment path. Review the generated configuration before exposing an instance publicly.

The current OpenAlgo middleware has no CIDR allowlist feature. Use a host firewall, cloud security group, VPN, or reverse-proxy access policy when network allowlisting is required.

## Recommended Baseline

1. Use a unique application password and enable OpenAlgo TOTP.
2. Keep `.env`, database files, signing keys, and backups private.
3. Terminate TLS at a maintained reverse proxy for public deployments.
4. Keep `TRUST_PROXY_HEADERS` disabled unless the proxy boundary is enforced.
5. Review Traffic and Security dashboards after authentication failures or unexpected routes.
6. Test threshold changes before enabling automatic permanent bans.
7. Update with `bash install/update.sh` and review the release notes and migration output.

---

**Previous**: [26 - Traffic Logs](../26-traffic-logs/README.md)

**Next**: [28 - Two-Factor Authentication](../28-two-factor-auth/README.md)
