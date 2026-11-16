# Integrating an XTS broker

An XTS broker is a broker plugin with its own authentication, mappings,
capabilities and streaming behavior. Sharing the XTS protocol does not make
adding one a configuration-only change. Start with the
[broker integration guide](broker-integration-guide.md); this page describes
XTS-specific integration points in the current application.

## Existing examples

The tree contains XTS-based plugins including `compositedge`, `rmoney`,
`jainamxts`, `fivepaisaxts`, `iiflcapital` and `iifl`. Select the closest example
by the broker's actual API version and login contract. Keep its Interactive and
Market Data credentials separate.

For example, `broker/compositedge/baseurl.py` defines:

```python
BASE_URL = "https://xts.compositedge.com"
MARKET_DATA_URL = f"{BASE_URL}/apimarketdata"
INTERACTIVE_URL = f"{BASE_URL}/interactive"
```

Do not assume all XTS brokers use `/apimarketdata`,
`/apibinarymarketdata`, identical hostnames or identical packet layouts. Compare
the target broker's API with its existing plugin counterpart before reusing code.
Do not repoint an existing plugin to another broker: it would retain the wrong
broker identity, symbol mappings and authentication behavior.

## Registering the plugin

Use a unique broker ID consistently in the following places:

| Area | Source to inspect |
|---|---|
| Plugin implementation and capabilities | `broker/<id>/plugin.json`, `api/`, `mapping/`, `database/`, `streaming/` |
| Enabled broker inventory | `VALID_BROKERS` in `.sample.env` and the instance's `.env` |
| Broker setup fields and sign-in guidance | `utils/broker_setup_guide.py` |
| Starting and validating login | `utils/broker_login.py`, `utils/auth_utils.py` |
| Callback parsing and account identity | `blueprints/brlogin.py` and the plugin's `api/auth_api.py` |
| Broker session and feed persistence | Shared auth helpers in `database/auth_db.py` and `utils/auth_utils.py` |

The browser's **Select Broker** page reads `GET /api/broker/list`; it does not
use `templates/broker.html` or a client-side switch that assembles broker login
URLs. Broker keys are entered at `/broker/config`. The setup guide supplies the
fields and hints shown there.

## Keys and account identity

A configured `.env` broker uses its `.env` credentials first. Other broker key
sets are encrypted in `broker_keys` in `openalgo.db`. Keep `VALID_BROKERS` set
even if broker credentials in `.env` are empty. Multiple key sets may be saved,
but only one broker session is active at a time.

Plugins must read `BROKER_API_KEY`, `BROKER_API_SECRET` and any market-data keys
when called, rather than capturing them in module constants. A login stages its
keys for its own request; the shared auth helpers publish them only when that
login commits. A callback must not directly replace the active process's keys.

CompositEdge exchanges the returned token at `/interactive/user/session`, reads
the broker-reported account identity, and obtains a separate Market Data token.
When both identities are known it refuses a mismatch. Return the account named
by the broker, not an account label supplied by the browser. Preserve the shared
login commit and broker-switch checks when adding another callback branch.

## Callback state and cross-site POSTs

The browser starts a login through the CSRF-checked
`POST /auth/broker/login`. `utils/broker_login.py` records a pending login in
`broker_login_states` as nonce/state digests. It is single-use and expires after
ten minutes. A callback must match that pending login.

Some XTS brokers POST their answer from the broker's website. A cross-site POST
may not carry OpenAlgo's session cookie. The current CompositEdge and RMoney
flow puts the issued state on the encoded `returnURL`; IIFL Capital also
supports a broker-site POST. These integrations are represented in
`BROKER_SITE_POST_BROKERS` and `STATE_BROKERS`. A new broker with that behavior
needs a matching server-side login URL and state-validation path. Adding a
broker ID to a set alone does not implement the flow.

Never restore the legacy callback behavior that accepted any incoming token
while a user was signed in, or created an OpenAlgo login from an uncorrelated
broker POST. Use the existing login helpers and reject answers without a
matching pending login.

## Verification

Before calling an integration complete, verify:

- Broker configuration before any broker login, environment precedence, and
  saved Interactive/Market Data credentials.
- Successful login, cancelled/failed login, wrong account, replayed callback,
  expired state and broker-site POST without a session cookie.
- Current session behavior when another broker login fails, and broker-switch
  refusal while Live automation is running.
- Symbol master and exchange/token mapping; quote and depth fields actually
  supplied by this broker; reconnect and unsubscribe behavior.
- Orders, modifications, cancellation, funds, holdings and positions against the
  target broker's contracts. An XTS plugin's success does not certify another.
- Logs contain no API keys, token values or token prefixes. See
  `test/test_xts_credential_logging.py` and `test/test_broker_keys.py` for existing
  regression coverage.

Use `/websocket/test` for market data and `/websocket/order` for account updates.
The [broker QA checklist](audit/qa_audit/broker/broker-qa-audit-checklist.md)
provides a wider verification procedure. Live broker checks need that broker's
credentials; reading the plugin or passing a static check does not replace them.
