# Security policy

## Reporting a vulnerability

Report suspected vulnerabilities privately to
[rajandran@openalgo.in](mailto:rajandran@openalgo.in), or through GitHub's
[private vulnerability reporting](https://github.com/marketcalls/openalgo-charts/security/advisories/new)
for this repository. Please do not open a public issue for anything that could be exploited before
a fix exists.

Include what you need to make the report actionable: affected version, the tier or entry point,
a minimal reproduction, and the impact you believe it has. If you have a suggested fix, say so.

We aim to acknowledge a report within three working days and to give an initial assessment,
including whether we consider it in scope, within ten working days. Fix timelines depend on
severity and on whether the issue is in shipped runtime code or in build tooling.

## What is in scope

This package ships **zero runtime dependencies** and renders to a canvas in the browser. The
security surface is correspondingly narrow, and it is worth being precise about what that means.

In scope:

- anything in the published bundles that can be made to execute attacker-controlled code, read
  data it should not, or corrupt state that a host relies on for correctness;
- parsing of untrusted input: bar data, WebSocket frames, broker responses, saved chart state,
  clipboard payloads, and drawing state restored from storage;
- state restore paths, since a saved layout is attacker-controlled input if it can be shared;
- the build and release pipeline, which can affect published artifacts even though the runtime has
  no dependencies.

Out of scope, and important to state plainly because this library is used in trading systems:

- **The browser is not a trust boundary.** This is a presentation SDK. It is not the source of
  truth for identity, risk, orders, positions, or entitlements, and it cannot be made into one.
  A host that enforces a trading control only in this library has built the control in the wrong
  place. Server-side enforcement is the broker's responsibility.
- **Credentials held by the host.** The example adapters accept an API key so the demos can run
  against a local OpenAlgo instance. That pattern is for development. A production deployment must
  put a broker-owned backend between the browser and any trading credential. See the broker
  integration guidance in the documentation.
- Denial of service achieved by feeding the chart implausibly large data sets from the host's own
  code. The host controls its own inputs.
- Findings in the documentation website's dependency tree that do not affect the published package.

## Supported versions

Fixes land on the latest minor release. Older minors do not receive backports unless a broker
adoption depends on one and has agreed a support arrangement.

## Build and release integrity

The published package has no runtime dependencies, so the practical supply-chain risk is the
development toolchain rather than anything a consumer installs transitively.

- GitHub Actions are pinned by commit SHA rather than by tag, so a moved tag cannot silently
  change what CI runs. The human-readable tag is kept as a trailing comment.
- `npm audit` on the shipped runtime is expected to report zero vulnerabilities. Development
  advisories are tracked and either remediated or recorded as an accepted risk with a reason.
- Releases are cut from `master` with the version, tag, changelog entry, and npm publish in one
  step, and the tag is what the GitHub release points at.

If you find a way to influence a published artifact without a corresponding commit on `master`,
treat it as a high-severity report and use the private reporting channel above.
