/**
 * The one call into the engine a backtest makes, written once for both threads.
 *
 * **Why the worker and the page share this rather than each holding a copy.**
 * A run happens on a worker where there is one and on the page otherwise, and
 * the two used to be two copies of the same dozen lines. That is how the
 * instrument facts came to be missing from both: a fact added to one copy and
 * not the other is a backtest whose answer depends on which thread took it,
 * which nobody reading a report could ever tell. One function, imported by
 * both, cannot disagree with itself.
 *
 * **It imports the engine and nothing else**, for the reason the worker entry
 * gives: a worker has no DOM and no session, so a page module reached from here
 * would fail at load and the run would simply never start.
 *
 * Nothing here throws. Whatever happens is answered as a reply, because on the
 * worker a thrown error reaches the page as an `error` event with a message the
 * browser wrote.
 */

import type { RunRecord } from 'openalgo-script'
import type { BacktestMessage, BacktestReply, RunStop } from './backtestWorkerProtocol'

type Engine = typeof import('openalgo-script')

/** A catalogue slot, `{name}`, in the one syntax the catalogue declares. */
const SLOT = /\{[A-Za-z][A-Za-z0-9_]*\}/

/**
 * The diagnostic that stopped the run on a bar, or null when it reached the end.
 *
 * The engine stops at the first failure on a bar and records it, so the record
 * holds at most one, and it is the one that stopped the run. The record keeps
 * its code, its place and its bar and not the values that filled its sentence,
 * so the sentence is rebuilt from the catalogue: the title, which has no slots,
 * and the advice only where it has none either. A sentence with `{qty}` written
 * in it would read as the platform failing rather than the script.
 */
function stopOf(engine: Engine, record: RunRecord, bars: readonly unknown[]): RunStop | null {
  const all = Array.isArray(record.diagnostics) ? record.diagnostics : []
  const last = all[all.length - 1]
  if (last === undefined) return null

  const entry = engine.isDiagnosticCode(last.code) ? engine.entryFor(last.code) : undefined
  const bar =
    last.barIndex === null ? undefined : (bars[last.barIndex] as { time?: unknown } | undefined)
  const time = bar?.time

  return {
    code: last.code,
    title: entry?.title ?? '',
    fix: entry && !SLOT.test(entry.fix) ? entry.fix : null,
    line: last.line,
    column: last.column,
    barIndex: last.barIndex,
    barTime: typeof time === 'number' && Number.isFinite(time) ? time : null,
  }
}

/**
 * One run, on whichever thread called this.
 *
 * The instrument facts go in as `DriveOptions.instrument`, beside the contract
 * the money is priced under. That is where the engine reads the interval, the
 * zone and the session from, and a run without them has every session fact,
 * every zoned date and every daily read absent on every bar.
 */
export async function foldBacktest(message: BacktestMessage): Promise<BacktestReply> {
  try {
    const engine = await import('openalgo-script')

    const settings = engine.settingsFor(message.contract)
    // Cast at the one place the two type worlds meet. The panel builds these
    // through `settingsFromForm`, so what arrives is already the plain values
    // the engine resolves declarations against.
    const inputs = message.inputs as typeof settings.inputs

    const started = performance.now()
    const out = engine.backtest(
      message.program as Parameters<typeof engine.backtest>[0],
      message.bars as Parameters<typeof engine.backtest>[1],
      { ...settings, inputs },
      { instrument: message.instrument }
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
      // is exactly the channels the page reads. The record carries more, and
      // copying the rest would be paying the clone for data nobody uses.
      report: {
        summary: report.summary as unknown as Record<string, unknown>,
        trades: report.trades as unknown as Record<string, unknown>[],
        equity: report.equity as unknown as Record<string, unknown>[],
        markers: report.markers as unknown as Record<string, unknown>[],
      },
      stopped: stopOf(engine, out.record, message.bars),
    }
  } catch (failed) {
    return {
      ok: false,
      code: '',
      message: failed instanceof Error ? failed.message : 'The engine could not run this program.',
    }
  }
}
