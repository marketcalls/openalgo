
# ⚙️ How to Integrate Any XTS API-Supported Broker in OpenAlgo (5-Minute Setup)

OpenAlgo already supports XTS API through the `compositedge` plugin. Any broker using XTS (like AliceBlue, SMC Global, SSJ, etc.) can be added with **zero code duplication**—just a few config updates.

---

## ✅ Minimal Changes Required

| File            | What to Change                                      |
|-----------------|-----------------------------------------------------|
| `baseurl.py`    | Update to your broker’s base domain and API paths   |
| `brlogin.py`    | Add your broker’s login redirect                    |
| `broker.html`   | Add login UI card for your broker                   |
| `.env`          | Add the new broker’s credentials                    |

> ⚡️ *No other backend or API changes are needed if the broker supports `apibinarymarketdata`.*

---

## 🧩 Step-by-Step Integration Guide

### 1. 🗂 Copy or Repurpose `compositedge`

Either copy the existing plugin:

```bash
cp -r broker/compositedge broker/<yourbroker>
```

Or reuse `compositedge` folder directly, just updating the credentials and URLs dynamically.

---

### 2. ✏️ Edit `baseurl.py`

Replace the base URLs with your broker's:

```python
BASE_URL = "https://xts.<yourbroker>.com"  # Replace with actual broker domain

MARKET_DATA_URL = f"{BASE_URL}/apibinarymarketdata"
INTERACTIVE_URL = f"{BASE_URL}/interactive"
```

> ✅ This makes the integration use your broker’s market data and trading APIs.

---

### 3. 🌐 Update `brlogin.py`

Add your broker to the login logic:

```python
elif broker_name == "xtsbroker":
    return redirect(get_xts_login_url("xtsbroker"))
```

The `get_xts_login_url()` should be implemented or reused from `auth_api.py` to build the OAuth redirect URL.

---

### 4. 🖼️ Update `broker.html`

Add a clickable card for your broker:

```html
<a href="/login/xtsbroker">
  <div class="broker-card">
    <img src="/static/xtsbroker.png" alt="XTS Broker Logo" />
    <p>XTS Broker</p>
  </div>
</a>
```

---

### 5. 🔐 Add Environment Variables

Update `.env` or `.sample.env` with:

```env
# Broker Configuration
BROKER_API_KEY='YOUR_BROKER_API_KEY'
BROKER_API_SECRET='YOUR_BROKER_API_SECRET'

# Market Data Configuration (Optional and Required only for XTS API Supported Brokers)
BROKER_API_KEY_MARKET='YOUR_BROKER_MARKET_API_KEY'
BROKER_API_SECRET_MARKET='YOUR_BROKER_MARKET_API_SECRET'

# Redirect URL (adjust broker name as required)
REDIRECT_URL='http://127.0.0.1:5000/<broker>/callback'

# List of Valid Brokers
VALID_BROKERS='fivepaisa,aliceblue,angel,compositedge,dhan,firstock,flattrade,fyers,icici,kotak,paytm,shoonya,upstox,zebu,zerodha,xtsbroker'
```

> 🔐 **Important**: If your broker is not added to `VALID_BROKERS`, login attempts will be blocked.

---

## 🧪 Final Integration Checklist

- [x] Login from UI via `broker.html`
- [x] Token stored in session and database
- [x] Order API: `/api/place_order`
- [x] Historical API: `/api/history`
- [x] Funds, positions, holdings work
- [x] Master contract is downloaded
- [x] WebSocket live data via `apibinarymarketdata`

---

# 📁 Breakdown: `broker/compositedge/` Folder

Use this plugin as a boilerplate for all future XTS broker integrations.

### 🔹 `baseurl.py`
Defines base URLs for:
- XTS Interactive API
- XTS Binary Market Data (WebSocket)

```python
BASE_URL = "https://xts.<broker>.com"
MARKET_DATA_URL = f"{BASE_URL}/apibinarymarketdata"
INTERACTIVE_URL = f"{BASE_URL}/interactive"
```

---

### 🔹 `plugin.json`
Broker metadata:

```json
{
  "broker": "compositedge",
  "display_name": "CompositeEdge",
  "api_class": "xts_api",
  "auth_type": "oauth",
  "version": "1.0"
}
```

---

### 📁 `api/` – XTS API Wrappers

| File             | Purpose                                      |
|------------------|----------------------------------------------|
| `auth_api.py`    | Handles login, token exchange, logout        |
| `order_api.py`   | Places, modifies, cancels orders             |
| `data.py`        | Fetches OHLC, LTP, quotes                    |
| `funds.py`       | Fetches available margin/fund details        |

---

### 📁 `database/` – Contract Storage

| File                   | Purpose                                 |
|------------------------|-----------------------------------------|
| `master_contract_db.py`| Downloads and parses broker contract DB |

---

### 📁 `mapping/` – Format Translators

| File                | Role                                                  |
|---------------------|-------------------------------------------------------|
| `order_data.py`     | Maps OpenAlgo's order schema to XTS format            |
| `transform_data.py` | Converts XTS API responses to OpenAlgo standard       |

---

# 🚀 Conclusion

Thanks to OpenAlgo’s modular architecture and XTS API’s standardization:

> ⚡️ **You can integrate any new XTS-supported broker in under 5 minutes**—by only changing `baseurl.py`, updating `.env`, and adding a login hook.

This keeps the backend logic DRY, secure, and highly extensible.
