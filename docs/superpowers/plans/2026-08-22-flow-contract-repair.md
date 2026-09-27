# Flow Node Contract Repair Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make Flow activation, execution, React configuration, and import documentation enforce one safe contract for all audited nodes, while retaining draft-save and backward-compatibility behavior.

**Architecture:** Keep the existing editor -> validator -> executor -> OpenAlgo client pipeline. Put static and strict-completeness checks in `flow_workflow_validator.py`, resolve dynamic templates and fail closed in `flow_executor_service.py`, expose the same fields in `ConfigPanel.tsx` and Flow types/defaults, and continuously validate the prompt's JSON examples against the strict validator.

**Tech Stack:** Python 3, Flask service layer, pytest, Ruff, React 19, TypeScript, Vitest, Testing Library, Vite, Biome.

**Spec:** `docs/superpowers/specs/2026-08-22-flow-contract-repair-design.md`

## Global Constraints

- Work only in `D:\testing\openalgo\.worktrees\flow-contract-repair` on branch `fix/flow-contract-repair`. Do not reset, clean, stage, or overwrite the user's dirty checkout at `D:\testing\openalgo`.
- Add no node types, broker constants, or Telegram cross-account recipient capability.
- Keep incomplete draft saves permissive: conditional completeness checks belong behind `strict=True`; malformed supplied constants and unsafe supplied values remain invalid in both modes.
- Defer a value containing `{{...}}` when it cannot be resolved during activation, then validate its resolved runtime value before a broker call.
- Keep Telegram delivery tied to the workflow API key. Ignore legacy `username` JSON rather than rejecting old workflows.
- Keep one common expiry for Options Multi-Order. Do not read or advertise per-leg expiry.
- Preserve list-form BasketOrder leg values. Common node-level product/price fields fill only missing leg properties.
- Follow red-green-refactor for every behavior change: write one focused failing test, run it and inspect the expected failure, implement the smallest correction, rerun the focused test, then refactor if needed.
- Use `apply_patch` for source and documentation edits. Stage only files listed by the current task.
- Before each commit run the task's focused tests and `git diff --check`.

## Baseline

- Clean worktree base: `origin/main` at `60156bc52` plus approved design commit `04a0245c1`.
- Focused baseline command:

  ```powershell
  $env:PYTEST_DISABLE_PLUGIN_AUTOLOAD='1'
  pytest -o addopts='' -q test/test_flow_workflow_validator.py test/test_flow_qa_regressions.py test/test_flow_market_hours.py
  ```

  Expected baseline: `199 passed, 3 skipped`.

- Repository-wide collection currently has two unrelated baseline failures: `test/test_bot_web.py` cannot import `get_telegram_bot`, and `test/test_telegram_startup.py` cannot import `eventlet`. Recheck them at final verification, but do not modify those unrelated areas as part of this repair.

---

## Task 1: Repair conditional activation validation

**Files:**

- Modify: `services/flow_workflow_validator.py`
- Modify: `test/test_flow_workflow_validator.py`

**Interfaces:**

- Keep `validate_workflow(payload, *, require_name=True, strict=True) -> list[dict]` unchanged.
- Reuse JSON-pointer paths such as `/nodes/1/data/symbol` and existing error dictionaries from `_err(...)`.
- Import `VALID_STATUSES` from `services.flow_order_update_monitor_service` or define a shared dependency that both validator and monitor import; do not duplicate a status set that can drift.

- [ ] **Step 1: Add failing nested Indicator tests.**

  Add parametrized tests proving that `indicatorName` is always required, a `sourceSeries` Indicator accepts blank `symbol`/`exchange`, and a history-backed Indicator still requires both fields.

  ```python
  @pytest.mark.parametrize(
      ("data", "missing"),
      [
          ({"indicatorName": "RSI", "sourceSeries": "{{bars}}"}, set()),
          ({"indicatorName": "RSI"}, {"symbol", "exchange"}),
          ({"sourceSeries": "{{bars}}"}, {"indicatorName"}),
      ],
  )
  def test_indicator_requirements_follow_its_data_source(data, missing):
      errors = validate_workflow(_single_action_workflow("indicator", data))
      paths = {error["path"].rsplit("/", 1)[-1] for error in errors if error["code"] == "missing_field"}
      assert paths == missing
  ```

- [ ] **Step 2: Run the Indicator test and confirm the current validator wrongly requires `symbol` and `exchange` for the nested case.**

  ```powershell
  $env:PYTEST_DISABLE_PLUGIN_AUTOLOAD='1'
  pytest -o addopts='' -q test/test_flow_workflow_validator.py -k indicator_requirements
  ```

- [ ] **Step 3: Make Indicator requirements conditional.**

  Change `REQUIRED_NODE_FIELDS["indicator"]` to only `("indicatorName",)`. In the strict node loop append `symbol` and `exchange` only when `sourceSeries` is missing or blank. Treat a template source such as `{{history.data}}` as supplied.

- [ ] **Step 4: Add failing SmartOrder zero tests.**

  Parametrize SmartOrder quantities `0`, `"0"`, `-1`, and a positive value. Assert zero and positive values validate, negative values fail with `invalid_quantity`, and `placeOrder` still rejects zero.

- [ ] **Step 5: Run the SmartOrder tests and confirm zero currently fails.**

  ```powershell
  pytest -o addopts='' -q test/test_flow_workflow_validator.py -k smart_order_quantity
  ```

- [ ] **Step 6: Split quantity range rules by node type.**

  Replace the global `quantity` treatment with a helper that accepts `allow_zero=True` only for `smartOrder`; keep `splitSize` and `lots` positive everywhere. Use error text that says SmartOrder quantity must be non-negative and all other order quantities must be positive.

- [ ] **Step 7: Add failing Order Update Trigger tests.**

  Cover literal `orderId`, symbol-only filtering, neither field, templated `orderId`, case-insensitive valid statuses, and an unknown status. Assert error paths end in `orderId`, `symbol`, or `status` as appropriate.

  ```python
  @pytest.mark.parametrize("data", [{}, {"orderId": "{{previous.orderid}}"}])
  def test_order_update_trigger_rejects_unwatchable_filters(data):
      errors = _strict_node_errors("orderUpdateTrigger", {"status": "complete", **data})
      assert any(error["code"] in {"missing_alternative", "invalid_trigger_filter"} for error in errors)
  ```

- [ ] **Step 8: Run the Order Update tests and confirm graph validation currently accepts the invalid cases.**

  ```powershell
  pytest -o addopts='' -q test/test_flow_workflow_validator.py -k order_update_trigger
  ```

- [ ] **Step 9: Mirror the monitor's watch contract in strict validation.**

  Require at least one nonblank `orderId` or `symbol`; reject `{{...}}` in `orderId`; normalize status with `strip().lower()` and validate against the monitor's `VALID_STATUSES`. Dynamic symbol filters remain allowed because they are not prohibited by the existing monitor.

- [ ] **Step 10: Add failing expiry-dependent node tests.**

  Test `optionSymbol` and `optionChain` with explicit `expiryDate`, with an embedded expiry such as `NIFTY27AUG26`, and with plain `NIFTY` plus no expiry. Test `syntheticFuture` with and without explicit expiry. Import and call `parse_underlying_symbol()` so the acceptance test uses the production parser rather than a second regex.

- [ ] **Step 11: Run the expiry tests and confirm missing expiry is currently accepted.**

  ```powershell
  pytest -o addopts='' -q test/test_flow_workflow_validator.py -k expiry_requirement
  ```

- [ ] **Step 12: Implement the expiry rules behind strict validation.**

  For `optionSymbol` and `optionChain`, require `expiryDate` only when `parse_underlying_symbol(underlying)` returns no embedded expiry. Always require it for `syntheticFuture`. A templated underlying or expiry is supplied but deferred.

- [ ] **Step 13: Run all Task 1 tests and the full validator module.**

  ```powershell
  pytest -o addopts='' -q test/test_flow_workflow_validator.py -k "indicator_requirements or smart_order_quantity or order_update_trigger or expiry_requirement"
  pytest -o addopts='' -q test/test_flow_workflow_validator.py
  git diff --check
  ```

- [ ] **Step 14: Commit Task 1.**

  ```powershell
  git add services/flow_workflow_validator.py test/test_flow_workflow_validator.py
  git commit -m "fix(flow): validate conditional node requirements"
  ```

---

## Task 2: Validate priced orders, Margin, custom option legs, and Variable configuration

**Files:**

- Modify: `services/flow_workflow_validator.py`
- Modify: `test/test_flow_workflow_validator.py`

**Interfaces:**

- Price rules cover `placeOrder`, `smartOrder`, `optionsOrder`, `optionsMultiOrder`, `basketOrder`, and `splitOrder`.
- `LIMIT`/`SL` require positive `price`; `SL`/`SL-M` require positive `triggerPrice`.
- `VALID_VARIABLE_OPERATIONS` contains exactly `set`, `get`, `add`, `subtract`, `multiply`, `divide`, `increment`, `decrement`, `parse_json`, `stringify`, and `append`.

- [ ] **Step 1: Add failing top-level priced-order tests for all six node types.**

  Parametrize node type, minimal complete data, price type, required field, and supplied value. Cover absent, blank, zero, negative, positive, and `{{webhook.price}}`. Assert absent/blank/static non-positive values fail only in strict mode where absence is a completeness concern; a supplied non-positive value still fails non-strict saves; a template and a positive value pass.

  ```python
  @pytest.mark.parametrize("node_type,minimal", PRICED_ORDER_NODES.items())
  @pytest.mark.parametrize(
      ("price_type", "required_field"),
      [("LIMIT", "price"), ("SL", "price"), ("SL", "triggerPrice"), ("SL-M", "triggerPrice")],
  )
  def test_priced_order_requires_each_static_price(node_type, minimal, price_type, required_field):
      errors = _strict_node_errors(node_type, {**minimal, "priceType": price_type})
      assert any(error["path"].endswith(f"/{required_field}") for error in errors)
  ```

- [ ] **Step 2: Run the priced-order tests and confirm missing fields currently pass.**

  ```powershell
  pytest -o addopts='' -q test/test_flow_workflow_validator.py -k priced_order
  ```

- [ ] **Step 3: Centralize price validation without skipping missing fields.**

  Add a helper accepting `(base, data, strict, price_type_key="priceType")`. If a required field is absent or blank and `strict` is true, emit `missing_price`; if present and statically non-positive, emit `invalid_price` in both modes. Return without judging `{{...}}`. Invoke it once for each supported top-level order node. Preserve lowercase `pricetype` support for list-form legs.

- [ ] **Step 4: Add failing Margin validation tests.**

  Cover empty data, blank `positionsJson`, malformed JSON, empty `[]`, an object instead of an array, a non-object leg, a missing required leg field, an invalid constant, a LIMIT leg without positive price, a whole-field template, a templated leg value, valid `positions`, and legacy `symbol`. Use the same minimum leg shape as `MarginPositionsFields`:

  ```python
  MARGIN_LEG = {
      "symbol": "RELIANCE",
      "exchange": "NSE",
      "action": "BUY",
      "quantity": "1",
      "product": "MIS",
      "pricetype": "MARKET",
      "price": "0",
  }
  ```

- [ ] **Step 5: Run the Margin tests and confirm blank or malformed baskets are accepted by the graph validator.**

  ```powershell
  pytest -o addopts='' -q test/test_flow_workflow_validator.py -k margin_contract
  ```

- [ ] **Step 6: Implement strict Margin structure validation.**

  Accept a nonblank `positionsJson`, `positions`, or legacy `symbol`. Defer a whole-field template. For static JSON require a nonempty list of dictionaries, then validate `symbol`, `exchange`, `action`, `quantity`, `product`, and `pricetype`; reuse enum, numeric, and priced-order helpers with paths such as `/nodes/1/data/positionsJson/0/price`. Do not mutate or normalize the stored JSON.

- [ ] **Step 7: Add failing custom Options Multi-Order tests.**

  Assert `strategy: custom` requires a nonempty list. For each static leg require `offset`, `optionType`, `action`, and positive `quantity`; validate optional `product`, `priceType`/`pricetype`, `price`, and `triggerPrice`. Assert a generated strategy with `priceType: SL` is rejected, a generated MARKET/LIMIT strategy passes when correctly priced, and a custom SL leg with both prices passes. Assert templates are deferred.

- [ ] **Step 8: Run the custom-leg tests and confirm current strict validation misses leg completeness.**

  ```powershell
  pytest -o addopts='' -q test/test_flow_workflow_validator.py -k options_multi_contract
  ```

- [ ] **Step 9: Implement generated/custom strategy validation.**

  Normalize `strategy`. For `custom`, validate a nonempty `legs` array and every static leg. For generated strategies accept only `MARKET` and `LIMIT`; apply the common top-level price rule. Ignore legacy per-leg `expiryDate` rather than rejecting the extra property.

- [ ] **Step 10: Add failing Variable configuration tests.**

  Assert every one of the eleven operations is accepted. Reject an unknown operation. Require `sourceVariable` for `get` and `stringify`; require `value` for arithmetic and `parse_json`; permit empty extra fields for `set`, `append`, `increment`, and `decrement` as specified. A templated required value counts as supplied.

- [ ] **Step 11: Run Variable validation tests and confirm an unknown operation and missing conditional values currently pass.**

  ```powershell
  pytest -o addopts='' -q test/test_flow_workflow_validator.py -k variable_contract
  ```

- [ ] **Step 12: Implement Variable enum and conditional fields.**

  Add `VALID_VARIABLE_OPERATIONS`; validate a statically supplied operation in both modes. Behind `strict=True`, require `sourceVariable` for `get`/`stringify` and nonblank `value` for `add`/`subtract`/`multiply`/`divide`/`parse_json`. Default a missing operation to `set` for backward compatibility.

- [ ] **Step 13: Run Task 2 tests and the full validator module.**

  ```powershell
  pytest -o addopts='' -q test/test_flow_workflow_validator.py -k "priced_order or margin_contract or options_multi_contract or variable_contract"
  pytest -o addopts='' -q test/test_flow_workflow_validator.py
  git diff --check
  ```

- [ ] **Step 14: Commit Task 2.**

  ```powershell
  git add services/flow_workflow_validator.py test/test_flow_workflow_validator.py
  git commit -m "fix(flow): reject incomplete executable node data"
  ```

---

## Task 3: Preserve numeric zero and propagate Smart, Split, and Basket prices

**Files:**

- Modify: `services/flow_executor_service.py`
- Modify: `test/test_flow_qa_regressions.py`

**Interfaces:**

- Keep client method signatures unchanged: `place_smart_order(..., price, trigger_price)`, `split_order(..., price, trigger_price)`, and `basket_order(orders, strategy)`.
- All broker-bound price fields must pass `_invalid_price_reason()` after interpolation.

- [ ] **Step 1: Add failing numeric accessor tests.**

  Construct `ExecutionContext` and `NodeExecutor` through the existing executor fixture. Assert `get_int({"quantity": 0}, "quantity", 1) == 0`, `get_float({"price": 0}, "price", 1.0) == 0.0`, absent values return defaults, and unparsable interpolated values still return defaults for non-order callers.

- [ ] **Step 2: Run the accessor tests and confirm explicit zero is replaced by the default.**

  ```powershell
  pytest -o addopts='' -q test/test_flow_qa_regressions.py -k numeric_accessors_preserve_zero
  ```

- [ ] **Step 3: Preserve zero by testing presence, not truthiness.**

  In `get_int` and `get_float`, distinguish `None`/missing from `0`. Convert non-string zero directly; leave current interpolation and conversion fallback behavior intact.

  ```python
  value = node_data.get(key)
  if value is None or value == "":
      return default
  ```

- [ ] **Step 4: Add a recording order client and failing Smart/Split propagation tests.**

  Extend `_RecordingClient` with `place_smart_order`, `split_order`, and `basket_order`. Execute LIMIT and SL nodes and assert exact `price`/`trigger_price` kwargs. Add cases where a runtime template resolves to zero and assert no client call and `status == "error"`.

- [ ] **Step 5: Run Smart/Split tests and confirm prices are currently absent from calls.**

  ```powershell
  pytest -o addopts='' -q test/test_flow_qa_regressions.py -k "smart_order_price or split_order_price"
  ```

- [ ] **Step 6: Read, validate, and send Smart/Split prices.**

  In both executors read `price` and `triggerPrice` using `get_float`, call `_invalid_price_reason`, return/log an error before the client call when invalid, and pass `price=price` plus `trigger_price=trigger_price` to the existing client method.

- [ ] **Step 7: Add failing Basket common/default precedence tests.**

  Cover CSV rows receiving common `product`, `priceType` as `pricetype`, `price`, and `triggerPrice` as `triggerprice`. Cover imported list-form rows where explicit per-leg values win and only absent values are filled. Assert invalid resolved common pricing or any invalid static/imported leg stops the entire basket before a broker call rather than silently skipping it.

  ```python
  assert sent[0] == {
      "symbol": "SBIN", "exchange": "NSE", "action": "BUY", "quantity": 2,
      "product": "MIS", "pricetype": "SL", "price": 625.0, "triggerprice": 624.0,
  }
  ```

- [ ] **Step 8: Run Basket tests and confirm common prices are currently omitted and list rows are passed through unfilled.**

  ```powershell
  pytest -o addopts='' -q test/test_flow_qa_regressions.py -k basket_order_price
  ```

- [ ] **Step 9: Implement Basket normalization and fail-closed pricing.**

  Build a new normalized order list rather than mutating `orders_raw`. CSV rows use all common values. List rows preserve existing `product`, `pricetype`/`priceType`, `price`, `triggerprice`/`triggerPrice`; common values fill only missing keys, then aliases normalize to the payload spelling accepted by `basket_order`. Resolve strings, validate quantity and prices, and return one indexed error on the first unusable row.

- [ ] **Step 10: Run all Task 3 tests and focused executor regressions.**

  ```powershell
  pytest -o addopts='' -q test/test_flow_qa_regressions.py -k "numeric_accessors_preserve_zero or smart_order_price or split_order_price or basket_order_price"
  pytest -o addopts='' -q test/test_flow_qa_regressions.py
  ruff check services/flow_executor_service.py test/test_flow_qa_regressions.py
  git diff --check
  ```

- [ ] **Step 11: Commit Task 3.**

  ```powershell
  git add services/flow_executor_service.py test/test_flow_qa_regressions.py
  git commit -m "fix(flow): propagate prices through order executors"
  ```

---

## Task 4: Implement all Variable operations and safe `floor()`

**Files:**

- Modify: `services/flow_executor_service.py`
- Modify: `test/test_flow_qa_regressions.py`

**Interfaces:**

- `execute_variable(node_data) -> {"status": "success", "variable": str, "value": Any}` on success.
- Errors return `{"status": "error", "message": str}` and do not mutate the target variable.
- `_safe_eval_math(expression) -> float` permits arithmetic plus direct one-argument `floor(...)` only.

- [ ] **Step 1: Add failing success-path Variable tests for all eleven operations.**

  Parametrize initial context, node data, and expected raw stored value. Include nested `get` paths (`portfolio.orders[1].price`), numeric operations stored as floats, valid JSON parsing, JSON stringification, append to an unset target, and the existing `set` JSON auto-parse behavior.

  ```python
  @pytest.mark.parametrize(
      ("operation", "initial", "data", "expected"),
      [
          ("subtract", {"x": 9}, {"value": "4"}, 5.0),
          ("multiply", {"x": 3}, {"value": "2.5"}, 7.5),
          ("divide", {"x": 9}, {"value": "2"}, 4.5),
          ("parse_json", {}, {"value": '{"ok": true}'}, {"ok": True}),
          ("append", {}, {"value": "done"}, "done"),
      ],
  )
  def test_variable_operation_success(operation, initial, data, expected):
      ...
  ```

- [ ] **Step 2: Run the success tests and confirm unimplemented operations return success without storing the expected value.**

  ```powershell
  pytest -o addopts='' -q test/test_flow_qa_regressions.py -k variable_operation_success
  ```

- [ ] **Step 3: Add failing error/no-mutation tests.**

  Cover unknown operation, missing `sourceVariable`, a missing dotted/indexed path, invalid numeric current/value, divide by zero, invalid JSON, and a non-JSON-serializable source. Seed the target with a sentinel and assert it is unchanged after each error.

- [ ] **Step 4: Run the error tests and confirm current execution either raises or falsely succeeds.**

  ```powershell
  pytest -o addopts='' -q test/test_flow_qa_regressions.py -k variable_operation_error
  ```

- [ ] **Step 5: Implement traversal and operation helpers.**

  Add a private raw-source lookup that distinguishes a missing variable from a stored `None`, then traverse optional dotted keys and bracketed integer indexes without using `eval`. Compute into a local `result`; call `set_variable` only after the operation succeeds. Catch `ValueError`, `TypeError`, `KeyError`, `IndexError`, `json.JSONDecodeError`, and serialization errors and return a precise error.

  Operation semantics must match the approved spec exactly:

  - `set`: interpolate then retain current JSON-looking auto-parse.
  - `get`: raw source plus optional `jsonPath`.
  - arithmetic: coerce current and value to floats.
  - `increment`/`decrement`: coerce current and change by one.
  - `parse_json`: `json.loads()` the interpolated string.
  - `stringify`: `json.dumps()` the raw source.
  - `append`: concatenate target and supplied values as text, using empty text for an unset target.

- [ ] **Step 6: Rerun all Variable tests and confirm errors do not mutate context.**

  ```powershell
  pytest -o addopts='' -q test/test_flow_qa_regressions.py -k "variable_operation_success or variable_operation_error"
  ```

- [ ] **Step 7: Add failing safe-math tests.**

  Assert `floor(3.9) == 3.0`, `floor(2 + 2.8) == 4.0`, and reject `ceil(1.1)`, `math.floor(2.2)`, `floor()`, `floor(1, 2)`, `floor(x=1)`, nested unknown calls, and import/system expressions.

- [ ] **Step 8: Run the math tests and confirm `floor` is currently rejected as `ast.Call`.**

  ```powershell
  pytest -o addopts='' -q test/test_flow_qa_regressions.py -k safe_math_floor
  ```

- [ ] **Step 9: Whitelist only direct `floor(expr)`.**

  In `_eval`, accept `ast.Call` only when `node.func` is `ast.Name(id="floor")`, there is exactly one positional argument, and `node.keywords` is empty. Evaluate the argument recursively and call `math.floor`; all other call shapes continue through a `ValueError`.

- [ ] **Step 10: Run Task 4 tests plus the full executor regression module.**

  ```powershell
  pytest -o addopts='' -q test/test_flow_qa_regressions.py -k "variable_operation or safe_math_floor"
  pytest -o addopts='' -q test/test_flow_qa_regressions.py
  ruff check services/flow_executor_service.py test/test_flow_qa_regressions.py
  git diff --check
  ```

- [ ] **Step 11: Commit Task 4.**

  ```powershell
  git add services/flow_executor_service.py test/test_flow_qa_regressions.py
  git commit -m "fix(flow): execute variable operations safely"
  ```

---

## Task 5: Align React order controls, defaults, and Flow types

**Files:**

- Create: `frontend/src/components/flow/panels/OrderPriceFields.tsx`
- Create: `frontend/src/components/flow/panels/OrderPriceFields.test.tsx`
- Modify: `frontend/src/components/flow/panels/ConfigPanel.tsx`
- Modify: `frontend/src/components/flow/panels/index.ts`
- Modify: `frontend/src/lib/flow/constants.ts`
- Modify: `frontend/src/types/flow.ts`

**Interfaces:**

- `OrderPriceFields` receives `priceType`, `price`, `triggerPrice`, and callbacks; it shows Price for `LIMIT`/`SL` and Trigger Price for `SL`/`SL-M`.
- SmartOrder, BasketOrder, and SplitOrder default `price` and `triggerPrice` to numeric zero.
- All relevant TypeScript order unions include `MARKET | LIMIT | SL | SL-M` where the backend supports them.

- [ ] **Step 1: Add the failing `OrderPriceFields` visibility test before its component exists.**

  Test MARKET shows neither numeric field; LIMIT shows only Price; SL shows both; SL-M shows only Trigger Price. Change the visible input and assert the corresponding callback receives a number.

  ```tsx
  it.each([
    ['MARKET', false, false],
    ['LIMIT', true, false],
    ['SL', true, true],
    ['SL-M', false, true],
  ] as const)('renders %s fields', (priceType, hasPrice, hasTrigger) => {
    render(<OrderPriceFields priceType={priceType} price={0} triggerPrice={0} onPriceChange={vi.fn()} onTriggerPriceChange={vi.fn()} />)
    expect(screen.queryByLabelText('Price')).toBe(hasPrice ? expect.anything() : null)
    expect(screen.queryByLabelText('Trigger Price')).toBe(hasTrigger ? expect.anything() : null)
  })
  ```

- [ ] **Step 2: Run the component test and confirm the missing module failure.**

  ```powershell
  Set-Location frontend
  npm run test:run -- src/components/flow/panels/OrderPriceFields.test.tsx
  Set-Location ..
  ```

- [ ] **Step 3: Implement and export `OrderPriceFields`.**

  Use existing `Label` and numeric `Input` primitives. Do not coerce an empty edit to an unintended positive value; persist `0` for empty/invalid numeric text so validator feedback remains authoritative. Export the component through `panels/index.ts`.

- [ ] **Step 4: Add failing default/type contract checks.**

  Extend `test_every_registered_node_has_default_data` or add a focused source/default parity test asserting SmartOrder, BasketOrder, and SplitOrder contain `price: 0` and `triggerPrice: 0`; Telegram defaults do not contain `username`; Options Multi leg types do not contain `expiryDate`. Run `npm run build` once to expose the currently narrow order-type unions.

- [ ] **Step 5: Run the default/type checks and confirm the current mismatches.**

  ```powershell
  $env:PYTEST_DISABLE_PLUGIN_AUTOLOAD='1'
  pytest -o addopts='' -q test/test_flow_workflow_validator.py -k frontend_order_defaults
  Set-Location frontend
  npm run build
  Set-Location ..
  ```

- [ ] **Step 6: Align Flow types and defaults.**

  Update:

  - `OptionsOrderNodeData.priceType` to all four price types and add `triggerPrice?: number`.
  - `OptionsMultiOrderNodeData` top-level price fields; remove leg `expiryDate`; define optional per-leg `product`, `priceType`, `price`, and `triggerPrice` for custom imports.
  - `BasketOrderNodeData` and `SplitOrderNodeData` to all four price types with optional `price` and `triggerPrice`.
  - `TelegramAlertNodeData` to remove `username`.
  - `DEFAULT_NODE_DATA.smartOrder`, `.basketOrder`, and `.splitOrder` with both numeric price defaults.

- [ ] **Step 7: Wire SmartOrder, BasketOrder, and SplitOrder panels to common price controls.**

  Keep their existing exchange/action/product/quantity fields. Ensure each has a Price Type select using `PRICE_TYPES`, followed by `OrderPriceFields`, and updates the exact `price`/`triggerPrice` keys. Remove the Telegram username input and its explanatory copy; retain only Message plus API-key ownership guidance.

- [ ] **Step 8: Constrain generated Options Multi UI without restricting custom imported legs.**

  When `strategy !== "custom"`, show only MARKET and LIMIT in the common Price Type select. Keep custom-leg data type support for SL/SL-M with per-leg price values; do not add a per-leg expiry input.

- [ ] **Step 9: Run frontend component, type, lint, and build checks.**

  ```powershell
  Set-Location frontend
  npm run test:run -- src/components/flow/panels/OrderPriceFields.test.tsx src/components/flow/panels/MarginPositionsFields.test.tsx
  npm run lint
  npm run build
  Set-Location ..
  $env:PYTEST_DISABLE_PLUGIN_AUTOLOAD='1'
  pytest -o addopts='' -q test/test_flow_workflow_validator.py -k "frontend_order_defaults or registry"
  git diff --check
  ```

- [ ] **Step 10: Commit Task 5.**

  ```powershell
  git add frontend/src/components/flow/panels/OrderPriceFields.tsx frontend/src/components/flow/panels/OrderPriceFields.test.tsx frontend/src/components/flow/panels/ConfigPanel.tsx frontend/src/components/flow/panels/index.ts frontend/src/lib/flow/constants.ts frontend/src/types/flow.ts test/test_flow_workflow_validator.py
  git commit -m "fix(flow): align order configuration controls"
  ```

---

## Task 6: Correct the import prompt and validate every parseable JSON fence

**Files:**

- Modify: `docs/prompt/flow-import-format.md`
- Modify: `test/test_flow_workflow_validator.py`

**Interfaces:**

- Every parseable fenced `json` block is decoded during the test.
- Full workflow examples pass `validate_workflow(..., strict=True)` with no errors.
- Standalone node snippets are wrapped with a valid Start node and edge; only the wrapper's expected `no_trigger` condition may be ignored when a snippet cannot be connected as a full workflow.

- [ ] **Step 1: Add the failing prompt JSON contract test.**

  Extract fenced JSON with a regex, `json.loads()` every fence containing one JSON value, and report the fence index/starting line on parse failure. Classify full workflow objects by `nodes`/`edges`; wrap individual node objects or arrays in a minimal workflow. Validate strictly and filter only `error["code"] == "no_trigger"` for documented standalone snippets. Do not suppress missing fields, invalid constants, price errors, or graph errors.

  ```python
  def test_every_parseable_prompt_json_example_matches_the_strict_contract():
      prompt = (ROOT / "docs/prompt/flow-import-format.md").read_text(encoding="utf-8")
      failures = []
      for line, raw in _json_fences(prompt):
          try:
              value = json.loads(raw)
          except json.JSONDecodeError:
              continue  # multi-object teaching fences are checked separately
          payload = _as_workflow_example(value)
          errors = [e for e in validate_workflow(payload) if e["code"] != "no_trigger"]
          if errors:
              failures.append((line, errors))
      assert failures == []
  ```

  Add an explicit assertion for the known multi-object teaching fences so a newly malformed single-object example cannot be hidden by the parse skip.

- [ ] **Step 2: Run the prompt test and record the current SmartOrder zero and HTTP timeout failures.**

  ```powershell
  $env:PYTEST_DISABLE_PLUGIN_AUTOLOAD='1'
  pytest -o addopts='' -q test/test_flow_workflow_validator.py -k prompt_json_example
  ```

- [ ] **Step 3: Correct trigger and data-node documentation.**

  Update the prompt to state strict validation rejects a second trigger. Document History `days` and explicit `startDate`/`endDate` precedence. Replace Holidays' nonexistent `exchange` with `year`; replace Timings' nonexistent `exchange` with `date`. Keep formats consistent with `docs/prompt/symbol-format.md` and `docs/prompt/order-constants.md`.

- [ ] **Step 4: Correct Variable, math, alert, and HTTP documentation.**

  Document all eleven Variable operations and their conditional fields/semantics. State `floor()` is the sole allowed function and other calls are rejected. Remove Telegram `username` from tables/examples and explain API-key-owned delivery. Change HTTP timeout examples from `10` to `10000` milliseconds.

- [ ] **Step 5: Correct options, price, P&L, and tradability examples.**

  Remove per-leg expiry and diagonal/calendar-spread claims. Document one common Options Multi expiry and MARKET/LIMIT restriction for generated strategies. Add common `price`/`triggerPrice` fields to SmartOrder, BasketOrder, and SplitOrder examples with the exact priced-order rules. Replace computed P&L `priceCondition` examples with `varCondition`. Replace any `placeOrder` on `NSE_INDEX`/`BSE_INDEX` with a tradable symbol/exchange pair while leaving index underlyings on option data/order nodes.

- [ ] **Step 6: Rerun the prompt validator and scan stale claims.**

  ```powershell
  pytest -o addopts='' -q test/test_flow_workflow_validator.py -k prompt_json_example
  rg -n 'silently ignored|days.*ignored|username|calendar spread|diagonal|"timeout": 10\b|priceCondition.*P&L|placeOrder.*NSE_INDEX' docs/prompt/flow-import-format.md
  ```

  Expected scan result: no stale contract claims. Legitimate historical wording, if any, must be inspected rather than blanket-suppressed.

- [ ] **Step 7: Run the complete validator and documentation-related checks.**

  ```powershell
  pytest -o addopts='' -q test/test_flow_workflow_validator.py
  ruff check services/flow_workflow_validator.py test/test_flow_workflow_validator.py
  git diff --check
  ```

- [ ] **Step 8: Commit Task 6.**

  ```powershell
  git add docs/prompt/flow-import-format.md test/test_flow_workflow_validator.py
  git commit -m "docs(flow): align import examples with runtime"
  ```

---

## Task 7: Cross-layer audit, full verification, and approved fast-forward delivery

**Files:**

- Review: `docs/superpowers/specs/2026-08-22-flow-contract-repair-design.md`
- Review: all files changed in Tasks 1-6
- Modify only if verification exposes an in-scope regression; add the reproducing test first.

- [ ] **Step 1: Audit every approved requirement against code and tests.**

  Use a checklist containing nested Indicator, SmartOrder zero, six priced nodes, Order Update Trigger, three expiry nodes, Margin, custom Options Multi legs, eleven Variable operations, safe `floor`, Telegram identity, React price controls, all prompt corrections, and JSON-fence validation. For each item record the exact test name that proves it. Do not mark an item complete based only on code inspection.

- [ ] **Step 2: Run the focused backend Flow suite from a clean process.**

  ```powershell
  $env:PYTEST_DISABLE_PLUGIN_AUTOLOAD='1'
  pytest -o addopts='' -q test/test_flow_workflow_validator.py test/test_flow_qa_regressions.py test/test_flow_market_hours.py
  ```

  Expected: all tests pass with only the existing three market-hours skips unless a test count changed because of the new coverage.

- [ ] **Step 3: Run Ruff on every changed Python file.**

  ```powershell
  ruff check services/flow_workflow_validator.py services/flow_executor_service.py test/test_flow_workflow_validator.py test/test_flow_qa_regressions.py
  ```

- [ ] **Step 4: Run the complete frontend test suite and production checks.**

  ```powershell
  Set-Location frontend
  npm run test:run
  npm run lint
  npm run build
  Set-Location ..
  ```

- [ ] **Step 5: Attempt the complete backend suite and separate baseline failures from regressions.**

  ```powershell
  $env:PYTEST_DISABLE_PLUGIN_AUTOLOAD='1'
  pytest -o addopts='' -q
  ```

  If collection still stops on missing `get_telegram_bot` and `eventlet`, compare the messages to the recorded baseline and report them verbatim as unrelated blockers. Any new Flow-related failure is in scope: write a focused reproducer, fix it, and rerun Steps 2-5.

- [ ] **Step 6: Inspect the final diff and repository state.**

  ```powershell
  git diff origin/main...HEAD --check
  git diff --stat origin/main...HEAD
  git status --short --branch
  git log --oneline --decorate origin/main..HEAD
  ```

  Confirm only the design, plan, Flow backend/tests, Flow frontend/tests, and prompt documentation are changed. Confirm no generated `dist`, coverage, cache, environment, secret, or database file is tracked.

- [ ] **Step 7: Commit any final in-scope verification correction.**

  Stage only the named corrected files and use:

  ```powershell
  git commit -m "test(flow): complete contract regression coverage"
  ```

  Skip this commit when the tree is already clean.

- [ ] **Step 8: Rebase/fast-forward against current remote main without touching the dirty original checkout.**

  ```powershell
  git fetch origin main
  git rebase origin/main
  ```

  If upstream changed an in-scope file, resolve in the clean worktree, rerun Steps 2-4, and inspect the resolution. If the rebase cannot be resolved without changing an unrelated user-owned area, stop and report the exact conflict instead of forcing it.

- [ ] **Step 9: Push the verified branch tip directly to `main` as approved.**

  ```powershell
  git push origin HEAD:main
  ```

  Do not use `--force`. If the server rejects a non-fast-forward update, fetch/rebase and repeat the verification affected by the new commits before trying again.

- [ ] **Step 10: Verify the remote result and report evidence.**

  ```powershell
  git fetch origin main
  git rev-parse HEAD
  git rev-parse origin/main
  git status --short --branch
  ```

  The two revisions must match. Final reporting must include the pushed commit, focused backend result, frontend test/lint/build results, Ruff result, full-suite result or the two unchanged baseline collection blockers, and confirmation that the original dirty checkout was left untouched.
