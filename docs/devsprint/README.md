# OpenAlgo DevSprint: Contributor Prep Guide

A guide for developers joining the FOSS United / BangPypers devsprint and picking
up OpenAlgo as their first open-source project.

**Please work through sections 1 to 8 at least two days before the event.**
Setup is the single biggest reason people leave a devsprint without a merged pull
request. If your environment is already green when you walk in, you spend the day
writing code and getting reviewed instead of fighting `npm install`.

If anything below fails, do not silently give up. Ask in the event group or on the
OpenAlgo Discord (https://discord.com/invite/UPh7QPsNhP) before the event. Setup
questions asked on Thursday get answered. Setup questions asked at 10:30 on the
day cost you the morning.

---

## 1. What OpenAlgo is (3 minute read)

OpenAlgo is a self-hosted algorithmic trading platform for Indian markets. It puts
one common API in front of 36 different broker APIs, so a strategy written once
runs against any supported broker without change.

- Backend: Python 3.12+, Flask, SQLAlchemy, Flask-SocketIO
- Frontend: React 19, TypeScript, Vite, Tailwind, shadcn/ui
- Data plane: broker WebSocket feeds, a ZeroMQ bus, and a WebSocket proxy
- Storage: SQLite (six isolated databases) plus DuckDB for historical data

It is several products sharing one broker session:

| Surface | Route | What it does |
| --- | --- | --- |
| Unified Broker API | `/api/v1/` | REST API used by TradingView, Amibroker, Excel, Python, MCP clients |
| Python Strategy Host | `/python` | In-browser editor, strategies run as scheduled subprocesses |
| Flow (no-code builder) | `/flow` | Node graph: market data to indicators to conditions to orders |
| Options and Portfolio tools | `/tools` | 18 analytics tools (option chain, Greeks, max pain, backtesters) |
| Charting Terminal | `/trading` | Chart based trading |
| Scalping Terminal | `/scalping` | Keyboard driven options scalping |

Two properties shape almost every design decision, and they explain a lot of the
code you are about to read:

1. **Single user per deployment.** There is no multi-tenancy and no SaaS. One
   person, one broker session, running on their own machine or VPS.
2. **Production runs one Gunicorn worker under eventlet.** No `asyncio`, and
   anything that leaks a file descriptor accumulates until the process dies.

Links:

- Quick start for users: https://www.openalgo.in/getting-started
- Full docs: https://docs.openalgo.in
- Repository: https://github.com/marketcalls/openalgo
- Contributing guide: [CONTRIBUTING.md](../../CONTRIBUTING.md)
- Documentation map for contributors: [docs/INDEX.md](../INDEX.md)

---

## 2. The one page checklist

- [ ] GitHub account, and `git config user.name` / `user.email` set
- [ ] Forked `marketcalls/openalgo`, and **disabled Actions on your fork**
- [ ] Cloned your fork, `upstream` remote added
- [ ] Python 3.12 or newer
- [ ] `uv` installed
- [ ] `uv sync` completed
- [ ] `.env` created from `.sample.env`
- [ ] `uv run app.py` starts and `http://127.0.0.1:5000` loads
- [ ] Node.js installed and `frontend` builds (only if you plan to touch the UI)
- [ ] The verification commands in section 7 all pass
- [ ] Read section 9 (house rules). It is short and it decides whether your PR merges.
- [ ] Warm-up pull request opened (section 8)
- [ ] Optional but strongly recommended: a broker account with free API access,
      opened at least a week in advance (section 4)

---

## 3. Prerequisites

| Requirement | Version or size | Notes |
| --- | --- | --- |
| Git | any recent | https://git-scm.com/downloads |
| Python | 3.12 or newer | `uv` can install it for you, so this is optional |
| uv | latest | `pip install uv`, or the standalone installer from https://docs.astral.sh/uv/ |
| Node.js | 20.20+, 22.22+, or 24.13+ | **Only needed if you work on the React frontend.** See section 5. |
| Disk space | about 3 GB local, about 10 GB for the Docker route | `.git` is roughly 250 MB, `.venv` roughly 650 MB, `node_modules` roughly 700 MB |
| RAM | 4 GB minimum, 8 GB comfortable | |
| OS | Windows 10/11, macOS 11+, or Ubuntu 20.04+ | All three are supported and used by maintainers |
| Editor | VS Code recommended | Extensions: Python, Pylance, Biome, Tailwind CSS IntelliSense |

Helpful but not required: familiarity with Flask, React hooks, and how a REST API
works. You do **not** need to know anything about trading. Several of the curated
issues are pure Python or pure React with no market knowledge involved.

---

## 4. Do you need a broker account? Read this one carefully

Short answer: **not to contribute, but yes to see the logged-in UI.**

OpenAlgo only marks a browser session as logged in after a real broker
authentication succeeds. Practically that means: with no broker account you can
start the app, create your admin user at `/setup`, and see the login and broker
selection screens, but you cannot reach the dashboard, order book, positions, or
holdings pages.

That gives you two tracks. Pick one before the event.

### Track A: no broker account

Perfectly viable, and a good chunk of the curated issues live here. You can work on:

- Documentation anywhere under `docs/`
- Backend Python: type hints, docstrings, error handling, logging, refactors,
  constants, validation, security headers
- The Python test suite (`test/`), which runs without any credentials
- React components verified through Vitest component tests rather than by
  clicking through a live page
- Tooling, CI, linting, and developer experience

### Track B: with a broker account (recommended if you can)

This unlocks the whole UI and every issue. The important detail: you do **not**
have to risk any money. Log in with your broker, then switch OpenAlgo into
**Analyzer mode** (also called sandbox). Orders are then simulated locally against
`db/sandbox.db` with 1 crore of virtual capital, and your real broker account is
never touched for execution. Market prices still come from the broker feed, which
is exactly why the broker login is needed.

**API access is free with every supported broker except Zerodha, Groww and Dhan,
which charge for it.** Any of the other brokers works. Shoonya (Finvasia) and
Flattrade are common choices for developers because account opening and API access
are both free.

**Open the account at least a week before the event.** KYC is not same day. This
is the one prep item you cannot do the night before.

### Two warnings about using a broker at the venue

1. **Static IP whitelisting.** Since 1 April 2026, SEBI requires broker-side static
   IP whitelisting for transactional API orders. If your broker enforces IP
   restrictions, API calls from the venue wifi will be rejected because the venue
   IP is not the one you registered. Analyzer mode sidesteps this for order
   placement (nothing is sent to the broker), but broker login and market data may
   still be IP checked.
2. **Work around it by logging in before you leave home.** An OpenAlgo broker
   session stays valid until roughly 3:00 AM IST the next day. Complete your broker
   login on your home network on the morning of the event, do not log out, and
   carry the laptop over. The session travels with you.

Do not plan to place live orders at the event. There is no reason to, and Analyzer
mode does everything you need for development.

---

## 5. Setup option A: local (recommended)

### 5.1 Fork and clone

Fork https://github.com/marketcalls/openalgo on GitHub, then:

```bash
git clone https://github.com/YOUR_USERNAME/openalgo.git
cd openalgo
git remote add upstream https://github.com/marketcalls/openalgo.git
git remote -v
```

**Now disable Actions on your fork.** Go to
`https://github.com/YOUR_USERNAME/openalgo/settings/actions` and select
"Disable actions". The upstream CI builds Docker images and commits frontend
bundles. You do not want those running on your fork.

### 5.2 Backend

```bash
pip install uv          # skip if uv is already installed
uv sync                 # creates .venv and installs everything
```

`uv sync` reads `pyproject.toml` and `uv.lock`. It downloads a fair amount
(pandas, numpy, DuckDB, plotly and friends), so run it on a decent connection,
not on venue wifi.

**Always use `uv run` to run Python.** Never activate a virtualenv by hand, never
call global `python`. Every command in this repository is `uv run <thing>`.

### 5.3 Configuration

```bash
cp .sample.env .env     # Windows PowerShell: copy .sample.env .env
```

That is genuinely all. The shipped `.env` contains placeholder secrets, and on
first startup OpenAlgo detects them, generates real random values with
`secrets.token_hex(32)`, and writes them back. You will see a one-time
`[OpenAlgo first-run setup]` message in the console. You only need to edit `.env`
by hand if you are configuring a broker (Track B), in which case set
`BROKER_API_KEY`, `BROKER_API_SECRET` and `REDIRECT_URL` for your broker.

Never commit your `.env`. It is gitignored, and after first run it holds real
secrets.

### 5.4 Frontend (skip this if you are backend or docs only)

The built frontend at `frontend/dist/` is committed on `main` by CI. A fresh
clone of `main` already contains a working UI, so **backend and documentation
contributors do not need Node.js at all**. Just run the app.

If you are working on React:

```bash
cd frontend
npm ci
npm run build
cd ..
```

For an actual frontend workflow, run two terminals:

```bash
# Terminal 1: Vite dev server with hot reload, on port 5173
cd frontend && npm run dev

# Terminal 2: Flask backend on port 5000
uv run app.py
```

Vite proxies `/api`, `/auth` and `/socket.io` through to Flask on port 5000, so
open `http://localhost:5173` and edit React with hot reload.

### 5.5 Run it

```bash
uv run app.py
```

Open `http://127.0.0.1:5000`, go to `/setup`, and create your admin user.

### 5.6 Optional: pre-commit hooks

```bash
uvx pre-commit install
```

This runs Ruff, Biome, secret detection, and whitespace checks before each commit.
Recommended, not required.

---

## 6. Setup option B: Docker

Use this if the local route fights you, or if you would rather not install Python
and Node on your machine. It needs Docker Engine and Docker Compose, and roughly
10 GB of free disk.

```bash
git clone https://github.com/YOUR_USERNAME/openalgo.git
cd openalgo
cp .sample.env .env
```

For Docker, edit `.env` so services bind inside the container correctly:

```
FLASK_HOST_IP='0.0.0.0'
FLASK_PORT='5000'
WEBSOCKET_HOST='0.0.0.0'
WEBSOCKET_PORT='8765'
WEBSOCKET_URL='ws://localhost:8765'
ZMQ_HOST='0.0.0.0'
ZMQ_PORT='5555'
```

`127.0.0.1` only accepts connections from inside the container. `0.0.0.0` lets the
port mapping reach your host.

```bash
docker compose up --build     # first build takes a while, do it the night before
docker compose logs -f
```

| Action | Command |
| --- | --- |
| Start | `docker compose up -d` |
| Logs | `docker compose logs -f` |
| Stop | `docker compose down` |
| Rebuild after changes | `docker compose up --build` |
| Shell into the container | `docker compose exec openalgo bash` |
| Status | `docker compose ps` |

Caveat: the Docker image is built for production (Gunicorn plus eventlet). It is
excellent for "does my change work end to end" and poor for fast iteration. Most
contributors will be happier on option A. Ports exposed: 5000 (web), 8765
(WebSocket), 5555 (ZeroMQ).

Full details: https://docs.openalgo.in/installation-guidelines/getting-started/docker-development

---

## 7. Verify your setup

Run these. All of them should pass on a clean checkout of `main`, with no broker
and no credentials.

**Backend tests** (this is the same subset CI runs, and it needs nothing configured):

```bash
uv run pytest test/test_log_location.py test/test_rate_limits_simple.py \
  test/test_event_bus_bounded.py -q
```

Expect `10 passed` in a few seconds.

The wider CI-safe set, if you want to be thorough:

```bash
uv run pytest test/test_log_location.py test/test_navigation_update.py \
  test/test_python_editor.py test/test_rate_limits_simple.py \
  test/test_logout_csrf.py test/test_auth_logout.py \
  test/test_auth_resume.py test/test_auth_upsert_multisession.py \
  test/sandbox/test_execution_backlog.py test/test_event_bus_bounded.py -v
```

Do not run the whole `test/` directory and panic. Many tests in there talk to live
broker feeds and are expected to fail without credentials.

**Linting.** Important nuance: `uv run ruff check .` across the whole repository
currently reports a large number of pre-existing findings in older broker modules,
and CI marks that job `continue-on-error` for exactly that reason. So do **not**
try to make the whole repository clean. Lint only what you touched:

```bash
uv run ruff check path/to/file_you_changed.py
uv run ruff format path/to/file_you_changed.py
```

**Frontend** (only if you set up Node):

```bash
cd frontend
npm run lint         # Biome
npm run test:run     # Vitest
npm run build        # must be clean, TypeScript errors fail CI
```

**The app itself:**

```bash
uv run app.py
```

`http://127.0.0.1:5000` should load and `/setup` should let you create an admin
user.

---

## 8. Warm-up pull request, before you arrive

Open one trivial pull request before the event so that the mechanics (fork, branch,
commit message format, push, PR description, review, rebase) are already muscle
memory. On the day you then spend your review cycles on the actual code.

Add your name to [`participants.md`](participants.md) in this folder:

```bash
git checkout main
git pull upstream main
git checkout -b docs/add-<yourname>-devsprint
# add one row to docs/devsprint/participants.md
git add docs/devsprint/participants.md
git commit -m "docs: add <Your Name> to devsprint participants"
git push origin docs/add-<yourname>-devsprint
```

Then open the pull request against `marketcalls/openalgo:main`.

If someone else's PR merges first and yours conflicts, good. Resolving that
conflict is part of the exercise:

```bash
git fetch upstream
git rebase upstream/main
# fix the conflict, then
git add docs/devsprint/participants.md
git rebase --continue
git push --force-with-lease
```

---

## 9. House rules that decide whether your PR gets merged

These are not style preferences. They are the things maintainers actually send PRs
back for.

**One feature or one fix per pull request.** OpenAlgo supports 36 broker plugins, and
every change has to be validated across that surface. Large combined PRs are not
reviewable and will be asked to be split. The one exception is a brand new broker
integration, which is self-contained inside its own `broker/` directory.

**Conventional Commits.** `feat:`, `fix:`, `docs:`, `refactor:`, `test:`, `chore:`,
`style:`. For example `fix: correct margin calculation for options`.

**No emoji and no icons in any text.** Not in code, comments, log messages, commit
messages, PR descriptions, docs, or terminal output. Plain text labels only. (To be
clear: `lucide-react` SVG icons inside React components are normal UI and are fine.
The rule is about emoji characters in text.)

**Python conventions:**

- `uv run` for everything. Never global Python, never a hand-managed venv.
- `logger = get_logger(__name__)` from `utils/logging.py` in every module.
- Error logging is always `logger.exception()`. Never `import traceback`, never
  `traceback.print_exc()`, never `print()`. Those bypass centralized logging.
- Database access through the SQLAlchemy ORM, not raw SQL.
- 4 spaces, Google-style docstrings, 100 character lines.

**Frontend conventions:** Biome for lint and format, functional components with
hooks, PascalCase component filenames, TanStack Query for server state, Zustand for
client state.

**Do not commit `frontend/dist/`.** It is gitignored for contributors and CI builds
it on merge.

**Schema changes need a migration script** in `upgrade/`, registered in
`upgrade/migrate_all.py`. A change applied only in `init_db()` never reaches
existing installations. Migrations must be idempotent and must not clobber values a
user has customised.

**Resource hygiene.** Every DB session, file, socket, WebSocket, ZeroMQ socket,
subprocess pipe, thread and executor is a file descriptor, and production is a
single worker that never restarts. If your change touches any of those, say so in
the PR description so it gets the right review.

**On AI assistance:** using an AI coding assistant is fine and common here (the
repository even ships a `CLAUDE.md` with project context). What is not fine is
opening a PR you have not read, run, and tested yourself. Be ready to explain every
line in review. Unreviewed generated code is the fastest way to get a PR closed.

**PR description should include:** what it does, the issue it closes
(`Closes #123`), how you tested it, and before/after screenshots for UI changes.

---

## 10. Picking an issue

Filtered list of beginner issues:
https://github.com/marketcalls/openalgo/labels/good%20first%20issue

Currently open and suitable for a first contribution:

| Issue | Area | Track | What it involves |
| --- | --- | --- | --- |
| [#893](https://github.com/marketcalls/openalgo/issues/893) | Python | A | Add type hints to validation functions in `restx_api/data_schemas.py` |
| [#895](https://github.com/marketcalls/openalgo/issues/895) | Python | A | Replace a magic number in the broker init param count check with a named constant |
| [#897](https://github.com/marketcalls/openalgo/issues/897) | Python | A | Add Google-style docstrings to `telegram_bot.py` helpers |
| [#889](https://github.com/marketcalls/openalgo/issues/889) | React | A or B | Consistent empty-state UI pattern across pages |
| [#1008](https://github.com/marketcalls/openalgo/issues/1008) | React | B preferred | Loading skeletons for stats cards on Holdings and Positions |
| [#1010](https://github.com/marketcalls/openalgo/issues/1010) | React, security | A | `maxLength` on login and reset password inputs |
| [#1011](https://github.com/marketcalls/openalgo/issues/1011) | React, a11y | B preferred | Tooltips on icon-only buttons in OrderBook and Positions |

"Track" refers to section 4. Track A issues need no broker account at all.

A fresh batch of issues will be labelled specifically for this devsprint closer to
the date, sized so that a first-time contributor can realistically finish one in a
day. Watch the label list on the repository.

**Etiquette:** comment on the issue to claim it before you start, so two people do
not build the same thing. If you pick it up and then stall, say so in the thread and
let it go back to the pool. Nobody minds.

---

## 11. Reading list, about 30 minutes, skimming is fine

1. [CONTRIBUTING.md](../../CONTRIBUTING.md), especially "Development Workflow" and
   "Contributing Guidelines"
2. [CLAUDE.md](../../CLAUDE.md) at the repository root. It is written for AI agents
   but it is the most concentrated description of the architecture, invariants and
   runtime constraints anywhere in the repo. Humans should read it too.
3. [docs/INDEX.md](../INDEX.md), the map to everything else. Do not read the whole
   `docs/` tree, open only what you need.
4. [docs/userguide/README.md](../userguide/README.md) if you want product context on
   what users actually do with this.
5. [docs/broker-integration-guide.md](../broker-integration-guide.md) only if you
   are interested in adding a broker. That is an advanced track, not a first PR.

---

## 12. If setup breaks

**Read `log/errors.jsonl` first.** One JSON object per line with timestamp, module,
`file:line`, message, full traceback, and request context. It answers most questions
faster than reading the console.

| Symptom | Fix |
| --- | --- |
| Port 5000 already in use on macOS | AirPlay Receiver uses port 5000. Turn it off in System Settings, or set `FLASK_PORT` in `.env` to something else. |
| Port 5000 or 8765 in use elsewhere | `lsof -i :5000` on macOS and Linux, `netstat -ano` filtered on `:5000` on Windows. Kill it, or change the port in `.env`. |
| `.env file not found` on startup | You skipped `cp .sample.env .env`. |
| Warning that your `.env` version is outdated | Add the missing variables from `.sample.env` to your `.env`. Do not copy `.sample.env` over an existing `.env`, you will destroy your generated secrets. |
| `uv: command not found` | `pip install uv`, then reopen your terminal so PATH refreshes. |
| Python version errors | `uv python install 3.12` and let uv manage it. |
| `npm ci` fails | Check your Node version against section 3. Delete `frontend/node_modules` and retry. |
| Whole test suite fails | Expected. Run only the CI-safe subset in section 7. |
| Ruff reports hundreds of errors | Expected on the repository as a whole. Lint only the files you changed. |
| Docker: database permission errors | `chmod -R 777 db/` |
| Docker: stale build | `docker compose build --no-cache` |
| SQLite locking errors on Windows | Stop any other running instance of the app. Windows is stricter about this than Linux. |

Still stuck: post in the event group, or ask on the OpenAlgo Discord
(https://discord.com/invite/UPh7QPsNhP). Include your OS, Python version, Node
version, the exact command, and the exact error text.

---

## 13. At the venue

Bring:

- Your laptop with setup already done and verified, plus its charger
- A phone hotspot as backup. Conference wifi is conference wifi, and `uv sync` or
  `npm ci` over a shared connection with 60 other people is a bad afternoon.
- If you are on Track B: your broker credentials, and a broker session you logged
  into at home that morning (see section 4)

Rough shape of the day:

1. Short walkthrough of the architecture and where things live
2. Pick an issue, claim it in the thread, ask the maintainer if it is a good fit
3. Build it, test it, open the PR
4. Review, iterate, merge

The goal is one merged pull request each. Small and merged beats ambitious and
abandoned. If you finish early, pick up a second one.

---

Questions before the event: the OpenAlgo Discord is the fastest channel, and the
maintainers are on it.
