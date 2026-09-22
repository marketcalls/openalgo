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
    }
  | {
      ok: false
      /** The engine's own refusal, already written for a person to read. */
      code: string
      message: string
    }
