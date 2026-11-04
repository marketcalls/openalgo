# Product Plan: Phase 1 Rebranding and Design Language

Date: 2026-10-17 (revision 3, after owner and partner review)
Status: Phase 1 scope agreed and every Phase 1 question decided. M1.1 and M1.2 proposals are in `docs/design/brand/design-language.md`, awaiting the owner's choice of name and token sign-off.
Repository: https://github.com/ranjeetthorat/ai-algo

---

## 1. Agreed facts

- **Hard fork.** ai-algo is cut off from OpenAlgo from now on. We do not merge from upstream. We watch upstream manually and write any fixes we want ourselves.
- **The product.** Our own name, logo and design language. OpenAlgo branding is removed. We do not use the OpenAlgo trademark. One attribution line ("based on OpenAlgo") stays, as AGPL requires.
- **The business.** We make money from services: installation, configuration, custom strategies and support. Copying of the code or the packaged software is not a concern.
- **Licence.** AGPL-3.0 is honoured: source published, copyright notices kept.
- **Brokers.** Every broker present today stays supported. No changes.
- **Deployment.** Desktop and VPS, on Windows, macOS and Linux. Network and broker requirements (static IP and similar) are the client's responsibility. No code-signing certificates.
- **Branding is UI cosmetic.** We do not rename any package, Python import, SDK, route, API path, database, env variable or module in Phase 1.
- **Proposals accepted from revision 2:**
  - Emails, Telegram and WhatsApp messages count as UI and are rebranded.
  - In-app guides (FAQ, Python strategy guide) are rewritten under our brand.
  - Attribution goes on an About page, plus a small line in the footer.
  - The GitHub README is rebranded.
- **GitHub Actions is out of scope until Phase 2.** No CI is triggered or changed in Phase 1. All checks run locally.

## 2. Phases

| Phase | Scope | Status |
| --- | --- | --- |
| 1 | Rebranding: decide the design language and implement it | Done 2026-10-23 (v1.0.0) |
| 2 | Cleanup: remove unnecessary code, modules and integrations | In progress (M2.1 done 2026-10-23) |
| 3 | Cross-OS compatibility, distribution and release | Not started |
| 4 | Multi-broker | Not started |

Each phase is split into milestones. Each milestone has a deliverable and exit criteria, so progress can be tracked and a milestone is either done or not done.

---

## 3. Phase 1 milestones

| ID | Milestone | Owner | Deliverable | Exit criteria | Depends on | Status |
| --- | --- | --- | --- | --- | --- | --- |
| M1.1 | Brand identity | Dev (delegated by owner) | Name (FastAlgo), short name, tagline, logo set (mark, glyph, light and dark wordmarks, favicon, touch icon, 192 and 512 px PNGs), primary palette, fonts, tone of voice | Assets in the repo under `frontend/src/brand/assets/`. Name cleared for use | None | Done 2026-10-17. Owner still to run the trademark registry and Play Store check for "FastAlgo" |
| M1.2 | Design language spec | Dev (delegated by owner) | `docs/design/brand/design-language.md`: colour tokens (light, dark, analyzer mode), profit and loss colours, type scale, spacing, radius, elevation, component rules, chart colours, empty and error states, copy style | Spec reviewed and signed off | M1.1 | Done 2026-10-17 (D1 to D6 approved) |
| M1.3 | Brand foundation in code | Dev | `frontend/src/brand/brand.ts` (name, URLs, support contact, attribution, with a per-instance override for the client's logo and display name, Q6), theme tokens wired into Tailwind and the CSS variables, new assets in `frontend/public/`, `index.html` title and meta, `NOTICE` file | The app builds and runs with the new name, logo and colours on the login page. Nothing else is changed yet | M1.1, M1.2 | Done 2026-10-17. Also pulled forward from M1.4: browser page titles (`usePageTitle`) and the login page's GitHub and Discord links, replaced with one "Get support" link |
| M1.4 | Global chrome and links | Dev | Navbar, footer, page titles, login, setup, broker select, TOTP, 404 and error pages. Every external link to OpenAlgo's site, docs, GitHub, Discord, X or YouTube replaced or removed | No OpenAlgo name or link visible in global chrome, in light or dark mode | M1.3 | Done 2026-10-17 |
| M1.5 | Content pages | Dev | Our own Home, FAQ, Download, Platforms, Python strategy guide, TradingView, GoCharting and Telegram setup text. New About page with attribution and source link | No upstream name or link left in these pages. About page live | M1.3 | Done 2026-10-17 |
| M1.6 | Design language applied | Dev | Tokens and component rules applied across all pages, including charts (`lib/trading/chartTheme.ts`), the Flow editor, scalping, the option tools and analyzer mode | Visual review of every page in the navigation, in both themes, signed off | M1.2, M1.3 | Done 2026-10-17 (code). Visual review limited to pages reachable without a broker login, see M1.9 notes |
| M1.7 | Backend user-facing text | Dev | Email templates (`utils/email_utils.py`), Telegram and WhatsApp bot messages, MCP metadata (`blueprints/mcp_oauth.py` documentation URLs), user-facing error text | A test email, Telegram alert and WhatsApp alert all show our brand | M1.1 | Done 2026-10-17 |
| M1.8 | Repository face | Dev | Rebranded README, `NOTICE`, `SECURITY.md` and `CONTRIBUTING.md` contacts. Update `CLAUDE.md` so its repo, docs and upstream references match a hard fork | Someone landing on the GitHub repo sees only our product, with attribution | M1.1 | Done 2026-10-17. SECURITY.md points to the support site until a security email exists |
| M1.9 | Brand check and release | Dev | `scripts/brand-check.mjs` (lists visible "OpenAlgo" text and upstream links in `frontend/src` and user-facing backend text, ignoring identifiers), run locally. Frontend tests updated where they assert on changed text. A locally built `frontend/dist` committed to `main`. Release tag | Brand check, `uv run pytest test/ -v`, `npm test` and `npm run build` all pass locally. Tag pushed | M1.4 to M1.8 | Done 2026-10-23. Released as `v1.0.0` on `main` with a locally built dist |

Found during M1.1, for later milestones:

- **Image files with OpenAlgo artwork:** `frontend/public/images/android-chrome-192x192.png` (Flow editor and Playground headers), `images/openalgo-glyph.svg` (the AI agent's chart watermark, `CandleViz.tsx`) and `images/openalgo-mark.svg`. M1.3 replaces their contents with FastAlgo artwork and keeps the filenames, so no code reference changes.
- **Watermark label:** `CandleViz.tsx` labels the watermark "OpenAlgo Charts". This is visible text, for M1.4.
- **Library default watermark:** the `openalgo-charts` library draws a default branding watermark of its own. M1.6 must check every chart surface (`/trading`, Historify, strategy charts) for it and configure it to the FastAlgo glyph.
- **Alt text:** eight `<img>` tags use `alt="OpenAlgo"`. This is text, for M1.4. The login page's two were fixed in M1.3.

Found during M1.3:

- **Teal highlight word (M1.6):** headings that highlight a word with `text-primary`, for example "Welcome to FastAlgo", now show it in Ink. Ink is barely different from the heading colour, so the highlight no longer stands out. Consider pulse-600 for highlighted words.
- **Pre-existing test timeouts:** `StrategyBuilder.test.tsx` and `StrategyBuilder.accessibility.test.tsx` time out on this machine, 3 to 15 tests per run at the 5-second limit. They fail the same way with the M1.3 changes set aside, so they are not caused by the rebrand. Run them alone, or raise their timeout, before treating a failure there as real.
- **Override can't be checked in the dev server alone:** `/brand-config.js` comes from Flask. With only `npm run dev`, the proxy has no backend and the app shows the default FastAlgo brand, which is the intended fallback.

Found during M1.4 to M1.9:

- **Chart library watermark:** `openalgo-charts` draws OpenAlgo's mark unless a chart passes `branding`. Every `openalgo-charts` chart now passes `CHART_BRANDING` (`brand.ts`). Pages built on `lightweight-charts` have no such mark; their text watermarks use `BRAND.displayName`.
- **Accent picker removed (Q2):** gone from Profile. The theme store always applies the default palette, so an accent saved before the rebrand cannot override it.
- **Version (Q5):** `utils/version.py` is 1.0.0, and `/auth/app-info` returns the display name.
- **Brand check:** `scripts/brand-check.mjs` scans the frontend, the user-facing backend files and the GoCharting guide, skipping comments, docstrings and log lines. It reports 0.
- **Known not covered:** logged-in pages could not be checked in a browser without broker credentials. They are covered by the brand check, the type check and the unit tests, but a short click-through after the first login is recommended.
- **Left for Phase 2:** `services/telegram_bot_service_fixed.py` and `services/telegram_bot_service_v2.py` (dead duplicates, still say OpenAlgo), WhatsApp's raw `SDK error: {e}` reply, Telegram first names not escaped for Markdown, and upstream developer docs (`INSTALL.md`, `DOCKER_README.md`, `DISCOVERY_MAP.md`, `docs/`).
- **Pre-existing test failures (not caused by the rebrand):** live-broker mstock tests, the installer tests (need bash), a Windows file lock in the Python editor test, missing fixtures in the rate-limit tests, a LiteLLM model-registry check, and one Strategy Module database test that hangs on a SQLite lock. Strategy Builder frontend tests time out on this machine.
- **Incident:** during M1.4 to M1.7, `.env` was overwritten with `.sample.env` by a process in the session, most likely a helper agent. The original values were recovered from a running app process and restored, after verifying they decrypt the database. Backups: `.env.restored-2026-10-17` (good) and `.env.sample-overwritten` (the overwritten one), both gitignored.

M1.4, M1.5, M1.7 and M1.8 can run in parallel once M1.3 is done. M1.6 is the largest milestone, and it can start page by page as soon as the M1.2 spec is signed off.

### 3.1 How to track

I recommend **GitHub Milestones** on ranjeetthorat/ai-algo:

- One milestone per row above (M1.1 to M1.9).
- One issue per deliverable inside it, with labels `phase-1` and the area (`frontend`, `backend`, `design`, `docs`).
- A GitHub Project board (To do, In progress, Review, Done) gives the partners a single view.
- This table stays the plan, and GitHub stays the progress record. Update the Status column here when a milestone closes.

### 3.2 Phase 2 milestones

Milestones are added as the owner scopes them.

| ID | Milestone | Deliverable | Exit criteria | Status |
| --- | --- | --- | --- | --- |
| M2.1 | Docker removal and public site | Docker tooling deleted: `Dockerfile`, `docker-compose.yaml`, `.dockerignore`, `docker-build.sh`/`.bat`, `start.sh`, `DOCKER_README.md`, the six Docker scripts and readmes in `install/`, `docs/docker/`, `docs/design/11-docker/`, and the `docker-build` and `docker-manifest` CI jobs. References repointed in tests, the security-audit and broker-integration skills, `CLAUDE.md`, `.sample.env` and the broker guide. New `static/` folder: the home page as one self-contained HTML file, without log-in or installation links, for S3 or GitHub Pages | No file in the repo depends on a deleted file. `uv run pytest test/` and the brand check pass. The static page renders in light, dark and at 375 px with no horizontal scroll | Done 2026-10-23 |

Found during M2.1, for later milestones:

- **Code that still handles Docker:** `app.py` (standalone mode, `/.dockerenv` detection), `blueprints/admin.py` (version without `.git`, `.env` bind mounts), `utils/env_check.py`, `utils/oauth_keys.py`, `utils/ip_helper.py` and `blueprints/mcp_http.py`. Their comments still describe the Docker case. Removing that code changes behaviour, so it needs its own milestone with tests.
- **Upstream docs that still describe Docker:** `docs/userguide/04-installation/`, `docs/userguide/remote-mcp.md`, `install/Remote-MCP-readme.md`, `docs/telegram-chart-rendering.md`, `docs/prd/ci-cd*.md` and the FastAPI migration plan. They go with the wider upstream-docs cleanup. Release notes under `docs/releases/` are history and stay.
- **Tests already failing before M2.1:** 13 failures, 6 errors and one occasional hang, none in files M2.1 touched. Causes, a skip command and suggested fixes are in [`docs/test/KNOWN_FAILING_TESTS.md`](../test/KNOWN_FAILING_TESTS.md). Fixing or moving them is a candidate milestone.
- **Bare-metal tooling kept on purpose:** `install/install.sh`, `install-multi.sh`, `update.sh`/`.bat`, `change-domain.sh`, `requirements-nginx.txt` and `Caddyfile` (local HTTPS dev). Removing `install/` still waits on the client-install runbook (section 6).

---

## 4. Phase 1 approach notes

### 4.1 Scope rule: what changes and what does not

| Changes | Does not change in Phase 1 |
| --- | --- |
| Product name and visible text | Package names (`openalgoUI`, `openalgo` SDK, `openalgo-charts`) |
| Logo, favicon, images | Imports, module and file names |
| Colours, fonts, spacing, component look | Routes, `/api/v1/` paths, webhook formats |
| External links (docs, community, GitHub) | Database, table and env variable names, localStorage keys such as `openalgo-theme` |
| Email and bot message text | Backend logic, brokers, `services/risk/`, the order path |

### 4.2 Findings from the code that affect Phase 1

- **58 links to OpenAlgo properties sit in 24 frontend files.** Examples: `Footer.tsx` (6: website, GitHub, Discord, X, YouTube), `Home.tsx` (10), `Faq.tsx` (9), `Download.tsx` (7). Each one needs a replacement destination or removal (Q3, Q4).
- **The theme already supports light and dark modes, several selectable accent colours (`ThemeColor` in `stores/themeStore.ts`), and a separate purple theme for analyzer mode.** The design language has to decide what happens to all three (Q2).
- **The chart theme reads the app's CSS tokens** (`lib/trading/chartTheme.ts`), so charts follow the new palette once the tokens change. Only chart-specific colours, such as candles and profit and loss, need explicit decisions.
- **The version string `2.0.2.5` in `utils/version.py` is OpenAlgo's version.** If it is shown in the UI, it should become ours (Q5).

### 4.3 Urgent note outside Phase 1

**The install and Docker scripts still install OpenAlgo itself, not ai-algo.**

- `install/install.sh`, `install-multi.sh`, `install-docker.sh` and `install-docker-multi-custom-ssl.sh` clone `https://github.com/marketcalls/openalgo.git`.
- `install/docker-run.sh` and `docker-run.bat` pull the image `marketcalls/openalgo:latest`.

Anyone installing a client with these scripts would get upstream code, with none of our changes. Decided under Q9 (section 5.3): we never use them, we install every client ourselves, and Phase 2 removes them.

### 4.4 Licence hygiene for a hard fork

- Keep `License.md` and every existing copyright notice in source files.
- `NOTICE` at the repo root: "ai-algo is a modified version of OpenAlgo (https://github.com/marketcalls/openalgo), licensed under AGPL-3.0." List the main modifications, and update it at each phase.
- The About page links to our public source repository, which covers AGPL section 13 for network users.
- Keep the git history. It is the clearest record of what came from upstream and what is ours.

### 4.5 Watching upstream manually

Since we no longer merge, I suggest a light routine so that important fixes are not missed:

- Watch upstream releases on GitHub (Watch, then Custom, then Releases).
- Once a month, skim upstream commits in `broker/`, `services/risk/`, `database/` and anything labelled security.
- Record each item reviewed in `docs/upstream-watch.md`: date, upstream commit, decision (ported, not relevant, later) and our commit if ported. Ports are written by hand, as agreed.
- Broker API changes are the most likely to matter, since we keep every broker.

---

## 5. Phase 1 decisions and open questions

### 5.1 Decided (locked on 2026-10-17)

| # | Question | Decision | Lands in |
| --- | --- | --- | --- |
| Q1 | Re-skin or redesign? | Re-skin only. Layouts and navigation structure stay. Layout changes, if any, belong to Phase 2 | M1.6 |
| Q2 | Themes | One brand palette in light and dark. Analyzer mode keeps its own visibly different look. The selectable accent colours are removed from the UI | M1.2, M1.6 |
| Q3 | Documentation links | Removed in Phase 1. "Help" points at our support contact. A docs site comes later | M1.4, M1.5 |
| Q4 | Support and community channels | Our website plus one support channel | M1.4, M1.5 |
| Q5 | Version numbering | Our own, starting at 1.0.0. `NOTICE` records "forked from OpenAlgo 2.0.2.5" | M1.8, M1.9 |
| Q6 | Per-client white-label | Yes. `brand.ts` holds our defaults, and an optional per-instance override sets at least the logo and display name | M1.3 |
| Q8 | Download page | Replaced with a "Get help installing" page until Phase 3 ships installers | M1.5 |
| Q10 | Identifier renames after Phase 1 | The `openalgo` SDK and `/api/v1/` stay compatible permanently. Internal names may be revisited in Phase 2 | Phase 2 |
| Q11 | Design sign-off | One named approver per milestone, recorded in its GitHub issue | All |
| Q12 | GitHub tracking | Create GitHub Milestones M1.1 to M1.9 and their issues on ranjeetthorat/ai-algo | Tracking |
| Q7a | Email text | "Sent by <Client name>, managed by <OurBrand>", using the per-instance display name from Q6 | M1.7 |
| Q7b | Which mail account sends | The client's own mailbox, entered by us at installation. If the client has none, email stays off and we reset passwords during support | Installation runbook |
| Q9 | Install, update and Docker scripts | Never used. We install and update every client ourselves, which is part of the service. All existing install and Docker tooling is ignored in Phase 1 and removed in Phase 2. Our own Docker setup, if any, is a future project built from scratch | Phase 2 |

All Phase 1 questions are now decided. The background for Q7 and Q9 follows.

### 5.2 Background: Q7, emails

**What the code does today.** Each installation sends exactly two emails, both from `utils/email_utils.py`:

| Email | When it is sent | Branded text it contains today |
| --- | --- | --- |
| SMTP test | When someone clicks "send test email" on the SMTP settings page | Subject "OpenAlgo - SMTP Test Successful", sender name "OpenAlgo Admin", footer "Sent by OpenAlgo" |
| Password reset | When the user clicks "forgot password" on the login page | Subject "Reset your OpenAlgo password", body text and footer "Sent by OpenAlgo" |

Nothing is sent centrally. There is no OpenAlgo mail server. Each installation sends through whatever SMTP server is entered on its own settings page (server, port, username, encrypted password, from-address and HELO hostname, stored in `database/settings_db.py`). The from-address is not in the code at all. Whoever configures the instance types it in.

**So Q7 is really two separate questions.**

**Q7a. What text do the emails show?** This is the subject, sender display name and footer. It is the only part that is code, and it belongs to M1.7. With Q6 (white-label) decided, the options are:

| Option | Example | Effect |
| --- | --- | --- |
| A. Our brand only | "Sent by <OurBrand>" | Simple. Every client sees our name |
| B. The client's display name only | "Sent by <Client name>" | Pure white-label. Our name never appears |
| C. Both | "Sent by <Client name>, managed by <OurBrand>" | White-label, and reminds the client who supports them |

**Q7b. Whose mail account sends them?** This is configuration, not code. It is decided at each installation, so it is really a service-delivery policy:

| Option | How it works | Trade-off |
| --- | --- | --- |
| A. The client's own mailbox | At install we enter the client's Gmail or Outlook app password, or their company SMTP | No cost to us, and nothing of ours sits on their machine. Each client needs a mailbox, and setup takes us a few minutes |
| B. Our company's mail service | Every client instance uses our SMTP account (for example a transactional mail provider) with a no-reply address on our domain | Consistent and reliable delivery. But our SMTP password is stored on every client's machine, and anyone with server access can read it and send mail as us. One leak forces a password change on every client |
| C. Leave it unconfigured | Emails are simply off. A forgotten password is reset by us during a support call | Zero setup. The user cannot reset a password without contacting us |

**Decided.** Q7a option C, and Q7b option A with C as the fallback, as recommended. Option B was rejected because it would put one shared credential on every client machine.

### 5.3 Background: Q9, the install scripts (decided: not used, removed in Phase 2)

The owner's decision replaces options A to C below. Clients never run install or update scripts, so the scripts' upstream URLs do no harm as long as nobody runs them. What follows is kept as the record of what these files do, for the Phase 2 removal.

**What the scripts do today.** The repo has several scripts in `install/`. Each one fetches code or a ready-made image from OpenAlgo's GitHub and Docker Hub, not from ours:

| Script | What it does | Where it fetches from today |
| --- | --- | --- |
| `install.sh` | Full Ubuntu server setup: clones the code, installs Python dependencies, nginx, SSL and a systemd service | `git clone https://github.com/marketcalls/openalgo.git` |
| `install-multi.sh` | Same, for several instances on one server | `REPO_URL="https://github.com/marketcalls/openalgo.git"` |
| `install-docker.sh` | Server setup that builds and runs the app in Docker | Clones `marketcalls/openalgo` |
| `install-docker-multi-custom-ssl.sh` | Docker, several instances, custom SSL | `DEFAULT_REPO` is `marketcalls/openalgo` |
| `docker-run.sh`, `docker-run.bat` | Quick start on any machine with Docker: downloads a prebuilt image and starts it | Image `marketcalls/openalgo:latest` from Docker Hub, `.sample.env` from marketcalls' GitHub |
| `update.sh`, `update.bat` | Updates an existing install with `git pull origin` | Wherever the install was cloned from. Already correct for machines cloned from our repo |

**Why it matters now.** If one of us installs a client tomorrow with `install.sh`, the client gets OpenAlgo's current code. They get none of our branding, none of our fixes, and OpenAlgo's future changes whenever `update.sh` runs, because that machine's `origin` is OpenAlgo. The Docker quick-start is worse: it runs OpenAlgo's published image, which we do not control at all. After the hard fork, these scripts install the wrong product.

**The options.**

| Option | What changes | Effort | Trade-off |
| --- | --- | --- | --- |
| A. Fix now | Point the four clone URLs and the `.sample.env` URL at `ranjeetthorat/ai-algo`. `docker-run` cannot simply be repointed, because no ai-algo image exists on Docker Hub. It either builds the image locally (`docker-build.sh` already exists) or gets a "not available yet" message | About 10 lines plus a short test install on a VM | Correct today. Phase 3 replaces these scripts anyway |
| B. Disable now, replace in Phase 3 | Each script prints "Not for use: see the support team" and exits | Very small | No accidental wrong installs. Until Phase 3 we install clients by hand: `git clone` our repo, then `uv sync` |
| C. Leave until Phase 3 | Nothing | None | Any use of these scripts installs OpenAlgo. Relies on everyone remembering not to use them |

**Two facts decide this:**

1. **How do we install clients today?** If someone already uses these scripts, A or B is urgent. If installs are done by hand, the urgency is lower.
2. **Is ranjeetthorat/ai-algo public or private?** The scripts clone without logging in, so a private repo makes option A fail at the clone step. A private repo also matters for AGPL: clients must be able to get the source, so the repo, or a published source archive, needs to be reachable by them.

**What I recommend.** Option A for the four git-based scripts. Mark `docker-run` "not available yet" until Phase 3 publishes our own image. If the repo is private, choose B until it is public.

---

## 6. Recorded for later phases

**Phase 2: cleanup**
- Dead duplicate files: `services/telegram_bot_service_fixed.py` and `services/telegram_bot_service_v2.py`. Neither is imported anywhere.
- GitHub Actions: decide what CI we want (tests, lint, the brand check, the dist build), and remove the rest. Until then, Actions is disabled in the repo settings.
- Install and Docker tooling (Q9): `install/` (except anything we turn into our own runbook first), `Dockerfile`, `docker-compose.yaml`, `docker-build.sh`/`.bat`, `start.sh`, `Caddyfile`, `DOCKER_README.md`, `requirements-nginx.txt`, and the `docker-build` and `docker-manifest` jobs in `.github/workflows/ci.yml`. Keep `upgrade/`: the database migrations live there, and our own update procedure must run them.
- Before deleting `install/install.sh`, copy its production setup knowledge into an internal runbook (`docs/runbooks/client-install.md`): gunicorn with an eventlet single worker, nginx, systemd, SSL, how `APP_KEY` and `API_KEY_PEPPER` are generated, and the WebSocket proxy process.
- Candidates to remove or keep:
  - AI agent (LiteLLM, voice, ChatGPT sign-in)
  - WhatsApp
  - Remote MCP
  - Historify
  - Niche option tools
  - Developer pages: `ChartTest`, `WebSocketTest`, `Playground`
  - Root developer files: `DISCOVERY_MAP.md`, `benchmark_api.py`, `audit/`, `okf/`, `workspace/`, `tmp/`
- Guardrails:
  - Leave `services/risk/`, the order path and the eventlet and real-thread code untouched unless a test covers the change.
  - Run the `fd-audit` skill after removals that touch the database, streaming, threads or subprocesses.

**Phase 3: cross-OS distribution and release**
- Research and proposed milestones: [2026-11-04-desktop-packaging-research.md](2026-11-04-desktop-packaging-research.md).
- Plan (Windows desktop panel, keeper and reset; replaces the service approach; built 2026-11-05, uncommitted): [2026-11-05-desktop-panel-and-reset-plan.md](2026-11-05-desktop-panel-and-reset-plan.md).
- Production uses gunicorn with eventlet, and gunicorn does not run on Windows. Desktop needs the threading server mode, so we must decide which modes we support.
- Bundle a standalone Python with `uv` and the locked environment rather than freezing.
- Keep client data outside the program folder.
- Build a first-run setup wizard to replace hand-editing `.env`.
- Installers and Docker image names.

**Phase 4: multi-broker**
- `SymToken` is one global table that each broker's master contract download replaces.
- An API key resolves to exactly one broker.
- The lowest-risk route is one instance per account plus an aggregating dashboard.
