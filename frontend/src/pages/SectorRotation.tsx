/**
 * Sector Rotation: NSE sector indices, or any stocks and indices the trader
 * picks, on a four-quadrant map against a benchmark, with the trail each took
 * to get there.
 *
 * One request returns the whole map with each trail at its longest. The tail
 * slider, the visibility toggles and the zoom only change what is drawn, so
 * none of them costs a request; changing the benchmark, the timeframe, the
 * data source or the list of symbols does. Every choice is kept across visits
 * by the sector rotation store.
 */

import { keepPreviousData, useQuery } from '@tanstack/react-query'
import html2canvas from 'html2canvas-pro'
import { Camera, Info, Minus, Plus, RotateCcw, X } from 'lucide-react'
import { useMemo, useRef, useState } from 'react'
import {
  getRotationOptions,
  getSectorRotation,
  type Quadrant,
  type RotationEntry,
  type RotationInstrument,
  type RotationPoint,
} from '@/api/sector-rotation'
import { InstrumentSearch, type SearchHit } from '@/components/sector-rotation/InstrumentSearch'
import { Button } from '@/components/ui/button'
import { Card, CardContent } from '@/components/ui/card'
import { Checkbox } from '@/components/ui/checkbox'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from '@/components/ui/dialog'
import { Label } from '@/components/ui/label'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip'
import { useAuthStore } from '@/stores/authStore'
import {
  instrumentKey,
  type MapInstrument,
  useSectorRotationStore,
} from '@/stores/sectorRotationStore'
import { showToast } from '@/utils/toast'

const TAIL_STEPS = [4, 6, 8, 12, 16, 20]
const ZOOM_STEPS = [1, 1.5, 2, 3, 4]
const FALLBACK_EXCHANGES = ['NSE', 'BSE', 'NSE_INDEX', 'BSE_INDEX']

const VIEW_W = 1600
const VIEW_H = 1000
const PAD_X = 60
const PAD_Y = 48

// Mid-lightness so every colour reads on both the light and the dark
// background. A symbol keeps the colour it was given when it joined the map.
const SERIES_COLORS = [
  '#6366f1',
  '#eab308',
  '#22c55e',
  '#ec4899',
  '#a855f7',
  '#f59e0b',
  '#f43f5e',
  '#3b82f6',
  '#06b6d4',
  '#84cc16',
  '#f97316',
  '#d4a373',
  '#14b8a6',
  '#e879f9',
  '#10b981',
  '#2dd4bf',
  '#8b5cf6',
  '#0ea5e9',
]

const QUADRANT_LABEL: Record<Quadrant, string> = {
  leading: 'Leading',
  weakening: 'Weakening',
  lagging: 'Lagging',
  improving: 'Improving',
}

const QUADRANT_BADGE: Record<Quadrant, string> = {
  leading: 'bg-emerald-500/15 text-emerald-600 dark:text-emerald-400',
  weakening: 'bg-amber-500/15 text-amber-600 dark:text-amber-400',
  lagging: 'bg-rose-500/15 text-rose-600 dark:text-rose-400',
  improving: 'bg-blue-500/15 text-blue-600 dark:text-blue-400',
}

const RS_INFO =
  'How a symbol is performing against the benchmark now. Above 100 is outperforming, below 100 is underperforming.'
const MOM_INFO =
  'Whether that relative performance is building or fading. Above 100 is strengthening, below 100 is weakening.'

function defaultInstruments(sectors: RotationInstrument[]): MapInstrument[] {
  return sectors.map((s, i) => ({ ...s, color: SERIES_COLORS[i % SERIES_COLORS.length] }))
}

function nextColor(used: MapInstrument[]): string {
  const taken = new Set(used.map((i) => i.color))
  return (
    SERIES_COLORS.find((c) => !taken.has(c)) ?? SERIES_COLORS[used.length % SERIES_COLORS.length]
  )
}

/** Half-width of an axis around 100, wide enough for every visible point plus a margin. */
function axisRadius(points: RotationPoint[], key: 'rs_ratio' | 'rs_momentum'): number {
  let r = 1.5
  for (const p of points) r = Math.max(r, Math.abs(p[key] - 100))
  return 1.3 * r
}

function errorMessage(err: unknown): string {
  const e = err as { response?: { data?: { message?: unknown } }; message?: string }
  const msg = e.response?.data?.message ?? e.message ?? 'The sector map could not be loaded.'
  return typeof msg === 'string' ? msg : JSON.stringify(msg)
}

/**
 * Copy each SVG element's computed paint onto its clone.
 *
 * The image export serialises the SVG on its own, without the page stylesheet,
 * so anything coloured by a theme class would come out black. Writing the
 * computed values as attributes keeps the export identical to the screen in
 * every theme.
 */
function inlineSvgPaint(original: SVGSVGElement, clone: SVGSVGElement) {
  const from = [original, ...Array.from(original.querySelectorAll('*'))]
  const to = [clone, ...Array.from(clone.querySelectorAll('*'))]
  from.forEach((el, i) => {
    const target = to[i]
    if (!target) return
    const style = getComputedStyle(el)
    target.setAttribute('fill', style.fill)
    target.setAttribute('stroke', style.stroke)
    if (el.tagName.toLowerCase() === 'text') {
      target.setAttribute('font-family', style.fontFamily)
    }
  })
}

interface HoverPoint {
  entry: RotationEntry
  point: RotationPoint
  x: number
  y: number
}

function InfoTip({ text }: { text: string }) {
  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <button
          type="button"
          aria-label={text}
          className="inline-grid size-4 cursor-help place-items-center text-muted-foreground hover:text-foreground"
        >
          <Info className="size-3" />
        </button>
      </TooltipTrigger>
      <TooltipContent className="max-w-64">{text}</TooltipContent>
    </Tooltip>
  )
}

function RotationMap({
  entries,
  colors,
  tail,
  zoom,
  focusedId,
  onFocus,
  svgRef,
}: {
  entries: RotationEntry[]
  colors: Map<string, string>
  tail: number
  zoom: number
  focusedId: string | null
  onFocus: (id: string | null) => void
  svgRef: React.RefObject<SVGSVGElement | null>
}) {
  const [hover, setHover] = useState<HoverPoint | null>(null)

  const trails = useMemo(
    () => entries.map((e) => ({ entry: e, points: e.tail.slice(-tail) })),
    [entries, tail]
  )

  const { radiusX, radiusY } = useMemo(() => {
    const all = trails.flatMap((t) => t.points)
    return {
      radiusX: axisRadius(all, 'rs_ratio') / zoom,
      radiusY: axisRadius(all, 'rs_momentum') / zoom,
    }
  }, [trails, zoom])

  const x = (v: number) => PAD_X + ((v - (100 - radiusX)) / (2 * radiusX)) * (VIEW_W - 2 * PAD_X)
  const y = (v: number) =>
    VIEW_H - PAD_Y - ((v - (100 - radiusY)) / (2 * radiusY)) * (VIEW_H - 2 * PAD_Y)
  const cx = x(100)
  const cy = y(100)

  return (
    <div className="relative aspect-[16/10] w-full overflow-hidden rounded-lg border bg-card">
      <svg
        ref={svgRef}
        viewBox={`0 0 ${VIEW_W} ${VIEW_H}`}
        className="absolute inset-0 h-full w-full"
        role="img"
        aria-label="Sector rotation map"
        onMouseLeave={() => setHover(null)}
      >
        {/* Quadrant backgrounds, clockwise from top right. */}
        <rect x={cx} y={0} width={VIEW_W - cx} height={cy} fill="#10b981" fillOpacity={0.09} />
        <rect
          x={cx}
          y={cy}
          width={VIEW_W - cx}
          height={VIEW_H - cy}
          fill="#f59e0b"
          fillOpacity={0.08}
        />
        <rect x={0} y={cy} width={cx} height={VIEW_H - cy} fill="#f43f5e" fillOpacity={0.08} />
        <rect x={0} y={0} width={cx} height={cy} fill="#3b82f6" fillOpacity={0.09} />

        <g fontWeight={600} letterSpacing={4} fontSize={30}>
          <text x={40} y={60} fill="#3b82f6">
            IMPROVING
          </text>
          <text x={VIEW_W - 40} y={60} textAnchor="end" fill="#10b981">
            LEADING
          </text>
          <text x={40} y={VIEW_H - 36} fill="#f43f5e">
            LAGGING
          </text>
          <text x={VIEW_W - 40} y={VIEW_H - 36} textAnchor="end" fill="#f59e0b">
            WEAKENING
          </text>
        </g>

        <line
          x1={cx}
          x2={cx}
          y1={0}
          y2={VIEW_H}
          className="stroke-muted-foreground"
          strokeOpacity={0.6}
          strokeDasharray="8 8"
          strokeWidth={2}
        />
        <line
          x1={0}
          x2={VIEW_W}
          y1={cy}
          y2={cy}
          className="stroke-muted-foreground"
          strokeOpacity={0.6}
          strokeDasharray="8 8"
          strokeWidth={2}
        />

        <text
          x={VIEW_W / 2}
          y={VIEW_H - 12}
          textAnchor="middle"
          fontSize={22}
          className="fill-muted-foreground"
        >
          RS-Ratio
        </text>
        <text
          x={22}
          y={VIEW_H / 2}
          textAnchor="middle"
          fontSize={22}
          transform={`rotate(-90 22 ${VIEW_H / 2})`}
          className="fill-muted-foreground"
        >
          RS-Momentum
        </text>

        {trails.map(({ entry, points }) => {
          if (points.length === 0) return null
          const key = instrumentKey(entry)
          const color = colors.get(key) ?? '#888888'
          const dimmed = focusedId !== null && focusedId !== key
          const head = points[points.length - 1]
          const path = points.map((p) => `${x(p.rs_ratio)},${y(p.rs_momentum)}`).join(' ')
          return (
            <g
              key={key}
              opacity={dimmed ? 0.15 : 1}
              onMouseEnter={() => onFocus(key)}
              onMouseLeave={() => onFocus(null)}
            >
              <polyline
                points={path}
                fill="none"
                stroke={color}
                strokeWidth={3}
                strokeLinejoin="round"
              />
              {points.slice(0, -1).map((p) => (
                <circle
                  key={p.date}
                  cx={x(p.rs_ratio)}
                  cy={y(p.rs_momentum)}
                  r={5}
                  fill={color}
                  onMouseEnter={() =>
                    setHover({ entry, point: p, x: x(p.rs_ratio), y: y(p.rs_momentum) })
                  }
                />
              ))}
              <circle
                cx={x(head.rs_ratio)}
                cy={y(head.rs_momentum)}
                r={12}
                fill={color}
                className="stroke-background"
                strokeWidth={3}
                onMouseEnter={() =>
                  setHover({ entry, point: head, x: x(head.rs_ratio), y: y(head.rs_momentum) })
                }
              />
              <text
                x={x(head.rs_ratio) + 18}
                y={y(head.rs_momentum) + 8}
                fontSize={24}
                fontWeight={600}
                className="fill-foreground stroke-background"
                strokeWidth={5}
                paintOrder="stroke"
              >
                {entry.label}
              </text>
            </g>
          )
        })}
      </svg>

      {hover && (
        <div
          className="pointer-events-none absolute z-10 -translate-x-1/2 -translate-y-[calc(100%+12px)] rounded-md border bg-popover px-3 py-2 text-xs text-popover-foreground shadow-md"
          style={{ left: `${(hover.x / VIEW_W) * 100}%`, top: `${(hover.y / VIEW_H) * 100}%` }}
        >
          <div className="font-medium">{hover.entry.label}</div>
          <div className="text-muted-foreground">{hover.point.date}</div>
          <div className="mt-1 tabular-nums">
            RS {hover.point.rs_ratio.toFixed(1)} / Mom. {hover.point.rs_momentum.toFixed(1)}
          </div>
        </div>
      )}
    </div>
  )
}

function RankingTable({
  entries,
  colors,
  hidden,
  barsLabel,
  focusedId,
  onToggle,
  onShowAll,
  onHideAll,
  onRemove,
  onFocus,
}: {
  entries: RotationEntry[]
  colors: Map<string, string>
  hidden: Set<string>
  barsLabel: string
  focusedId: string | null
  onToggle: (key: string) => void
  onShowAll: () => void
  onHideAll: () => void
  onRemove: (key: string) => void
  onFocus: (key: string | null) => void
}) {
  const visible = entries.filter((e) => !hidden.has(instrumentKey(e))).length
  return (
    <Card className="flex h-full min-h-0 flex-col gap-0 py-0">
      <div className="flex items-center justify-between border-b px-4 py-3">
        <div>
          <p className="text-xs text-muted-foreground">Ranking</p>
          <p className="text-sm font-medium">
            {visible} of {entries.length} visible
          </p>
        </div>
        <div className="flex gap-1" data-screenshot-ignore>
          <Button size="sm" variant="secondary" className="h-7 px-2 text-xs" onClick={onShowAll}>
            All
          </Button>
          <Button size="sm" variant="ghost" className="h-7 px-2 text-xs" onClick={onHideAll}>
            None
          </Button>
        </div>
      </div>
      <div className="min-h-0 flex-1 overflow-auto">
        <table className="w-full text-sm">
          <thead className="sticky top-0 bg-card text-xs text-muted-foreground">
            <tr className="border-b">
              <th className="w-8 py-2 pl-4" aria-label="Visible" />
              <th className="py-2 text-left font-medium">Symbol</th>
              <th className="py-2 text-left font-medium">Quadrant</th>
              <th className="py-2 pr-1 text-right font-medium">
                <span className="inline-flex items-center gap-0.5">
                  RS <InfoTip text={RS_INFO} />
                </span>
              </th>
              <th className="py-2 pr-1 text-right font-medium">
                <span className="inline-flex items-center gap-0.5">
                  Mom. <InfoTip text={MOM_INFO} />
                </span>
              </th>
              <th className="py-2 pr-2 text-right font-medium">{barsLabel}</th>
              <th className="w-8 pr-2" aria-label="Remove" />
            </tr>
          </thead>
          <tbody>
            {entries.map((e) => {
              const key = instrumentKey(e)
              const off = hidden.has(key)
              return (
                <tr
                  key={key}
                  className={`group border-b transition-colors last:border-0 hover:bg-muted/50 ${
                    off ? 'opacity-40' : ''
                  } ${focusedId === key ? 'bg-muted/50' : ''}`}
                  onMouseEnter={() => !off && onFocus(key)}
                  onMouseLeave={() => onFocus(null)}
                >
                  <td className="py-2.5 pl-4">
                    <Checkbox
                      checked={!off}
                      onCheckedChange={() => onToggle(key)}
                      aria-label={`Show ${e.label}`}
                    />
                  </td>
                  <td className="py-2.5" title={`${e.symbol} (${e.exchange})`}>
                    <span className="inline-flex items-center gap-2">
                      <span
                        className="size-2.5 shrink-0 rounded-full"
                        style={{ backgroundColor: colors.get(key) }}
                      />
                      {e.label}
                    </span>
                  </td>
                  <td className="py-2.5">
                    <span
                      className={`inline-flex h-6 items-center rounded-full px-2 text-xs font-medium ${QUADRANT_BADGE[e.quadrant]}`}
                    >
                      {QUADRANT_LABEL[e.quadrant]}
                    </span>
                  </td>
                  <td className="py-2.5 pr-1 text-right tabular-nums">{e.rs_ratio.toFixed(1)}</td>
                  <td className="py-2.5 pr-1 text-right tabular-nums">
                    {e.rs_momentum.toFixed(1)}
                  </td>
                  <td className="py-2.5 pr-2 text-right tabular-nums">{e.bars_in_quadrant}</td>
                  <td className="pr-2">
                    <button
                      type="button"
                      aria-label={`Remove ${e.label}`}
                      onClick={() => onRemove(key)}
                      data-screenshot-ignore
                      className="grid size-6 place-items-center rounded text-muted-foreground opacity-0 transition-opacity group-hover:opacity-100 hover:bg-muted hover:text-foreground focus-visible:opacity-100"
                    >
                      <X className="size-3.5" />
                    </button>
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>
    </Card>
  )
}

function MethodologyDialog() {
  return (
    <Dialog>
      <DialogTrigger asChild>
        <Button variant="outline" size="sm" className="gap-1.5">
          <Info className="size-3.5" />
          Methodology
        </Button>
      </DialogTrigger>
      <DialogContent className="max-w-xl">
        <DialogHeader>
          <DialogTitle>How the map is built</DialogTitle>
          <DialogDescription>
            Each dot is a sector index, stock or index measured against the benchmark you pick.
          </DialogDescription>
        </DialogHeader>
        <div className="space-y-3 text-sm">
          <p>
            <span className="font-medium">RS-Ratio</span> (horizontal) shows whether the symbol's
            recent relative strength against the benchmark is running above its longer trend.{' '}
            <span className="font-medium">RS-Momentum</span> (vertical) shows whether that relative
            strength is still accelerating. Both are centred on 100, and recent bars count most.
          </p>
          <p>
            Bars are daily sessions, or weeks ending Friday built from daily closes. Only sessions
            both the symbol and the benchmark traded are used, so a newly listed index shows a
            shorter trail until enough history builds up. The Days or Weeks column counts
            consecutive bars in the current quadrant.
          </p>
          <ul className="grid grid-cols-2 gap-2 text-xs">
            <li className={`rounded-md p-2 ${QUADRANT_BADGE.leading}`}>
              Leading: strong and rising
            </li>
            <li className={`rounded-md p-2 ${QUADRANT_BADGE.weakening}`}>
              Weakening: strong but slowing
            </li>
            <li className={`rounded-md p-2 ${QUADRANT_BADGE.improving}`}>
              Improving: weak but turning up
            </li>
            <li className={`rounded-md p-2 ${QUADRANT_BADGE.lagging}`}>
              Lagging: weak and falling
            </li>
          </ul>
          <p className="text-xs text-muted-foreground">
            Symbols usually rotate clockwise: Improving, Leading, Weakening, Lagging. The map
            describes where they stand today; it does not predict what happens next.
          </p>
        </div>
      </DialogContent>
    </Dialog>
  )
}

export default function SectorRotation() {
  const { apiKey } = useAuthStore()
  const store = useSectorRotationStore()
  const [focusedId, setFocusedId] = useState<string | null>(null)
  const [isCapturing, setIsCapturing] = useState(false)
  const captureRef = useRef<HTMLDivElement>(null)
  const svgRef = useRef<SVGSVGElement>(null)

  const { data: options } = useQuery({
    queryKey: ['sector-rotation', 'options'],
    queryFn: getRotationOptions,
    staleTime: Number.POSITIVE_INFINITY,
  })

  const defaults = useMemo(() => defaultInstruments(options?.sectors ?? []), [options])
  const onMap = store.instruments ?? defaults
  const maxInstruments = options?.max_instruments ?? 40
  const requested = store.instruments
    ? store.instruments.map(({ symbol, exchange, label }) => ({ symbol, exchange, label }))
    : []
  // An empty request means the default sectors to the server, so a list the
  // trader emptied is never sent: it would fetch every sector they removed.
  const isEmptyMap = store.instruments !== null && store.instruments.length === 0

  const {
    data: result,
    error,
    isFetching,
    isPending,
  } = useQuery({
    queryKey: [
      'sector-rotation',
      store.benchmark,
      store.timeframe,
      store.source,
      requested.map(instrumentKey).join(','),
    ],
    queryFn: () =>
      getSectorRotation({
        apikey: apiKey ?? '',
        benchmark: store.benchmark,
        timeframe: store.timeframe,
        source: store.source,
        instruments: requested,
      }),
    enabled: !!apiKey && !isEmptyMap,
    placeholderData: keepPreviousData,
    staleTime: 5 * 60_000,
    retry: false,
  })

  const colors = useMemo(() => {
    const map = new Map<string, string>()
    for (const i of onMap) map.set(instrumentKey(i), i.color)
    return map
  }, [onMap])

  const hidden = useMemo(() => new Set(store.hidden), [store.hidden])
  // Rows follow the order of the list on the map, so a symbol just added lands
  // where the trader expects it rather than wherever the server put it.
  const entries = useMemo(() => {
    const placed = new Map((result?.instruments ?? []).map((e) => [instrumentKey(e), e]))
    return onMap.map((i) => placed.get(instrumentKey(i))).filter((e): e is RotationEntry => !!e)
  }, [result, onMap])
  const visibleEntries = entries.filter((e) => !hidden.has(instrumentKey(e)))
  // A previous result can still be on screen while the next loads; only report
  // symbols that are still on the trader's list.
  const unavailable = (result?.unavailable ?? []).filter((u) =>
    onMap.some((i) => instrumentKey(i) === instrumentKey(u))
  )
  // A row removed while hovered never fires its mouse-leave, so a focus on a
  // symbol no longer drawn is dropped rather than dimming every other trail.
  const activeFocus =
    focusedId && visibleEntries.some((e) => instrumentKey(e) === focusedId) ? focusedId : null
  const tailStep = Math.min(store.tailStep, TAIL_STEPS.length - 1)
  const zoomStep = Math.min(store.zoomStep, ZOOM_STEPS.length - 1)
  const tail = TAIL_STEPS[tailStep]
  const isWeekly = store.timeframe === 'weekly'
  const benchmarkLabel =
    options?.benchmarks.find((b) => b.symbol === store.benchmark)?.label ?? store.benchmark

  const isOnMap = (hit: { symbol: string; exchange: string }) =>
    onMap.some((i) => instrumentKey(i) === instrumentKey(hit))

  const addInstrument = (hit: SearchHit) => {
    // Until the sector list arrives the defaults are unknown, and adding then
    // would save a list without them.
    if (!options || isOnMap(hit) || onMap.length >= maxInstruments) return
    const known = [...options.sectors, ...(options.optional_sectors ?? [])].find(
      (s) => instrumentKey(s) === instrumentKey(hit)
    )
    store.setInstruments([
      ...onMap,
      {
        symbol: hit.symbol,
        exchange: hit.exchange,
        label: known?.label ?? hit.symbol,
        color: nextColor(onMap),
      },
    ])
  }

  const removeInstrument = (key: string) => {
    if (!options) return
    setFocusedId(null)
    store.setInstruments(onMap.filter((i) => instrumentKey(i) !== key))
    store.setHidden(store.hidden.filter((k) => k !== key))
  }

  const resetInstruments = () => {
    store.setInstruments(null)
    store.setHidden([])
  }

  const saveImage = async () => {
    if (!captureRef.current) return
    setIsCapturing(true)
    try {
      const background = getComputedStyle(document.body).backgroundColor || '#ffffff'
      const canvas = await html2canvas(captureRef.current, {
        backgroundColor: background,
        scale: 2,
        logging: false,
        ignoreElements: (el) => el.hasAttribute('data-screenshot-ignore'),
        onclone: (doc) => {
          const clone = doc.querySelector<SVGSVGElement>('[data-rotation-map] svg')
          if (svgRef.current && clone) inlineSvgPaint(svgRef.current, clone)
          // The table scrolls on screen; the image shows every row.
          doc
            .querySelectorAll<HTMLElement>('[data-rotation-capture] .overflow-auto')
            .forEach((n) => {
              n.style.overflow = 'visible'
              n.style.maxHeight = 'none'
            })
          doc
            .querySelectorAll<HTMLElement>('[data-rotation-capture] [data-capture-unbound]')
            .forEach((n) => {
              n.style.maxHeight = 'none'
            })
        },
      })
      canvas.toBlob(
        (blob) => {
          if (!blob) return
          const url = URL.createObjectURL(blob)
          const link = document.createElement('a')
          link.download = `Sector_Rotation_${store.benchmark}_${store.timeframe}_${
            result?.as_of ?? new Date().toISOString().slice(0, 10)
          }.png`
          link.href = url
          document.body.appendChild(link)
          link.click()
          document.body.removeChild(link)
          URL.revokeObjectURL(url)
          showToast.success('Sector rotation image saved')
        },
        'image/png',
        1.0
      )
    } catch {
      showToast.error('The image could not be saved. Try again after the map finishes loading.')
    } finally {
      setIsCapturing(false)
    }
  }

  return (
    <div className="container mx-auto space-y-4 p-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 className="text-2xl font-bold tracking-tight">Sector Rotation</h1>
          <p className="text-sm text-muted-foreground">
            Which sectors and stocks are leading the benchmark, which are fading, and which are
            turning up.
          </p>
        </div>
        <div className="flex gap-2">
          <Button
            variant="outline"
            size="sm"
            className="gap-1.5"
            onClick={saveImage}
            disabled={isCapturing || entries.length === 0}
          >
            <Camera className="size-3.5" />
            {isCapturing ? 'Saving...' : 'Save image'}
          </Button>
          <MethodologyDialog />
        </div>
      </div>

      <div className="flex flex-wrap items-end gap-3">
        <div className="space-y-1">
          <Label className="text-xs">Benchmark</Label>
          <Select value={store.benchmark} onValueChange={store.setBenchmark}>
            <SelectTrigger className="w-40">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {(options?.benchmarks ?? [{ symbol: 'NIFTY', label: 'Nifty 50', exchange: '' }]).map(
                (b) => (
                  <SelectItem key={b.symbol} value={b.symbol}>
                    {b.label}
                  </SelectItem>
                )
              )}
            </SelectContent>
          </Select>
        </div>
        <div className="space-y-1">
          <Label className="text-xs">Timeframe</Label>
          <Select
            value={store.timeframe}
            onValueChange={(v) => store.setTimeframe(v as 'daily' | 'weekly')}
          >
            <SelectTrigger className="w-32">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="daily">Daily</SelectItem>
              <SelectItem value="weekly">Weekly</SelectItem>
            </SelectContent>
          </Select>
        </div>
        <div className="space-y-1">
          <Label htmlFor="rotation-tail" className="text-xs">
            Tail: {tail} {isWeekly ? 'weeks' : 'days'}
          </Label>
          <input
            id="rotation-tail"
            type="range"
            min={0}
            max={TAIL_STEPS.length - 1}
            step={1}
            value={tailStep}
            onChange={(e) => store.setTailStep(Number(e.target.value))}
            className="block h-9 w-40 accent-primary"
          />
        </div>
        <div className="space-y-1">
          <Label className="text-xs">Data source</Label>
          <Select value={store.source} onValueChange={(v) => store.setSource(v as 'db' | 'api')}>
            <SelectTrigger className="w-40">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="api">Broker API</SelectItem>
              <SelectItem value="db">Historify (local)</SelectItem>
            </SelectContent>
          </Select>
        </div>
        <p className="pb-2 text-xs text-muted-foreground">
          {isFetching
            ? 'Loading history...'
            : store.source === 'api'
              ? 'Broker history needs an active broker login.'
              : 'Historify works without a broker login.'}
        </p>
      </div>

      <div className="flex flex-wrap items-center gap-2">
        <div className="min-w-72 flex-1">
          <InstrumentSearch
            exchanges={options?.exchanges ?? FALLBACK_EXCHANGES}
            isOnMap={isOnMap}
            onAdd={addInstrument}
            disabled={!options || onMap.length >= maxInstruments}
          />
        </div>
        <span className="text-xs text-muted-foreground">
          {onMap.length} of {maxInstruments} symbols
        </span>
        {store.instruments !== null && (
          <Button variant="ghost" size="sm" onClick={resetInstruments}>
            Reset to sectors
          </Button>
        )}
      </div>

      {error && (
        <div className="rounded-md border border-destructive/50 bg-destructive/10 p-3 text-sm text-destructive">
          {errorMessage(error)}
        </div>
      )}

      {!apiKey && (
        <div className="rounded-md border p-3 text-sm text-muted-foreground">
          Generate an API key on the API Key page to load the sector map.
        </div>
      )}

      <div ref={captureRef} data-rotation-capture className="space-y-3 bg-background">
        <div className="flex flex-wrap items-baseline justify-between gap-2 text-sm">
          <span className="font-medium">
            Sector Rotation vs {benchmarkLabel}, {isWeekly ? 'weekly' : 'daily'}, tail {tail}{' '}
            {isWeekly ? 'weeks' : 'days'}
          </span>
          <span className="text-xs text-muted-foreground">
            {result?.as_of ? `As of ${result.as_of}` : ''}
          </span>
        </div>

        <div className="grid grid-cols-1 gap-4 lg:grid-cols-[minmax(0,1fr)_420px]">
          <Card className="py-0">
            <CardContent className="relative p-3" data-rotation-map>
              <div
                className="absolute top-5 left-1/2 z-10 flex -translate-x-1/2 gap-1"
                data-screenshot-ignore
              >
                <Button
                  size="icon"
                  variant="outline"
                  className="size-8"
                  aria-label="Zoom in"
                  disabled={zoomStep === ZOOM_STEPS.length - 1}
                  onClick={() => store.setZoomStep(Math.min(zoomStep + 1, ZOOM_STEPS.length - 1))}
                >
                  <Plus className="size-4" />
                </Button>
                <Button
                  size="icon"
                  variant="outline"
                  className="size-8"
                  aria-label="Zoom out"
                  disabled={zoomStep === 0}
                  onClick={() => store.setZoomStep(Math.max(zoomStep - 1, 0))}
                >
                  <Minus className="size-4" />
                </Button>
                <Button
                  size="icon"
                  variant="outline"
                  className="size-8"
                  aria-label="Reset zoom"
                  onClick={() => store.setZoomStep(0)}
                >
                  <RotateCcw className="size-4" />
                </Button>
              </div>
              {isEmptyMap ? (
                <div className="grid aspect-[16/10] w-full place-items-center rounded-lg border p-6 text-center text-sm text-muted-foreground">
                  No symbols on the map. Search above to add one, or use Reset to sectors.
                </div>
              ) : isPending && apiKey ? (
                <div className="grid aspect-[16/10] w-full place-items-center rounded-lg border text-sm text-muted-foreground">
                  Loading history...
                </div>
              ) : (
                <RotationMap
                  entries={visibleEntries}
                  colors={colors}
                  tail={tail}
                  zoom={ZOOM_STEPS[zoomStep]}
                  focusedId={activeFocus}
                  onFocus={setFocusedId}
                  svgRef={svgRef}
                />
              )}
            </CardContent>
          </Card>

          <div
            className="flex min-h-0 flex-col lg:max-h-[calc((100vw-2rem)*0.4)]"
            data-capture-unbound
          >
            <RankingTable
              entries={entries}
              colors={colors}
              hidden={hidden}
              barsLabel={isWeekly ? 'Weeks' : 'Days'}
              focusedId={activeFocus}
              onToggle={store.toggleHidden}
              onShowAll={() => store.setHidden([])}
              onHideAll={() => store.setHidden(entries.map(instrumentKey))}
              onRemove={removeInstrument}
              onFocus={setFocusedId}
            />
          </div>
        </div>
      </div>

      {unavailable.length > 0 && (
        <Card className="py-3">
          <CardContent className="space-y-1 px-4 text-sm">
            <p className="font-medium">Not on the map</p>
            {unavailable.map((u) => (
              <div key={instrumentKey(u)} className="flex items-start justify-between gap-2">
                <p className="text-muted-foreground">
                  <span className="text-foreground">{u.label}</span>: {u.reason}
                </p>
                <Button
                  variant="ghost"
                  size="sm"
                  className="h-7 shrink-0 px-2 text-xs"
                  onClick={() => removeInstrument(instrumentKey(u))}
                >
                  Remove
                </Button>
              </div>
            ))}
          </CardContent>
        </Card>
      )}

      <p className="text-center text-xs text-muted-foreground">
        A descriptive view of relative strength for analysis only. It is not investment advice.
      </p>
    </div>
  )
}
