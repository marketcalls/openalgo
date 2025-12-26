# Cloudflare Tunnel Setup

This folder contains instructions and configuration for running a Cloudflare Tunnel
to expose a local service securely to the internet.

> ⚠️ Tunnel credential JSON files are secrets and are intentionally git-ignored.

---

## 1. Prerequisites

- Cloudflare account
- A domain added to Cloudflare (for custom domain setup)
- `cloudflared` installed

### Install cloudflared (Windows)
```powershell
winget install Cloudflare.cloudflared
````

Verify:

```powershell
cloudflared --version
```

---

## 2. Option A — Free / Temporary Tunnel (No Domain Required)

Use this for quick testing or demos.

```powershell
cloudflared tunnel --url http://127.0.0.1:5000
```

Cloudflare will generate a **temporary public URL** like:

```
https://random-name.trycloudflare.com
```

Limitations:

* URL changes every time
* No custom domain
* Not meant for production

---

## 3. Option B — Custom Domain Tunnel (Recommended)

### Step 1: Login

```powershell
cloudflared tunnel login
```

Select your domain when prompted.

---

### Step 2: Create a tunnel

```powershell
cloudflared tunnel create openalgo
```

This creates a credentials JSON file (DO NOT COMMIT).

---

### Step 3: Create `config.yml`

Example:

```yaml
tunnel: openalgo
credentials-file: <ABSOLUTE_PATH_TO_JSON>

ingress:
  - hostname: demo.example.com
    service: http://127.0.0.1:5000
  - service: http_status:404
```

---

### Step 4: Route DNS

```powershell
cloudflared tunnel route dns openalgo demo.example.com
```

---

### Step 5: Run the tunnel

```powershell
cloudflared tunnel --config .\config.yml run openalgo
```

---

## 4. Notes

* Cloudflare Tunnel always serves traffic over **HTTPS**
* The local service must be running before starting the tunnel
* Spaces in Windows paths are supported
* The JSON credentials file must never be shared

---
