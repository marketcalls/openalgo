# OpenAlgo Advanced Docker Installation (Multi-Instance & Custom SSL)

This guide covers the advanced installation script (`install-docker-multi-custom-ssl.sh`), which is designed for power users who need:
- **Multiple OpenAlgo instances** on a single server.
- **Custom SSL Certificates** (e.g., Wildcard SSLs).
- **Portainer** for container management.
- **Robust Healthchecks** and automatic error recovery: a failed image build never replaces a running instance.
- **Per-instance options**: the web server (eventlet or the opt-in gthread) and a memory profile.

## Quick Start

Run the following command on your Ubuntu 20.04+ or Debian 11+ server:

```bash
wget https://raw.githubusercontent.com/marketcalls/openalgo/main/install/install-docker-multi-custom-ssl.sh
chmod +x install-docker-multi-custom-ssl.sh
./install-docker-multi-custom-ssl.sh
```

## Prerequisites

- **OS**: Ubuntu 20.04+ LTS (Recommended: Ubuntu 24.04 LTS for Azure ARM64)
- **Permissions**: Root access or `sudo` privileges.
- **Domain**: A valid domain pointed to your server IP.
- **Ports**: 80, 443 (Server), 9000 (Portainer - Optional), 22 (SSH).

## Installation Features

When you run the script, it will interactively prompt you for:

1.  **Git repository**: press Enter for `https://github.com/marketcalls/openalgo.git`.

2.  **Domains**: one or more domain names separated by spaces (for example `zerodha.example.com upstox.example.com`). Each domain is one independent OpenAlgo instance, installed in `/opt/openalgo/<domain>`.

3.  **Per new instance**: broker, API key and secret (and the market-data key and secret for XTS brokers).

4.  **SSL Configuration** (new domains only):
    - **Let's Encrypt**: Auto-generate free SSL certificates.
    - **Custom SSL**: Provide paths to your existing `.pem` and `.key` files, or one wildcard certificate for all new domains.

5.  **Per instance (new and updated)**: the web server and the memory profile. Pressing Enter keeps what the instance already has. See below.

6.  **Portainer Management UI**:
    - Option to install Portainer to manage your Docker containers visually.
    - Can be exposed on a subdomain (e.g., `portainer.example.com`) or via IP (`http://IP:9000`).

## Web server: eventlet or gthread

OpenAlgo runs on **eventlet** by default. **gthread** is an opt-in alternative (one thread per request, 64 per instance) described in [`docs/gthread/README.md`](../docs/gthread/README.md). Each instance chooses for itself, so one can run gthread while another stays on eventlet.

- The installer asks `Web server for <domain> [eventlet/gthread]`. Enter keeps the current one; new instances start on eventlet.
- The choice is written to the instance's `.env` as `OPENALGO_WORKER_CLASS = 'gthread'` (or `'eventlet'`) **after** the image builds, so a failed build never changes it.
- Every generated compose file sets `stop_grace_period: 45s`. gthread needs it (a stop lets open requests finish for up to 30 s; Docker would otherwise kill the container after 10 s). It does no harm on eventlet.
- A changed web server recreates the container, because `.env` is bind-mounted and Docker does not restart a container when it changes.
- After starting, the installer reads the container log and confirms the instance really runs on the server it asked for. An image without the gthread launcher (an older OpenAlgo version or a fork) silently falls back to eventlet; the installer reports that as a failure instead of success.
- **Switch at the right time.** A switch restarts the instance and pauses strategies and market data for up to a minute. The gthread guide asks for 23:30-09:00 IST. Between 09:00 and 23:30 IST the installer asks for an explicit `yes` (set `FORCE_WORKER_SWITCH=1` to skip the question).
- Unattended runs: `INSTALL_WORKER_CLASS=gthread` answers the question for **every** instance in that run.
- Switching later without the installer: `openalgo-ctl worker <domain> gthread` (or `eventlet`); `openalgo-ctl worker <domain>` shows what `.env` asks for and what is running.

Only Upstox is listed as verified on gthread so far, and only on a single instance. Try it on one instance first.

## Memory profile

Each instance has one of two profiles, asked per instance (Enter keeps the current one) and remembered in `<instance>/.installer.conf`:

| | `auto` (default) | `unrestricted` |
|---|---|---|
| Strategy memory cap (`STRATEGY_MEMORY_LIMIT_MB`) | 256 / 512 / 1024 MB, by RAM per instance (RAM divided by the instances in **this run**) | 3072 MB (override with `STRATEGY_MEM_LIMIT_MB`) |
| `/dev/shm` | 25% of that share, 128-1024 MB | 1024 MB |
| BLAS/OMP threads | 1-4 by RAM share and cores | by core count, 2-4 |
| Container memory limit | none | none |

Notes:
- `STRATEGY_MEMORY_LIMIT_MB` limits each Python **strategy process** (as address space, `RLIMIT_AS`), not the container. Scripts that import numpy or pandas reach it with far less real memory. If you test many or large strategy scripts, use `unrestricted`.
- Neither profile caps the container. To add a ceiling that protects the other instances, set `OPENALGO_CONTAINER_MEM_MB=4096` (for example) when running the installer; it writes `mem_limit` into every instance in that run.
- The `auto` share depends on how many domains you enter in one run, so updating two instances together gives each a smaller share than updating them one at a time. `unrestricted` does not depend on it.
- Unattended runs: `INSTALL_MEMORY_PROFILE=unrestricted` answers the question for every instance in that run.

## Setting Up Portainer (Important)

If you chose to install Portainer, follow these steps immediately after installation:

1.  **Access Portainer**:
    - Open your browser and navigate to the domain you configured (e.g., `https://portainer.example.com`) or `http://YOUR_SERVER_IP:9000`.

2.  **Create Admin User**:
    - You will be asked to create an initial admin username and password.
    - **Note:** For security, Portainer creates a timeout window for this initial setup.

### **Restarting Portainer (If Setup Times Out)**

If you wait too long to configure Portainer after installation, you may be locked out of the initial setup screen. To fix this, you must restart the container to reset the setup window:

```bash
# Restart the Portainer container
docker restart portainer
```

After running this command, refresh your browser immediately and set up your username and password.

## Managing Multiple Instances

Each instance lives in `/opt/openalgo/<domain>` with its own ports, containers and Docker volumes, so `docker compose` commands run in the instance directory. The installer also creates `openalgo-ctl`:

```
/opt/openalgo/
  ├── zerodha.example.com/   # Instance 1
  │   ├── docker-compose.yaml
  │   └── .env
  └── upstox.example.com/    # Instance 2
      ├── docker-compose.yaml
      └── .env
```

```bash
openalgo-ctl list
openalgo-ctl restart <domain>
openalgo-ctl logs <domain>
openalgo-ctl status <domain>
openalgo-ctl worker <domain> [gthread|eventlet]
```

Or directly:

```bash
cd /opt/openalgo/zerodha.example.com
docker compose logs -f
docker compose restart
```

Each instance is published only on `127.0.0.1` (Flask from port 5000, WebSocket from 8765, one pair per instance); Nginx on the host serves it over HTTPS. **An instance keeps its ports across updates.** Ports are only allocated for a new instance.

## Updating Existing Instances

When you run the script with existing domains, it will detect them and offer smart update options:

```
Instance for domain.com already exists. Update code only? (y=update, n=skip, r=reinstall):
```

| Option | Behavior |
|--------|----------|
| **y (Update)** | Pulls latest code, preserves `.env` file (passwords remain valid), skips the broker, credential and SSL prompts, and asks only for the web server and memory profile |
| **n (Skip)** | Skips this domain entirely |
| **r (Reinstall)** | Fresh install with new config ( regenerates security keys, invalidates existing passwords) |

### What Gets Preserved During Updates

When you choose **Update (y)**:
- `.env` file (APP_KEY, PEPPER, broker credentials, web server choice). Only `OPENALGO_GIT_BRANCH` and `OPENALGO_GIT_COMMIT` are refreshed on every run, to the commit just built, so the Diagnostics page shows what is running.
- User passwords and login sessions
- SSL certificates
- Database (stored in Docker volumes)
- The instance's ports and its memory profile

### If the image build fails

The compose file and Nginx vhost are saved before anything changes and put back if the build fails, so the container that was already running stays reachable on its existing ports. The run ends with `INSTALLATION COMPLETED WITH ERRORS` and lists the instances that did not update. Fix the cause and run the script again.

### Portainer Smart Detection

If Portainer is already running, the script will:
1. Detect the existing installation
2. Offer to check for version updates
3. Skip redundant configuration prompts

## Troubleshooting

1.  **Healthcheck Failures**:
    - If the container shows `unhealthy`, check the container log: `openalgo-ctl logs <domain>`.

2.  **SSL Errors**:
    - If using Custom SSL, ensure your `.pem` file supports the full chain and your `.key` file is unencrypted.
    - Check Nginx logs: `tail -f /var/log/nginx/error.log`

3.  **WebSocket 403 Errors**:
    - If you experience disconnects after broker re-login, restart the specific instance:
      ```bash
      openalgo-ctl restart <domain>
      ```

4.  **The image build is very slow or times out downloading Python packages**
    (`ReadTimeoutError ... files.pythonhosted.org`):
    - PyPI is served by a CDN. From some networks one CDN edge is fast and the others crawl, so a 16 MB download can take minutes or fail while other sites are fast. This is a routing problem outside OpenAlgo.
    - Check from the server itself (not inside Docker): download a wheel with `curl -4` and look at the speed. If the host is slow too, Docker is not the cause.
    - Forcing IPv4 does not help: Docker builds already use IPv4, and many servers have no IPv6 route at all.
    - Pin the download host to a fast edge for the build:
      ```bash
      sudo PYPI_EDGE_IP=auto ./install-docker-multi-custom-ssl.sh      # time each known edge, pin the fastest if DNS is slow
      sudo PYPI_EDGE_IP=151.101.128.223 ./install-docker-multi-custom-ssl.sh   # or pin one address yourself
      ```
      This writes `extra_hosts` into the build section of each generated compose file. It is a workaround: leave `PYPI_EDGE_IP` unset once routing is normal again.
    - Otherwise wait and re-run; a failed build never replaces a running instance.

## Environment variables

All optional. Set them in front of the command, for example `sudo INSTALL_WORKER_CLASS=gthread ./install-docker-multi-custom-ssl.sh`.

| Variable | Effect |
|---|---|
| `INSTALL_WORKER_CLASS` | `eventlet` or `gthread`, for every instance in the run (skips the question) |
| `INSTALL_MEMORY_PROFILE` | `auto` or `unrestricted`, for every instance in the run (skips the question) |
| `FORCE_WORKER_SWITCH` | `1` skips the trading-hours confirmation for a web server change |
| `STRATEGY_MEM_LIMIT_MB` | Strategy memory cap for the `unrestricted` profile (default 3072) |
| `OPENALGO_CONTAINER_MEM_MB` | Adds a container `mem_limit` (in MB) to every instance in the run |
| `PYPI_EDGE_IP` | `auto` or an address: pin the PyPI download host during the build |
