# Blocker Register — Global-Market Architecture

**Last updated:** 2026-07-13 · **Living doc** — update in place as blockers move.
**Companion:** [roadmap](../roadmap/2026-07-13-phased-roadmap.md) ·
[reviews](../reviews/) · [spec](../specs/2026-07-13-global-market-architecture-design.md)

Legend: 🔴 open · 🟡 needs a decision · 🟢 resolved

## Verdict at a glance

- **Start P0A: not blocked** (its doc-consistency sub-task is already done).
- **Start P1 implementation: blocked** by B1–B4 below.
- After three Codex review rounds there are **no surprise blockers** — all
  remaining ones are known, scoped, and expected pre-implementation work.

## Active blockers (dependency order)

### 🔴 B1 — P0A inventory & surface enumeration not done
- **Blocks:** P1 (true scope unknown until this exists).
- **Detail:** doc-consistency is complete, but the *real* AST/schema coupling
  inventory and the full enumeration of the 34 adapters + every order-entry
  surface are not. Today's `audit/coupling_inventory.py` scans only 9 directories
  for token coupling.
- **Cleared by:** P0A.

### 🔴 B2 — P0B compatibility & migration foundation missing  *(highest priority)*
- **Blocks:** the "zero breaks" guarantee, and everything that changes schema (P2+).
- **Detail:** CI has no golden tests; migrations are a hardcoded central list
  (`upgrade/migrate_all.py`); **`start.sh:291` continues after a migration failure**
  (`… || echo "completed"`). Until fail-stop migrations + golden fixtures + old-DB
  tests exist, additive-zero-breaks is unenforceable.
- **Cleared by:** P0B.

### 🔴 B3 — `SymToken` schema ownership undecided
- **Blocks:** P2 (cannot add columns / Decimal precision).
- **Detail:** 34 `class SymToken` definitions in `broker/` + 1 shared
  (`database/symbol.py`) + the `token_db_enhanced` cache. Ownership model (shared
  base/mixin vs per-broker), centralized migration, downloader compatibility, and
  cache serialization must be decided first.
- **Cleared by:** P2 prerequisite (or a P2A slice — see D1).

### 🔴 B4 — the four design gates are scoped but not yet designed
- **Blocks:** P1 implementation (not P0A).
- **Detail:** (a) manifest `capability_scopes` JSON Schema; (b) registry bootstrap
  + pre-auth `BrokerDescriptor`; (c) operation matrix; (d) idempotency ledger.
  Captured as P1/P0B/P2 deliverables; detailed design still to be produced in those
  phase specs.
- **Cleared by:** P1 (with P0B for migration bits).

### 🔴 B5 — sandbox replatform  *(downstream, not immediate)*
- **Blocks:** crypto sandbox.
- **Detail:** integer quantity / `DECIMAL(10,2)` / no-partial-fills /
  single-INR-account (`database/sandbox_db.py`); schema + execution changes.
- **Cleared by:** P5 (depends on P2+P3+P4).

## Owner decisions (🟡 needs your call)

### 🟡 D1 — precision sequencing (P1.5 ↔ P2 boundary)
Narrow **P1.5 to Decimal DTOs only** and defer persisted precision to P2, **or**
insert a **P2A** (schema-ownership + precision-migration) slice *before* P1.5.
- **Recommendation:** the P2A slice — cleaner than proving Delta on DTOs you then
  re-migrate.
- **Impacts:** the P1.5/P2 boundary and B3's timing.

## Resolved (kept for history)

### 🟢 R1 — out-of-tree plugins not feasible → **dissolved**
Superseded by [ADR-0003](../decisions/2026-07-13-in-tree-broker-model.md):
brokers are in-tree (PR-contributed). `packages = []` is a non-issue; the unified
registry remains, but purely for internal decoupling.

### 🟢 R2 — design docs internally inconsistent → **fixed**
All stale statements reconciled in review-3
([response](../reviews/2026-07-13-codex-review-3-response.md)); P0A's
"no doc contradicts the spec" criterion is met.

## Critical path

**Finish P0A (inventory) → build P0B (safety foundation) → decide `SymToken`
ownership (B3/D1) → design the four gates in P1 → P1.5 Delta → P2 …**
