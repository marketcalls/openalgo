/**
 * The worker itself: take a run, fold it, answer it.
 *
 * **Deliberately almost empty.** Everything a backtest decides, which script,
 * which instrument, which range, what is refused and why, is decided on the
 * page before anything reaches here. This receives a program, bars, settings
 * and the instrument facts and hands them to `foldBacktest`, the same function
 * the page calls when there is no worker. A worker that made decisions would be
 * a second place they were made, reachable only through a message boundary and
 * testable only by starting a thread; a worker with its own copy of the engine
 * call is how the two threads came to state different facts to the engine.
 *
 * **It imports the engine and nothing else**, through `backtestFold`, which
 * imports nothing but the engine. No page module, no store, no client. A worker
 * has no DOM and no session, so an import that reached for one would fail at
 * load, and the failure would arrive as the run never starting rather than as
 * anything a reader could act on.
 *
 * Nothing here throws. A thrown error in a worker reaches the page as an
 * `error` event with a message the browser wrote, which is not something to put
 * in front of a trader. `foldBacktest` answers whatever happens as a reply the
 * page can read.
 */

import { foldBacktest } from './backtestFold'
import type { BacktestMessage } from './backtestWorkerProtocol'

self.onmessage = async (event: MessageEvent<BacktestMessage>) => {
  self.postMessage(await foldBacktest(event.data))
}
