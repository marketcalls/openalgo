# /python Strategy Resource Limits

Every strategy started from `/python` runs under four limits, so that one faulty script cannot take down OpenAlgo or the other strategies. This page says what each limit is, what happens when a strategy reaches it, and how to size a server.

Figures marked "measured" were taken in November 2026 on Linux (x86-64, Python 3.12, pandas 2.3.3, numpy 2.4.4), in the OpenAlgo Docker image and on a source install, with the limits set exactly as the host sets them.

## At a glance

| Limit | Value | Can it be changed | What happens at the limit |
|---|---|---|---|
| Memory (address space) | 1024 MB | Yes, `STRATEGY_MEMORY_LIMIT_MB` in `.env` | The strategy gets a `MemoryError` and exits. The error is in its log. |
| CPU time | 3600 CPU-seconds per run | No | The strategy is ended at once. Nothing is written to its log. |
| Open files | 256 | No | The strategy gets "Too many open files". |
| Processes and threads | 256, counted across the whole user | No | The strategy gets "can't start new thread". |

All four apply on Linux. None applies on Windows. For macOS see [Platform differences](#platform-differences).

OpenAlgo does not record why a strategy ended. See [When a strategy stops by itself](#when-a-strategy-stops-by-itself).

## How strategies are isolated

Each strategy runs as its own process, with its own memory, open files and CPU accounting. A crash in one strategy cannot directly affect another strategy or OpenAlgo itself.

The limits are set as the process starts and the strategy cannot raise them. They are the same under both web servers (eventlet and gthread) and on the development server.

Every start is a new process and a new log file, whether you press Start, the schedule starts it, or it resumes after a holiday. This matters for the CPU limit, which is counted per run.

## Memory

### The cap is on address space, not on RAM

`STRATEGY_MEMORY_LIMIT_MB` (default 1024) caps the address space a strategy may reserve (`RLIMIT_AS`, and `RLIMIT_DATA` with it). Address space is not the RAM in use. Libraries reserve far more than they touch, and every thread reserves more. A strategy can reach the cap while using a small part of it in RAM.

Measured, for a strategy that imports the `openalgo` SDK, holds an API client and builds a 500-candle DataFrame. Importing the SDK loads pandas and numpy, so every SDK strategy carries them.

| Numeric library threads | RAM in use | Address space reserved |
|---|---|---|
| 1 | 118 to 129 MB | 338 to 360 MB |
| 2 (the Docker image default) | 119 to 128 MB | 378 to 399 MB |
| 12 (the default on a 12-core source install) | 119 MB | 778 MB |

- Each extra Python thread, such as a WebSocket listener, reserved about 70 MB more address space and very little RAM. The first one reserved about 140 MB.
- A 50,000-candle DataFrame made no visible difference to either figure.
- A bare Python process uses 11 MB of RAM and 16 MB of address space.

"Numeric library threads" are the threads numpy starts for itself, one per CPU core unless told otherwise. See [Processes and threads](#processes-and-threads) for the settings that control them.

### The smallest cap that works

Measured in the Docker image, for the strategy above:

| Numeric library threads | Started under | Did not start under |
|---|---|---|
| 1 | 320 MB | 256 MB |
| 2 | 448 MB | 384 MB |

On the 12-core source install with the thread settings left alone, it started under 896 MB and did not start under 768 MB.

What follows from that:

- **256 MB is too low.** No strategy that imports the SDK starts under it. The log shows a `MemoryError` during the imports. Some Docker install scripts choose 256 MB on a small host: `docker-run.sh`, `docker-run.bat` and `install-docker.sh` on a host with less than 3 GB of RAM, and the `auto` profile of the multi-instance installer with less than 2 GB per instance. If your strategies fail this way, set `STRATEGY_MEMORY_LIMIT_MB = '512'` in `.env` and restart. A value in `.env` takes precedence over the one the script passed.
- **512 MB is the practical minimum.** In the Docker image it ran the same strategy with a WebSocket listener and two worker threads, with nothing to spare.
- **1024 MB, the default, suits most strategies.** On a machine with many cores, limit the numeric library threads, or the imports alone take most of it.
- **Raising the cap does not reserve RAM.** It is a ceiling per strategy. The multi-instance Docker installer's `unrestricted` profile sets it to 3072 MB for hosts that run large strategies.

### What happens at the cap

The allocation that would cross the cap fails, and Python raises `MemoryError` (numpy says "Unable to allocate"). Unless the strategy catches it, the strategy exits with the traceback in its log. Measured: a strategy asking numpy for 2 GB under the default cap exited with that message. The process is not killed by the cap itself.

A native library that cannot get memory may stop in its own way. OpenBLAS, which numpy uses, prints "Memory allocation still failed after 10 retries, giving up".

### How many strategies fit

RAM is what runs out, not the cap. Count about 130 MB of RAM for each strategy that uses the SDK, more if it holds large data or loads a model, and leave room for OpenAlgo itself: the web application, the WebSocket proxy and the broker feed. Check the real figures on your own server with the command under [Monitoring](#monitoring).

## CPU time

### The limit

Each run may use 3600 seconds of CPU time. It is a constant in `blueprints/python_strategy.py` (`STRATEGY_CPU_TIME_LIMIT_SEC`) and there is no setting for it.

- It counts CPU actually used, not elapsed time. A strategy that sleeps uses none. Measured: a loop using about 5 percent of a core for 25 seconds had used 1.3 seconds of its budget.
- It counts all the strategy's threads together. Measured: four busy threads used a 4-second budget in 1.1 seconds.
- It starts again from zero on every start, because every start is a new process.

### How long the budget lasts

| Average CPU use | Time until the limit |
|---|---|
| 1 percent of one core | 100 hours |
| 2 percent | 50 hours |
| 5 percent | 20 hours |
| 10 percent | 10 hours |
| 14 percent | 7 hours, the default 09:00 to 16:00 schedule |
| 25 percent | 4 hours |
| 100 percent, a loop that never sleeps | 1 hour |

- **A strategy on a daily schedule** is started and stopped each trading day, so it begins every session with a full budget. With the default 09:00 to 16:00 schedule it is safe as long as its average stays under about 14 percent of one core (under 7 percent for a 14-hour MCX day). A strategy that checks signals once a minute and sleeps in between uses a small fraction of that.
- **A strategy that runs without a stop time**, which is the default for a CRYPTO strategy, never gets a new budget. At an average of 2 percent it is ended after about two days. Give it a stop time and a start time a few minutes apart, so it restarts once a day, or keep its CPU use very low. A restart is a new process: the strategy has to pick up its open positions when it starts.
- **Heavy work does not belong in a live strategy.** Run a backtest, an optimisation or model training outside `/python`, or it spends the budget the live loop needs.

A strategy can watch its own budget. `time.process_time()` returns the CPU seconds the process has used so far, all threads included, so `3600 - time.process_time()` is what is left. Log it, or send yourself an alert when it runs low.

### What happens at the limit

The strategy is ended immediately. Measured: it receives no warning signal it can catch, it cannot clean up, and nothing is written to its log. The log simply stops. Its open positions and orders stay as they were.

## Open files

A strategy may hold 256 open files, sockets included. Measured: a strategy could open 253 more files after its standard input, output and error, and the next attempt raised `OSError: [Errno 24] Too many open files`, which the strategy can catch.

A strategy that has imported the SDK and opened nothing else holds 3. An HTTP connection and a WebSocket connection add a few. The limit only matters for a script that opens files or connections in a loop without closing them.

Each strategy has its own count, so one strategy's files do not count against another's. OpenAlgo itself keeps no file open for a running strategy: the log file is handed to the strategy when it starts.

## Processes and threads

The limit is 256, and on Linux it is not a count per strategy. It counts every thread of every process that runs under the same user ID as OpenAlgo: OpenAlgo itself (64 request threads under the gthread web server), the WebSocket proxy, every running strategy, and the numeric library threads inside each of them. Measured: with another process of the same user holding 200 threads, a strategy could start only 5 of its own.

The count is kept by the server's kernel, not per container. Every OpenAlgo container runs as user ID 1000, so several instances on one server share the one count, together with anything else on that server that runs as user ID 1000. Measured: 100 threads held inside one container left a strategy outside it, under the same user ID, able to start 81 threads instead of 209.

What reaching it looks like:

- `RuntimeError: can't start new thread` when the strategy starts a thread.
- A traceback ending in `KeyboardInterrupt` during `import numpy` or `import pandas`, right at startup. numpy's OpenBLAS could not start its threads.

numpy starts one thread per CPU core in every strategy that imports it, which is every strategy that uses the SDK. On a 12-core machine that is 12 threads per strategy before the strategy has done anything. Limit them in `.env`:

```
OPENBLAS_NUM_THREADS = '2'
OMP_NUM_THREADS = '2'
MKL_NUM_THREADS = '2'
NUMEXPR_NUM_THREADS = '2'
NUMBA_NUM_THREADS = '2'
```

The Docker image sets these to 2, the Docker install scripts set them from the host's RAM (1, 2, or up to 4), and the Ubuntu install script sets the first two to 2 for the service. An install started by hand with `uv run app.py` sets none, so add them yourself on a machine with many cores. They lower the address space each strategy reserves as well (see [Memory](#memory)). Strategies inherit them from OpenAlgo, so restart OpenAlgo after changing them.

## Logs

Each run writes its own file, `log/strategies/<strategy id>_<date>_<time>_IST.log`. Three settings bound what is kept for each strategy:

| Setting | Default | Purpose |
|---|---|---|
| `STRATEGY_LOG_MAX_FILES` | 10 | Most log files kept per strategy |
| `STRATEGY_LOG_MAX_SIZE_MB` | 50 | Most total log size per strategy |
| `STRATEGY_LOG_RETENTION_DAYS` | 7 | Logs older than this are deleted |

The clean-up runs when OpenAlgo stops a strategy, by the Stop button or by the schedule. It does not run when a strategy ends by itself, so those logs are trimmed at that strategy's next stop. The limits are per strategy: one strategy's logging cannot push out another's.

## When a strategy stops by itself

OpenAlgo checks every 60 seconds for strategies whose process has gone and marks them stopped. It does not record an exit code or a reason, and it does not restart them: a strategy on a schedule starts again at its next scheduled start, and any other stays stopped until you start it.

The last log file of the run is where the reason is, when there is one:

| The log ends with | Likely cause |
|---|---|
| `MemoryError`, "Unable to allocate", or the OpenBLAS memory message | The memory cap |
| Nothing: the log just stops | The CPU limit, or the server itself ran out of memory |
| "Too many open files" | The open files limit |
| "can't start new thread", or `KeyboardInterrupt` during an import | The process and thread limit |
| Any other traceback | An error in the strategy itself |

## Platform differences

| | Linux | macOS | Windows |
|---|---|---|---|
| Memory cap | Applied (measured) | Set, but reported not to be enforced by macOS | Not applied |
| CPU limit | Applied (measured) | Set, not measured | Not applied |
| Open files limit | Applied (measured) | Set, not measured | Not applied |
| Process and thread limit | Applied (measured) | Set, not measured | Not applied |
| Process isolation | New session | New session | New process group |

On Windows a strategy can use as much memory, CPU and as many files as the machine allows. Watch it in Task Manager.

On macOS OpenAlgo sets the same four limits. Nothing on this page was measured on macOS, and macOS is widely reported to ignore the memory cap, so treat memory as uncapped there.

## Settings

All of these go in `.env`. Restart OpenAlgo after changing one.

```
STRATEGY_MEMORY_LIMIT_MB = '1024'    # address space per strategy, see Memory
OPENBLAS_NUM_THREADS = '2'           # numeric library threads, see Processes and threads
STRATEGY_LOG_MAX_FILES = '10'
STRATEGY_LOG_MAX_SIZE_MB = '50'
STRATEGY_LOG_RETENTION_DAYS = '7'
```

The CPU, open files and process limits have no setting.

## Monitoring

The process ID of a running strategy is in the "Strategy started with PID" message when it starts, and in `strategies/strategy_configs.json`. On Linux:

```bash
ps -o pid,etime,time,rss,vsz,nlwp,comm -p <PID>
```

- `ELAPSED` is how long it has run, and `TIME` is the CPU time it has used, the figure the 3600-second limit counts.
- `RSS` is RAM in use and `VSZ` is address space reserved, both in KB. `VSZ` is the figure the memory cap counts.
- `NLWP` is its number of threads.

```bash
# Open files of one strategy
ls /proc/<PID>/fd | wc -l

# Threads of every process of the user OpenAlgo runs as (the figure the 256 limit counts)
ps -L -u <user> --no-headers | wc -l
```
