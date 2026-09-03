/**
 * What a `viz` frame becomes once the thread has folded it in.
 *
 * Three renderers draw for the agent, chosen by domain, and none of them is
 * new: candles go to `openalgo-charts`, the engine `/trading` already runs;
 * option analytics go to the shared `Plot2D` and `Plot3D` wrappers that
 * `/strategybuilder` and the option pages already use; everything else goes to
 * OpenUI. `kind` picks one, and **an unknown kind renders nothing**, so a
 * backend that learns a fourth cannot break a client that has not been
 * rebuilt.
 *
 * Provenance is why the split exists rather than being a style preference:
 *
 * - **`candles` and `plotly` are built by a tool**, from a `services/` call.
 *   The model asks for the chart and never supplies the numbers, so a price
 *   chart cannot show a candle the platform did not return. The payload also
 *   never enters the model's context: the tool answers with one line while the
 *   series travels on the frame, which is what makes charting five hundred
 *   candles almost free.
 * - **`openui` is markup the model composed**, so its numbers are whatever it
 *   typed. That tier carries the provenance rule in its prompt instead. See
 *   `openuiLibrary.ts`.
 *
 * **`spec` is carried through unvalidated and unwrapped, on purpose.** Each
 * renderer parses the payload it knows, in one place, and reports its own
 * "nothing to draw". A second validation here would be a copy of theirs, and a
 * copy drifts: the one that goes wrong is the one nobody is looking at. It is
 * also why the object's identity must survive a re-render untouched, which is
 * what stops `CandleViz` tearing its chart down and rebuilding it on every
 * streamed token.
 */

import type { VizFrame } from './stream'

/**
 * The kind an OpenUI block carries.
 *
 * It has no frame of its own on the wire: `ui` deltas are folded into an item
 * of this kind so all three renderers live in one ordered list, and the thread
 * needs no second code path for the one that streams.
 */
export const OPENUI_VIZ = 'openui'

/**
 * One visualization inside a turn, in the order it arrived.
 *
 * `at` is the length of the assistant's prose at the moment the frame landed,
 * which is what lets the thread put the chart back where the model drew it
 * instead of piling every chart at the end of the answer.
 */
export interface AgentVizItem {
  /** `candles`, `plotly`, `openui`, or a kind this client cannot draw. */
  kind: string
  /** The renderer's payload, straight off the wire. Never parsed here. */
  spec: Record<string, unknown>
  /** Heading shown above the chart. May be empty. */
  title: string
  /** The service the data came from, so provenance is never a guess. */
  source: string
  /** Offset into `AgentMessage.content` this block belongs after. */
  at: number
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}

function text(value: unknown): string {
  return typeof value === 'string' ? value : ''
}

/**
 * The OpenUI Lang markup accumulated so far.
 *
 * @param spec - The `spec` of an `openui` item.
 * @returns The whole accumulated string, which is what the renderer wants on
 *   every frame: its parser diffs internally and is O(new characters), so
 *   handing it the delta instead renders one fragment and loses the rest.
 */
export function openUiMarkup(spec: Record<string, unknown>): string {
  return text(spec.markup)
}

/**
 * Build the spec an `openui` item carries.
 *
 * @param markup - The accumulated OpenUI Lang markup.
 * @returns A spec in the same shape every other kind uses, so one list holds
 *   all three renderers. A **new object every time**, because growing markup
 *   is a changed payload and a renderer memoized on spec identity has to see
 *   that; a chart's spec never changes and so keeps its identity for the life
 *   of the turn.
 */
export function openUiSpec(markup: string): Record<string, unknown> {
  return { markup }
}

/**
 * A frame as the item the thread stores.
 *
 * @param frame - The `viz` frame, already parsed.
 * @param at - Length of the turn's prose when it arrived.
 * @returns The item. `spec` is the frame's own object, passed by reference.
 */
export function vizItemFromFrame(frame: VizFrame, at: number): AgentVizItem {
  return {
    kind: text(frame.kind),
    spec: isRecord(frame.spec) ? frame.spec : {},
    title: text(frame.title),
    source: text(frame.source),
    at,
  }
}
