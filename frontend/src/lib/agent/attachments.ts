/**
 * Files on their way into a turn.
 *
 * The wire shape is `services/agent/attachments.py`: each file travels as
 * `{name, mime, data}` inside the JSON body of `POST /agent/api/chat/stream`,
 * where `data` is base64 and may carry its own `data:` URL prefix. That is
 * exactly what `FileReader.readAsDataURL` produces, so a browser needs no
 * re-encoding step and this module does none.
 *
 * **The server decides what a file is; this module only counts.** The bytes are
 * sniffed there, against magic-byte signatures, and a declared type that
 * contradicts them is refused by name. Repeating that check here would be a
 * second sniffer to keep in step with the first, so the only rules kept on this
 * side are the caps, which are the ones worth enforcing before a 4 MB upload
 * rather than after it. The numbers below are mirrored from that module and a
 * comment there is what has to change if they move.
 *
 * Two decisions that are not obvious:
 *
 * - **`mime` is forwarded only when the server has a rule for it.** `file.type`
 *   is the operating system guessing from an extension, and it guesses things
 *   like `application/x-yaml` that the server reads as a declaration
 *   contradicting plain text. An omitted type means "the client does not know",
 *   which cannot contradict anything, so the bytes decide and the operator
 *   never sees a refusal about a type they did not choose. A type the server
 *   does act on, `image/jpeg` on a file that is really a PNG, is still passed
 *   through, because that mismatch is one worth reporting.
 *
 * - **No object URL is ever created, so there is none to revoke.** The data URL
 *   is already in hand for the request, and `<img src={dataUrl}>` renders from
 *   the same string. `URL.createObjectURL` would allocate a second handle per
 *   thumbnail whose lifetime nothing in a chat thread naturally ends, which is
 *   a leak that survives until the tab closes.
 */

/**
 * Files one turn may carry.
 *
 * This and the two size caps below mirror `MAX_ATTACHMENTS`,
 * `MAX_ATTACHMENT_BYTES` and `MAX_TOTAL_BYTES` in
 * `services/agent/attachments.py`. The server is the authority; these exist so
 * a refusal happens before the bytes are read rather than after they are sent.
 */
export const MAX_ATTACHMENTS = 4

/** Decoded bytes in one file. */
export const MAX_ATTACHMENT_BYTES = 4_000_000

/** Decoded bytes across one turn. */
export const MAX_TOTAL_BYTES = 8_000_000

/** What a file is, for an icon and for the vision question. */
export type AttachmentKind = 'image' | 'text'

/** One file the operator has attached but not yet sent. */
export interface AgentAttachment {
  /** Stable for the life of the chip, so React keys and removal agree. */
  id: string
  name: string
  kind: AttachmentKind
  /** The type the browser declared, or empty when it declared nothing. */
  mime: string
  size: number
  /** `data:<type>;base64,<...>` exactly as FileReader produced it. */
  dataUrl: string
}

/**
 * What a sent turn remembers about a file.
 *
 * The same fields `services/agent/attachments.stored_metadata` writes onto the
 * message row, so a live turn and a reloaded one render the same chips. The
 * bytes are deliberately absent from both: an image is orders of magnitude
 * larger than the text column it would sit in, and it is read in full every
 * time the conversation is opened.
 */
export interface AgentAttachmentMeta {
  name: string
  kind: AttachmentKind
  mime: string
  size: number
}

/** The payload one file becomes in the request body. */
export interface AttachmentPayload {
  name: string
  mime?: string
  data: string
}

/**
 * Media types the server has a rule for.
 *
 * Anything else is dropped from the request rather than sent, for the reason
 * in the module docstring. Mirrors `_IMAGE_SIGNATURES` and
 * `_TEXT_DECLARATIONS` in `services/agent/attachments.py`.
 */
const DECLARABLE: ReadonlySet<string> = new Set([
  'image/png',
  'image/jpeg',
  'image/jpg',
  'image/pjpeg',
  'image/gif',
  'image/webp',
  'text/plain',
  'text/csv',
  'text/markdown',
  'text/x-markdown',
  'text/tab-separated-values',
  'text/x-python',
  'text/xml',
  'text/html',
  'application/json',
  'application/x-ndjson',
  'application/xml',
  'application/csv',
])

/**
 * What the file dialog offers first.
 *
 * A hint rather than a gate: every operating system treats it differently and
 * a file can always be dragged in past it, which is why the server sniffs.
 */
export const ATTACHMENT_ACCEPT =
  'image/png,image/jpeg,image/gif,image/webp,.txt,.csv,.tsv,.md,.json,.py,.xml,.html,.log'

/**
 * Base64 prefixes of the image signatures the server accepts.
 *
 * This chooses a thumbnail, never an allow: a file is attachable because the
 * caps allow it, and it is an image because the server said so after reading
 * its bytes. Reading it from the encoded string rather than from `file.type`
 * means a screenshot pasted with no declared type still shows itself.
 */
const IMAGE_BASE64_PREFIXES = ['iVBORw0KGgo', '/9j/', 'R0lGODdh', 'R0lGODlh', 'UklGR']

let attachmentSeq = 0

/**
 * A size an operator can read.
 *
 * Decimal, because the server's refusals are decimal: it reports the per-file
 * cap as "4000 kB". Dividing by 1024 here would print 3.8 MB for the same
 * limit, and a browser and a server disagreeing about how big a file is
 * allowed to be is how a cap stops being believable.
 *
 * @param bytes - A byte count.
 * @returns The size as `900 kB` or `3.4 MB`.
 */
export function formatBytes(bytes: number): string {
  if (bytes < 1000) return `${Math.max(0, Math.round(bytes))} B`
  if (bytes < 1_000_000) return `${Math.round(bytes / 1000)} kB`
  return `${(bytes / 1_000_000).toFixed(1)} MB`
}

/**
 * What the attached files weigh.
 *
 * @param items - The files currently attached.
 * @returns Their total decoded size in bytes.
 */
export function attachmentTotal(items: readonly AgentAttachment[]): number {
  return items.reduce((sum, item) => sum + item.size, 0)
}

/**
 * Why this file cannot be added, or null when it can.
 *
 * Every message names the file and the number it broke, because "too large" on
 * its own leaves the operator guessing which file and by how much.
 *
 * @param items - What is already attached, including files added earlier in
 *   this same drop.
 * @param file - The candidate.
 * @returns The reason, written for the operator, or null.
 */
export function rejectReason(items: readonly AgentAttachment[], file: File): string | null {
  if (items.length >= MAX_ATTACHMENTS) {
    return `A message can carry ${MAX_ATTACHMENTS} files. ${file.name} would be one too many.`
  }
  if (file.size > MAX_ATTACHMENT_BYTES) {
    return `${file.name} is ${formatBytes(file.size)}, over the ${formatBytes(
      MAX_ATTACHMENT_BYTES
    )} limit for one file.`
  }
  if (attachmentTotal(items) + file.size > MAX_TOTAL_BYTES) {
    return `${file.name} would take this message over the ${formatBytes(
      MAX_TOTAL_BYTES
    )} limit for one turn.`
  }
  return null
}

/**
 * The name to show and send.
 *
 * Trimmed to what the server keeps, and stripped of anything path-like, so the
 * label in the composer is the label in the prompt. A browser does not hand out
 * a real path, but a dragged file from an archive tool can carry separators in
 * its name.
 *
 * @param name - The file's own name.
 * @returns A short, path-free label.
 */
function labelOf(name: string): string {
  const bare = name.split(/[\\/]/).pop() || 'file'
  return bare.slice(0, 120)
}

/**
 * Read one file into the shape the composer holds and the request sends.
 *
 * @param file - The picked, dropped or pasted file.
 * @returns The attachment, with its data URL.
 * @throws Error when the file cannot be read at all, which is a disk or
 *   permission failure rather than anything about its content.
 */
export function readAttachment(file: File): Promise<AgentAttachment> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader()
    reader.onerror = () => reject(new Error(`${labelOf(file.name)} could not be read.`))
    reader.onload = () => {
      const dataUrl = typeof reader.result === 'string' ? reader.result : ''
      if (!dataUrl) {
        reject(new Error(`${labelOf(file.name)} could not be read.`))
        return
      }
      attachmentSeq += 1
      const encoded = dataUrl.slice(dataUrl.indexOf(',') + 1)
      const mime = (file.type || '').split(';', 1)[0].trim().toLowerCase()
      resolve({
        id: `attachment-${attachmentSeq}`,
        name: labelOf(file.name),
        kind: IMAGE_BASE64_PREFIXES.some((prefix) => encoded.startsWith(prefix)) ? 'image' : 'text',
        mime,
        size: file.size,
        dataUrl,
      })
    }
    reader.readAsDataURL(file)
  })
}

/**
 * One attachment as the request body carries it.
 *
 * @param item - An attached file.
 * @returns Its `{name, mime, data}` entry, with `mime` omitted where the server
 *   has no rule for it. See the module docstring.
 */
export function attachmentPayload(item: AgentAttachment): AttachmentPayload {
  const payload: AttachmentPayload = { name: item.name, data: item.dataUrl }
  if (DECLARABLE.has(item.mime)) payload.mime = item.mime
  return payload
}

/**
 * One attachment as the sent message remembers it.
 *
 * @param item - An attached file.
 * @returns Its metadata, without the bytes.
 */
export function attachmentMeta(item: AgentAttachment): AgentAttachmentMeta {
  return { name: item.name, kind: item.kind, mime: item.mime, size: item.size }
}

/**
 * The files carried by a drop, a paste or a file input.
 *
 * A `DataTransfer` reports files two ways and neither is reliable alone: Chrome
 * fills `items` for a pasted screenshot and `files` for a dragged one, and a
 * directory drag produces an item with no file behind it at all.
 *
 * @param transfer - The event's `dataTransfer` or `clipboardData`.
 * @returns Every real file it carries, in order, with duplicates removed.
 */
export function filesFrom(transfer: DataTransfer | null | undefined): File[] {
  if (!transfer) return []
  const found: File[] = []
  // Array.from, not indexing: a FileList and a DataTransferItemList are
  // array-like rather than arrays, and neither has the methods of one.
  for (const file of Array.from<File>(transfer.files ?? [])) {
    if (file) found.push(file)
  }
  if (found.length > 0) return found
  for (const entry of Array.from<DataTransferItem>(transfer.items ?? [])) {
    if (entry?.kind !== 'file') continue
    const file = entry.getAsFile()
    if (file) found.push(file)
  }
  return found
}
