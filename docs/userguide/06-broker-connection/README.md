# 06 - Broker Connection

## Overview

OpenAlgo loads broker adapters from `broker/<name>/`. The current repository contains 34 plugin directories: 33 securities integrations and Delta Exchange for crypto derivatives. One OpenAlgo instance uses one configured broker at a time.

The installed plugin directories are the authoritative inventory:

```text
aliceblue, angel, arrow, compositedge, definedge, deltaexchange,
dhan, dhan_sandbox, firstock, fivepaisa, fivepaisaxts, flattrade,
fyers, groww, ibulls, iifl, iiflcapital, indmoney, jainamxts,
kotak, motilal, mstock, nubra, paytm, pocketful, rmoney, samco,
shoonya, tradejini, tradesmart, upstox, wisdom, zebu, zerodha
```

Each `plugin.json` declares the adapter's supported exchanges, broker type, and whether leverage configuration is available. The application caches these capabilities at startup and exposes the active broker's values to the frontend.

## Configure Credentials

The installer normally writes the broker configuration to `.env`. An authenticated administrator can review or update the same values from **Profile > Broker Credentials**:

| Variable | Purpose |
|---|---|
| `BROKER_API_KEY` | Broker-specific API key or combined identifier |
| `BROKER_API_SECRET` | Broker-specific API secret or token |
| `BROKER_API_KEY_MARKET` | Optional market-data key used by some XTS adapters |
| `BROKER_API_SECRET_MARKET` | Optional market-data secret used by some XTS adapters |
| `REDIRECT_URL` | Callback URL ending in `/<broker>/callback` |
| `VALID_BROKERS` | Comma-separated adapters allowed by this deployment |

Credential formats differ by adapter. Use the field hints shown in the Profile form and the current instructions from your broker's developer portal. Do not reuse an example format from another broker.

Changes made through Profile update `.env` and require an application restart. The UI masks stored values when it reads them back, but `.env` remains a sensitive configuration file and must not be committed or shared.

## Connect the Broker Session

1. Sign in to OpenAlgo.
2. Open the broker connection page when prompted.
3. Complete the adapter-specific login, consent, token, or TOTP flow.
4. Confirm the dashboard loads account data before starting a strategy.

OpenAlgo imports the selected adapter's authentication module only when it is needed. Some adapters redirect to a broker-hosted consent page; others collect a token or TOTP through an OpenAlgo form. The broker's current authentication policy determines when another login is required.

The OpenAlgo application session and broker session are separate. If the broker token expires while the application session is still valid, the dashboard sends the user back to `/broker` to reconnect rather than discarding the OpenAlgo login.

## Verify the Connection

After login, verify at least one read-only account call before placing an order:

- Funds loads without an authentication error.
- Order book and position book return current broker data.
- The active broker's supported exchanges match `/api/broker/capabilities`.
- WebSocket market data connects if the adapter and account support it.

Use Analyzer Mode for the first order workflow. It isolates order execution from the live broker while preserving the OpenAlgo API shape.

## Switch or Run Multiple Brokers

To switch the configured broker, update the credentials and callback broker name, restart OpenAlgo, and authenticate again. To use multiple brokers concurrently, run separate OpenAlgo instances with separate `.env` files, ports, databases, and process supervision.

## Troubleshooting

| Symptom | Check |
|---|---|
| Callback rejected | `REDIRECT_URL` exactly matches the broker app and ends in the configured broker name |
| Invalid credentials | Required key format, whitespace, expiry, and broker-side app status |
| Repeated login prompt | Broker token expiry or daily reauthentication policy |
| Account calls fail after login | Broker session state and server logs; reconnect from `/broker` |
| Market data unavailable | Adapter exchange capabilities, account entitlement, and WebSocket configuration |

Broker pricing, static-IP requirements, callback rules, and session lifetimes are external policies. Verify them with the broker instead of relying on a fixed value in OpenAlgo documentation.

---

**Previous**: [05 - First-Time Setup](../05-first-time-setup/README.md)

**Next**: [07 - Dashboard Overview](../07-dashboard-overview/README.md)
