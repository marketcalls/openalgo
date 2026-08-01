# PR-10b — Close the open registry questions

**Status:** Done · **Tracker items:** GT-A12-04, GT-A12-08, GT-A12-09, GT-A14-03 · **Runs on:** the current eventlet setup

Four items had been carried as **"investigate"** — questions, not answers. They
are the reason classification coverage sat at 88% rather than higher. Each is
now settled with evidence: either the code was already right and the item
closes, or a real defect was found and fixed.

## The one that was a real bug

**Rotating your API key left a WebSocket connection open forever.**

Connections to the market-data proxy are kept in a shared list, looked up **by
API key**. Two problems followed from that:

**No way to remove just one.** The only cleanup available closed *every*
connection at once, which would disconnect every other consumer. So nothing
ever called it. When you regenerated your API key, a new connection was made
under the new key, and **the old one stayed open and in the list for the life of
the process** — unreachable, but still holding a socket. The production server
runs for weeks.

**A dead connection was handed out forever.** A new connection was only created
when the key was *absent* from the list. If the connection dropped, the entry
stayed, and every later caller received the dead connection with no attempt to
rebuild it.

Both are fixed. There is now a way to close a single key's connection; a
connection found to be dead is discarded and rebuilt; and API-key rotation now
closes the outgoing key's connection at the one moment the old key is still
known. That teardown can never block a rotation — if the socket cannot be
closed, or the old key cannot be decrypted after a security-key rotation, the
key still changes.

## Two that were already correct

**Order-update adapters.** Guarded by a lock, and removed on logout. No change —
closed with evidence rather than "looks fine".

**Historify job state.** Its running/paused job tables are covered by a
dedicated lock at every mutation. No change.

## One accepted as-is, with the reasoning written down

**The device-session limit.** Signing in checks "am I at the limit?" and, if so,
removes the oldest session. That *is* a check-then-act: several simultaneous
logins could each see the same count and each add a session, briefly exceeding
the limit.

We are leaving it, deliberately:

- it **self-corrects** — the next login trims again;
- it limits how many devices stay signed in; it is **not** a security boundary,
  and every session is still individually authenticated;
- OpenAlgo is single-user, so several simultaneous logins by the same person is
  close to unreachable in practice.

The important part is that this is now a **recorded decision** rather than an
unexamined gap, and there is a test pinning the mechanism so the reasoning gets
re-checked if anyone changes it.

## Note on one of my own tests

The first version of the session-limit test asserted the code "trims rather than
counts" — and passed, because it merely looked for a deletion in the source.
That was a shallow check that would have let me record the wrong conclusion: the
code *does* count first.

Rewritten to state what the code actually does and why that is acceptable. A
test that passes for a reason you did not intend is worse than one that fails,
because it launders a guess into an apparent fact.

## How we know it works

`test/test_gthread_registries.py` — **9 checks, all passing.**

Closing one connection removes **only** that entry and leaves other consumers
connected; removing an unknown key is a harmless no-op; a dead connection is
detected rather than served; rotation calls the teardown and can never raise;
and all registry access holds its lock.

Total suite: **132 checks passing.**
