# Documentation gap audit — 2026-11-06

## Scope and evidence

Audited repository commit: `0faa9dbf357a60326f241dbfcf5d337786cd37c9`.
The change window is **2026-09-06 through 2026-11-06**, containing 552 commits
including merges and generated frontend builds. Current source contracts take
precedence over commit subjects and historical documents.

This audit covers the complete local `docs/` tree and the four root entry
references (`README.md`, `INSTALL.md`, `CONTRIBUTING.md`, `DOCKER_README.md`) for
navigation/link structure,
then compares current references with the API and broker registries, frontend
tool registry, runtime/deployment scripts and the implementations behind the
recently changed features. It is a documentation audit, not a new certification
of every implementation or third-party integration. No application code,
instance configuration, credentials or live trading state was changed.

Historical release notes, benchmark results, implementation plans, old audits
and dated validation reports retain their original observations. Status notices
and index labels distinguish them from current operating instructions. Generated
indicator and OpenUI references retain their generator ownership.

## Confirmed gaps and corrections

| Area | Gap found | Correction and current reference |
|---|---|---|
| Broker setup | Guides required manual `.env` edits, used unsupported `BROKER=`, and missed saved broker keys | Document Select Broker and Broker Configuration, `.env` precedence, saved encrypted keys, one active broker, switch restrictions and pending-login validation. See [broker connection](../userguide/06-broker-connection/README.md) and [configuration design](../design/51-broker-system-config/README.md). |
| Installation secrets | First-time setup advised replacing installation secrets after creating the account | Explain first-run generation and preserving the original secrets with an existing database. See [setup](../userguide/05-first-time-setup/README.md). |
| Broker inventory | Current references and BDD inventory still listed 36 plugins | Reconcile 38 plugin IDs, including Rupeezy, Sahi and Dhan Sandbox. An installed plugin does not guarantee every data field or exchange entitlement. See [integration guide](../broker-integration-guide.md). |
| Public API coverage | The API index omitted eight registered methods/paths | Add Portfolio (four), SIP (two), and Sector Rotation (two) contracts, including authentication, request units, limits and response shapes. The index and BDD inventory cover all 74 registered pairs. See [API index](../api/README.md). |
| GTT capability and OCO limits | Documentation assumed only Dhan/Zerodha supported live GTT and promised uniform atomic OCO changes | Match all six live modules (Angel, Dhan, Fyers, Rupeezy, Upstox, Zerodha); document broker-specific history support and Angel's independent rules/sequential changes. See [GTT placement](../api/order-management/placegttorder.md) and [GTT order book](../api/order-management/gttorderbook.md). |
| Trading tutorials | Some examples used nonexistent SDK method spellings and blind order/basket retries | Use `placeorder`, `placesmartorder`, `basketorder`; remove retry examples that could duplicate an accepted order and explain reconciliation. See [Python guide](../userguide/20-python-strategies/README.md), [baskets](../userguide/13-basket-orders/README.md) and [Amibroker](../userguide/17-amibroker-integration/README.md). |
| Action Center | The guide invented modification controls, thresholds and public SDK approval methods | Describe the actual `/apikey` Auto/Semi-Auto control, approval UI, execution versus fill, interrupted sends, and broker reconciliation. See [Action Center](../userguide/22-action-center/README.md). |
| Bulk trading actions | MCP wording implied `strategy` restricted bulk cancellations/position closure | State account-wide scope; a strategy tag is not a filter. Use individual order IDs to cancel a subset. See [MCP tools](../mcp-tool-reference.md). |
| Tools | The tools guide omitted six of the 20 registered tools | Cover Portfolio Backtester, SIP Backtester, Portfolio Analyzer, OI Range, Strike Profile and Sector Rotation, with data requirements and limits. See [tools](../userguide/31-tools/README.md). |
| Python strategy host | The guide was mostly external SDK examples and missed hosted lifecycle controls | Cover upload, schedules, exchange calendars, crypto Run 24/7, editor Start/Stop/Cancel/log links, environment variables, process recovery and position reconciliation. See [Python strategies](../userguide/20-python-strategies/README.md). |
| Flow | User instructions described unsupported nodes and a nonexistent webhook path | Point to the actual generated workflow URL and supported node/import contract. See [Flow](../userguide/21-flow-visual-builder/README.md) and [import reference](../prompt/flow-import-format.md). |
| Charting and OpenScript | References lagged the full-screen terminal, runtime controls and current engine | Reconcile chart/indicator versions and describe strategy deployments, backtesting, pause/stop and supported execution destinations. See [terminal](../userguide/32-charting-terminal/README.md), [OpenScript](../openscript.md), [custom indicators](../custom-indicators.md). |
| WebSocket protocol | A standalone guide showed acknowledgements/flattened frames that the server does not send | Replace with real auth/subscription envelopes, nested market data and mode handling. Document broker-dependent optional fields and the pinned SDK's normalization limits. See [quote feed](../websocket-quote-feed.md), [wire protocol](../prompt/websockets-format.md) and [streaming API](../api/README.md#websocket-protocol). |
| Streaming topology | References implied an in-process production proxy and lossless/unlimited delivery | Explain the child/external proxy, one shared broker feed, SUB as sole binder, publisher connections on the fixed ZMQ port, and delivery/capability limits. See [architecture](../websocket-architecture.md). |
| Production workers | Several current references described eventlet as the only runtime | Describe eventlet default, optional one-worker/64-thread gthread, threaded development server, thread-safe helpers and separate proxy. See [worker guide](../gthread/README.md) and [backend](../design/02-backend/README.md). |
| Docker and Ubuntu | Old examples used a replacement Dockerfile, broad permissions, public ZMQ binding and obsolete installer prompts | Use the shipped build/launch scripts, writable private config, internal ZMQ, current broker setup and worker switch/rollback guidance. See [Docker](../docker/README.md) and [Ubuntu](../installation-guidelines/getting-started/ubuntu-server-installation.md). |
| Health monitoring | Probe examples requested `/health`, which serves the HTML dashboard; integration steps were already implemented | Use `/health/status` and `/health/check`, correct session/CSRF requirements, distinguish shipped and code-default thresholds, and remove unmeasured latency guarantees. See [health operations](../HEALTH_MONITORING_IMPLEMENTATION.md) and [frontend](../HEALTH_MONITOR_REACT_FRONTEND.md). |
| XTS integrations | The guide instructed editing `broker.html` and accepting old uncorrelated callbacks | Replace with current plugin registration, request-time keys, separate Interactive/Market Data identity, and started-login/state checks. See [XTS integration](../xtsapi.md). |
| Notifications | WhatsApp restart prerequisites and session-copy internals were stale; Telegram rendering pin/runtime notes lagged | Document connected-state requirements, live session snapshots in a subprocess, the current renderer pin and both production workers. See [WhatsApp](../whatsapp.md) and [Telegram rendering](../telegram-chart-rendering.md). |
| Specifications | Global PRD counts/versions were frozen; GTT specs contradicted sandbox support | Reconcile current registries, add broker-configuration contracts, update runtime/EventBus/CI references and remove the sandbox-GTT unsupported claim. See [PRD index](../prd/README.md) and [BDD index](../bdd/README.md). |
| Historical versus shipped | Scanner architecture read like an installed Redis scanner service, but no implementation is shipped | Mark it as an external-service proposal, preserve the design and remove unlimited-feed assertions. See [scanner proposal](../scanner-architecture.md). |
| Static examples | Lot-size snapshots and crypto arithmetic examples looked like current market data | Label dated/hypothetical examples and direct sizing to current symbol metadata. See [lot sizes](../prompt/LotSize.md), [crypto symbols](../prompt/crypto-symbol-format.md) and [test checklist](../test/QUICK_TEST_CHECKLIST.md). |
| Navigation | New features were absent from the documentation map; four local links/anchors did not resolve | Add current entry points, fix the GTT order-book link and P&L anchor, and label two unavailable historical QA addenda instead of linking to missing files. See [documentation map](../INDEX.md). |

## Recent-change coverage

| Changes in the two-month window | Current documentation checked |
|---|---|
| Saved broker keys, server-started login and multiple-device session handover | Broker user guide; login/config/environment/database design; broker configuration PRD and BDD |
| Rupeezy and Sahi plugins; broker quote/depth corrections through November 6 | Broker inventories and guide; raw WebSocket/SDK field-availability references |
| Strike Profile and Sector Rotation; existing portfolio/SIP APIs | Tools guide; analytical API pages; API/BDD inventories |
| Full-screen chart workspace, new intervals, combined instruments, drawings, backtests | Charting terminal and custom-indicator guide |
| OpenScript storage, server execution and multiple deployments | OpenScript and terminal references |
| Python editor controls and crypto 24/7 schedules | Hosted Python guide and existing scheduling/API references |
| Optional gthread, backpressure, shutdown, shared feeds and EventBus | Deployment, backend/cache/streaming design, worker guide and CI references |
| Ambiguous broker-write outcomes and approved orders with no answer | Order API, Action Center, SDK/tutorial and MCP references; residual below |
| Sandbox GTT support and order-book history | GTT API pages, PRD and BDD |
| Position-average caveats and opening charts from books | Positions/holdings and terminal guides |
| Voice agent and chart engine consolidation | Agent/voice design and current chart references; indexed voice entry |
| WhatsApp live-session persistence and TLS-verified email | WhatsApp guide and existing SMTP design |
| New companion downloads and Desktop | Installation guide links the public `/download` page, whose own explainers carry the release details |
| Freeze/holiday upgrades and special sessions | Existing release/migration notes and current calendar/scheduling references; snapshot sizing advice corrected |

## Remaining implementation discrepancies

These are source-backed follow-ups found while auditing docs. They were not
silently repaired as part of a documentation change.

1. **Action Center can label an ambiguous send as rejected.**
   `services/place_order_service.py` returns unsuccessful/502 when the transport
   records an unanswered broker write. `services/pending_order_execution_service.py`
   then calls `update_broker_status(..., "rejected")` for unsuccessful responses
   other than a recorded 429 refusal. The broker may already hold the order.
   Its outcome should remain explicitly unknown until reconciled. The guide now
   advises checking broker books after a lost response even if the UI says
   rejected; that guidance does not fix the state transition.
2. **MCP `check_holiday` calls a nonexistent route.**
   `mcp/mcpserver.py:check_holiday` posts to `/api/v1/checkholiday`, absent from
   `restx_api/__init__.py`. The tool is declared but unavailable at this revision;
   the reference directs callers to `get_timings` / `get_holidays` instead.
3. **The unused frontend simple-health helper requests HTML.**
   `frontend/src/api/health.ts:getSimpleHealth` requests `/health`, whereas JSON
   lives at `/health/status` in `blueprints/health.py`. The current dashboard does
   not call this helper. Probe documentation now uses the actual JSON route.
4. **Broker-key masking differs from the repository invariant.**
   `CLAUDE.md` says reads disclose no characters of saved keys. In the current
   code, `blueprints/broker_config.py:_mask` asks
   `blueprints/broker_credentials.py:mask_secret` to retain up to six API-key
   characters and append eight asterisks; secrets receive an all-mask value.
   The design reference describes the observed behavior. The invariant and code
   need a deliberate follow-up decision.
5. **OpenScript can detect a changed order destination after dispatch.**
   In `openscript_host/openscript_runner.py`, the placement path calls
   `client.placeorder(...)` before comparing the response's mode with the run's
   prior destination. If a position was already held, detecting the change does
   not undo that newly sent order or flatten the old destination. The
   [OpenScript reference](../openscript.md) documents the consequence; do not
   switch the instance's execution mode while a deployment holds a position.
   Changing this guarantee requires runtime work and tests.

Broker-specific GTT/OCO limitations and the SDK's loss of raw optional-field
availability are also explicitly documented. Named chart-workspace scale
round-tripping and the P&L percentage reference are recorded on their current
user pages; this audit does not claim to change those behaviors.

## Verification and boundaries

The checks use source parsing and filesystem reads, without importing the app or
starting database, broker or messaging services. The final measured counts and
results are recorded below. Registry parity is exact set comparison, not just
a matching total.

| Check | Result |
|---|---|
| Markdown files scanned | 329 under `docs/`, plus four root entry references |
| Relative Markdown file links and heading anchors | 1,150 local links checked; zero unresolved findings |
| REST API registration versus API index and BDD rows | All 74 method/path pairs match, no missing or extra entries |
| Plugin directories versus `.sample.env` and BDD | All 38 plugin IDs match |
| Live GTT module inventory versus BDD | All six current implementations match |
| Tool registry routes versus tools guide | All 20 routes represented |
| MCP declarations versus tool reference | All 49 names represented; unavailable `check_holiday` explicitly labelled |
| Gherkin syntax | All 18 files parse: 138 definitions, eight outlines, 136 example rows, 266 expanded cases |
| API examples | Nine new JSON examples and the Python quote-feed example parse |
| Userguide/OpenScript examples | 31 JSON fences parse; local links/anchors and code fences checked |
| Pinned SDK feed behavior | Published 2.0.5 message-processing methods checked for nested callbacks, missing-field zero defaults and Depth field filtering |
| Whitespace/errors in patch | `git diff --check` passes |

These results establish documentation structure, declaration coverage and the
listed source/example checks. They do not establish that all 266 documented
scenario cases pass at runtime.

No broker credentials, live orders, external webhook deliveries, messaging
accounts, browser interactions, production worker processes, Docker builds or
external documentation site were exercised. Those need their existing dedicated
checks when changing the implementation. The published `docs.openalgo.in`
repository/diagrams were not modified by this local documentation-only change.
External broker pricing, market entitlements and exchange/regulatory policies
are not certified by this audit. Runtime checks were not represented as passing
because prose or an inventory matched the code.

### Reproduce registry and coverage checks

Run from the repository root. These checks inspect declarations and documented
inventories; they do not execute endpoints or trade.

```bash
uv run --no-project python - <<'PY'
import ast
import re
from pathlib import Path

root = Path.cwd()
api_dir = root / 'restx_api'
read = lambda p: p.read_text(encoding='utf-8')
tree = ast.parse(read(api_dir / '__init__.py'))
imports = {
    a.asname or a.name: n.module
    for n in tree.body if isinstance(n, ast.ImportFrom)
    for a in n.names
}
actual = set()
for n in tree.body:
    if not isinstance(n, ast.Expr) or not isinstance(n.value, ast.Call):
        continue
    call = n.value
    if not isinstance(call.func, ast.Attribute) or call.func.attr != 'add_namespace':
        continue
    module = imports[call.args[0].id]
    prefix = next(k.value.value for k in call.keywords if k.arg == 'path')
    for cls in ast.parse(read(api_dir / (module + '.py'))).body:
        if not isinstance(cls, ast.ClassDef):
            continue
        for dec in cls.decorator_list:
            if not (isinstance(dec, ast.Call) and isinstance(dec.func, ast.Attribute)
                    and dec.func.attr == 'route'):
                continue
            for arg in dec.args:
                path = '/api/v1' + (prefix + arg.value).rstrip('/')
                for method in cls.body:
                    if isinstance(method, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        if method.name in ('get', 'post', 'put', 'patch', 'delete'):
                            actual.add((method.name.upper(), path))
api_doc = read(root / 'docs/api/README.md')
documented = {
    (method, '/api/v1' + path)
    for methods, path in re.findall(r'^\| ([A-Z, ]+) \| `([^`]+)` \|', api_doc, re.M)
    for method in methods.split(', ')
}
assert actual == documented, (actual - documented, documented - actual)
bdd = read(root / 'docs/bdd/rest_api_inventory.feature')
bdd_pairs = {(method, '/api/v1' + path) for method, path in re.findall(r'^\s*\|\s*(GET|POST|PUT|PATCH|DELETE)\s*\|\s*(/[^| ]+)\s*\|', bdd, re.M)}
assert actual == bdd_pairs, (actual - bdd_pairs, bdd_pairs - actual)
plugins = {p.parent.name for p in (root / 'broker').glob('*/plugin.json')}
configured = set(re.search(r"^VALID_BROKERS\s*=\s*'([^']+)'", read(root / '.sample.env'), re.M)[1].split(','))
assert plugins == configured, plugins ^ configured
broker_bdd = read(root / 'docs/bdd/broker_plugin_inventory.feature')
broker_rows = set(re.findall(r'^\s*\|\s*([a-z][a-z0-9_]+)\s*\|', broker_bdd, re.M)) - {'broker'}
assert plugins == broker_rows, plugins ^ broker_rows
tool_routes = re.findall(r"href: '([^']+)'", read(root / 'frontend/src/lib/tools.ts'))
tool_guide = read(root / 'docs/userguide/31-tools/README.md')
assert all(route in tool_guide for route in tool_routes)
mcp = ast.parse(read(root / 'mcp/mcpserver.py'))
mcp_tools = [
    n.name for n in mcp.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
    and any(isinstance(d, ast.Call) and isinstance(d.func, ast.Name)
            and d.func.id == 'openalgo_tool' for d in n.decorator_list)
]
mcp_doc = read(root / 'docs/mcp-tool-reference.md')
assert all(name in mcp_doc for name in mcp_tools)
print(f'REST {len(actual)}; plugins {len(plugins)}; tools {len(tool_routes)}; declared MCP tools {len(mcp_tools)}: parity passed')
PY
```

### Reproduce Gherkin syntax validation

This parses the specification documents. It does **not** run their scenarios;
there are no corresponding Behave/Cucumber step implementations in this tree.

```bash
uv run --no-project --with gherkin-official python - <<'PY'
from pathlib import Path
from gherkin.parser import Parser

files = sorted(Path('docs/bdd').glob('*.feature'))
definitions = outlines = rows = 0
for path in files:
    feature = Parser().parse(path.read_text(encoding='utf-8'))['feature']
    for child in feature['children']:
        if 'scenario' not in child:
            continue
        scenario = child['scenario']
        definitions += 1
        if scenario.get('examples'):
            outlines += 1
            rows += sum(len(e.get('tableBody', [])) for e in scenario['examples'])
print(len(files), 'files;', definitions, 'definitions;', outlines, 'outlines;', rows, 'example rows;', definitions - outlines + rows, 'expanded cases')
PY
```

### Reproduce Markdown link and anchor checks

The following checks relative Markdown file/image links, reference-style links
and Markdown heading anchors in all `docs/**/*.md` and the four root entry
references. It ignores fenced code, external URLs and application-absolute URL
paths. It does not check remote URL availability, arbitrary inline code paths,
HTML links or external-site rendering.

```bash
uv run --no-project python - <<'PY'
import collections, json, pathlib, re, subprocess, unicodedata, urllib.parse
ROOT = pathlib.Path.cwd()
HISTORICAL = ('docs/releases/', 'docs/audit/', 'docs/plans/', 'docs/superpowers/', 'docs/migration/', 'docs/benchmarks/')
def visible(text):
    lines=[]; fence=None
    for line in text.splitlines():
        m=re.match(r'^\s*(`{3,}|~{3,})',line)
        if m:
            if fence is None: fence=m[1][0]
            elif m[1][0]==fence: fence=None
            lines.append(''); continue
        lines.append('' if fence else line)
    return '\n'.join(lines)
def anchors(path):
    s=visible(path.read_text(encoding='utf-8')); out=set(); counts=collections.Counter()
    for title in re.findall(r'^\s{0,3}#{1,6}\s+(.+?)\s*#*\s*$',s,re.M):
        title=re.sub(r'!?\[([^]]+)\]\([^)]*\)',r'\1',title)
        title=re.sub(r'<[^>]+>','',title).lower().strip()
        slug=''.join(c for c in title if c in '-_ ' or unicodedata.category(c)[0] in 'LN').replace(' ','-')
        n=counts[slug]; counts[slug]+=1; out.add(slug+(f'-{n}' if n else ''))
    out.update(re.findall(r'<a\s+(?:name|id)=[\"\']([^\"\']+)',s))
    return out
files=sorted((ROOT/'docs').rglob('*.md'))+[ROOT/name for name in ('README.md','INSTALL.md','CONTRIBUTING.md','DOCKER_README.md')]; findings=[]; links=0; kinds=collections.Counter(); anchor_cache={}
for path in files:
    rel=str(path.relative_to(ROOT)); s=visible(path.read_text(encoding='utf-8')); historic=rel.startswith(HISTORICAL)
    kinds['historical' if historic else 'reference']+=1
    refs={m[1].strip().lower(): m[2] for m in re.finditer(r'^\s*\[([^]]+)\]:\s*<?([^\s>]+)>?',s,re.M)}
    matches=[(m.start(),m[1] or m[2]) for m in re.finditer(r'!?\[[^\]\n]*\]\(\s*(?:<([^>]+)>|([^\n]*?))\s*\)',s)]
    matches += [(m.start(),refs.get((m[2] or m[1]).strip().lower(),'')) for m in re.finditer(r'\[([^]\n]+)\]\[([^]\n]*)\]',s)]
    for pos, raw in matches:
        dest=raw.strip(); dest=re.sub(r'\s+[\"\'][^\n]*$','',dest)
        if not dest or re.match(r'^[a-zA-Z][a-zA-Z0-9+.-]*:',dest) or dest.startswith('//'): continue
        if dest.startswith('/'): continue
        links+=1
        url=urllib.parse.urlsplit(dest); target=(path.parent/urllib.parse.unquote(url.path)).resolve() if url.path else path
        line=s[:pos].count('\n')+1
        finding=None
        if not target.exists(): finding='missing-file'
        elif url.fragment and target.suffix.lower()=='.md':
            if target not in anchor_cache: anchor_cache[target]=anchors(target)
            if urllib.parse.unquote(url.fragment) not in anchor_cache[target]: finding='missing-anchor'
        if finding: findings.append(dict(file=rel,line=line,target=dest,kind=finding,historical=historic))
result=dict(markdown_files=len(files),classification=dict(kinds),local_links=links,findings=findings)
print(json.dumps({k:v for k,v in result.items() if k!='findings'}))
print('Findings:',len(findings),'current:',sum(not x['historical'] for x in findings))
for x in findings: print(f"{x['file']}:{x['line']} [{x['kind']}, {'history' if x['historical'] else 'current'}] {x['target']}")

assert not findings, f'{len(findings)} unresolved Markdown links/anchors'
PY
```

Also run `git diff --check`. Generated chart/indicator/OpenUI references were
not regenerated: this checkout has no installed project `.venv` or
`frontend/node_modules`. Their dedicated generator/parity checks belong to a
fully installed development environment and were not claimed as passing here.
