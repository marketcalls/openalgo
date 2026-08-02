# PR-12a — What PR-12 missed in /python

**Status:** Done · **Tracker:** GT-A15-02/03/04 done; GT-A15-05/06/07 open · **Runs on:** both

An external audit reviewed PR-12 and found more. Every claim was reproduced
before being accepted; all of them held. Two were launch-blocking and neither
was anywhere near the registries PR-12 fixed.

## 1. Strategies were launched in a way Python documents as unsafe

`subprocess_args` set `preexec_fn=set_resource_limits`. `preexec_fn` runs in the
child between `fork()` and `exec()`, and the Python documentation is blunt about
it: *"not safe to use in the presence of threads. The child process could
deadlock before exec is called."*

Ours made that concrete rather than theoretical. `set_resource_limits()` called
`logger.debug()` and `logger.warning()`, and the logging module takes locks. If
any other thread held a logging lock at the moment of the fork, the child
inherited a locked lock that nobody would ever release. It would hang forever,
**before the strategy ran at all**, while the parent waited on a process that
was never going to start.

Under eventlet there are no real threads to hold that lock, so it could not
happen. Under gthread it can — and on the Windows and macOS dev servers, which
have always used real threads, it already could.

The limits now apply **in the child after exec**, via a small bootstrap that
reads them from the environment, sets them, and then runs the real strategy
file. Nothing is inherited from a forking thread, so the hazard is gone.

The bootstrap had to preserve how a strategy sees itself, or every
`if __name__ == "__main__":` would silently stop firing. Verified: `__name__` is
`__main__`, `__file__` is the strategy path, `sys.argv[0]` is the strategy path,
and the CPU limit is applied. The memory limit is applied on Linux (checked
inside the actual container: 512 MB) and refused by macOS, which rejects
`RLIMIT_AS` outright — the same behaviour as before, since the old code also
swallowed that failure.

## 2. Two saves could publish each other's half-written file

`save_configs()` wrote to **one shared temp path** and renamed it into place. The
rename is atomic; the write into a shared temp file is not. Two savers
interleaved their JSON in the same file, and whichever renamed second published
whatever the other had left there.

Now the whole read-serialise-write-rename is serialised, each writer gets its own
`mkstemp` file, and a failed save cleans its temp file up instead of leaving them
to accumulate next to the config on a worker that never restarts.

`PROCESS_LOCK` is held only long enough to serialise the dict — never across the
disk write. Holding it across the write would let a slow disk block a strategy
from starting, which is a worse bug than the one being fixed.

## 3. My own structural test had a blind spot

PR-12 added a check that no code iterates the live registry. All seven tests
passed. `/python/status` was iterating the live registry the whole time.

The check looked at `ast.For` nodes only. The offending code was a **list
comprehension**. A blind spot in a check is indistinguishable from a clean file —
this is now the fourth time in this migration that a green check was covering
nothing, so it is worth stating plainly rather than filing quietly.

The check now covers list, set, dict and generator comprehensions, and the
comprehension in question was fixed. Verified by reintroducing it: caught.

## 4. Initialization published itself before it was finished

`initialize_with_app_context()` set `_initialized = True` **first**, then restored
strategy state. A second thread arriving mid-restore saw the flag, returned
immediately, and served requests against half-restored state. The check-then-set
was itself racy — two threads could both pass the test before either set it.

Now serialised, and the flag is set **last, and only on success**, so a
concurrent caller blocks until restoration is genuinely done.

## 5. Shutdown could outrun the graceful timeout

`cleanup_on_exit()` held `PROCESS_LOCK` while stopping every strategy in turn.
`stop_strategy_process()` terminates a child and waits for it, so the lock was
held across every wait, blocking all other threads for the whole shutdown — and
the waits are sequential, so enough strategies could exceed Gunicorn's 30-second
graceful timeout and get the worker `SIGKILL`ed part-way through cleanup.

The registry is now snapshotted under the lock and the stopping happens outside
it, bounded to 20 seconds. On exhaustion it logs what it did not stop rather than
pretending to have finished; the OS reaps the rest with the worker, which is
strictly better than being killed mid-cleanup.

## How we know it works

`test/test_gthread_python_strategy.py` — **12 checks**, all passing.

Mutation-verified: reintroducing the comprehension is caught, and reinstating
`preexec_fn` is caught (structurally, so the comments explaining why it was
removed do not themselves trip the check).

## Still open, and deliberately not claimed

- **GT-A15-06 — lifecycle operations are still not atomic.** The accessors hand
  back shared mutable dicts, so start, stop, schedule, edit, delete and log
  cleanup can still interleave with each other. Fixing this properly needs a
  per-strategy lock or an explicit state machine. Widening the global lock
  instead would serialise the whole feature and put lock-holding back across
  process waits — trading a race for a stall.
- **GT-A15-07 — APScheduler jobs lack per-job DB session cleanup.** Under gthread
  each job runs on a real thread, and a `scoped_session` never removed holds a
  connection for the life of the worker.
- **GT-A15-05 — the gate still has the blind spots** that hid all of this: no
  name-based guards, no subscript mutation, and check-then-read not detected at
  all. Five unguarded sites remain elsewhere in the codebase.
