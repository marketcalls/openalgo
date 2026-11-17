# 05 - First-Time Setup

## Start OpenAlgo

For a local source installation, run this from the OpenAlgo folder:

```bash
uv run app.py
```

Open `http://127.0.0.1:5000`, or your installation's configured Host Server URL. On a new installation, **Create Account** opens at `/setup`; an existing installation opens the sign-in page.

## Keep the Installation's Security Keys

The installers and the first startup without a `.env` generate unique `APP_KEY`, `API_KEY_PEPPER` and `FERNET_SALT` values. Startup also replaces public sample placeholders on a fresh database. Keep `.env` private and back it up with your databases.

Do not replace these values as a routine setup or upgrade step after creating your account. `API_KEY_PEPPER` and `FERNET_SALT` protect stored credentials; changing them without migration can make that data unreadable. If an existing installation reports a public sample pepper, follow the startup message and the dedicated `upgrade/rotate_pepper.py` migration. See [Installation](../04-installation/README.md) for install and backup procedures.

## Create the Administrator Account

Enter your username, email, password and password confirmation, then choose **Create Account**. The password must contain at least eight characters, uppercase and lowercase letters, a number, and a special character from `!@#$%^&*`.

OpenAlgo is a single-user deployment. The administrator account controls the instance and its one active broker session.

## Save Broker Credentials

1. Sign in to OpenAlgo.
2. On **Select Broker** (`/broker`), search for your broker and choose **Configure**. You can also open **Broker Configuration** (`/broker/config`) before connecting a broker.
3. Select the broker, follow the field hints, enter the required keys, and choose **Save**.
4. If the broker redirects back to OpenAlgo, register the exact Redirect URL shown on the page in the broker's developer console.

Keys saved here are encrypted in the database and apply without a restart. You can save several brokers' keys, while connecting to one broker at a time.

An existing `.env` configuration still works: when `REDIRECT_URL` names a broker and `BROKER_API_KEY` is set, that broker uses the `.env` keys first. Saving its keys in Broker Configuration updates `.env`; other brokers use their saved database keys. `BROKER=...` is not the broker selector. See [Broker Connection](../06-broker-connection/README.md) for precedence, broker-specific fields, migration from `.env`, switching and session rules.

## Connect the Broker

On **Select Broker**, choose **Login with <broker>** and complete the login described on its card. Start the login from OpenAlgo, finish within ten minutes, and use the same OpenAlgo address as the registered redirect URL.

After connecting, confirm the Dashboard loads funds and that the master contract is ready. Check the order book and positions before starting automation. An expired broker token can require another broker login even while your OpenAlgo sign-in is still valid.

## Generate an OpenAlgo API Key

Open the profile menu and choose **API Key** (`/apikey`). Generate a key and use this OpenAlgo key in external integrations; it is different from your broker's API key. See [API Key Management](../09-api-key-management/README.md) for key handling and Auto/Semi-Auto order mode.

## Rehearse the First Order

Use the header's mode control to switch to **Analyze**, verify the badge, and follow [Placing Your First Order](../10-placing-first-order/README.md). Analyzer sends supported orders to the sandbox; market data still depends on the broker. Confirm the sandbox order, trade and position before choosing Live.

Configure [two-factor authentication](../28-two-factor-auth/README.md) from Profile and review [security settings](../27-security-settings/README.md) before exposing an installation beyond your own machine.

---

**Previous**: [04 - Installation Guide](../04-installation/README.md)

**Next**: [06 - Broker Connection](../06-broker-connection/README.md)
