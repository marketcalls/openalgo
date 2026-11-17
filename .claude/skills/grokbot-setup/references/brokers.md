# Broker credentials and login types

Sources, checked Oct 17, 2026:

- docs.openalgo.in broker pages, `https://docs.openalgo.in/connect-brokers/brokers/<page>.md`
  (index: `https://docs.openalgo.in/connect-brokers/brokers.md`); Delta Exchange
  at `https://docs.openalgo.in/crypto/exchanges/delta-exchange.md`
- `VALID_BROKERS` in `.sample.env` (37 codes)
- Login behaviour from the plugin code: `blueprints/brlogin.py` (`broker_callback`),
  `frontend/src/pages/BrokerSelect.tsx` (where Connect goes),
  `frontend/src/pages/BrokerTOTP.tsx` (fields on OpenAlgo's own login forms)

Re-check the broker page before every new setup: brokers change their portals.
Where the docs are silent the table says **not documented**; do not guess.

## Legend

- **Redirect**: `REDIRECT_URL = 'http://127.0.0.1:5000/<code>/callback'` unless the
  row says otherwise. The code must match exactly; OpenAlgo reads the active broker
  from it. Register the same URL in the broker's developer portal when it asks.
- **Login in OpenAlgo** (what happens after **Connect Account** on `/broker`):
  - *OAuth redirect*: OpenAlgo sends the browser to the broker's own login page,
    which redirects back to the callback.
  - *OpenAlgo form*: OpenAlgo shows its own form at `/broker/<code>/totp`.
  - *Key and secret*: no login screen; OpenAlgo creates the session from the
    `.env` values.
  - *OTP form*: OpenAlgo triggers an SMS or email OTP and shows a form for it.
- **Daily login needed**: Indian sessions expire at about 3:00 AM IST, so every
  Indian broker needs a connect each day. Crypto does not (see Delta Exchange).
- **TOTP automation** (for the 8:00 AM routine):
  - *Yes*: the daily inputs are static values plus a TOTP the bot can generate
    from the TOTP secret with pyotp.
  - *Not needed*: Connect alone works; the routine only clicks Connect.
  - *No*: needs an OTP delivered to the user's phone or email.
  - *Unverified*: broker-hosted page; the docs do not describe its fields. Try it
    in manual mode first; automate only if the page is a plain user ID, password
    and TOTP form.
- **IP**: the page says the broker whitelists a static IP. See the IP section
  at the end for what that means on the box.

## Table

| Code | Broker | Market | `.env` fields | Login in OpenAlgo | Daily inputs | Daily login needed | TOTP automation | Notes |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `fivepaisa` | 5paisa | Indian | KEY `API_Key:::User_ID:::client_code`; SECRET Encryption Key | OpenAlgo form | Client ID / mobile, PIN, TOTP | Yes | Yes (TOTP secret source not documented) | Keys from Xstream API, Get API Keys |
| `fivepaisaxts` | 5paisa (XTS) | Indian | KEY, SECRET (Interactive app); `BROKER_API_KEY_MARKET`, `BROKER_API_SECRET_MARKET` (Market Data app) | Key and secret (from code; docs page silent) | None | Yes | Not needed | Redirect URL left empty in the XTS portal; `.env` still uses the code |
| `aliceblue` | AliceBlue | Indian | KEY App Code (not the login user ID); SECRET API Secret | OAuth redirect (`ant.aliceblueonline.com`) | Broker page, not documented | Yes | Unverified | IP asked at registration. `BrokerSelect.tsx` labels it `totp` but the backend redirects |
| `angel` | AngelOne | Indian | KEY SmartAPI key; SECRET unused (leave placeholder) | OpenAlgo form | Client ID, PIN, TOTP | Yes | Yes (TOTP enabled at smartapi.angelbroking.com/enable-totp, which shows a QR and a token) | |
| `arrow` | Arrow | Indian | KEY appID; SECRET appSecret | OAuth redirect (`app.arrow.trade`) | Broker page, not documented | Yes | Unverified | IP mandatory in app form |
| `compositedge` | Compositedge (XTS) | Indian | KEY, SECRET (Interactive); `_MARKET` pair (Market Data) | OAuth redirect (XTS hosted login) | Broker page; docs say enable TOTP | Yes | Unverified | Redirect URL required for the Interactive app |
| `definedge` | Definedge Securities | Indian | KEY API Token; SECRET API Secret | OTP form (OTP sent on Connect) | OTP from phone / email | Yes | No | Manual mode only |
| `deltaexchange` | Delta Exchange | Crypto | KEY, SECRET | Key and secret | None | No | Not needed | Set `DISABLE_SESSION_EXPIRY = 'true'` and `CRYPTO_MASTER_CONTRACT_CUTOFF_TIME = '00:00'`; no daily routine. IP whitelist. Symbols per `docs/prompt/crypto-symbol-format.md` |
| `dhan` | Dhan | Indian | KEY `client_id:::api_key`; SECRET API Secret | OAuth redirect (via `/dhan/initiate-oauth`) | Broker page; TOTP mandatory on the account | Yes | Unverified | IP (up to two); docs: daily login mandatory |
| `dhan_sandbox` | Dhan (Sandbox) | Indian (sandbox broker) | KEY client ID (or `client_id:::api_key`); SECRET sandbox access token | Key and secret | None | Yes (Indian plugin, same expiry; not documented separately) | Not needed | Separate plugin; switching to live Dhan changes `REDIRECT_URL` too. Simulated, not exchange orders |
| `firstock` | Firstock | Indian | KEY Vendor Code; SECRET API Key | OpenAlgo form | User ID, password, TOTP | Yes | Yes (TOTP secret source not documented) | |
| `flattrade` | Flattrade | Indian | KEY `client_id:::api_key`; SECRET API secret | OAuth redirect (`auth.flattrade.in`) | Broker page, not documented | Yes | Unverified | Primary IP required; key needs approval |
| `fyers` | Fyers | Indian | KEY App ID; SECRET Secret ID | OAuth redirect | Broker page, not documented | Yes | Unverified | |
| `groww` | Groww | Indian | KEY API key; SECRET API secret | Key and secret (checksum flow, from code) | None | Yes | Not needed | IP via Add/Update Static IP. `BrokerSelect.tsx` labels it `totp`; backend needs no TOTP |
| `hdfcsecurities` | HDFC Securities (InvestRight) | Indian | KEY API Key; SECRET API Secret | OAuth redirect (`developer.hdfcsec.com`) | Broker page, not documented | Yes | Unverified | Docs use `REDIRECT_URL = 'https://openalgo.local/hdfcsecurities/callback'`; how that reaches the box is not documented. IP mandatory |
| `hdfcsky` | HDFC Sky | Indian | KEY API Key; SECRET API Secret | OAuth redirect (`developer.hdfcsky.com`) | Broker page, not documented | Yes | Unverified | Docs use `https://openalgo.local/hdfcsky/callback`; same open question. IP mandatory |
| `ibulls` | IndiaBulls (XTS) | Indian | KEY, SECRET (Interactive); `_MARKET` pair | Key and secret (docs confirm no login screen) | None | Yes | Not needed | Code is `ibulls`, not `indiabulls` |
| `iifl` | IIFL (XTS) | Indian | KEY, SECRET (Interactive); `_MARKET` pair | Key and secret (docs confirm) | None | Yes | Not needed | Do not swap the two pairs: login works but quotes stay empty |
| `iiflcapital` | IIFL Capital | Indian | KEY App Key; SECRET App Secret | OAuth redirect | Broker page, not documented | Yes | Unverified | Docs: IIFL rejects all API calls from a non-whitelisted IP. Likely unusable from the box |
| `indmoney` | IndMoney (INDstocks) | Indian | KEY Client ID; SECRET blank for MPIN + TOTP (or a manual 24 h access token) | OpenAlgo form (when SECRET blank) | MPIN, TOTP | Yes | Yes (docs: setup key shown once at enrolment) | IP configured on INDstocks |
| `jainamxts` | JainamXTS | Indian | KEY, SECRET (Interactive); `_MARKET` pair | Key and secret (from code; docs silent) | None | Yes | Not needed | |
| `kotak` | Kotak Securities (Neo) | Indian | KEY 5-character UCC; SECRET Neo token | OpenAlgo form | Mobile number, MPIN, TOTP | Yes | Yes (TOTP registered by QR; extracting the secret is not documented) | |
| `motilal` | Motilal Oswal | Indian | KEY client code; SECRET generated API key | OpenAlgo form | User ID, password, TOTP, date of birth (DD/MM/YYYY) | Yes | Yes (docs: copy the 32-character secret key) | |
| `mstock` | mStock (Mirae Asset) | Indian | KEY client code; SECRET API key (Type B) | OpenAlgo form | Password, TOTP | Yes | Yes (docs: Generate TOTP; secret source not detailed) | |
| `nubra` | Nubra | Indian | KEY registered mobile number; SECRET 6-digit MPIN | OTP form (SMS on Connect) | SMS OTP | Yes | No (docs: OpenAlgo forces the SMS path even with TOTP enrolled) | IP via Resources, Update Static IP |
| `paytm` | Paytm Money | Indian | KEY API Key; SECRET API Secret | OAuth redirect (`login.paytmmoney.com`) | Broker page, not documented | Yes | Unverified | |
| `pocketful` | Pocketful | Indian | KEY App ID; SECRET App Secret | OAuth redirect (`trade.pocketful.in/oauth2/auth`) | Broker page, not documented | Yes | Unverified | |
| `rmoney` | RMoney (XTS) | Indian | KEY, SECRET (Interactive); `_MARKET` pair | OAuth redirect (XTS hosted login, from code) | Broker page, not documented | Yes | Unverified | Docs say leave the portal redirect empty, yet the code redirects to the XTS login; unclear |
| `rupeezy` | Rupeezy (Vortex) | Indian | KEY Application ID; SECRET Vortex API Key | OAuth redirect (`flow.rupeezy.in`) | Broker page, not documented | Yes | Unverified | Only client codes whitelisted at app creation can log in. IP. Missing from the brokers index page list |
| `samco` | Samco | Indian | KEY API Key (emailed); SECRET API Secret (shown once) | Key and secret (`/broker/samco/auth`) | None | Yes | Not needed | IP whitelist; Connect also checks the IP |
| `shoonya` | Shoonya (Finvasia) | Indian | KEY `userid:::client_id`; SECRET secret code | OAuth redirect (`api.shoonya.com`) | Broker page, not documented | Yes | Unverified | Docs use `https://openalgo.local/shoonya/callback`. `BrokerTOTP.tsx` still has a form entry; backend redirects |
| `tradejini` | Tradejini (CubePlus) | Indian | KEY app API Key; SECRET blank | OpenAlgo form | CubePlus PIN, 2FA (`totp` or `otp`) | Yes | Yes with `totp` | Docs: individual apps accept requests only from the whitelisted IP; login fails with 401 otherwise. Likely unusable from the box |
| `tradesmart` | TradeSmart | Indian | KEY `client_id:::api_key` (api_key = App ID); SECRET Secret Key | OAuth redirect (`v2api.tradesmartonline.in`) | Broker page, not documented | Yes | Unverified | Docs: login IP must match the Primary Static IP. Likely unusable from the box. Manual token fallback via `?access_token=` in code |
| `upstox` | Upstox | Indian | KEY API Key; SECRET API Secret | OAuth redirect (`api.upstox.com`) | Broker page, not documented | Yes | Unverified | |
| `wisdom` | Wisdom Capital (XTS) | Indian | KEY, SECRET (Interactive); `_MARKET` pair | Key and secret (from code; docs silent) | None | Yes | Not needed | |
| `zebu` | Zebu (MYNT) | Indian | KEY `userid:::client_id` (quote once as a whole); SECRET secret code | OAuth redirect (`go.mynt.in`) | Broker page, not documented | Yes | Unverified | `BrokerSelect.tsx` labels it `totp`; backend redirects |
| `zerodha` | Zerodha (Kite) | Indian | KEY API Key; SECRET API Secret | OAuth redirect (`kite.trade/connect/login`) | Kite user ID, password, External TOTP | Yes | Yes, verified on the box Oct 17, 2026 | Kite page may not auto-submit; click Continue |

37 codes: 36 Indian (including the Dhan Sandbox plugin) and 1 crypto.

## Where the docs are unclear

- **HDFC Securities, HDFC Sky, Shoonya**: the pages give an `https://openalgo.local/...`
  redirect instead of `http://127.0.0.1:5000/...`. Not documented how that host
  reaches a local install. Ask the user what they registered and use exactly that.
- **RMoney**: page says leave the portal redirect empty; the code sends the user to
  the XTS hosted login with a return URL built from `HOST_SERVER`.
- **5paisa (XTS), JainamXTS, Wisdom Capital**: pages do not say whether there is a
  login screen; the code creates the session from key and secret (IIFL and
  IndiaBulls pages confirm this for the same XTS pattern).
- **Rupeezy**: present in the docs index and `VALID_BROKERS` but listed without a
  link or code on the brokers index page.
- **Groww, AliceBlue, Zebu, Shoonya**: `BrokerSelect.tsx` / `BrokerTOTP.tsx` labels
  disagree with the backend flow; the table follows the backend.
- **Every OAuth redirect broker except Zerodha**: the docs do not describe the
  broker-hosted login fields, so TOTP automation is unverified.
- **TOTP secret**: most pages describe scanning a QR code, not copying the base32
  key. Only IndMoney and Motilal Oswal say a key is shown to copy.
- **Dhan Sandbox**: daily expiry is not documented separately; treated as an
  Indian plugin.

## Static IP on the box

The box has no static IP (shared rotating Cloudflare egress). Under the SEBI
mandate effective April 1, 2026, Live API orders need the broker-registered IP,
so Live orders from the box will be rejected for every broker. Data, charts and
Sandbox mode still work for brokers that whitelist only orders. IIFL Capital,
Tradejini and TradeSmart docs say the whitelist applies to all API calls or the
login itself, so those may not work on the box at all. Delta Exchange also
whitelists IPs for its API key. For Live trading, run OpenAlgo on a VPS with a
static IP and register that IP with the broker.
