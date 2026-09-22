/**
 * The worker itself: take a run, fold it, answer it.
 *
 * **Deliberately almost empty.** Everything a backtest decides, which script,
 * which instrument, which range, what is refused and why, is decided on the
 * page before anything reaches here. This receives a program, bars and
 * settings and calls the engine. A worker that made decisions would be a second
 * place they were made, reachable only through a message boundary and testable
 * only by starting a thread.
 *
 * **It imports the engine and nothing else.** No page module, no store, no
 * client. A worker has no DOM and no session, so an import that reached for one
 * would fail at load, and the failure would arrive as the run never starting
 * rather than as anything a reader could act on.
 *
 * Nothing here throws. A thrown error in a worker reaches the page as an
 * `error` event with a message the browser wrote, which is not something to put
 * in front of a trader. Whatever happens is answered as a reply the page can
 * read.
 */

import type { BacktestMessage, BacktestReply } from './backtestWorkerProtocol'

self.onmessage = async (event: MessageEvent<BacktestMessage>) => {
  const reply = await run(event.data)
  self.postMessage(reply)
}

async function run(request: BacktestMessage): Promise<BacktestReply> {
  try {
    const engine = await import('openalgo-script')

    const settings = engine.settingsFor(request.contract)
    // Cast at the one place the two type worlds meet, the same as the inline
    // path. The panel builds these through `settingsFromForm`, so what arrives
    // is already the plain values the engine resolves declarations against.
    const inputs = request.inputs as typeof settings.inputs

    const started = performance.now()
    const out = engine.backtest(
      request.program as Parameters<typeof engine.backtest>[0],
      request.bars as Parameters<typeof engine.backtest>[1],
      { ...settings, inputs },
      {}
    )
    const ranMs = performance.now() - started

    if (!out.ok) {
      return { ok: false, code: out.diagnostic.code, message: out.diagnostic.message }
    }

    const report = out.record.report
    return {
      ok: true,
      ranMs,
      // Rebuilt as a plain object rather than passed through, so what crosses
      // is exactly the four channels the page reads. The record carries more,
      // and copying the rest would be paying the clone for data nobody uses.
      report: {
        summary: report.summary as unknown as Record<string, unknown>,
        trades: report.trades as unknown as Record<string, unknown>[],
        equity: report.equity as unknown as Record<string, unknown>[],
        markers: report.markers as unknown as Record<string, unknown>[],
      },
    }
  } catch (failed) {
    return {
      ok: false,
      code: '',
      message: failed instanceof Error ? failed.message : 'the run could not be completed',
    }
  }
}
