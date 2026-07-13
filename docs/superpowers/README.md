# OpenAlgo Global-Market Architecture — Design Initiative

This folder holds the design work for evolving OpenAlgo from an
Indian-equity-centric platform into one that cleanly supports **all markets and
asset classes** (Indian equity/F&O, crypto derivatives & spot, US equities &
options, and any future venue) — **without breaking the ~200,000 existing users**
who depend on today's `/api/v1`, symbol format, and order constants.

> Status: **design / awaiting verification.** No implementation has started.
> The docs here are the "understand + design" deliverable that precedes any code.

## The four locked decisions

Every part of this design follows from four decisions made during brainstorming:

| # | Decision | Meaning |
|---|----------|---------|
| 1 | **Additive, zero breaks** | Existing symbol format & order constants (`CNC/NRML/MIS`, `SL/SL-M`) render **byte-identical**; `/api/v1` keeps **semantic JSON compatibility** (existing keys/values/types unchanged; responses may gain keys). All global capability is additive. |
| 2 | **In-tree brokers, formal contract** | Brokers live in `broker/{name}/`, contributed via PR, against an **in-repo `BrokerAdapter` contract** + a **unified registry** + a conformance suite. No out-of-tree/installable plugins ([ADR-0003](decisions/2026-07-13-in-tree-broker-model.md)). |
| 3 | **Model four, build two** | The domain model + contract are designed & paper-validated against **four** shapes (Indian F&O, crypto derivatives, crypto spot, US equity/options). Only **Indian + crypto-derivatives (Delta)** are wired up & tested **live** now. |
| 4 | **Normalized domain core** | A structured **five-axis** model (Venue · Market/Region · Segment · UnderlyingAssetClass · InstrumentKind → Instrument) sits *underneath* the flat symbol; the string becomes a *rendering* that is byte-identical for existing symbols. Cross-cutting concerns resolve from metadata, not hardcoding. |

## Documents

| Doc | What it covers |
|-----|----------------|
| [`problem/2026-07-13-challenges-and-solutions.md`](problem/2026-07-13-challenges-and-solutions.md) | **The why — read first.** Each current challenge paired with how the design overcomes it and where in the roadmap. |
| [`specs/2026-07-13-global-market-architecture-design.md`](specs/2026-07-13-global-market-architecture-design.md) | The full target architecture — the six design sections, principles, and best practices. **The how.** |
| [`audit/2026-07-13-sitewide-coupling-audit.md`](audit/2026-07-13-sitewide-coupling-audit.md) | The complete folder-by-folder audit of Indian-market coupling across the whole repo. |
| [`roadmap/2026-07-13-phased-roadmap.md`](roadmap/2026-07-13-phased-roadmap.md) | The P0–P7 phase plan; each phase becomes its own spec → plan → implementation cycle. |
| [`decisions/`](decisions/) | Architecture Decision Records (ADRs). **ADR-0003:** in-tree broker model (no out-of-tree plugins). **ADR-0002:** direct API/WebSocket integration, no vendor SDKs or aggregation libraries. **ADR-0001:** the crypto/CCXT instance of that rule. |
| [`reviews/`](reviews/) | External review responses — **three Codex rounds** (all findings verified & applied): #1 architecture corrections, #2 implementation-readiness, #3 post-ADR-0003 reconciliation + design gates. |
| [`audit/coupling_inventory.py`](audit/coupling_inventory.py) | Reproducible, commit-pinned coupling-count script (replaces ad-hoc greps). |

**Related reference (outside this folder):**
[`docs/prompt/crypto-symbol-format.md`](../prompt/crypto-symbol-format.md) — the
code-accurate crypto (Delta) symbol format, sibling to the Indian
`docs/prompt/symbol-format.md`.

## How this was produced

Via the `superpowers:brainstorming` flow: explore → clarifying questions →
approaches → section-by-section design (with a visual companion) → this write-up.
The next step after your review is `writing-plans` to turn **Phase P1** into a
detailed implementation plan.
