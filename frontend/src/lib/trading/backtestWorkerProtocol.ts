/**
 * What crosses between the page and the worker that runs the engine.
 *
 * Its own file because both sides import it and neither should import the
 * other: the worker must not pull in the page's module graph, and the page must
 * not pull in the worker's. A shared type file is the seam, and keeping the
 * seam explicit is what stops the two drifting into disagreement about a field.
 *
 * **Everything here is plain data on purpose.** The browser copies a message by
 * structured clone, which carries numbers, strings, plain objects and arrays
 * and silently refuses a function, a class instance or a handle. Every type
 * below is the first kind, so nothing is lost in the crossing.
 */

import type { InstrumentFacts } from 'openalgo-script'

/**
 * What the engine is told about the instrument beside the contract.
 *
 * The engine's own type, `DriveOptions.instrument`: the interval, the zone, the
 * session, the kind of instrument and whether it reports volume and open
 * interest. The six facts the contract holds cannot be written here, which the
 * compiler enforces, so the two can never state different tick sizes.
 */
export type RunInstrument = InstrumentFacts

/**
 * The diagnostic that stopped a run part way, as the trader is shown it.
 *
 * A run that fails on a bar is not a refusal: it happened, it stopped, and its
 * record carries what it did up to that bar and the code that stopped it. The
 * record keeps the code, the place in the script and the bar, and drops the
 * values that filled the catalogue's sentence, so what is shown is the
 * catalogue's title for the code and its advice where that advice names none of
 * the dropped values.
 */
export interface RunStop {
  code: string
  /** The catalogue's name for what went wrong, or empty for a code it does not hold. */
  title: string
  /** What to do about it, only where the catalogue's advice is complete without the dropped values. */
  fix: string | null
  /** Where in the script, 1-based. */
  line: number
  column: number
  /** The bar it stopped on, counted from the first bar fetched, 0-based. */
  barIndex: number | null
  /** That bar's open time, in the milliseconds the engine counts. */
  barTime: number | null
}

/** The run, as the page asks for it. */
export interface BacktestMessage {
  /** The compiled program, already parsed from its canonical text. */
  program: unknown
  /** The bars, already converted to the milliseconds the engine counts. */
  bars: readonly unknown[]
  /** The instrument facts the engine sizes and prices from. */
  contract: {
    currency: string
    symbol: string
    exchange: string
    tickSize: number
    lotSize: number
    pointValue: number
    digits: number
  }
  /** The script's own parameters, plain values as the engine reads them. */
  inputs: Record<string, unknown>
  /**
   * The interval, the zone, the session and the rest, stated beside the contract.
   *
   * Without it a script's session facts, its zoned dates and every daily or
   * weekly `req.timeframe` read are absent on every bar, which is a strategy
   * that never trades and a report that looks entirely normal.
   */
  instrument: RunInstrument
}

/**
 * What the worker answers, which is the engine's own outcome and nothing more.
 *
 * **The refusal is carried, not turned into a failure.** A run refused before
 * its first bar, a cost model stated twice, a quantity in a unit it cannot
 * size, is an answer about the run and reaches the trader as one. Rejecting the
 * promise instead would make it indistinguishable from the worker not starting,
 * and the caller falls back to running inline when that happens, which would
 * mean doing the whole refused run a second time to be told the same thing.
 */
export type BacktestReply =
  | {
      ok: true
      /** The report channels, exactly as the engine built them. */
      report: {
        summary: Record<string, unknown>
        trades: readonly Record<string, unknown>[]
        equity: readonly Record<string, unknown>[]
        markers: readonly Record<string, unknown>[]
      }
      /** How long the engine itself took, timed inside the worker. */
      ranMs: number
      /** The diagnostic that stopped the run on a bar, or null for a run that reached the last bar. */
      stopped: RunStop | null
    }
  | {
      ok: false
      /** The engine's own refusal, already written for a person to read. */
      code: string
      message: string
    }
