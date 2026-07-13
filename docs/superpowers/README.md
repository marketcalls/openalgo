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
| 1 | **Additive, zero breaks** | Existing symbol format, order constants (`CNC/NRML/MIS`, `SL/SL-M`), and `/api/v1` request+response shapes stay **byte-identical**. All global capability is additive. |
| 2 | **Out-of-tree plugins** | Brokers become installable packages against a **versioned public `BrokerAdapter` contract**. *Requires a distributable contract package + a unified broker registry — the current core hard-codes broker dispatch in several spots, so this is real decoupling work, not just an entry-point loader (roadmap P1).* |
| 3 | **Model four, build two** | The domain model + contract are designed & paper-validated against **four** shapes (Indian F&O, crypto derivatives, crypto spot, US equity/options). Only **Indian + crypto-derivatives (Delta)** are wired up & tested **live** now. |
| 4 | **Normalized domain core** | A structured **five-axis** model (Venue · Market/Region · Segment · UnderlyingAssetClass · InstrumentKind → Instrument) sits *underneath* the flat symbol; the string becomes a *rendering* that is byte-identical for existing symbols. Cross-cutting concerns resolve from metadata, not hardcoding. |

## Documents

| Doc | What it covers |
|-----|----------------|
| [`problem/2026-07-13-challenges-and-solutions.md`](problem/2026-07-13-challenges-and-solutions.md) | **The why — read first.** Each current challenge paired with how the design overcomes it and where in the roadmap. |
| [`specs/2026-07-13-global-market-architecture-design.md`](specs/2026-07-13-global-market-architecture-design.md) | The full target architecture — the six design sections, principles, and best practices. **The how.** |
| [`audit/2026-07-13-sitewide-coupling-audit.md`](audit/2026-07-13-sitewide-coupling-audit.md) | The complete folder-by-folder audit of Indian-market coupling across the whole repo. |
| [`roadmap/2026-07-13-phased-roadmap.md`](roadmap/2026-07-13-phased-roadmap.md) | The P0–P7 phase plan; each phase becomes its own spec → plan → implementation cycle. |
| [`decisions/`](decisions/) | Architecture Decision Records (ADRs). **ADR-0002:** direct API/WebSocket integration, no vendor SDKs or aggregation libraries. **ADR-0001:** the crypto/CCXT instance of that rule. |
| [`reviews/`](reviews/) | External review responses. **2026-07-13 Codex review** — 10 findings verified, all confirmed; corrections applied across the design. |
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
