---
name: verify
description: Verify a claim before stating it, and verify a test before trusting it. Use before asserting that a security control holds, that a pattern is safe, that a bug is fixed, or that a test guards a fix. Also use when reporting audit or scanner findings, when a grep "found nothing", when a lint or test count looks clean, and before telling a user that something is or is not a vulnerability.
---

# Verify before claiming

Every high-severity finding this repo has produced came from executing
something. Every wrong claim came from reading something and reasoning about it.

The rules below are cheap. Skipping them is what produces a confident, wrong
answer that a maintainer then acts on.

## Rule 1 - execute the pattern, never read it

A regex, a redaction filter, a permission mask or a capability gate is code.
Run it against a realistic value and look at the output.

**What happens when you don't.** `utils/logging.py` redacts key-value shapes.
Reading the pattern suggested `"Feed Token: {t}"` leaked, so nine call sites
were reported as leaks. Executing it showed the alternation contains a bare
`token`, which matches `Token:` and redacts the value. The finding was wrong in
the direction that wastes a maintainer's time.

The same run showed `"Access Token obtained: {t}"` genuinely leaks, because a
word sits between the keyword and the colon. Neither result was predictable by
inspection.

```bash
uv run python .claude/skills/verify/redaction_check.py \
  "Access Token obtained: {t}" "eyJhbGciOiJIUzI1NiJ9.SEKRET.sig"
```

Prints `LEAKS` or `redact` and exits non-zero when the secret survives, so it
drops into a loop or a test.

**Corollary: whether a log line leaks depends on data you have not read yet.**
`?susertoken=` and `?token=` redact; `?Value1=` and `?jKey=` do not. You cannot
judge a logged URL without opening the code that builds it and learning the real
parameter name.

## Rule 2 - break the code to validate the test

A test that passes proves nothing until you have seen it fail. Revert the fix,
or neuter the guard it depends on, and confirm the test goes red. Then restore.

**What happens when you don't.** A `StrategyBuilder` test asserted a tile was
absent after an identity reset. It passed. It also passed against the exact bug
it was written to catch, because the assertion raced a 400ms debounce that
legitimately re-rendered the tile.

Two ways this goes wrong, both seen here:

- **Tautological assertion.** The test re-implements the predicate inline
  (`is_stale = qty != 0 and updated_at < boundary`) instead of calling the
  function under test. It is then testing Python's `<` operator.
- **Vacuous pass.** The assertion is true for a reason unrelated to the fix, so
  it holds whether or not the fix is present.

When disabling a guard to prove a test, target the exact line. A blind
`replace(..., 1)` hits the first match, which may be a different, pre-existing
guard, and then the "proof" proves nothing.

## Rule 3 - grep for the sink, not the variable name

A grep that returns nothing is not evidence of absence. It is evidence about
your pattern.

**What happens when you don't.** Searching `broker/` for credential variable
names inside f-strings found and fixed the direct cases. It was structurally
incapable of seeing the larger class, where the secret rides inside something
else that gets logged:

- a URL assembled with the token in the query string
- an auth request or response body
- a headers dict
- an exception message (`httpx.HTTPStatusError` embeds the full URL, so a
  credential in the URL *path* leaked on every 4xx, exactly the wrong-credential
  case)

Before concluding a class is clear, ask what a leak would look like if the
secret were never named in the log statement, then search for that.

## Rule 4 - baseline before and after

A tool's output is meaningless without its prior value. Capture the count on
`HEAD`, apply the change, capture it again.

```bash
uv run ruff check <paths> | grep -oE "Found [0-9]+ errors"
git stash -q && uv run ruff check <paths> | grep -oE "Found [0-9]+ errors"; git stash pop -q
```

Two traps specific to this repo:

- **`F401` is in the ruff ignore list** (`pyproject.toml`). An orphaned
  `import logging` will not be flagged. Verify unused imports by grep.
- **Windows checkouts fail Biome on CRLF.** Every `.tsx` reports a format error,
  including files you never touched. Run the check on an untouched file first to
  establish that the error is environmental.

## Rule 5 - distinguish "already safe" from "fixed"

Reporting a safe site as fixed inflates the apparent severity of your work and
teaches the reader that the report cannot be trusted.

Of seven sites reported as leaking WebSocket URLs, two leaked and five were
already redacted. The fix touched the two. The other five were left alone and
named as false positives in the review. Churning them would have produced a
diff that looked like a fix and taught nobody anything.

State plainly which of the reported items were real. When a scanner is the
source, expect false positives and triage each one:

- A substring check can match the documentation that warns against the defect.
  The `NullPool` check failed on `engine_factory.py`'s own docstring.
- A decorator check misses an inline guard. Routes calling `is_session_valid()`
  in the function body read as unprotected.
- POSIX permission bits are synthesized on Windows. Every file reports `0o666`.

## Rule 6 - an unrun check is not a pass

If a tool times out, is not installed, or is skipped, say so and treat the area
as unverified. `detect-secrets` timing out means secret scanning did not happen,
regardless of the exit code of the run that contained it.

## When you are wrong

Correct it in one plain sentence with the evidence, and carry on. A wrong claim
that gets quietly dropped is worse than one that gets corrected, because the
maintainer may already have acted on it.
