# 06 - Broker Connection

## Overview

OpenAlgo loads broker adapters from `broker/<name>/`. The current repository contains 36 plugin directories: 35 securities integrations and Delta Exchange for crypto derivatives. One OpenAlgo instance is logged in to one broker at a time; the keys of several can be saved.

The installed plugin directories are the authoritative inventory:

```text
aliceblue, angel, arrow, compositedge, definedge, deltaexchange,
dhan, dhan_sandbox, firstock, fivepaisa, fivepaisaxts, flattrade,
fyers, groww, hdfcsecurities, hdfcsky, ibulls, iifl, iiflcapital,
indmoney, jainamxts, kotak, motilal, mstock, nubra, paytm,
pocketful, rmoney, samco, shoonya, tradejini, tradesmart,
upstox, wisdom, zebu, zerodha
```

Each `plugin.json` declares the adapter's supported exchanges, broker type, and whether leverage configuration is available. The application caches these capabilities at startup and exposes the active broker's values to the frontend.

## Where the Broker Keys Come From

The broker pages are the same as in OpenAlgo Desktop: **Select Broker** after you sign in, and **Broker Configuration** for the keys. OpenAlgo reads broker keys from two places, and the `.env` file always comes first:

1. **The `.env` file.** When `REDIRECT_URL` names a broker and `BROKER_API_KEY` is set, that broker always logs in with the `.env` keys. This is how every install worked before, and it still works unchanged.
2. **Keys saved in OpenAlgo.** Open **Broker Configuration**: the button at the top of Select Broker, **Configure** or **Edit keys** on a broker's card, or the button in **Profile > Broker**. It opens before any broker login, so a new install adds its first broker there. Choose the broker, enter its keys and press **Save**. Each broker asks for its keys by the names it uses itself (for example Zerodha's API Key, Fyers' App ID), with a hint for each and a sentence on how its login works. The keys are encrypted in the database, each bound to its broker and field, and never shown again: the page shows the first characters of an API key and only whether a secret is saved. They apply at once, with no restart, and serve every broker the `.env` file does not set, and all brokers when `.env` sets none. **Forget this broker** removes them.

Saving keys for the `.env` broker on Broker Configuration writes them to `.env`, and it cannot be forgotten there: remove its lines from `.env` instead.

| Variable in `.env` | On Broker Configuration | Purpose |
|---|---|---|
| `BROKER_API_KEY` | The broker's API key field (named as the broker names it) | Broker-specific API key or combined identifier |
| `BROKER_API_SECRET` | The broker's secret field | Broker-specific API secret or token |
| `BROKER_API_KEY_MARKET` | Market Data App Key (XTS brokers) | Optional market-data key |
| `BROKER_API_SECRET_MARKET` | Market Data Secret Key (XTS brokers) | Optional market-data secret |
| `REDIRECT_URL` | Redirect URL (brokers that send you back) | Automatic (your Host Server URL plus `/<broker>/callback`) or your own |
| `VALID_BROKERS` | (not on the page) | Comma-separated adapters this install allows; the pages list only these |

Credential formats differ by adapter. Use the hints on the page and the current instructions from your broker's developer portal; 5paisa, Flattrade and Dhan keys are checked for their `:::` layout when you save. For a broker that sends you back to OpenAlgo, register the Redirect URL Broker Configuration shows for it, exactly, in that broker's developer console.

Settings some brokers need beyond these (for example HDFC Sky's `BROKER_CLIENT_ID` or Motilal's `BROKER_VENDOR_CODE`) are still read from `.env`.

### A new install without a broker in `.env`

The installers, and a first `uv run app.py` with no `.env`, leave `REDIRECT_URL`, `BROKER_API_KEY` and `BROKER_API_SECRET` empty. OpenAlgo starts and prints that no broker is set in `.env`. After you sign in, Select Broker lists every broker; **Configure** on its card opens Broker Configuration.

### Moving an existing install off `.env`

1. Keep a copy of the broker's keys from `.env`.
2. Empty `REDIRECT_URL`, `BROKER_API_KEY` and `BROKER_API_SECRET` in `.env` and restart.
3. Sign in, open **Broker Configuration**, choose the broker, enter its keys and save. From now on they are saved in OpenAlgo.

## Connect the Broker Session

1. Sign in to OpenAlgo.
2. On **Select Broker**, find your broker (**Search brokers** narrows the list) and press **Login with <broker>** on its card. A broker without keys shows **Configure** instead.
3. Complete the broker's login: its own login page, a short form in OpenAlgo, or one click with the saved keys. Broker Configuration says which, for each broker.
4. Confirm the dashboard loads account data before starting a strategy.

OpenAlgo starts every broker login on the server. The page sends only the broker you chose; the server checks it can be used and opens the broker's own sign-in page or OpenAlgo's login form, and puts the broker's keys in place when the broker answers. Your API secret never reaches the browser; the broker's sign-in address carries only the public API key it needs, as before. The broker's answer is accepted only for a login started this way, within 10 minutes, and only once: from the same browser, or, for a broker that returns the state OpenAlgo gave it, with that state. A link from someone else cannot connect your OpenAlgo to their account. If it is refused, the broker's card says "This broker login was not started from OpenAlgo, or it took longer than 10 minutes": start the login again.

OpenAlgo imports the selected adapter's authentication module only when it is needed. The broker's current authentication policy determines when another login is required.

## Sign-in and Session Rules

- The OpenAlgo application session and broker session are separate. If the broker token expires while the application session is still valid, the dashboard sends you back to the broker login page to reconnect rather than discarding the OpenAlgo login.
- **Logging out ends your sign-in on every device.** So does changing or resetting your password. A browser that was signed in before that moment has to sign in again, even if it still holds its cookie.
- Signing out from the broker login page, before any broker is connected, ends only that browser's sign-in.
- A sign-in that never connected a broker ends at the daily session expiry (`SESSION_EXPIRY_TIME`, 03:00 IST by default), like a connected one.
- Profile opens before any broker login, so a new install can add its first broker there.

## Verify the Connection

After login, verify at least one read-only account call before placing an order:

- Funds loads without an authentication error.
- Order book and position book return current broker data.
- The active broker's supported exchanges match `/api/broker/capabilities`.
- WebSocket market data connects if the adapter and account support it.

Use Analyzer Mode for the first order workflow. It isolates order execution from the live broker while preserving the OpenAlgo API shape.

## Switch or Run Multiple Brokers

OpenAlgo is logged in to one broker at a time, as OpenAlgo Desktop is. Its card shows **Active** and **Open Dashboard** (which also joins a session opened on another device). To switch, press **Login with** on another broker's card. OpenAlgo asks first, and the old broker's session ends only when the new login completes, on every device; a login that fails or is abandoned leaves the old broker connected. You stay signed in, and the other devices sign in again. Open positions and orders stay with the old broker. No restart is needed.

A switch is refused while the logged-in broker still has running Live strategies, Live OpenScript runs, running Python strategies or positions under scalping protection, because they would otherwise trade through the new broker or lose their stop. Stop them first, then switch.

New keys for the logged-in broker, or forgetting it, end its session; Broker Configuration asks you to confirm first.

To use multiple brokers concurrently, run separate OpenAlgo instances with separate `.env` files, ports, databases, and process supervision.

## Troubleshooting

| Symptom | Check |
|---|---|
| Callback rejected | The redirect URL (in `.env`, or on Broker Configuration) exactly matches the broker app and ends in the broker's name |
| "This broker login was not started from OpenAlgo" | Start the login again from the broker login page, in the same browser, and finish it within 10 minutes. Open OpenAlgo at the same address as the redirect URL: `127.0.0.1` and `localhost` are different sites to a browser, and the broker returns to the redirect URL |
| "No API key is saved for ..." | Add the broker's keys on Broker Configuration, or set them in `.env` |
| "... still has 1 running Live strategy ..." | Stop the strategies and the scalping protection on the logged-in broker, then switch |
| "A login to ... is under way" | A login to that broker is completing, perhaps on another device; wait a moment and try again |
| Saved keys seem to be ignored | `.env` sets keys for the same broker and comes first; empty the broker lines in `.env` and restart |
| Invalid credentials | Required key format, whitespace, expiry, and broker-side app status |
| Repeated login prompt | Broker token expiry or daily reauthentication policy |
| Account calls fail after login | Broker session state and server logs; reconnect from `/broker` |
| Market data unavailable | Adapter exchange capabilities, account entitlement, and WebSocket configuration |

Broker pricing, static-IP requirements, callback rules, and session lifetimes are external policies. Verify them with the broker instead of relying on a fixed value in OpenAlgo documentation.

---

**Previous**: [05 - First-Time Setup](../05-first-time-setup/README.md)

**Next**: [07 - Dashboard Overview](../07-dashboard-overview/README.md)
