/**
 * The indicator browser.
 *
 * It replaces a 264px dropdown that listed all 88 built-ins in one scrolling
 * column. At that length a dropdown is a scroll race: the category headings
 * were there, but you could not jump to one, and nothing remembered what you
 * reach for every day.
 *
 * The left rail is the filter. Every entry is backed by data this app actually
 * has: the four categories the engine tags its descriptors with, what is on
 * this chart right now, what you have starred, and what you added recently.
 * There is deliberately no author column, no popularity score, and no community
 * or store section -- this is a local registry of built-ins, nobody publishes
 * to it, and a column of blanks or a section that opens onto nothing would be
 * furniture pretending to be a feature.
 *
 * Favourites and recents are keyed globally rather than per pane: "my
 * indicators" is a property of the person, not of the pane they happen to have
 * clicked. Both degrade to empty if storage is unavailable rather than throwing
 * on the way into a dialog.
 */
import { useEffect, useMemo, useRef, useState } from 'react'
import { cn } from '@/lib/utils'

export interface CatalogEntry {
  id: string
  name: string
  category: string
}

interface Props {
  open: boolean
  /** Every registered indicator. Empty while the tier is still loading. */
  catalog: CatalogEntry[]
  /** What is on this chart right now, in the order the chart holds them. */
  active: { id: string; name: string }[]
  onAdd(indicatorId: string): void
  onRemove(instanceId: string): void
  onSettings(instanceId: string): void
  onClose(): void
}

const FAV_KEY = 'oa-trading-fav-indicators'
const RECENT_KEY = 'oa-trading-recent-indicators'
const RECENT_MAX = 8

function readIds(key: string): string[] {
  try {
    const raw = localStorage.getItem(key)
    const parsed = raw ? JSON.parse(raw) : []
    return Array.isArray(parsed) ? parsed.filter((x): x is string => typeof x === 'string') : []
  } catch {
    return []
  }
}

function writeIds(key: string, ids: string[]): void {
  try {
    localStorage.setItem(key, JSON.stringify(ids))
  } catch {
    /* private window, quota, storage disabled: the dialog still works */
  }
}

/** Record `id` as most recently used. Exported so the pane can call it too. */
export function noteRecentIndicator(id: string): void {
  const next = [id, ...readIds(RECENT_KEY).filter((x) => x !== id)].slice(0, RECENT_MAX)
  writeIds(RECENT_KEY, next)
}

type SectionId = 'active' | 'favourites' | 'recent' | 'all' | string

export function IndicatorPickerDialog({
  open,
  catalog,
  active,
  onAdd,
  onRemove,
  onSettings,
  onClose,
}: Props) {
  const [section, setSection] = useState<SectionId>('all')
  const [query, setQuery] = useState('')
  const [favourites, setFavourites] = useState<string[]>([])
  const [recent, setRecent] = useState<string[]>([])
  const searchRef = useRef<HTMLInputElement>(null)

  // Read storage on open, not on mount: another pane may have starred something
  // since this dialog was last closed.
  useEffect(() => {
    if (!open) return
    setFavourites(readIds(FAV_KEY))
    setRecent(readIds(RECENT_KEY))
    setQuery('')
    searchRef.current?.focus()
  }, [open])

  useEffect(() => {
    if (!open) return
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [open, onClose])

  /** Categories the registry actually uses, in descending size. */
  const categories = useMemo(() => {
    const counts = new Map<string, number>()
    for (const d of catalog) counts.set(d.category, (counts.get(d.category) ?? 0) + 1)
    return [...counts.entries()].sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]))
  }, [catalog])

  const byId = useMemo(() => new Map(catalog.map((d) => [d.id, d])), [catalog])
  const favSet = useMemo(() => new Set(favourites), [favourites])

  /**
   * The rows for the chosen section, always alphabetical -- except Recent,
   * whose whole point is its order.
   */
  const rows = useMemo(() => {
    const alpha = (list: CatalogEntry[]) => [...list].sort((a, b) => a.name.localeCompare(b.name))
    if (section === 'favourites') return alpha(favourites.map((id) => byId.get(id)).filter((d): d is CatalogEntry => !!d))
    if (section === 'recent') return recent.map((id) => byId.get(id)).filter((d): d is CatalogEntry => !!d)
    if (section === 'all') return alpha(catalog)
    return alpha(catalog.filter((d) => d.category === section))
  }, [section, catalog, favourites, recent, byId])

  const filter = query.trim().toLowerCase()
  const shown = useMemo(
    () => (filter ? rows.filter((d) => d.name.toLowerCase().includes(filter) || d.id.includes(filter)) : rows),
    [rows, filter]
  )

  if (!open) return null

  const toggleFavourite = (id: string) => {
    const next = favSet.has(id) ? favourites.filter((x) => x !== id) : [...favourites, id]
    setFavourites(next)
    writeIds(FAV_KEY, next)
  }

  const add = (id: string) => {
    noteRecentIndicator(id)
    setRecent(readIds(RECENT_KEY))
    onAdd(id)
  }

  const railRow = (id: SectionId, label: string, count: number) => (
    <button
      key={id}
      type="button"
      onClick={() => setSection(id)}
      // Spelt out, because the visible label and the count are separate
      // elements and concatenate to "Trend3" for a screen reader otherwise.
      aria-label={`${label}, ${count} indicators`}
      aria-pressed={section === id}
      className={cn(
        'flex w-full items-center justify-between gap-2 rounded px-2 py-1.5 text-left text-[13px] transition-colors',
        section === id ? 'bg-accent text-foreground' : 'text-muted-foreground hover:text-foreground'
      )}
    >
      <span className="truncate">{label}</span>
      <span className="shrink-0 text-[11px] tabular-nums opacity-60">{count}</span>
    </button>
  )

  const heading = (text: string) => (
    <div className="px-2 pb-1 pt-3 text-[10px] font-medium uppercase tracking-wider text-muted-foreground/70">
      {text}
    </div>
  )

  return (
    <div
      className="absolute inset-0 z-40 flex items-center justify-center bg-black/50"
      onMouseDown={(e) => e.target === e.currentTarget && onClose()}
      role="presentation"
    >
      <div className="flex h-[440px] max-h-[92%] w-[620px] max-w-[94%] flex-col rounded-lg border bg-popover shadow-2xl">
        <div className="flex shrink-0 items-center justify-between px-4 pb-2 pt-3">
          <h3 className="text-[15px] font-semibold tracking-tight">Indicators</h3>
          <button
            type="button"
            onClick={onClose}
            aria-label="Close"
            className="-mr-1 rounded p-1 text-muted-foreground transition-colors hover:bg-accent hover:text-foreground"
          >
            <svg
              viewBox="0 0 24 24"
              className="h-4 w-4"
              fill="none"
              stroke="currentColor"
              strokeWidth={1.8}
              strokeLinecap="round"
              aria-hidden="true"
            >
              <path d="M6 6l12 12M18 6L6 18" />
            </svg>
          </button>
        </div>

        <div className="shrink-0 px-4 pb-2">
          <div className="relative">
            <svg
              viewBox="0 0 24 24"
              className="pointer-events-none absolute left-2 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-muted-foreground"
              fill="none"
              stroke="currentColor"
              strokeWidth={1.8}
              strokeLinecap="round"
              aria-hidden="true"
            >
              <circle cx="11" cy="11" r="7" />
              <path d="m20 20-3.5-3.5" />
            </svg>
            <input
              ref={searchRef}
              type="text"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder={catalog.length ? `Search ${catalog.length} indicators` : 'Loading…'}
              aria-label="Search indicators"
              className="h-8 w-full rounded border bg-background pl-7 pr-2 text-[13px] outline-none transition-colors focus:border-primary"
            />
          </div>
        </div>

        <div className="flex min-h-0 flex-1 border-t">
          {/* Rail */}
          <div className="w-[168px] shrink-0 overflow-y-auto border-r px-2 pb-3">
            {heading('On this chart')}
            {railRow('active', 'Active', active.length)}
            {railRow('favourites', 'Favourites', favourites.length)}
            {railRow('recent', 'Recent', recent.length)}
            {heading('Library')}
            {railRow('all', 'All', catalog.length)}
            {categories.map(([cat, n]) => railRow(cat, cat, n))}
          </div>

          {/* List */}
          <div className="min-w-0 flex-1 overflow-y-auto px-2 pb-3">
            {section === 'active' ? (
              <ActiveList active={active} onRemove={onRemove} onSettings={onSettings} />
            ) : shown.length === 0 ? (
              <p className="px-2 py-6 text-center text-[13px] text-muted-foreground">
                {catalog.length === 0
                  ? 'Loading the indicator library…'
                  : filter
                    ? 'Nothing matches that.'
                    : section === 'favourites'
                      ? 'Star an indicator to keep it here.'
                      : 'Nothing here yet.'}
              </p>
            ) : (
              shown.map((d) => (
                <div
                  key={d.id}
                  className="group flex items-center gap-1 rounded px-1 hover:bg-accent/60"
                >
                  <button
                    type="button"
                    onClick={() => toggleFavourite(d.id)}
                    aria-label={favSet.has(d.id) ? `Unstar ${d.name}` : `Star ${d.name}`}
                    aria-pressed={favSet.has(d.id)}
                    className={cn(
                      'shrink-0 rounded p-1 transition-colors',
                      favSet.has(d.id)
                        ? 'text-primary'
                        : 'text-muted-foreground/40 hover:text-muted-foreground'
                    )}
                  >
                    <svg
                      viewBox="0 0 24 24"
                      className="h-3.5 w-3.5"
                      fill={favSet.has(d.id) ? 'currentColor' : 'none'}
                      stroke="currentColor"
                      strokeWidth={1.6}
                      strokeLinejoin="round"
                      aria-hidden="true"
                    >
                      <path d="m12 3.6 2.6 5.3 5.8.8-4.2 4.1 1 5.8-5.2-2.7-5.2 2.7 1-5.8L3.6 9.7l5.8-.8Z" />
                    </svg>
                  </button>
                  <button
                    type="button"
                    onClick={() => add(d.id)}
                    className="flex-1 truncate py-1.5 text-left text-[13px]"
                    title={`Add ${d.name}`}
                  >
                    {d.name}
                  </button>
                  <span className="shrink-0 pr-1 text-[10px] uppercase tracking-wide text-muted-foreground/60 opacity-0 transition-opacity group-hover:opacity-100">
                    {d.category}
                  </span>
                </div>
              ))
            )}
          </div>
        </div>
      </div>
    </div>
  )
}

/**
 * The Active section is a different thing from the library and says so: these
 * rows are instances, not descriptors, so they carry an instance id and offer
 * settings and remove rather than add. Two SMAs differ only by that id, which
 * is why the row cannot be keyed on the indicator.
 */
function ActiveList({
  active,
  onRemove,
  onSettings,
}: {
  active: { id: string; name: string }[]
  onRemove(id: string): void
  onSettings(id: string): void
}) {
  if (active.length === 0) {
    return (
      <p className="px-2 py-6 text-center text-[13px] text-muted-foreground">
        No indicators on this chart yet.
      </p>
    )
  }
  return (
    <>
      {active.map((i) => (
        <div key={i.id} className="flex items-center gap-2 rounded px-2 hover:bg-accent/60">
          <span className="flex-1 truncate py-1.5 text-[13px]">{i.name}</span>
          <button
            type="button"
            onClick={() => onSettings(i.id)}
            className="shrink-0 rounded px-1.5 py-0.5 text-[12px] text-primary transition-colors hover:bg-accent"
          >
            Settings
          </button>
          <button
            type="button"
            onClick={() => onRemove(i.id)}
            className="shrink-0 rounded px-1.5 py-0.5 text-[12px] text-muted-foreground transition-colors hover:bg-accent hover:text-foreground"
          >
            Remove
          </button>
        </div>
      ))}
    </>
  )
}
