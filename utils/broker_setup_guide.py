# utils/broker_setup_guide.py
"""What Broker Configuration asks for, per broker, as OpenAlgo Desktop shows it.

For every broker: the keys it needs, labelled the way that broker names them,
a hint for each, a sentence on how its sign-in works, and what to do with the
redirect URL. Carried over from OpenAlgo Desktop's setup guide
(``src-tauri/src/brokers/setup_guide.rs``) so a trader sees the same page in
both, with these changes for how the web signs in:

- ``sign_in`` follows this server's login flow (``utils/broker_login`` and
  the callback routes in ``blueprints/brlogin.py``): a redirect to the
  broker's site, OpenAlgo's own form, or one click with the saved keys. Groww
  signs in with the saved keys here, so its sentence says so. A test starts
  each broker's login and checks where it goes against this table.
- No client ID is saved here, so the Client ID fields and the sentences about
  checking a login against one are left out. HDFC Sky's BROKER_CLIENT_ID
  stays in .env.
- Every field maps to one of the .env names in ``FIELD_ENV_VARS``.

A broker missing from the table gets the generic entry.
"""

#: The .env name each field is saved as.
FIELD_ENV_VARS = {
    "api_key": "BROKER_API_KEY",
    "api_secret": "BROKER_API_SECRET",
    "api_key_market": "BROKER_API_KEY_MARKET",
    "api_secret_market": "BROKER_API_SECRET_MARKET",
}

REDIRECT_REGISTER = "Register this exact address as the redirect URL in your broker app."

_GENERIC_FIELDS = (
    {
        "key": "api_key",
        "label": "API Key",
        "hint": "From your broker's developer portal.",
        "secret": False,
        "required": True,
    },
    {
        "key": "api_secret",
        "label": "API Secret",
        "hint": "From your broker's developer portal.",
        "secret": True,
        "required": True,
    },
)

_GENERIC_BANNERS = {
    "redirect": (
        "Login takes you to your broker's login page. Log in there and your broker "
        "sends you back to OpenAlgo."
    ),
    "form": "Login opens a short form in OpenAlgo for the details your broker asks for at each login.",
    "saved_keys": "Login signs you in with one click using the keys you saved.",
}

#: broker -> name, sign_in, fields, banner, redirect_hint
GUIDES = {
    "aliceblue": {
        "name": "Alice Blue",
        "sign_in": "redirect",
        "fields": (
            {
                "hint": "The App Code of your Alice Blue API app.",
                "key": "api_key",
                "label": "App Code",
                "required": True,
                "secret": False,
            },
            {
                "hint": "The API secret of your Alice Blue API app.",
                "key": "api_secret",
                "label": "API Secret",
                "required": True,
                "secret": True,
            },
        ),
        "banner": "Login with Alice Blue takes you to Alice Blue's login page. Log in "
        "there and Alice Blue sends you back to OpenAlgo.",
        "redirect_hint": "Register this exact address as the redirect URL in your broker app.",
    },
    "angel": {
        "name": "Angel One",
        "sign_in": "form",
        "fields": (
            {
                "hint": "The API key of your SmartAPI app at smartapi.angelbroking.com. "
                "Angel One needs no secret.",
                "key": "api_key",
                "label": "SmartAPI Key",
                "required": True,
                "secret": False,
            },
        ),
        "banner": "Login with Angel One opens a short form in OpenAlgo. Each time, enter "
        "your Angel One Client ID, PIN and the 6-digit TOTP from your "
        "authenticator app.",
        "redirect_hint": "",
    },
    "arrow": {
        "name": "Arrow",
        "sign_in": "redirect",
        "fields": (
            {
                "hint": "The App ID of your Arrow app (app.arrow.trade).",
                "key": "api_key",
                "label": "App ID",
                "required": True,
                "secret": False,
            },
            {
                "hint": "The App Secret of your Arrow app.",
                "key": "api_secret",
                "label": "App Secret",
                "required": True,
                "secret": True,
            },
        ),
        "banner": "Login with Arrow takes you to Arrow's login page. Log in there and Arrow "
        "sends you back to OpenAlgo.",
        "redirect_hint": "Register this exact address as the redirect URL in your broker app.",
    },
    "compositedge": {
        "name": "CompositEdge",
        "sign_in": "redirect",
        "fields": (
            {
                "hint": "The Interactive API app key from your CompositEdge XTS account.",
                "key": "api_key",
                "label": "Interactive App Key",
                "required": True,
                "secret": False,
            },
            {
                "hint": "The Interactive API secret key from your CompositEdge XTS account.",
                "key": "api_secret",
                "label": "Interactive Secret Key",
                "required": True,
                "secret": True,
            },
            {
                "hint": "The Market Data API app key from the same XTS account. "
                "Quotes and the live feed need it.",
                "key": "api_key_market",
                "label": "Market Data App Key",
                "required": False,
                "secret": False,
            },
            {
                "hint": "The Market Data API secret key from the same XTS account.",
                "key": "api_secret_market",
                "label": "Market Data Secret Key",
                "required": False,
                "secret": True,
            },
        ),
        "banner": "Login with CompositEdge takes you to CompositEdge's login page. "
        "Log in there and CompositEdge sends you back to OpenAlgo; your "
        "Market Data keys are then used for quotes and the live feed.",
        "redirect_hint": "OpenAlgo sends this address with each login. If your "
        "broker app asks for a redirect URL, register this exact "
        "address.",
    },
    "definedge": {
        "name": "Definedge",
        "sign_in": "form",
        "fields": (
            {
                "hint": "The API token from your Definedge Integrate account.",
                "key": "api_key",
                "label": "API Token",
                "required": True,
                "secret": False,
            },
            {
                "hint": "The API secret from your Definedge Integrate account.",
                "key": "api_secret",
                "label": "API Secret",
                "required": True,
                "secret": True,
            },
        ),
        "banner": "Login with Definedge opens a short form in OpenAlgo and sends a "
        "one-time code to your registered mobile or email. Enter that OTP to "
        "sign in.",
        "redirect_hint": "",
    },
    "deltaexchange": {
        "name": "Delta Exchange",
        "sign_in": "saved_keys",
        "fields": (
            {
                "hint": "An API key from your Delta Exchange India account.",
                "key": "api_key",
                "label": "API Key",
                "required": True,
                "secret": False,
            },
            {
                "hint": "The secret of that API key.",
                "key": "api_secret",
                "label": "API Secret",
                "required": True,
                "secret": True,
            },
        ),
        "banner": "Login with Delta Exchange signs you in with one click using the "
        "API key and secret you saved; there is nothing to type.",
        "redirect_hint": "",
    },
    "dhan": {
        "name": "Dhan",
        "sign_in": "redirect",
        "fields": (
            {
                "hint": "Your Dhan Client ID and your app's API key joined by ::: "
                "(client_id:::api_key).",
                "key": "api_key",
                "label": "Client ID and API Key",
                "required": True,
                "secret": False,
            },
            {
                "hint": "The API secret of your Dhan app.",
                "key": "api_secret",
                "label": "API Secret",
                "required": True,
                "secret": True,
            },
        ),
        "banner": "Login with Dhan takes you to Dhan's login page. Log in and approve, and "
        "Dhan sends you back to OpenAlgo. Market data needs an active Dhan Data "
        "API subscription.",
        "redirect_hint": "Register this exact address as the redirect URL in your broker app.",
    },
    "dhan_sandbox": {
        "name": "Dhan (Sandbox)",
        "sign_in": "saved_keys",
        "fields": (
            {
                "hint": "Your Dhan Client ID.",
                "key": "api_key",
                "label": "Client ID",
                "required": True,
                "secret": False,
            },
            {
                "hint": "The access token of your Dhan sandbox account.",
                "key": "api_secret",
                "label": "Sandbox Access Token",
                "required": True,
                "secret": True,
            },
        ),
        "banner": "Login with Dhan (Sandbox) signs you in with one click using the "
        "client ID and sandbox access token you saved.",
        "redirect_hint": "",
    },
    "firstock": {
        "name": "Firstock",
        "sign_in": "form",
        "fields": (
            {
                "hint": "Your Firstock vendor code.",
                "key": "api_key",
                "label": "Vendor Code",
                "required": True,
                "secret": False,
            },
            {
                "hint": "Your Firstock API key.",
                "key": "api_secret",
                "label": "API Key",
                "required": True,
                "secret": True,
            },
        ),
        "banner": "Login with Firstock opens a short form in OpenAlgo. Each time, enter "
        "your Firstock user ID, password and TOTP.",
        "redirect_hint": "",
    },
    "fivepaisa": {
        "name": "5 Paisa",
        "sign_in": "form",
        "fields": (
            {
                "hint": "The User Key and User ID of your 5paisa app and your "
                "client code, joined by ::: "
                "(User_Key:::User_ID:::client_id).",
                "key": "api_key",
                "label": "User Key, User ID and Client Code",
                "required": True,
                "secret": False,
            },
            {
                "hint": "The encryption key of your 5paisa app.",
                "key": "api_secret",
                "label": "Encryption Key",
                "required": True,
                "secret": True,
            },
        ),
        "banner": "Login with 5 Paisa opens a short form in OpenAlgo. Each time, enter "
        "your 5paisa login, PIN and the TOTP from your authenticator app.",
        "redirect_hint": "",
    },
    "fivepaisaxts": {
        "name": "5 Paisa (XTS)",
        "sign_in": "saved_keys",
        "fields": (
            {
                "hint": "The Interactive API app key from your XTS account.",
                "key": "api_key",
                "label": "Interactive App Key",
                "required": True,
                "secret": False,
            },
            {
                "hint": "The Interactive API secret key from your XTS account.",
                "key": "api_secret",
                "label": "Interactive Secret Key",
                "required": True,
                "secret": True,
            },
            {
                "hint": "The Market Data API app key from the same XTS account. "
                "Quotes and the live feed need it.",
                "key": "api_key_market",
                "label": "Market Data App Key",
                "required": False,
                "secret": False,
            },
            {
                "hint": "The Market Data API secret key from the same XTS account.",
                "key": "api_secret_market",
                "label": "Market Data Secret Key",
                "required": False,
                "secret": True,
            },
        ),
        "banner": "Login with 5 Paisa (XTS) signs you in with one click using your "
        "saved Interactive and Market Data keys.",
        "redirect_hint": "",
    },
    "flattrade": {
        "name": "Flattrade",
        "sign_in": "redirect",
        "fields": (
            {
                "hint": "Your Flattrade client ID and your app's API key joined by "
                "::: (client_id:::api_key).",
                "key": "api_key",
                "label": "Client ID and API Key",
                "required": True,
                "secret": False,
            },
            {
                "hint": "The API secret of your Flattrade app.",
                "key": "api_secret",
                "label": "API Secret",
                "required": True,
                "secret": True,
            },
        ),
        "banner": "Login with Flattrade takes you to Flattrade's login page. Log in "
        "there and Flattrade sends you back to OpenAlgo.",
        "redirect_hint": "Register this exact address as the redirect URL in your broker app.",
    },
    "fyers": {
        "name": "Fyers",
        "sign_in": "redirect",
        "fields": (
            {
                "hint": "The App ID of your app at myapi.fyers.in.",
                "key": "api_key",
                "label": "App ID",
                "required": True,
                "secret": False,
            },
            {
                "hint": "The secret of that app.",
                "key": "api_secret",
                "label": "App Secret",
                "required": True,
                "secret": True,
            },
        ),
        "banner": "Login with Fyers takes you to Fyers' login page. Log in there and Fyers "
        "sends you back to OpenAlgo.",
        "redirect_hint": "Register this exact address as the redirect URL in your broker app.",
    },
    "groww": {
        "name": "Groww",
        "sign_in": "saved_keys",
        "fields": (
            {
                "hint": "Your Groww Trade API key.",
                "key": "api_key",
                "label": "API Key",
                "required": True,
                "secret": False,
            },
            {
                "hint": "Needed when your key uses Groww's approval flow. Leave it "
                "empty for a TOTP key.",
                "key": "api_secret",
                "label": "API Secret",
                "required": False,
                "secret": True,
            },
        ),
        "banner": "Login with Groww signs you in with one click using your saved API key "
        "and secret.",
        "redirect_hint": "",
    },
    "hdfcsecurities": {
        "name": "HDFC Securities",
        "sign_in": "redirect",
        "fields": (
            {
                "hint": "The API key of your HDFC Securities InvestRight app.",
                "key": "api_key",
                "label": "API Key",
                "required": True,
                "secret": False,
            },
            {
                "hint": "The API secret of that app.",
                "key": "api_secret",
                "label": "API Secret",
                "required": True,
                "secret": True,
            },
        ),
        "banner": "Login with HDFC Securities takes you to HDFC Securities' login "
        "page. Log in there and you are sent back to OpenAlgo.",
        "redirect_hint": "Register this exact address as the redirect URL in your broker app.",
    },
    "hdfcsky": {
        "name": "HDFC Sky",
        "sign_in": "redirect",
        "fields": (
            {
                "hint": "The API key of your HDFC Sky app.",
                "key": "api_key",
                "label": "API Key",
                "required": True,
                "secret": False,
            },
            {
                "hint": "The API secret of that app.",
                "key": "api_secret",
                "label": "API Secret",
                "required": True,
                "secret": True,
            },
        ),
        "banner": "Login with HDFC Sky takes you to HDFC Sky's login page. Log in there "
        "and you are sent back to OpenAlgo.",
        "redirect_hint": "Register this exact address as the redirect URL in your broker app.",
    },
    "ibulls": {
        "name": "Ibulls",
        "sign_in": "saved_keys",
        "fields": (
            {
                "hint": "The Interactive API app key from your XTS account.",
                "key": "api_key",
                "label": "Interactive App Key",
                "required": True,
                "secret": False,
            },
            {
                "hint": "The Interactive API secret key from your XTS account.",
                "key": "api_secret",
                "label": "Interactive Secret Key",
                "required": True,
                "secret": True,
            },
            {
                "hint": "The Market Data API app key from the same XTS account. Quotes "
                "and the live feed need it.",
                "key": "api_key_market",
                "label": "Market Data App Key",
                "required": False,
                "secret": False,
            },
            {
                "hint": "The Market Data API secret key from the same XTS account.",
                "key": "api_secret_market",
                "label": "Market Data Secret Key",
                "required": False,
                "secret": True,
            },
        ),
        "banner": "Login with Ibulls signs you in with one click using your saved "
        "Interactive and Market Data keys.",
        "redirect_hint": "",
    },
    "iifl": {
        "name": "IIFL",
        "sign_in": "saved_keys",
        "fields": (
            {
                "hint": "The Interactive API app key from your XTS account.",
                "key": "api_key",
                "label": "Interactive App Key",
                "required": True,
                "secret": False,
            },
            {
                "hint": "The Interactive API secret key from your XTS account.",
                "key": "api_secret",
                "label": "Interactive Secret Key",
                "required": True,
                "secret": True,
            },
            {
                "hint": "The Market Data API app key from the same XTS account. Quotes "
                "and the live feed need it.",
                "key": "api_key_market",
                "label": "Market Data App Key",
                "required": False,
                "secret": False,
            },
            {
                "hint": "The Market Data API secret key from the same XTS account.",
                "key": "api_secret_market",
                "label": "Market Data Secret Key",
                "required": False,
                "secret": True,
            },
        ),
        "banner": "Login with IIFL signs you in with one click using your saved Interactive "
        "and Market Data keys.",
        "redirect_hint": "",
    },
    "iiflcapital": {
        "name": "IIFL Capital",
        "sign_in": "redirect",
        "fields": (
            {
                "hint": "The app key of your IIFL Capital app.",
                "key": "api_key",
                "label": "App Key",
                "required": True,
                "secret": False,
            },
            {
                "hint": "The app secret of that app.",
                "key": "api_secret",
                "label": "App Secret",
                "required": True,
                "secret": True,
            },
        ),
        "banner": "Login with IIFL Capital takes you to IIFL Capital's login page. "
        "Log in there and IIFL sends you back to OpenAlgo.",
        "redirect_hint": "Register this exact address as the redirect URL with IIFL "
        "Capital; it must be whitelisted on your app.",
    },
    "indmoney": {
        "name": "IndMoney",
        "sign_in": "form",
        "fields": (
            {
                "hint": "The Client ID shown at indstocks.com, API Trading, Access "
                "Tokens, after you set up TOTP there.",
                "key": "api_key",
                "label": "Client ID",
                "required": True,
                "secret": False,
            },
            {
                "hint": "Leave empty to log in with your MPIN and TOTP "
                "(recommended). A pasted access token is used as is and "
                "lasts 24 hours.",
                "key": "api_secret",
                "label": "Access Token",
                "required": False,
                "secret": True,
            },
        ),
        "banner": "Login with IndMoney opens a short form in OpenAlgo. Each time, enter "
        "your INDstocks MPIN and a fresh TOTP; a new code can be requested "
        "once a minute.",
        "redirect_hint": "",
    },
    "jainamxts": {
        "name": "JainamXts",
        "sign_in": "saved_keys",
        "fields": (
            {
                "hint": "The Interactive API app key from your XTS account.",
                "key": "api_key",
                "label": "Interactive App Key",
                "required": True,
                "secret": False,
            },
            {
                "hint": "The Interactive API secret key from your XTS account.",
                "key": "api_secret",
                "label": "Interactive Secret Key",
                "required": True,
                "secret": True,
            },
            {
                "hint": "The Market Data API app key from the same XTS account. "
                "Quotes and the live feed need it.",
                "key": "api_key_market",
                "label": "Market Data App Key",
                "required": False,
                "secret": False,
            },
            {
                "hint": "The Market Data API secret key from the same XTS account.",
                "key": "api_secret_market",
                "label": "Market Data Secret Key",
                "required": False,
                "secret": True,
            },
        ),
        "banner": "Login with JainamXts signs you in with one click using your saved "
        "Interactive and Market Data keys.",
        "redirect_hint": "",
    },
    "kotak": {
        "name": "Kotak Securities",
        "sign_in": "form",
        "fields": (
            {
                "hint": "Your Kotak Neo Unique Client Code.",
                "key": "api_key",
                "label": "UCC",
                "required": True,
                "secret": False,
            },
            {
                "hint": "The Neo API access token from Kotak's developer portal.",
                "key": "api_secret",
                "label": "Access Token",
                "required": True,
                "secret": True,
            },
        ),
        "banner": "Login with Kotak Securities opens a short form in OpenAlgo. Each time, "
        "enter your registered mobile number, the TOTP from the Kotak Neo app and "
        "your MPIN.",
        "redirect_hint": "",
    },
    "motilal": {
        "name": "Motilal Oswal",
        "sign_in": "form",
        "fields": (
            {
                "hint": "The API key of your Motilal Oswal app.",
                "key": "api_key",
                "label": "API Key",
                "required": True,
                "secret": False,
            },
            {
                "hint": "The API secret of that app, if it has one.",
                "key": "api_secret",
                "label": "API Secret",
                "required": False,
                "secret": True,
            },
        ),
        "banner": "Login with Motilal Oswal opens a short form in OpenAlgo. Each time, "
        "enter your user ID, password, date of birth and, if you use one, your "
        "TOTP.",
        "redirect_hint": "",
    },
    "mstock": {
        "name": "mStock by Mirae Asset",
        "sign_in": "form",
        "fields": (
            {
                "hint": "Your mStock client code (your login ID).",
                "key": "api_key",
                "label": "Client Code",
                "required": True,
                "secret": False,
            },
            {
                "hint": "The API key of your mStock app.",
                "key": "api_secret",
                "label": "API Key",
                "required": True,
                "secret": True,
            },
        ),
        "banner": "Login with mStock by Mirae Asset opens a short form in OpenAlgo. Each "
        "time, enter your mStock password and TOTP.",
        "redirect_hint": "",
    },
    "nubra": {
        "name": "Nubra",
        "sign_in": "form",
        "fields": (
            {
                "hint": "The mobile number registered with your Nubra account.",
                "key": "api_key",
                "label": "Registered Mobile Number",
                "required": True,
                "secret": False,
            },
            {
                "hint": "Your Nubra MPIN.",
                "key": "api_secret",
                "label": "MPIN",
                "required": True,
                "secret": True,
            },
        ),
        "banner": "Login with Nubra opens a short form in OpenAlgo and texts a one-time "
        "code to your registered mobile. Enter it, and OpenAlgo uses your saved "
        "MPIN to finish.",
        "redirect_hint": "",
    },
    "paytm": {
        "name": "Paytm Money",
        "sign_in": "redirect",
        "fields": (
            {
                "hint": "The API key of your Paytm Money app.",
                "key": "api_key",
                "label": "API Key",
                "required": True,
                "secret": False,
            },
            {
                "hint": "The API secret of that app.",
                "key": "api_secret",
                "label": "API Secret",
                "required": True,
                "secret": True,
            },
        ),
        "banner": "Login with Paytm Money takes you to Paytm Money's login page. Log in "
        "there and you are sent back to OpenAlgo.",
        "redirect_hint": "Register this exact address as the redirect URL in your broker app.",
    },
    "pocketful": {
        "name": "Pocketful",
        "sign_in": "redirect",
        "fields": (
            {
                "hint": "The client ID of your Pocketful app, not your trading account ID.",
                "key": "api_key",
                "label": "App Client ID",
                "required": True,
                "secret": False,
            },
            {
                "hint": "The client secret of that app.",
                "key": "api_secret",
                "label": "Client Secret",
                "required": True,
                "secret": True,
            },
        ),
        "banner": "Login with Pocketful takes you to Pocketful's login page. Log in and "
        "approve, and Pocketful sends you back to OpenAlgo.",
        "redirect_hint": "OpenAlgo sends this address with each login. If your broker "
        "app asks for a redirect URL, register this exact address.",
    },
    "rmoney": {
        "name": "RMoney",
        "sign_in": "redirect",
        "fields": (
            {
                "hint": "The Interactive API app key from your RMoney XTS account. "
                "RMoney needs no Interactive secret.",
                "key": "api_key",
                "label": "Interactive App Key",
                "required": True,
                "secret": False,
            },
            {
                "hint": "The Market Data API app key from the same XTS account. Quotes "
                "and the live feed need it.",
                "key": "api_key_market",
                "label": "Market Data App Key",
                "required": False,
                "secret": False,
            },
            {
                "hint": "The Market Data API secret key from the same XTS account.",
                "key": "api_secret_market",
                "label": "Market Data Secret Key",
                "required": False,
                "secret": True,
            },
        ),
        "banner": "Login with RMoney takes you to RMoney's login page. Log in there and "
        "RMoney sends you back to OpenAlgo; your Market Data keys are then used "
        "for quotes and the live feed.",
        "redirect_hint": "OpenAlgo sends this address with each login. If your broker app "
        "asks for a redirect URL, register this exact address.",
    },
    "rupeezy": {
        "name": "Rupeezy",
        "sign_in": "redirect",
        "fields": (
            {
                "hint": "The application ID of your Vortex app on the Rupeezy "
                "developer portal (vortex.rupeezy.in).",
                "key": "api_key",
                "label": "Application ID",
                "required": True,
                "secret": False,
            },
            {
                "hint": "The API key of that Vortex app. OpenAlgo sends it with every "
                "request and uses it to finish each login.",
                "key": "api_secret",
                "label": "API Key",
                "required": True,
                "secret": True,
            },
        ),
        "banner": "Login with Rupeezy takes you to Rupeezy's login page. Log in there and "
        "Rupeezy sends you back to OpenAlgo.",
        "redirect_hint": "Register this exact address as the redirect URL in your broker app.",
    },
    "sahi": {
        "name": "Sahi",
        "sign_in": "saved_keys",
        "fields": (
            {
                "hint": "The key id of an API key from Sahi web, Profile, API Dashboard "
                "(it starts with pk_). Create it with Full access to place "
                "orders.",
                "key": "api_key",
                "label": "API Key",
                "required": True,
                "secret": False,
            },
            {
                "hint": "The secret shown once when that key was created (it starts with "
                "sahi_sk_).",
                "key": "api_secret",
                "label": "API Secret",
                "required": True,
                "secret": True,
            },
        ),
        "banner": "Login with Sahi signs you in with one click using the API key and secret "
        "you saved. Approve the key in Sahi's API Dashboard once each trading day "
        "first, and register the internet address this computer's traffic leaves "
        "from as a static IP on your Sahi account: Sahi refuses orders from any "
        "other address.",
        "redirect_hint": "",
    },
    "samco": {
        "name": "Samco",
        "sign_in": "form",
        "fields": (
            {
                "hint": "The API key of your Samco app (tradeapi.samco.in), emailed "
                "when the app is created.",
                "key": "api_key",
                "label": "API Key",
                "required": True,
                "secret": False,
            },
            {
                "hint": "The API secret of that app, shown once when the app is created.",
                "key": "api_secret",
                "label": "API Secret",
                "required": True,
                "secret": True,
            },
        ),
        "banner": "Login with Samco opens Samco's connect page. One click signs you in with "
        "your saved keys and checks that this computer's internet address is the "
        "static IP registered with Samco.",
        "redirect_hint": "",
    },
    "shoonya": {
        "name": "Shoonya",
        "sign_in": "redirect",
        "fields": (
            {
                "hint": "Your Shoonya user ID and your app's client ID joined by ::: "
                "(userid:::client_id).",
                "key": "api_key",
                "label": "User ID and Client ID",
                "required": True,
                "secret": False,
            },
            {
                "hint": "The secret key of your Shoonya app.",
                "key": "api_secret",
                "label": "Secret Key",
                "required": True,
                "secret": True,
            },
        ),
        "banner": "Login with Shoonya takes you to Shoonya's login page. Log in there "
        "and Shoonya sends you back to OpenAlgo.",
        "redirect_hint": "Register this exact address as the redirect URL in your broker app.",
    },
    "tradejini": {
        "name": "Tradejini",
        "sign_in": "form",
        "fields": (
            {
                "hint": "The API key of your individual app in the Tradejini "
                "developer portal. Tradejini needs no secret; calls must "
                "come from the static IP whitelisted on that app.",
                "key": "api_key",
                "label": "API Key",
                "required": True,
                "secret": False,
            },
        ),
        "banner": "Login with Tradejini opens a short form in OpenAlgo. Each time, "
        "enter your CubePlus login PIN and TOTP.",
        "redirect_hint": "",
    },
    "tradesmart": {
        "name": "TradeSmart",
        "sign_in": "redirect",
        "fields": (
            {
                "hint": "Your TradeSmart user ID and your app key joined by ::: "
                "(userid:::app_key).",
                "key": "api_key",
                "label": "User ID and App Key",
                "required": True,
                "secret": False,
            },
            {
                "hint": "The secret key of your TradeSmart app.",
                "key": "api_secret",
                "label": "Secret Key",
                "required": True,
                "secret": True,
            },
        ),
        "banner": "Login with TradeSmart takes you to TradeSmart's login page. Log in "
        "there and TradeSmart sends you back to OpenAlgo.",
        "redirect_hint": "Register this exact address as the redirect URL in your broker app.",
    },
    "upstox": {
        "name": "Upstox",
        "sign_in": "redirect",
        "fields": (
            {
                "hint": "The API key of your Upstox app.",
                "key": "api_key",
                "label": "API Key",
                "required": True,
                "secret": False,
            },
            {
                "hint": "The API secret of that app.",
                "key": "api_secret",
                "label": "API Secret",
                "required": True,
                "secret": True,
            },
        ),
        "banner": "Login with Upstox takes you to Upstox's login page. Log in there and "
        "Upstox sends you back to OpenAlgo.",
        "redirect_hint": "Register this exact address as the redirect URL in your Upstox "
        "app; it must match character for character (localhost is not "
        "127.0.0.1).",
    },
    "wisdom": {
        "name": "Wisdom Capital",
        "sign_in": "saved_keys",
        "fields": (
            {
                "hint": "The Interactive API app key from your XTS account.",
                "key": "api_key",
                "label": "Interactive App Key",
                "required": True,
                "secret": False,
            },
            {
                "hint": "The Interactive API secret key from your XTS account.",
                "key": "api_secret",
                "label": "Interactive Secret Key",
                "required": True,
                "secret": True,
            },
            {
                "hint": "The Market Data API app key from the same XTS account. Quotes "
                "and the live feed need it.",
                "key": "api_key_market",
                "label": "Market Data App Key",
                "required": False,
                "secret": False,
            },
            {
                "hint": "The Market Data API secret key from the same XTS account.",
                "key": "api_secret_market",
                "label": "Market Data Secret Key",
                "required": False,
                "secret": True,
            },
        ),
        "banner": "Login with Wisdom Capital signs you in with one click using your saved "
        "Interactive and Market Data keys.",
        "redirect_hint": "",
    },
    "zebu": {
        "name": "Zebu",
        "sign_in": "redirect",
        "fields": (
            {
                "hint": "Your Zebu user ID and your app's client ID joined by ::: "
                "(userid:::client_id).",
                "key": "api_key",
                "label": "User ID and Client ID",
                "required": True,
                "secret": False,
            },
            {
                "hint": "The secret key of your Zebu app.",
                "key": "api_secret",
                "label": "Secret Key",
                "required": True,
                "secret": True,
            },
        ),
        "banner": "Login with Zebu takes you to Zebu's login page. Log in there and Zebu "
        "sends you back to OpenAlgo.",
        "redirect_hint": "Register this exact address as the redirect URL in your broker app.",
    },
    "zerodha": {
        "name": "Zerodha",
        "sign_in": "redirect",
        "fields": (
            {
                "hint": "The API key of your Kite Connect app at developers.kite.trade.",
                "key": "api_key",
                "label": "API Key",
                "required": True,
                "secret": False,
            },
            {
                "hint": "The API secret of that app.",
                "key": "api_secret",
                "label": "API Secret",
                "required": True,
                "secret": True,
            },
        ),
        "banner": "Login with Zerodha takes you to Zerodha's Kite login page. Log in "
        "there and Zerodha sends you back to OpenAlgo. Market data needs an "
        "active Kite Connect subscription.",
        "redirect_hint": "Register this exact address as the redirect URL in your broker app.",
    },
}


def guide(broker):
    """The Broker Configuration entry for a broker, the generic one if unknown."""
    entry = GUIDES.get(broker)
    if entry is not None:
        return entry
    from utils.broker_keys import broker_title
    from utils.broker_login import CALLBACK_START_BROKERS

    sign_in = "form" if broker in CALLBACK_START_BROKERS else "redirect"
    return {
        "name": broker_title(broker),
        "sign_in": sign_in,
        "fields": _GENERIC_FIELDS,
        "banner": _GENERIC_BANNERS[sign_in],
        "redirect_hint": REDIRECT_REGISTER if sign_in == "redirect" else "",
    }


def uses_redirect_url(broker):
    """Whether the broker sends the trader back to a redirect URL."""
    return guide(broker)["sign_in"] == "redirect"
