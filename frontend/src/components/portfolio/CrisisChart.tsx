/**
 * Crisis periods: when each one ran, how long it lasted, and what it cost.
 *
 * Three things have to be legible at once — *when*, *how long*, and *how bad* —
 * and a bar chart alone only carries the third. So each row pairs a timeline
 * band, positioned and sized by the actual dates, with the return bars beside
 * it. A one-week shock and a nine-month grind are different experiences even at
 * identical drawdown, and the timeline is what shows that.
 *
 * Both bars are labelled. Labelling only the portfolio made a row read as
 * "-7.5%" when the story was the gap to a benchmark that fell twice as far.
 */
interface CrisisPeriod {
  key: string
  label: string
  note?: string
  start: string
  end: string
  scope?: 'india' | 'global'
  days?: number
  sessions?: number
  portfolio: number | null
  benchmark: number | null
  excess: number | null
  partial?: boolean
}

interface Props {
  periods: CrisisPeriod[]
}

const fmtDate = (iso: string) =>
  new Date(`${iso}T00:00:00Z`).toLocaleDateString('en-GB', {
    day: '2-digit',
    month: 'short',
    year: '2-digit',
    timeZone: 'UTC',
  })

const humanSpan = (days?: number) => {
  if (!days || days < 1) return '1 day'
  if (days < 21) return `${days} days`
  if (days < 60) return `${Math.round(days / 7)} weeks`
  if (days < 400) return `${Math.round(days / 30)} months`
  return `${(days / 365).toFixed(1)} years`
}

export function CrisisChart({ periods }: Props) {
  const rows = periods.filter((p) => p.portfolio !== null)
  if (rows.length === 0) return null

  // Chronological, so the column reads as a history rather than a ranking.
  const ordered = [...rows].sort((a, b) => a.start.localeCompare(b.start))

  const values = ordered.flatMap((p) =>
    [p.portfolio, p.benchmark].filter((v): v is number => v !== null)
  )
  const extent = Math.max(...values.map(Math.abs), 0.05)
  const half = 50
  const span = (v: number) => Math.abs(v / extent) * half

  // The timeline runs across the whole reported history, so each band's
  // position and width are comparable between rows.
  const first = new Date(`${ordered[0].start}T00:00:00Z`).getTime()
  const last = Math.max(
    ...ordered.map((p) => new Date(`${p.end}T00:00:00Z`).getTime())
  )
  const total = Math.max(last - first, 1)
  const at = (iso: string) =>
    ((new Date(`${iso}T00:00:00Z`).getTime() - first) / total) * 100

  return (
    <div className="space-y-3">
      <div className="grid grid-cols-[15rem_10rem_1fr] gap-3 border-b pb-1.5 text-[10px] uppercase tracking-wide text-muted-foreground">
        <span>Period</span>
        <span>When it ran</span>
        <span>Return over the window</span>
      </div>

      {ordered.map((p) => {
        const port = p.portfolio ?? 0
        const bench = p.benchmark
        return (
          <div
            key={p.key}
            className="grid grid-cols-[15rem_10rem_1fr] items-center gap-3"
          >
            {/* What, and how long */}
            <div className="min-w-0">
              <div className="truncate text-sm" title={p.note || p.label}>
                {p.label}
                {p.partial && (
                  <span
                    className="ml-1 text-[10px] text-amber-500"
                    title="the backtest covers only part of this window"
                  >
                    partial
                  </span>
                )}
              </div>
              <div className="text-[11px] text-muted-foreground">
                {fmtDate(p.start)} → {fmtDate(p.end)} · {humanSpan(p.days)}
                {p.sessions ? ` · ${p.sessions} sessions` : ''}
              </div>
            </div>

            {/* When, on a shared timeline */}
            <div className="relative h-6">
              <div className="absolute inset-x-0 top-1/2 h-px -translate-y-1/2 bg-border" />
              <div
                className={`absolute top-1/2 h-2.5 -translate-y-1/2 rounded-sm ${
                  p.scope === 'india' ? 'bg-violet-500/70' : 'bg-sky-500/70'
                }`}
                style={{
                  left: `${at(p.start)}%`,
                  // A single-day event would otherwise be invisible.
                  width: `${Math.max(at(p.end) - at(p.start), 1.5)}%`,
                }}
                title={`${p.scope === 'india' ? 'Domestic' : 'Global'} · ${humanSpan(p.days)}`}
              />
            </div>

            {/* How bad */}
            <div className="relative h-8">
              <div className="absolute inset-y-0 left-1/2 w-px bg-border" />

              {bench !== null && (
                <div
                  className="absolute top-1 h-6 rounded-sm border border-dashed border-muted-foreground/50 bg-muted-foreground/10"
                  style={{
                    left: `${bench >= 0 ? half : half - span(bench)}%`,
                    width: `${span(bench)}%`,
                  }}
                  title={`Benchmark ${(bench * 100).toFixed(2)}%`}
                />
              )}

              <div
                className={`absolute top-2.5 h-3 rounded-sm ${
                  port >= 0 ? 'bg-blue-500' : 'bg-rose-500'
                }`}
                style={{
                  left: `${port >= 0 ? half : half - span(port)}%`,
                  width: `${span(port)}%`,
                }}
                title={`Portfolio ${(port * 100).toFixed(2)}%`}
              />

              <span
                className={`absolute top-1.5 whitespace-nowrap text-xs tabular-nums ${
                  port >= 0 ? 'text-blue-500' : 'text-rose-500'
                }`}
                style={
                  port >= 0
                    ? { left: `calc(${half + span(port)}% + 6px)` }
                    : { right: `calc(${half + span(port)}% + 6px)` }
                }
              >
                {port >= 0 ? '+' : ''}
                {(port * 100).toFixed(1)}%
                {bench !== null && (
                  <span className="ml-1.5 text-muted-foreground">
                    vs {bench >= 0 ? '+' : ''}
                    {(bench * 100).toFixed(1)}%
                  </span>
                )}
              </span>
            </div>
          </div>
        )
      })}

      <div className="flex flex-wrap justify-end gap-4 border-t pt-2 text-xs text-muted-foreground">
        <span className="flex items-center gap-1.5">
          <span className="inline-block h-2 w-4 rounded-sm bg-sky-500/70" /> Global
        </span>
        <span className="flex items-center gap-1.5">
          <span className="inline-block h-2 w-4 rounded-sm bg-violet-500/70" /> Domestic
        </span>
        <span className="flex items-center gap-1.5">
          <span className="inline-block h-2 w-4 rounded-sm bg-blue-500" /> Portfolio
        </span>
        <span className="flex items-center gap-1.5">
          <span className="inline-block h-2 w-4 rounded-sm border border-dashed border-muted-foreground/50 bg-muted-foreground/10" />
          Benchmark
        </span>
      </div>
    </div>
  )
}
