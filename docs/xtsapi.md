# ⚙️ How to Integrate Any XTS API-Supported Broker in OpenAlgo (5-Minute Setup)

OpenAlgo already supports XTS API through the `compositedge` plugin. Any broker using XTS (like IIFL, Nirmal Bang, Anand Rathi, Jainam, 5paisa, etc.) can be added with **zero code duplication**—just a few config updates.

---

## ✅ Minimal Changes Required

| File            | What to Change                                      |
|-----------------|-----------------------------------------------------|
| `baseurl.py`    | Update to your broker’s base domain and API paths   |
| `brlogin.py`    | Add your broker’s login redirect logic              |
| `broker.html`   | Add broker option and JS login switch               |
| `.sample.env`   | Add the new broker’s credentials                    |

> ⚡️ *No other backend or API changes are needed if the broker supports `apibinarymarketdata`.*

---

## 🧩 Step-by-Step Integration Guide

### 1. 🗂 Copy or Repurpose `compositedge`

```bash
cp -r broker/compositedge broker/<yourbroker>
```

Or reuse the same folder and override dynamically via `.env`.

---

### 2. ✏️ Edit `baseurl.py`

Update the base API endpoints:

```python
BASE_URL = "https://xts.<yourbroker>.com"

MARKET_DATA_URL = f"{BASE_URL}/apibinarymarketdata"
INTERACTIVE_URL = f"{BASE_URL}/interactive"
```

---

### 3. 🌐 Update `brlogin.py`

Add a new block similar to `compositedge`:

```python
elif broker == 'xtsalpha':
    # exact duplicate of compositedge logic with broker name replaced
    # handles session parsing and accessToken extraction
```

This ensures session redirection from XTS works correctly.

---

### 4. 🖼️ Update `broker.html`

#### A. Add broker to the dropdown:

```html
<option value="xtsalpha" {{ 'disabled' if broker_name != 'xtsalpha' }}>XTS Alpha {{ '(Disabled)' if broker_name != 'xtsalpha' }}</option>
```

#### B. Add to JavaScript login handler:

```javascript
case 'xtsalpha':
    loginUrl = 'https://xts.xtsalpha.com/interactive/thirdparty?appKey={{broker_api_key}}&returnURL={{ redirect_url }}';
    break;
```

> ✅ No need to add a broker login card section with `<a>` or `<img>`.

---

### 5. 🔐 Update `.env` or `.sample.env`

```env
# Broker Configuration
BROKER_API_KEY='YOUR_BROKER_API_KEY'
BROKER_API_SECRET='YOUR_BROKER_API_SECRET'

# Market Data Configuration (XTS only)
BROKER_API_KEY_MARKET='YOUR_BROKER_MARKET_API_KEY'
BROKER_API_SECRET_MARKET='YOUR_BROKER_MARKET_API_SECRET'

# OAuth Redirect
REDIRECT_URL='http://127.0.0.1:5000/xtsalpha/callback'

# Valid Brokers (must include new one)
VALID_BROKERS='fivepaisa,aliceblue,angel,compositedge,dhan,firstock,flattrade,fyers,icici,kotak,paytm,shoonya,upstox,zebu,zerodha,xtsalpha'
```

---

### ✅ Update Required in `.env` / `.sample.env`

To allow login for your new broker, you **must** add it to `VALID_BROKERS`.

#### Example:

**Before:**
```env
VALID_BROKERS='fivepaisa,aliceblue,angel,...'
```

**After:**
```env
VALID_BROKERS='fivepaisa,aliceblue,angel,...,xtsalpha'
```

> 🔐 This whitelist mechanism is used by `brlogin.py` or router logic to restrict unauthorized brokers.

---

## 🔁 Update Required in `brlogin.py` for New XTS Broker

You must add a block like this:

```python
elif broker == 'xtsalpha':
    try:
        if request.method == 'POST':
            if request.headers.get('Content-Type') == 'application/x-www-form-urlencoded':
                raw_data = request.get_data().decode('utf-8')
                if raw_data.startswith('session='):
                    from urllib.parse import unquote
                    session_data = unquote(raw_data[8:])
                else:
                    session_data = raw_data
            else:
                session_data = request.get_data().decode('utf-8')
        else:
            session_data = request.args.get('session')

        if not session_data:
            return jsonify({"error": "No session data received"}), 400

        try:
            if isinstance(session_data, str):
                session_data = session_data.strip()
                session_json = json.loads(session_data)
                if isinstance(session_json, str):
                    session_json = json.loads(session_json)
            else:
                session_json = session_data

        except json.JSONDecodeError as e:
            return jsonify({
                "error": f"Invalid JSON format: {str(e)}",
                "raw_data": session_data
            }), 400

        access_token = session_json.get('accessToken')
        if not access_token:
            return jsonify({"error": "No access token found"}), 400

        auth_token, feed_token, user_id, error_message = auth_function(access_token)
        forward_url = 'broker.html'

    except Exception as e:
        return jsonify({"error": f"Error processing request: {str(e)}"}), 500
```

---

## 📁 Breakdown: `broker/compositedge/` Folder Structure

```
broker/compositedge/
├── baseurl.py                  # XTS API base URLs
├── plugin.json                 # Metadata for plugin info
│
├── api/
│   ├── auth_api.py             # OAuth login + token handling
│   ├── data.py                 # Historical, quotes, LTP
│   ├── order_api.py            # Order handling (place, modify, cancel)
│   └── funds.py                # Fetch margin/funds
│
├── database/
│   └── master_contract_db.py   # Download & store broker's symbol master
│
└── mapping/
    ├── order_data.py           # OpenAlgo → XTS order translation
    └── transform_data.py       # XTS → OpenAlgo data formatting
```

---

### 📦 `plugin.json` Sample

```json
{
  "Plugin Name": "compositedge",
  "Plugin URI": "https://openalgo.in",
  "Description": "CompositedgeOpenAlgo Plugin",
  "Version": "1.0",
  "Author": "Kalaivani",
  "Author URI": "https://openalgo.in"
}
```

> 📦 Currently used for plugin metadata. Future versions may support dynamic plugin discovery.

---

## 🧪 Final Integration Checklist

- [x] Login from UI via `broker.html`
- [x] Token exchange successful
- [x] Order API: `/api/place_order`
- [x] Historical: `/api/history`
- [x] Funds and positions display
- [x] Master contract is downloaded
- [x] Market feed via `apibinarymarketdata`

---

## 🚀 Conclusion

Thanks to OpenAlgo’s modular and broker-agnostic design:

> 💡 You can integrate **any XTS broker in under 5 minutes** by changing only `baseurl.py`, `.env`, and a few UI/backend hooks.
