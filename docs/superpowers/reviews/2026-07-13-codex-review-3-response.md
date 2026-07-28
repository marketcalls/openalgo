# Review Response 3 — Codex re-audit after ADR-0003 (2026-07-13)

Codex confirmed the in-tree switch (ADR-0003) closes the packaging/entry-point
blocker and the revised design is "substantially better," with the verdict:
**P0A ready to begin; P0A not yet complete; not safe to start P1 implementation
yet.** Remaining work = document reconciliation + four design gates. All findings
verified against the docs/code and addressed below.

## 1. P0A documentation consistency — **fixed**

| Stale statement | Fix |
|---|---|
| README promised byte-identical `/api/v1` responses | → semantic JSON compatibility (byte-identity only for symbols) |
| Problem doc: third party can "ship" a broker | → **in-tree via PR** (ADR-0003) |
| Audit: "every top-level folder" swept | → noted the script scans 9 dirs; P0A expands |
| Audit: frontend 85, shim "33 brokers", sandbox "mostly wiring" | → 58; "34 = 33 Indian + Delta"; **replatform** |
| Spec risk: Delta cleanup "P7" | → **P1.5** |
| Review-2 tail: out-of-tree P7 | → second-venue **in-tree** proof |
| Spec §4: currency/tz/margin "hang on Market/Region" | → *default anchor*; each resolves on its own key |

## 2–7 + smaller — design gates, now scoped

| # | Gate | Resolution |
|---|------|-----------|
| 2 | P1.5 needs P2 storage | P1.5 narrowed to **Decimal at DTO/runtime**; **persisted** `SymToken` precision explicitly deferred to P2 (or a P2A slice ahead of P1.5). Cross-phase invariant now excepts the Delta refactor. |
| 3 | Manifest can't describe a real Indian broker | Manifest rewritten to **`capability_scopes`** with `(venue, segment, instrument_kinds)` selectors + scoped overrides for currency/rate-limits/history-intervals/depth/streaming; top-level `base_currency` retired; versioned JSON Schema. |
| 4 | Registry bootstrap under-specified | P1 now lists the decisions: Python-vs-`plugin.json` authority, static-vs-discovery, **lazy-load only the configured broker** (never import all 34), health on import/config failure, and a **pre-auth `BrokerDescriptor`** (public form/login metadata; secrets private). |
| 5 | Required-vs-optional ambiguous; idempotency over-promised | P1 delivers an **operation matrix** (required-always / required-when-declared / optional-experimental / expected-unsupported / shim-emulatable / conformance-fixture). Idempotency reworded to an **adapter-side ledger + request fingerprint + reconciliation + `unknown_execution_state`** (not "never duplicates"). |
| 6 | Migration terms reflect plugins | P0B: **broker-owned migration registration** (file/convention-based, precedes the registry); per-file transaction boundaries, checkpoint/resume, checksum ownership, backup/restore, dual-read/write for Float→Decimal. |
| 7 | Fractional-qty migrations too late | `strategy_db` + `chartink_db` Integer→Decimal **moved from P5 to P3** (live order-entry persistence). P5 keeps sandbox-only. |
| — | Delta gets auto-Indian manifest | Shim auto-generates Indian manifests for the **33 Indian** brokers only; **Delta authors its own crypto manifest**. |
| — | Compat tests too narrow | P0B fixtures now include official **Python/Node clients, webhooks, error status/message, strict decoders**. |

## Readiness

- **P0A doc-consistency:** complete (no doc contradicts the spec).
- **The four design gates** (manifest scoping · registry bootstrap · precision
  sequencing · operation matrix) are captured as explicit **P1/P0B/P2**
  deliverables — to be *designed* in those phase specs, not pre-solved here.
- **Start P1 implementation:** still no — P0A must first produce the real
  AST/schema inventory + order-surface enumeration, and P0B the migration
  foundation + golden fixtures. That is the correct next work.
