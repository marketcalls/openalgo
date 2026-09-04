/**
 * Turning a stored conversation back into the shape the thread renders.
 *
 * A reloaded conversation must look like the one that streamed, not like a
 * transcript of it. The backend records a turn with `_TurnRecorder` in
 * `blueprints/agent.py`, which puts the prose on `ag_message.content`, the tool
 * calls on `ag_message.tools`, and **everything else in one ordered sidecar on
 * `ag_message.notices`**, each entry keeping its own `type` discriminator:
 *
 * | stored entry | where it belongs on an AgentMessage |
 * | --- | --- |
 * | `{type: 'notice', level, message}` | one entry of `notices` |
 * | `{type: 'attachments', items}` | `attachments`, on the question that carried them |
 * | `{type: 'error', message, kind}` | one entry of `notices`, at error level |
 * | `{type: 'ui', content}` | one `openui` entry of `viz`, already accumulated |
 * | `{type: 'viz', kind, spec, title, source}` | one entry of `viz` |
 * | `{type: 'usage', ...}` | `usage` |
 * | `{type: 'confirm', run_id, session_id, requirements}` | `pending` |
 *
 * **Usage lives in that sidecar and nowhere else**, which is the whole reason
 * this file exists: read the row without unpacking it and a reloaded turn shows
 * no tokens and no cost, and the conversation total in the header silently
 * counts only what was sent since the page loaded.
 *
 * Three decisions that are not obvious:
 *
 * - **A stored chart renders after the prose, not inside it.** A live frame
 *   knows how much of the answer had been written when it arrived; the sidecar
 *   does not record that, and `_TurnRecorder` groups the viz entries together
 *   rather than interleaving them with the notices. Anchoring every stored
 *   chart at the end of the turn is the honest reading of what was kept, and
 *   guessing a position from the sidecar's order would put charts in places
 *   they were never drawn.
 * - **Only the last message may carry a pending confirmation.** Approving or
 *   rejecting a paused run resumes it, and the resumed run is persisted as its
 *   own message row, so a confirm entry with anything after it was already
 *   decided. Re-offering Approve on it would let the operator answer a question
 *   that has been answered.
 * - **Every field is read defensively.** `ag_message.notices` is free-form JSON
 *   written by whatever frame vocabulary was live when the turn ran, so an
 *   older row can be missing a field a newer renderer reads. A missing token
 *   count is zero and a missing cost is unknown, never a crash in the middle of
 *   a conversation the operator wanted to re-read.
 */

import type { ChatMessage, MessageNotice, NoticeLevel, ToolCall, UsageBilling } from '@/api/agent'
import type { AgentAttachmentMeta } from './attachments'
import {
  type AgentMessage,
  type AgentNotice,
  type AgentPendingConfirm,
  type AgentRole,
  type AgentUsage,
  createAgentMessage,
} from './useAgentStream'
import { type AgentVizItem, OPENUI_VIZ, openUiSpec } from './viz'

/** The levels `Message.tsx` has a style for. Anything else is read as info. */
const NOTICE_LEVELS: readonly NoticeLevel[] = ['info', 'warning', 'error']

/**
 * A count that is safe to add up.
 *
 * @param value - Whatever the stored frame carried in that position.
 * @returns The number, or 0 when the row has none.
 */
function toCount(value: unknown): number {
  return typeof value === 'number' && Number.isFinite(value) ? value : 0
}

/**
 * A measurement that is allowed to be unknown.
 *
 * @param value - Whatever the stored frame carried in that position.
 * @returns The number, or null. Null is rendered as unknown, never as zero.
 */
function toMeasure(value: unknown): number | null {
  return typeof value === 'number' && Number.isFinite(value) ? value : null
}

function toText(value: unknown): string {
  return typeof value === 'string' ? value : ''
}

function toLevel(value: unknown): NoticeLevel {
  return NOTICE_LEVELS.includes(value as NoticeLevel) ? (value as NoticeLevel) : 'info'
}

/**
 * Which billing path a stored turn took, when the row records one.
 *
 * Read strictly against the two known values rather than passed through, so a
 * row carrying anything else falls back to unknown and the badge says what it
 * always said. Guessing `subscription` from an unrecognised value would tell an
 * operator a turn was covered by a plan when nobody said it was.
 *
 * @param value - Whatever the stored frame carried in that position.
 * @returns The billing path, or undefined when the row predates the field.
 */
function toBilling(value: unknown): UsageBilling | undefined {
  return value === 'subscription' || value === 'metered' ? value : undefined
}

/**
 * The stored usage frame as the badge reads it.
 *
 * `cost_usd` stays null when the row has no price, because the backend reports
 * null for a model absent from LiteLLM's price table and a rendered $0.00 would
 * make an expensive turn look free.
 *
 * **`billing` has to be carried here, or a reloaded turn silently loses it.**
 * This function rebuilds the usage field by field rather than spreading the
 * stored entry, so a field it does not name does not survive the round trip. A
 * turn that ran on a ChatGPT plan would come back looking like a turn on a
 * model nobody has priced, which is a different and less honest statement.
 *
 * @param entry - The `usage` entry from a message's notices sidecar.
 * @returns The turn's usage.
 */
function toUsage(entry: Extract<MessageNotice, { type: 'usage' }>): AgentUsage {
  const billing = toBilling(entry.billing)
  return {
    input_tokens: toCount(entry.input_tokens),
    output_tokens: toCount(entry.output_tokens),
    total_tokens: toCount(entry.total_tokens),
    cached_tokens: toCount(entry.cached_tokens),
    reasoning_tokens: toCount(entry.reasoning_tokens),
    cost_usd: toMeasure(entry.cost_usd),
    model: typeof entry.model === 'string' ? entry.model : null,
    ttft_ms: toMeasure(entry.ttft_ms),
    // Omitted rather than set to undefined when the row has none, so an older
    // message hydrates to exactly the object shape it did before this existed.
    ...(billing ? { billing } : {}),
  }
}

/**
 * The tool calls of a stored turn, each already merged from its start and end.
 *
 * A call with no `ok` was still open when the turn ended, which is what the
 * timeline renders as unfinished rather than as failed.
 *
 * @param stored - The `tools` column, which is free-form JSON.
 * @returns One entry per call that carries an id.
 */
function toTools(stored: ChatMessage['tools']): ToolCall[] {
  if (!Array.isArray(stored)) return []
  const tools: ToolCall[] = []
  for (const entry of stored) {
    if (!entry) continue
    tools.push({
      id: toText(entry.id),
      name: toText(entry.name),
      args: entry.args ?? {},
      ok: typeof entry.ok === 'boolean' ? entry.ok : undefined,
      result: entry.result,
      duration: toMeasure(entry.duration),
    })
  }
  return tools
}

/**
 * One stored row as a thread message.
 *
 * @param row - The message as `GET /agent/api/conversations/<id>` returned it.
 * @param isLast - Whether this is the newest message in the conversation. Only
 *   the newest may re-offer a paused confirmation; see the module docstring.
 * @returns The message, in the same shape the live stream produces.
 */
function hydrateMessage(row: ChatMessage, isLast: boolean): AgentMessage {
  // 'system' and 'tool' are in the column's vocabulary but nothing writes them
  // today. Rendering an unexpected role as an assistant turn shows its content;
  // dropping it would lose the row without saying so.
  const role: AgentRole = row.role === 'user' ? 'user' : 'assistant'

  const content = toText(row.content)
  const notices: AgentNotice[] = []
  const attachments: AgentAttachmentMeta[] = []
  const viz: AgentVizItem[] = []
  let markup = ''
  let usage: AgentUsage | null = null
  let pending: AgentPendingConfirm | null = null

  for (const entry of row.notices ?? []) {
    if (!entry) continue
    switch (entry.type) {
      case 'notice':
        notices.push({ level: toLevel(entry.level), message: toText(entry.message) })
        break
      case 'attachments':
        // What the question carried. The bytes were never stored, so this
        // rebuilds the same labelled chips the composer showed and no image.
        for (const item of entry.items ?? []) {
          if (!item) continue
          attachments.push({
            name: toText(item.name),
            kind: item.kind === 'image' ? 'image' : 'text',
            mime: toText(item.mime),
            size: toCount(item.size),
          })
        }
        break
      case 'error':
        // The stream carries an error out of band; a stored one has nowhere
        // else to go, and losing it would leave a turn that stops mid-sentence
        // with no explanation of why.
        notices.push({ level: 'error', message: toText(entry.message) })
        break
      case 'ui':
        // The stored entry is the whole accumulated markup, not a delta, and
        // a turn keeps at most one. Concatenating rather than replacing costs
        // nothing and survives a row that somehow holds two.
        markup += toText(entry.content)
        break
      case 'viz':
        viz.push({
          kind: toText(entry.kind),
          spec:
            entry.spec && typeof entry.spec === 'object' && !Array.isArray(entry.spec)
              ? entry.spec
              : {},
          title: toText(entry.title),
          source: toText(entry.source),
          at: content.length,
        })
        break
      case 'usage':
        // A row holds at most one, and the last is the running total anyway.
        usage = toUsage(entry)
        break
      case 'confirm':
        pending = isLast
          ? {
              runId: toText(entry.run_id),
              sessionId: toText(entry.session_id),
              requirements: Array.isArray(entry.requirements) ? entry.requirements : [],
            }
          : null
        break
    }
  }

  if (markup) {
    // Last, so a turn that both drew a chart and composed markup keeps the
    // charts ahead of it, which is the order _TurnRecorder wrote them in.
    viz.push({
      kind: OPENUI_VIZ,
      spec: openUiSpec(markup),
      title: '',
      source: '',
      at: content.length,
    })
  }

  return createAgentMessage(role, content, {
    // Keyed on the row rather than on the hook's counter, so re-opening the
    // same conversation reuses React's nodes instead of remounting the thread.
    id: `stored-${row.id}`,
    tools: toTools(row.tools),
    attachments,
    notices,
    viz,
    usage,
    pending,
    streaming: false,
    runId: pending?.runId ?? null,
    sessionId: pending?.sessionId ?? null,
  })
}

/**
 * A stored conversation as the thread renders it.
 *
 * @param stored - The messages from `getConversation`, oldest first.
 * @returns The same turns as thread messages, oldest first, each carrying its
 *   tools, its notices and its usage.
 */
export function hydrateMessages(stored: readonly ChatMessage[] | undefined): AgentMessage[] {
  if (!Array.isArray(stored)) return []
  const last = stored.length - 1
  return stored.map((row, index) => hydrateMessage(row, index === last))
}
