/**
 * The engine, on a thread of its own.
 *
 * **Why this file exists at all.** Folding a hundred thousand bars takes most
 * of a second, and the thread it would take it from is the one drawing a live
 * chart and a live price. On an ordinary page a slow function is a slow button;
 * on a trading terminal it stalls the things somebody is watching while they
 * wait. A run also starts on its own now when the instrument or the interval
 * changes, so the pause arrives without anybody pressing anything.
 *
 * **It is a worker and not a chunked loop for one reason: the engine is a
 * single call.** `backtest` walks every bar and folds the report before it
 * returns, with no yield point to hand back at, so nothing short of another
 * thread keeps the terminal drawing through it.
 *
 * **The engine is a pure function over data, which is what makes this safe.** It
 * reads bars and a compiled program and answers a record; it holds no state
 * between calls, touches nothing outside itself and has no dependency of its
 * own. So running it here rather than on the page cannot change an answer. That
 * is the same property the second engine in the Python host rests on, and it is
 * why this is a move rather than a reimplementation.
 *
 * **Everything crossing the boundary is plain data.** A compiled program is
 * JSON, bars are numbers, settings are values, and the report that comes back
 * is the same. Nothing here is a function, a class or a handle, so the
 * structured clone the browser does on the way across is total rather than
 * lossy. It is also a copy, which costs: at a hundred thousand bars the arrays
 * are a few megabytes each way. Measured against a second of frozen chart, the
 * copy is the cheaper of the two.
 *
 * **Built as a served file, deliberately.** This application's content security
 * policy allows scripts from its own origin and nothing else, so a worker built
 * from a blob URL or a data URL is refused by the browser. `new URL(...,
 * import.meta.url)` is the form the bundler recognises: it emits a real file
 * beside the rest of the build and the page loads it from its own origin.
 */

import type { BacktestMessage, BacktestReply } from './backtestWorkerProtocol'

/** How long a run may take before the page stops waiting for it. */
const PATIENCE_MS = 60_000

/**
 * Whether this environment can run one.
 *
 * Checked rather than assumed: the test environment has no `Worker`, and a
 * browser may have it behind a setting. A caller that cannot have one falls
 * back to running the engine inline, which is slower for the page and answers
 * exactly the same thing.
 */
export function workersAvailable(): boolean {
  return typeof Worker !== 'undefined' && typeof URL !== 'undefined'
}

/**
 * One run, on a worker, resolved with whatever the engine answered.
 *
 * **A worker per run, not one kept alive.** A run is rare, it is started again
 * whenever the instrument or the interval changes, and the previous one is
 * abandoned when it does. A pool would have to decide what to do with a run
 * nobody wants any more; terminating the worker is that decision, made once and
 * unambiguously, and it is the only way to actually stop an engine call that is
 * already walking bars. Starting one costs a few milliseconds against a run
 * measured in hundreds.
 *
 * Rejects rather than resolving on a failure, so a caller can tell "the engine
 * refused this run", which is an answer, from "the run never happened", which
 * is not. The caller's own fallback is what turns the second into a run on the
 * page instead.
 */
export function runOnWorker(
  message: BacktestMessage,
  signal?: AbortSignal
): Promise<BacktestReply> {
  return new Promise((resolve, reject) => {
    if (signal?.aborted) {
      reject(new Error('aborted'))
      return
    }

    let worker: Worker
    try {
      worker = new Worker(new URL('./backtestWorkerEntry.ts', import.meta.url), {
        type: 'module',
      })
    } catch (refused) {
      // A policy that will not load it, or an environment without them. The
      // caller runs the engine inline instead, which is the whole reason this
      // reports the failure rather than swallowing it.
      reject(refused instanceof Error ? refused : new Error('the worker could not be started'))
      return
    }

    let settled = false

    // One place that tears down, so no path can leave a worker running. A
    // worker the page has stopped listening to still holds a thread and the
    // few megabytes of bars that were copied into it.
    const finish = (act: () => void) => {
      if (settled) return
      settled = true
      window.clearTimeout(timer)
      signal?.removeEventListener('abort', onAbort)
      worker.terminate()
      act()
    }

    const onAbort = () => finish(() => reject(new Error('aborted')))

    const timer = window.setTimeout(
      () =>
        finish(() =>
          reject(new Error('the run did not finish in time'))
        ),
      PATIENCE_MS
    )

    worker.onmessage = (event: MessageEvent<BacktestReply>) => {
      finish(() => resolve(event.data))
    }

    // Fired when the worker script itself fails to load or throws at the top
    // level. Without this the promise never settles and the panel shows a run
    // that is running forever.
    worker.onerror = (event) => {
      finish(() => reject(new Error(event.message || 'the run could not be started')))
    }
    worker.onmessageerror = () => {
      finish(() => reject(new Error('the run could not be read back')))
    }

    signal?.addEventListener('abort', onAbort, { once: true })

    try {
      worker.postMessage(message)
    } catch (uncopyable) {
      // Something in the message could not be cloned. Worth reporting as a
      // failure to start rather than a refusal, because the same run inline
      // will work.
      finish(() =>
        reject(uncopyable instanceof Error ? uncopyable : new Error('the run could not be sent'))
      )
    }
  })
}
