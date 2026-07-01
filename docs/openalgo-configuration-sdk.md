# OpenAlgo Configuration SDK

OpenAlgo Configuration SDK, or OCS, makes Python strategy inputs editable from the OpenAlgo web UI. A strategy declares configurable fields once, OpenAlgo discovers those declarations during upload, renders a configuration form, validates user input, stores the values, and injects the resolved runtime configuration when the strategy starts.

This guide describes the implemented system for the Python Strategy Management feature and the intended SDK-native direction for OpenAlgo libraries.

## Overview

Before OCS, changing strategy parameters usually meant editing Python source code. OCS moves those parameters into a platform-managed configuration flow.

```text
Strategy script
  -> ui.* declarations or legacy schema
  -> OpenAlgo schema discovery
  -> JSON schema and values storage
  -> React configuration page
  -> validated runtime values
  -> strategy subprocess environment
```

The current implementation focuses on Python strategies under `/python`, with a shared schema contract designed to support future SDKs such as Python, Node.js, Go, Java, .NET, and Rust.

## What Is Included

| Area | Implementation |
|---|---|
| Backend core | `openalgo_config` schema normalization, validation, value coercion, JSON storage, and runtime config building |
| Python strategy host | Upload-time schema discovery, config APIs, runtime injection, delete cleanup, and safe path handling |
| Frontend | Generated React configuration page at `/python/:strategyId/config` |
| Runtime | `OPENALGO_CONFIG_JSON`, `OPENALGO_CONFIG_SCHEMA_JSON`, and `OPENALGO_CONFIG_<KEY>` environment variables |
| Storage | File-backed JSON under `strategies/configs/` |
| Developer API | Local `openalgo_config.ui` helper, with the target public API being `from openalgo.config import ui` |
| Frontend build behavior | Optional background auto-build only when `OPENALGO_AUTO_BUILD_FRONTEND=true` |

## Storage Layout

OCS stores runtime state beside Python strategy runtime files:

```text
strategies/
|-- scripts/
|   `-- <strategy_id>.py
|-- strategy_configs.json
`-- configs/
    |-- schemas/
    |   `-- <strategy_id>.json
    `-- values/
        `-- <strategy_id>.json
```

`strategies/configs/` is local runtime state and should not be committed.

If the normal strategy directories cannot be created because of permissions, the Python strategy host falls back to a temporary OpenAlgo directory and moves the OCS store with it. This keeps strategy scripts, logs, schemas, and values in the same writable runtime area.

## Authoring Strategy Inputs

New strategy scripts should declare fields with explicit `ui.*` keys:

```python
try:
    from openalgo.config import ui
except ModuleNotFoundError:
    from openalgo_config import ui

strategy = ui.string("strategy", default="EMA Crossover Python", label="Strategy Name")
symbol = ui.symbol("symbol", default="NHPC", label="Symbol", required=True)
exchange = ui.exchange("exchange", default="BSE", label="Exchange")
product = ui.product("product", default="MIS", options=["MIS", "NRML", "CNC"])
quantity = ui.quantity("quantity", default=1, min=1)

fast_period = ui.int("fast_period", default=5, min=1, max=200)
slow_period = ui.int("slow_period", default=10, min=2, max=500)
debug = ui.bool("debug", default=False)
```

Explicit keys are required for reliable upload-time discovery and runtime value lookup. Keyless declarations are ignored by static schema discovery because assignment-name inference can drift from runtime helper semantics.

Legacy scripts can still expose a literal `DEFAULT_OCS_SCHEMA` or `OCS_SCHEMA` dictionary. That compatibility path is useful for older strategies, but new scripts should use `ui.*` declarations instead of hand-written schema dictionaries.

## Upload Flow

When a strategy is uploaded from `/python/new`, OpenAlgo:

1. Saves the strategy script under `strategies/scripts/`.
2. Parses the script with Python `ast`.
3. Extracts explicit `ui.*` declarations without executing trading code.
4. Falls back to literal `DEFAULT_OCS_SCHEMA` or `OCS_SCHEMA` only when needed.
5. Normalizes and validates the schema.
6. Stores the schema in `strategies/configs/schemas/`.
7. Creates or updates editable values in `strategies/configs/values/`.
8. Returns `has_config_schema` and `config_field_count` in the upload response.

The React upload flow can navigate directly to the generated config page when fields are discovered. The strategy list also receives live config metadata from `/python/api/strategies`, so the config icon appears from API data without rebuilding React after every upload.

## Configuration API

| Method | Endpoint | Purpose |
|---|---|---|
| `GET` | `/python/api/config/<strategy_id>` | Load schema, editable values, runtime-resolved values, and validation errors |
| `POST` | `/python/api/config/<strategy_id>/schema` | Save or replace a schema |
| `POST` | `/python/api/config/<strategy_id>/values` | Save user-edited values |
| `POST` | `/python/api/config/validate` | Validate draft schema and values without saving |

The read API distinguishes between editable values and runtime values:

| Field | Meaning |
|---|---|
| `values` | Safe editable draft values; available even when required fields are not filled yet |
| `resolved_values` | Runtime-valid values when validation succeeds; falls back to draft values when incomplete |
| `validation_errors` | Structured errors explaining why runtime values are not yet valid |

This lets users add required fields first, then fill values in the UI, without breaking config page loading.

## Runtime Injection

When a Python strategy starts, OpenAlgo validates the saved values and injects the resolved configuration into the subprocess environment.

| Environment variable | Description |
|---|---|
| `OPENALGO_CONFIG_JSON` | Full resolved value object as JSON |
| `OPENALGO_CONFIG_SCHEMA_JSON` | Normalized schema as JSON |
| `OPENALGO_CONFIG_<KEY>` | Per-field string convenience value |
| `OPENALGO_STRATEGY_EXCHANGE` | Exchange selected for the strategy runner |
| `OPENALGO_API_KEY` | User API key when available |
| `OPENALGO_HOST` | OpenAlgo host URL |

Strategies can read configuration through the `ui.*` helper or directly from `OPENALGO_CONFIG_JSON`.

## Generated React UI

The config page lives at:

```text
/python/<strategy_id>/config
```

It renders fields from the saved schema and supports:

- Text-like fields, including `string`, `symbol`, `broker`, `timeframe`, `expiry`, and `session`.
- Numeric fields, including `int`, `float`, `quantity`, `lot_size`, `percentage`, `price`, `trigger_price`, and `strike`.
- Boolean switches.
- Select and multi-select fields.
- JSON text areas.
- Date, time, color, and password inputs.
- Field descriptions, placeholders, min, max, step, options, and grouping metadata.

Number inputs preserve intermediate typing states such as `-`, `.`, and `1.` so users are not forced into invalid `NaN` or truncated values while editing. Running strategies cannot be edited until they are stopped.

The config icon on the strategy card is icon-only but includes an accessible label for screen readers.

## Validation Rules

OCS validation is centralized in `openalgo_config/core.py`.

| Validation area | Behavior |
|---|---|
| Schema shape | Schema must be an object; fields must be a list |
| Field keys | Keys must be unique and match Python-style identifier rules |
| Field types | Type must be one of the supported OCS field types |
| Required fields | Required values are enforced when saving runtime values |
| Defaults | Defaults are coerced and validated during schema normalization |
| Numeric limits | `min` and `max` apply to numeric field types |
| Options | `select` and `multi_select` enforce membership |
| Option value types | Numeric and boolean option values are preserved during validation |
| Regex | Regex syntax is validated at schema save time and applied after option matching |
| Unknown values | Extra value keys are rejected |
| Schema changes | Stale value keys are pruned when schemas change |

Schema persistence is resilient when a new required field has no default. The schema can be saved first, the config UI can show an incomplete draft, and the user can fill the required value before strategy start.

Bad disk I/O or unexpected runtime failures in OCS API handlers return structured API errors instead of leaking raw exceptions.

## Supported Field Types

| Category | Types |
|---|---|
| Basic | `int`, `float`, `bool`, `string`, `password` |
| Choice | `select`, `multi_select` |
| Trading | `symbol`, `exchange`, `product`, `broker`, `timeframe`, `quantity`, `lot_size`, `percentage`, `price`, `trigger_price`, `expiry`, `strike`, `option_type` |
| UI and data | `color`, `date`, `time`, `session`, `json` |

Additional UI metadata such as `label`, `description`, `placeholder`, `group`, `tab`, `section`, `min`, `max`, `step`, `regex`, `options`, `visible_if`, and `enabled_if` can be stored in the schema for current or future rendering behavior.

## Frontend Build Behavior

React is served from:

```text
frontend/dist/
```

OCS configuration discovery is runtime API behavior. Uploading a strategy does not require a frontend rebuild.

Auto-build is disabled by default. If explicitly enabled, OpenAlgo starts a background build during app startup when the React bundle is stale or missing:

```powershell
set OPENALGO_AUTO_BUILD_FRONTEND=true
uv run app.py
```

On Linux or macOS:

```bash
OPENALGO_AUTO_BUILD_FRONTEND=true uv run app.py
```

The auto-build path never runs inside a React route request handler, so page requests are not blocked by `npm install` or `npm run build`.

## Included Example Strategy

The maintained OCS example is:

```text
strategies/examples/simple_ema_strategy_config.py
```

It demonstrates:

- Explicit `ui.*` field declarations.
- Runtime values returned by the helper calls.
- OpenAlgo API key and host injection.
- `openalgo.ta` indicator usage.
- EMA crossover signals using `ta.ema`, `ta.crossover`, `ta.crossunder`, and `ta.exrem`.

Typical configurable fields include strategy name, symbol, exchange, product, quantity, fast EMA period, slow EMA period, interval, history window, and polling interval.

## OpenAlgo Python Library Direction

The current app includes `openalgo_config.ui` as a local helper for OpenAlgo-hosted strategies. The intended public developer experience is:

```python
from openalgo.config import ui

symbol = ui.symbol("symbol", default="NHPC")
ema = ui.int("ema", default=20, min=1, max=500, label="EMA Length")
stop_loss = ui.float("stop_loss", default=2.0, min=0.1)
debug = ui.bool("debug", default=False)
```

The OpenAlgo Python library should eventually provide:

```text
openalgo/
`-- config/
    |-- __init__.py
    |-- ui.py
    |-- registry.py
    |-- runtime.py
    `-- schema.py
```

Each helper call should:

1. Register field metadata for schema generation.
2. Read the configured runtime value from `OPENALGO_CONFIG_JSON`.
3. Fall back to the default when no runtime value exists.
4. Return a typed Python value.

The host can keep using safe static AST discovery for simple literal declarations. A future schema-export mode can support dynamic declarations by running a script in a non-trading schema-only mode.

## Multi-SDK Direction

The OCS schema contract is language-neutral. Other SDKs can expose native helpers that emit the same JSON schema.

```text
Python    ui.int("ema", default=20)
Node.js   ui.int("ema", { default: 20 })
Go        ui.Int("ema", ui.Default(20))
Rust      ui::int("ema").default(20).get()

All produce the same OCS schema.
```

The OpenAlgo host should remain the validator, storage owner, and UI renderer. SDKs should focus on ergonomic declaration and runtime value access.

## Operational Notes

- Stop a running strategy before changing its schema or values.
- Do not manually edit `strategies/configs/` unless repairing local runtime state.
- Use explicit keys in all `ui.*` declarations.
- Use literal defaults, options, labels, and limits when relying on static discovery.
- Keep frontend rebuilds separate from strategy uploads.
- Treat `DEFAULT_OCS_SCHEMA` and `OCS_SCHEMA` as compatibility paths, not the preferred authoring model.

## Troubleshooting

| Problem | Likely cause | Resolution |
|---|---|---|
| Config icon missing after upload | No explicit `ui.*` fields were discovered, or API metadata did not report fields | Check `/python/api/strategies` for `has_config_schema` and `config_field_count`; re-upload with explicit keys |
| Config page is empty | Script has no discoverable schema | Add explicit `ui.*` declarations or a compatibility schema |
| Required field blocks runtime | Field has no saved value yet | Open the config page, fill the value, and save |
| Schema saves but runtime values are incomplete | Required fields were added before values existed | Use the returned `validation_errors` to guide the user to missing fields |
| Numeric input behaves oddly while typing | Browser intermediate numeric text is not a final number | The UI preserves drafts; save only after entering a complete value |
| Select value rejected unexpectedly | Option value type or regex does not match | Confirm options and regex syntax; numeric and boolean options are preserved |
| Regex crashes validation | Invalid regex pattern | Schema normalization now returns structured regex errors |
| Frontend route shows old UI after source changes | `frontend/dist` is stale | Run `cd frontend && npm run build`, or opt into background auto-build |
| Warning mentions schema parsing from `.` | Legacy/corrupt strategy record has an empty path | The host ignores empty, directory, and out-of-scope paths |

## Verification

The OCS implementation is covered by focused backend and frontend checks:

```powershell
.\.venv\Scripts\python.exe -m pytest test\test_openalgo_config.py test\test_python_strategy_exchange_aware.py test\test_python_strategy_edge_cases.py -q
.\.venv\Scripts\python.exe -m py_compile app.py blueprints\python_strategy.py blueprints\react_app.py openalgo_config\core.py openalgo_config\ui.py
cd frontend
npx tsc -b
npm run lint
```

Some local test runs can print a Windows/colorama logging warning during Python `atexit` cleanup after tests pass. That warning is separate from OCS validation behavior.
