# Ubuntu Server Installation

### Prerequisites

#### System Requirements

* Ubuntu Server (22.04 LTS or later recommended)
* Minimum 2 GB RAM (or 0.5 GB + 2 GB swap — the installer auto-creates the swap file if needed)
* 1 GB free disk
* 1 vCPU
* Clean installation recommended

OpenAlgo runs on Ubuntu, Debian, Raspbian, RHEL, Rocky, AlmaLinux, Amazon Linux, Fedora, and Arch — the installation script auto-detects the distro and uses the right package manager. The flow below uses Ubuntu as the example.

#### Domain and DNS Setup (Required)

1. **Cloudflare Account Setup**
   * Create a Cloudflare account if you don't have one
   * Add your domain to Cloudflare
   * Update your domain's nameservers to Cloudflare's nameservers
2. **DNS Configuration**
   * Add an A record pointing to your server's IP address

     ```
     Type: A
     Name: yourdomain.com
     Content: YOUR_SERVER_IP
     Proxy status: Proxied
     ```

   * Add a CNAME record for `www` (optional — not required for `sub.yourdomain.com`)

     ```
     Type: CNAME
     Name: www
     Content: yourdomain.com
     Proxy status: Proxied
     ```
3. **SSL/TLS Configuration in Cloudflare**
   * Go to SSL/TLS section
   * Set encryption mode to **Full (strict)**

#### Broker Setup (Required)

* Obtain your broker's API credentials per the OpenAlgo documentation:
  * API Key
  * API Secret
* Prepare the redirect URL based on your domain and broker name:

```
# Example - root domain yourdomain.com with Zerodha
https://yourdomain.com/zerodha/callback

# Example - subdomain sub.yourdomain.com with Angel
https://sub.yourdomain.com/angel/callback
```

### Login to the Ubuntu Server

```bash
# Connect to your Ubuntu server via SSH
# Example: ssh root@134.56.76.23

ssh user@your_server_ip
```

### Installation Steps

#### 1. Download the Installation Script

```bash
mkdir -p ~/openalgo-install
cd ~/openalgo-install

wget https://raw.githubusercontent.com/marketcalls/openalgo/main/install/install.sh
chmod +x install.sh
```

#### 2. Run the Installation Script

```bash
sudo ./install.sh
```

The script will interactively prompt you for:

* Your domain name (root domains and subdomains both supported)
* Broker selection (30+ brokers — see the prompt for the full list)
* Broker API credentials (Key + Secret)
* For XTS-based brokers (5paisa XTS, Compositedge, IIFL, etc.): additional market-data API key/secret
* **Enable Remote MCP?** (y/N) — opt-in to expose `/mcp` and `/oauth/*` for hosted AI clients (Claude.ai, ChatGPT) at the same domain. You can also enable this later from the admin UI

The installer will:

* Detect your distro (Ubuntu / Debian / RHEL / Fedora / Arch / Amazon Linux) and use the right package manager
* Install required packages, including Chromium (used for Telegram /chart rendering — non-fatal if unavailable)
* Install the `uv` package manager (via snap on Ubuntu, or the Astral standalone installer on PEP 668 systems like Ubuntu 24.04+)
* Configure Nginx with HTTPS via Let's Encrypt (Certbot)
* Set up the OpenAlgo application under `/var/python/openalgo`
* Create the systemd unit `openalgo.service`
* Generate timestamped installation logs in `~/openalgo-install/logs/`

#### Default Layout (single deployment)

After a successful run, the install lives at:

```
/var/python/openalgo/                  cloned repo
/var/python/openalgo/.venv/            uv-managed Python virtual environment
/var/python/openalgo/.env              configuration
/var/python/openalgo/openalgo.sock     Gunicorn Unix socket
/etc/systemd/system/openalgo.service   systemd unit
/etc/nginx/sites-available/openalgo.conf   Nginx vhost (stable name across domain changes)
```

The Nginx vhost name `openalgo.conf` is intentionally fixed — `install/change-domain.sh` updates `server_name` in place rather than renaming the file.

#### Multi-Domain Deployment (Optional)

The default `install.sh` is single-deploy per server. If you need 2+ OpenAlgo instances side by side (different broker per instance, etc.), use the dedicated multi-deploy installer:

```bash
wget https://raw.githubusercontent.com/marketcalls/openalgo/main/install/install-multi.sh
chmod +x install-multi.sh
sudo ./install-multi.sh
```

Multi-deploy installs use a per-deployment layout:

```
/var/python/openalgo-flask/<domain-broker>/openalgo/
/var/python/openalgo-flask/<domain-broker>/venv/
openalgo-<domain-broker>.service
```

Each deployment gets its own service, configuration, virtual environment, SSL certificate, and log file. The single-deploy `update.sh` and `change-domain.sh` scripts also handle this layout transparently — they detect the simple path first and fall back to scanning `/var/python/openalgo-flask/`.

#### 3. Verify the Installation

1. **Check service status**

   ```bash
   sudo systemctl status openalgo
   ```
2. **Test the Nginx configuration**

   ```bash
   sudo nginx -t
   ls -l /etc/nginx/sites-enabled/openalgo.conf
   ```
3. **Open the dashboard** at `https://yourdomain.com`
4. **View installation log**

   ```bash
   ls -l ~/openalgo-install/logs/
   cat ~/openalgo-install/logs/install_YYYYMMDD_HHMMSS.log
   ```

### Remote MCP

Remote MCP exposes `/mcp` and `/oauth/*` so hosted AI clients (claude.ai, chatgpt.com) can connect to your OpenAlgo install over HTTPS. Local stdio MCP (Claude Desktop, Cursor, Windsurf) is unaffected — it works regardless of this setting.

You can enable Remote MCP two ways:

1. **At install time** — answer `y` when `install.sh` prompts. The installer sets `MCP_HTTP_ENABLED='True'` and `MCP_PUBLIC_URL='https://yourdomain.com'` in `.env` for you.

2. **From the admin UI** — visit `https://yourdomain.com/admin/remote-mcp`. The settings card at the top of the page lets you flip Remote MCP on or off, edit the public HTTPS origin, and adjust the OAuth posture toggles. Saving writes the new values to `.env`; a yellow banner then prompts you to restart the service:

   ```bash
   sudo systemctl restart openalgo
   ```

   The banner clears automatically once the running process picks up the new values.

#### Available Toggles

| Toggle | `.env` key | Default |
|---|---|---|
| Remote MCP enabled | `MCP_HTTP_ENABLED` | `False` |
| Auto-approve hosted clients | `MCP_OAUTH_REQUIRE_APPROVAL` | `False` (auto-approve ON) |
| Allow order placement | `MCP_OAUTH_WRITE_SCOPE_ENABLED` | `True` |

The MCP URL to give your AI client is the same as your dashboard URL with `/mcp` appended — e.g. `https://yourdomain.com/mcp`. The admin page displays it with a copy button when MCP is configured.

### Troubleshooting

#### Common Issues

1. **SSL certificate issues**

   ```bash
   sudo journalctl -u certbot

   # Re-run Certbot manually
   sudo certbot --nginx -d yourdomain.com
   ```

2. **Application not starting**

   ```bash
   # View live logs
   sudo journalctl -fu openalgo

   # Last 100 lines
   sudo journalctl -n 100 -u openalgo

   # Restart
   sudo systemctl restart openalgo
   ```

3. **Nginx issues**

   ```bash
   # Test config
   sudo nginx -t

   # Error log
   sudo tail -f /var/log/nginx/error.log

   # Access log
   sudo tail -f /var/log/nginx/access.log

   # Reload after config changes
   sudo systemctl reload nginx
   ```

4. **Installation logs**

   ```bash
   ls -l ~/openalgo-install/logs/
   cat ~/openalgo-install/logs/$(ls -t ~/openalgo-install/logs/ | head -1)
   ```

5. **`uv` install failed with `externally-managed-environment`**

   This is PEP 668 enforcement on Ubuntu 24.04+ / Debian 12+. The current `install.sh` falls through to the Astral standalone installer automatically; if you're on an older copy, refresh the script and re-run:

   ```bash
   cd ~/openalgo-install
   rm -f install.sh
   wget https://raw.githubusercontent.com/marketcalls/openalgo/main/install/install.sh
   chmod +x install.sh
   sudo ./install.sh
   ```

6. **Inspect the install directly**

   ```bash
   # Repo
   ls /var/python/openalgo

   # Effective configuration
   sudo cat /var/python/openalgo/.env

   # Application logs
   sudo tail -f /var/python/openalgo/log/openalgo_$(date +%F).log

   # JSON-formatted error log (always-on)
   sudo tail -f /var/python/openalgo/log/errors.jsonl
   ```

#### Multi-Domain Deployment Notes

If you ran `install-multi.sh` (per-deployment layout), substitute the deployment-specific names everywhere:

```bash
# List all OpenAlgo services on this host
systemctl list-units 'openalgo*'

# Manage a specific deployment (example: trading1.yourdomain.com + Fyers)
sudo systemctl status openalgo-trading1-yourdomain-com-fyers
sudo journalctl -fu openalgo-trading1-yourdomain-com-fyers

# Per-deployment install directories
ls /var/python/openalgo-flask/
```

### Updating

```bash
cd ~/openalgo-install
wget https://raw.githubusercontent.com/marketcalls/openalgo/main/install/update.sh
chmod +x update.sh
sudo ./update.sh
```

The update script detects both layouts (single-deploy at `/var/python/openalgo` and legacy multi-deploy under `/var/python/openalgo-flask/`) and asks which to update if multiple are present. It runs `git pull`, `uv sync`, and restarts the service.

### Changing the Domain

```bash
cd ~/openalgo-install
wget https://raw.githubusercontent.com/marketcalls/openalgo/main/install/change-domain.sh
chmod +x change-domain.sh
sudo ./change-domain.sh
```

The script updates `.env` (`HOST_SERVER`, `WEBSOCKET_URL`), the Nginx vhost's `server_name`, requests a new Let's Encrypt certificate for the new domain, and restarts the service.

### Security Notes

1. **Firewall**

   The installer configures UFW to allow only SSH, HTTP, and HTTPS. Open additional ports as needed:

   ```bash
   sudo ufw allow <port_number>
   ```

2. **SSL/TLS**

   * Certificates are auto-renewed by Certbot
   * The Nginx vhost uses TLS 1.2/1.3, modern ciphers, OCSP stapling, and HSTS
   * Keep the system patched:

     ```bash
     sudo apt update && sudo apt upgrade -y
     ```

3. **`.env` file**

   Contains `APP_KEY`, `API_KEY_PEPPER`, and broker credentials. The installer sets `chmod 600` on it and ownership to the service user (`www-data` on Ubuntu/Debian, `nginx` on RHEL, `http` on Arch). Never commit this file or expose it via Nginx.

4. **Auto-logout**

   Indian broker tokens expire daily at ~3:00 AM IST and the app forces a re-login at that time. For 24/7 crypto brokers (Delta Exchange), the installer detects this and disables the auto-logout.

5. **Single user per deployment**

   OpenAlgo is designed for one trader per server. There is no multi-user model — server access equals full control of the broker session. Don't share the host.

### Post-Installation

1. Configure your broker login on the dashboard
2. Set up monitoring and Telegram alerts if desired
3. Periodically review `log/errors.jsonl` for issues
4. Apply security updates regularly

### Support

* GitHub: [github.com/marketcalls/openalgo](https://github.com/marketcalls/openalgo)
* Documentation: [docs.openalgo.in](https://docs.openalgo.in)
* Discord: [openalgo.in/discord](https://www.openalgo.in/discord)

Remember to:

* Regularly back up your `.env` file and the `db/` directory
* Monitor system resources
* Keep the system updated
* Review security best practices

---

# Agent Instructions: Querying This Documentation

If you need additional information that is not directly available in this page, you can query the documentation dynamically by asking a question.

Perform an HTTP GET request on the current page URL with the `ask` query parameter:

```
GET https://docs.openalgo.in/installation-guidelines/getting-started/ubuntu-server-installation.md?ask=<question>
```

The question should be specific, self-contained, and written in natural language.
The response will contain a direct answer to the question and relevant excerpts and sources from the documentation.

Use this mechanism when the answer is not explicitly present in the current page, you need clarification or additional context, or you want to retrieve related documentation sections.
