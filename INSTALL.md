# OpenAlgo Installation Guide

The maintained installation instructions live under [`docs/`](docs/INDEX.md):

- [Local installation and first start](docs/userguide/04-installation/README.md)
- [Administrator and broker setup](docs/userguide/05-first-time-setup/README.md)
- [Ubuntu server](docs/installation-guidelines/getting-started/ubuntu-server-installation.md)
- [Docker](docs/docker/README.md)
- [Optional gthread worker and rollback](docs/gthread/README.md)
- [Contributor environment](docs/devsprint/README.md)

## Local quick start

Install Git, Python 3.12 or newer, and `uv`, then run:

```bash
git clone --filter=blob:none https://github.com/marketcalls/openalgo.git
cd openalgo
uv run app.py
```

Open `http://127.0.0.1:5000`, create your administrator account, sign in and
configure your broker at **Select Broker → Configure**. A fresh checkout creates
`.env` with unique installation secrets on first start. Keep those secrets with
the database when upgrading or restoring an existing instance.

The `main` branch includes the CI-built React frontend. Node.js is needed only
for frontend development. Use the version required by `frontend/package.json`
and run frontend commands inside `frontend/`:

```bash
cd frontend
npm ci
npm run dev
```

Use the deployment guides for production. Both supported Gunicorn workers use
exactly one worker process; eventlet is the default and gthread is opt-in. The
development command above uses normal threading.
