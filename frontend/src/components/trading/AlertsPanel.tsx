/**
 * Every alert on the chart, in the rail beside it.
 *
 * A list of alerts is a thing you keep open while you watch, not a thing you
 * open, read and dismiss. In a modal it covered the chart it was describing, so
 * checking what was armed meant hiding the prices that would arm it. The list
 * lives on the rail with the watchlist and the objects panel; the modal is left
 * to the one job a modal is good at, which is filling in a form.
 *
 * Two tabs, because an alert and its firings are different questions. **Alerts**
 * is what is watching now: a row per alert, its state, and what it is waiting
 * for. **Log** is what has happened: a row per firing, newest first, which is
 * what a trader reads when a toast went past while they were looking elsewhere.
 * The log outlives the tab. Alerts are still evaluated by the chart that is
 * open, so a firing only *happens* while somebody is watching, but what the
 * browser could not keep is the record of it: a tab closed at four o'clock took
 * the afternoon's firings with it, and an alert that fired while the trader was
 * on another screen left nothing at all. Each row also says which channels
 * accepted the message, because a firing that reached nobody and a firing that
 * never happened are different things and the panel has to tell them apart.
 */

import { Bell, Eraser, Loader2, MoreHorizontal, Pause, Play, Settings2, Trash2 } from 'lucide-react'
import type { Alert } from 'openalgo-charts'
import { useMemo, useState } from 'react'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import type { AlertFire, AlertsView } from '@/lib/trading/terminal'
import { cn } from '@/lib/utils'
import { PANEL_HEADER, PanelShell } from './panelShell'

interface Props {
  /** The chart's controller and clock, or null while no chart is ready. */
  view: AlertsView | null
  /** This session's firings, newest last. The panel does the reversing. */
  log: readonly AlertFire[]
  /** Which pane and instrument the list belongs to, for the subtitle. */
  paneLabel: string
  /**
   * Open the editor on one of these alerts.
   *
   * Always on an existing one: an alert is created by right-clicking the chart
   * at the price it should watch, never from this panel.
   */
  onEdit(alertId: string): void
  /** Forget every logged firing. */
  onClearLog(): void
  /**
   * Bumped whenever an alert changes.
   *
   * The controller is mutable and `list()` hands back a copy, so a render is
   * the only thing that reads it and nothing in React would know to run one.
   */
  revision: number
}

type Tab = 'alerts' | 'log'
type Sort = 'state' | 'name' | 'recent'

const SORTS: readonly { value: Sort; label: string }[] = [
  { value: 'state', label: 'Status' },
  { value: 'name', label: 'Name' },
  { value: 'recent', label: 'Recently fired' },
]

/** What the row says an alert is doing, in a trader's words rather than a state name. */
const STATE_LABEL: Record<Alert['state'], string> = {
  armed: 'Active',
  triggered: 'Fired',
  expired: 'Expired',
  disabled: 'Stopped',
}

/**
 * The colour of the state dot.
 *
 * Only two of the four are coloured. An alert that is watching and one that has
 * just fired are the two a glance down the list is looking for; stopped and
 * expired are the absence of that, and giving them a colour each would make
 * four things compete for the same glance.
 */
const STATE_DOT: Record<Alert['state'], string> = {
  armed: 'bg-emerald-500',
  triggered: 'bg-primary',
  expired: 'bg-muted-foreground/40',
  disabled: 'bg-muted-foreground/40',
}

/** Sorted so the ones still watching come first, then fired, then the rest. */
const STATE_ORDER: Record<Alert['state'], number> = {
  armed: 0,
  triggered: 1,
  disabled: 2,
  expired: 3,
}

/**
 * The price or level an alert is watching, read from the alert every render.
 *
 * Deliberately not read out of the alert's name. Dragging the line moves the
 * price and leaves the name alone, so the name is a name and this is the number.
 */
function levelOf(alert: Alert): number | undefined {
  const source = alert.source as { price?: number; value?: number; upperPrice?: number }
  return source.price ?? source.value
}

function upperOf(alert: Alert): number | undefined {
  const source = alert.source as { upperPrice?: number; upperValue?: number }
  return source.upperPrice ?? source.upperValue
}

/** A sentence naming what the alert is waiting for, in the engine's own terms. */
function conditionText(alert: Alert): string {
  const words = alert.condition.replace(/([A-Z])/g, ' $1').toLowerCase()
  const level = levelOf(alert)
  if (level === undefined) return words.charAt(0).toUpperCase() + words.slice(1)
  const upper = upperOf(alert)
  const bounds = upper === undefined ? String(level) : `${level} and ${upper}`
  return `${words.charAt(0).toUpperCase()}${words.slice(1)} ${bounds}`
}

/**
 * A clock reading for a row.
 *
 * The date is dropped for anything fired today, because a column of identical
 * dates is a column of noise and the time is the part being compared.
 */
function firedText(seconds: number): string {
  const when = new Date(seconds * 1000)
  if (Number.isNaN(when.getTime())) return ''
  const today = new Date()
  const sameDay =
    when.getFullYear() === today.getFullYear() &&
    when.getMonth() === today.getMonth() &&
    when.getDate() === today.getDate()
  const time = when.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', hour12: false })
  if (sameDay) return time
  const date = when.toLocaleDateString([], { day: '2-digit', month: 'short' })
  return `${date} ${time}`
}

function TabButton({
  active,
  count,
  label,
  onClick,
}: {
  active: boolean
  count: number
  label: string
  onClick(): void
}) {
  return (
    <button
      type="button"
      role="tab"
      aria-selected={active}
      onClick={onClick}
      className={cn(
        '-mb-px inline-flex items-center gap-1.5 border-b-2 px-2 py-1.5 text-xs transition-colors focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring',
        active
          ? 'border-primary text-foreground'
          : 'border-transparent text-muted-foreground hover:text-foreground'
      )}
    >
      {label}
      <span
        className={cn(
          'rounded px-1 text-[10px] leading-4 tabular-nums',
          active ? 'bg-primary/15 text-primary' : 'bg-muted text-muted-foreground'
        )}
      >
        {count}
      </span>
    </button>
  )
}

/** A hover action on a row: invisible until the row is under the pointer or focused. */
function RowAction({
  label,
  onClick,
  danger = false,
  children,
}: {
  label: string
  onClick(): void
  danger?: boolean
  children: React.ReactNode
}) {
  return (
    <button
      type="button"
      aria-label={label}
      title={label}
      onClick={onClick}
      className={cn(
        'shrink-0 rounded p-1 text-muted-foreground opacity-0 transition-opacity hover:bg-accent hover:text-foreground focus-visible:opacity-100 focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring group-hover:opacity-100',
        danger && 'hover:text-destructive'
      )}
    >
      {children}
    </button>
  )
}

export function AlertsPanel({ view, log, paneLabel, onEdit, onClearLog, revision }: Props) {
  const [tab, setTab] = useState<Tab>('alerts')
  const [query, setQuery] = useState('')
  const [sort, setSort] = useState<Sort>('state')

  // Read straight from the controller rather than mirrored into state. The
  // controller is the truth and `list()` returns a fresh copy; a second copy
  // here would be one more thing to keep in step with a chart that also
  // changes alerts from a drag and from the Delete key.
  //
  // `revision` is the dependency that matters: the controller is mutable and
  // nothing else tells React that a drag, a Delete key or a firing changed it.
  // biome-ignore lint/correctness/useExhaustiveDependencies: see above
  const alerts = useMemo(() => (view ? view.alerts.list() : []), [view, revision])

  /**
   * Why each alert that cannot fire right now cannot fire, keyed by id.
   *
   * The engine owns this judgement and the panel only reports it. Asked per
   * alert rather than derived here, because the reasons are the engine's to
   * know: a study that has not loaded, a drawing that was deleted, a timeframe
   * that is not the one the alert was made on.
   */
  // biome-ignore lint/correctness/useExhaustiveDependencies: `revision`, as above
  const paused = useMemo(() => {
    const reasons: Record<string, string> = {}
    if (!view) return reasons
    for (const alert of alerts) {
      // Only an alert that believes it is watching. A stopped or expired one
      // already says why in its own state, and saying it twice reads as two
      // different problems.
      if (alert.state !== 'armed') continue
      try {
        const how = view.alerts.availability(alert.id)
        if (!how.available && how.reason) reasons[alert.id] = how.reason
      } catch {
        // A controller mid-teardown is not a paused alert.
      }
    }
    return reasons
  }, [view, alerts, revision])

  const shown = useMemo(() => {
    const needle = query.trim().toLowerCase()
    const matched = needle
      ? alerts.filter(
          (alert) =>
            alert.title.toLowerCase().includes(needle) ||
            (alert.message ?? '').toLowerCase().includes(needle) ||
            (alert.scope.symbol ?? '').toLowerCase().includes(needle)
        )
      : alerts
    const sorted = [...matched]
    sorted.sort((a, b) => {
      if (sort === 'name') return a.title.localeCompare(b.title)
      if (sort === 'recent') return (b.lastTriggeredAt ?? 0) - (a.lastTriggeredAt ?? 0)
      const byState = STATE_ORDER[a.state] - STATE_ORDER[b.state]
      return byState !== 0 ? byState : a.title.localeCompare(b.title)
    })
    return sorted
  }, [alerts, query, sort])

  const shownLog = useMemo(() => {
    const needle = query.trim().toLowerCase()
    const matched = needle
      ? log.filter(
          (fire) =>
            fire.title.toLowerCase().includes(needle) ||
            fire.message.toLowerCase().includes(needle) ||
            fire.symbol.toLowerCase().includes(needle)
        )
      : log
    return [...matched].reverse()
  }, [log, query])

  const armedCount = alerts.filter((alert) => alert.state === 'armed').length

  return (
    <PanelShell
      id="trading-alerts-panel"
      label="Alerts"
      storageKey="trading.panel.alerts.width"
      defaultWidth={340}
    >
      <div className={PANEL_HEADER}>
        <div className="min-w-0 flex-1">
          <div className="truncate text-[13px] font-medium">Alerts</div>
          <div className="truncate text-[10px] text-muted-foreground">{paneLabel}</div>
        </div>
        {/* No New button. An alert is made where the price is, by
            right-clicking the chart at it, and a button here would be a second
            way in that starts from no price at all: the form would open on the
            last close and the trader would type the number they could have
            pointed at. This panel is for what is already watching. */}
        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <button
              type="button"
              aria-label="Alert list actions"
              disabled={view === null}
              className="shrink-0 rounded p-1 text-muted-foreground transition-colors hover:bg-accent hover:text-foreground focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring disabled:pointer-events-none disabled:opacity-40"
            >
              <MoreHorizontal className="h-4 w-4" strokeWidth={1.5} />
            </button>
          </DropdownMenuTrigger>
          <DropdownMenuContent align="end" className="w-44">
            <DropdownMenuItem
              disabled={!view || alerts.length === 0}
              onSelect={() => {
                for (const alert of alerts) view?.alerts.enable(alert.id)
              }}
            >
              Start all
            </DropdownMenuItem>
            <DropdownMenuItem
              disabled={!view || armedCount === 0}
              onSelect={() => {
                for (const alert of alerts) view?.alerts.disable(alert.id)
              }}
            >
              Stop all
            </DropdownMenuItem>
            <DropdownMenuSeparator />
            <DropdownMenuItem
              variant="destructive"
              disabled={!view || alerts.length === 0}
              onSelect={() => {
                for (const alert of alerts) view?.alerts.remove(alert.id)
              }}
            >
              Remove all alerts
            </DropdownMenuItem>
          </DropdownMenuContent>
        </DropdownMenu>
      </div>

      <div role="tablist" aria-label="Alerts and log" className="flex shrink-0 gap-1 border-b px-2">
        <TabButton
          label="Alerts"
          count={alerts.length}
          active={tab === 'alerts'}
          onClick={() => setTab('alerts')}
        />
        <TabButton
          label="Log"
          count={log.length}
          active={tab === 'log'}
          onClick={() => setTab('log')}
        />
      </div>

      <div className="flex shrink-0 items-center gap-1.5 border-b px-2 py-2">
        <input
          type="search"
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          placeholder={tab === 'alerts' ? 'Search alerts' : 'Search log'}
          aria-label={tab === 'alerts' ? 'Search alerts' : 'Search log'}
          className="h-8 min-w-0 flex-1 rounded-md border border-input bg-background px-2.5 text-xs outline-none placeholder:text-muted-foreground focus-visible:ring-1 focus-visible:ring-ring"
        />
        {tab === 'alerts' && (
          <select
            value={sort}
            onChange={(event) => setSort(event.target.value as Sort)}
            aria-label="Sort alerts"
            className="h-8 shrink-0 rounded-md border border-input bg-background px-1.5 text-[11px] outline-none focus-visible:ring-1 focus-visible:ring-ring"
          >
            {SORTS.map((one) => (
              <option key={one.value} value={one.value}>
                {one.label}
              </option>
            ))}
          </select>
        )}
        {tab === 'log' && (
          // On the tab it acts on, rather than in the menu beside "Stop all".
          // The list it empties is the one on screen, and an action that only
          // makes sense here should not be found on the tab where it does not.
          <button
            type="button"
            onClick={onClearLog}
            disabled={log.length === 0}
            className="inline-flex h-8 shrink-0 items-center gap-1 rounded-md border border-input px-2 text-[11px] leading-none text-muted-foreground transition-colors hover:bg-accent hover:text-foreground focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring disabled:pointer-events-none disabled:opacity-40"
          >
            <Eraser className="h-3 w-3" strokeWidth={1.5} />
            Clear
          </button>
        )}
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto">
        {view === null ? (
          <div className="flex items-center justify-center py-10">
            <Loader2 className="h-4 w-4 animate-spin text-muted-foreground" strokeWidth={1.5} />
          </div>
        ) : tab === 'alerts' ? (
          shown.length === 0 ? (
            <div className="flex flex-col items-center gap-3 px-4 py-10 text-center">
              <Bell className="h-6 w-6 text-muted-foreground" strokeWidth={1.5} />
              <p className="max-w-[17rem] text-xs leading-relaxed text-muted-foreground">
                {alerts.length === 0
                  ? 'No alerts on this chart yet. Right-click the chart at a price to set one there and then, or use Alerts on the toolbar for one that needs a condition the defaults do not give it.'
                  : 'No alert matches that search.'}
              </p>
            </div>
          ) : (
            shown.map((alert) => (
              <div
                key={alert.id}
                className="group flex items-start gap-2 border-b px-2 py-2 last:border-b-0 hover:bg-accent/50"
              >
                <span
                  className={cn('mt-1.5 h-2 w-2 shrink-0 rounded-full', STATE_DOT[alert.state])}
                  aria-hidden="true"
                />
                <div className="min-w-0 flex-1">
                  <div className="flex items-baseline gap-1.5">
                    <p className="min-w-0 flex-1 truncate text-xs font-medium">{alert.title}</p>
                    {alert.lastTriggeredAt !== undefined && (
                      <span className="shrink-0 text-[10px] tabular-nums text-muted-foreground">
                        {firedText(alert.lastTriggeredAt)}
                      </span>
                    )}
                  </div>
                  <p className="mt-0.5 truncate text-[11px] text-muted-foreground">
                    {alert.message?.trim() || conditionText(alert)}
                  </p>
                  <div className="mt-1 flex items-center gap-1.5">
                    {alert.scope.symbol && (
                      <span className="shrink-0 rounded border border-border px-1 text-[10px] leading-4 text-muted-foreground">
                        {alert.scope.symbol}
                        {alert.scope.interval ? ` · ${alert.scope.interval}` : ''}
                      </span>
                    )}
                    <span
                      className={cn(
                        'shrink-0 text-[10px]',
                        alert.state === 'armed' ? 'text-emerald-500' : 'text-muted-foreground'
                      )}
                    >
                      {STATE_LABEL[alert.state]}
                    </span>
                  </div>
                  {/*
                    Why an alert that says Active is not watching right now.
                    Since charts 2.5.0 an alert stays visible on other
                    timeframes but is evaluated only on the one it was made on,
                    so a row can read Active on a chart where nothing will fire.
                    Without this the alert looks broken; with it, it says which
                    timeframe to go back to.
                  */}
                  {paused[alert.id] && (
                    <p className="mt-1 text-[10px] leading-4 text-amber-600 dark:text-amber-500">
                      {paused[alert.id]}
                    </p>
                  )}
                </div>
                <RowAction
                  label={
                    alert.state === 'disabled' ? `Start ${alert.title}` : `Stop ${alert.title}`
                  }
                  onClick={() =>
                    alert.state === 'disabled'
                      ? view.alerts.enable(alert.id)
                      : view.alerts.disable(alert.id)
                  }
                >
                  {alert.state === 'disabled' ? (
                    <Play className="h-3.5 w-3.5" strokeWidth={1.5} />
                  ) : (
                    <Pause className="h-3.5 w-3.5" strokeWidth={1.5} />
                  )}
                </RowAction>
                <RowAction label={`Edit ${alert.title}`} onClick={() => onEdit(alert.id)}>
                  <Settings2 className="h-3.5 w-3.5" strokeWidth={1.5} />
                </RowAction>
                <RowAction
                  label={`Delete ${alert.title}`}
                  danger
                  onClick={() => view.alerts.remove(alert.id)}
                >
                  <Trash2 className="h-3.5 w-3.5" strokeWidth={1.5} />
                </RowAction>
              </div>
            ))
          )
        ) : shownLog.length === 0 ? (
          <div className="flex flex-col items-center gap-3 px-4 py-10 text-center">
            <Bell className="h-6 w-6 text-muted-foreground" strokeWidth={1.5} />
            <p className="max-w-[17rem] text-xs leading-relaxed text-muted-foreground">
              {log.length === 0
                ? 'Nothing has fired yet. Alerts are evaluated by the chart that is open, so one only fires while /trading is running. What fires is kept here afterwards.'
                : 'No firing matches that search.'}
            </p>
          </div>
        ) : (
          shownLog.map((fire) => (
            <div key={fire.key} className="border-b px-2 py-2 last:border-b-0">
              <div className="flex items-baseline gap-1.5">
                <p className="min-w-0 flex-1 truncate text-xs font-medium">{fire.title}</p>
                <span className="shrink-0 text-[10px] tabular-nums text-muted-foreground">
                  {firedText(fire.firedAt)}
                </span>
              </div>
              {fire.message.trim() !== '' && (
                <p className="mt-0.5 break-words text-[11px] text-muted-foreground">
                  {fire.message}
                </p>
              )}
              <div className="mt-1 flex items-center gap-1.5">
                {fire.symbol && (
                  <span className="shrink-0 rounded border border-border px-1 text-[10px] leading-4 text-muted-foreground">
                    {fire.symbol}
                  </span>
                )}
                {fire.price !== undefined && (
                  <span className="shrink-0 text-[10px] tabular-nums text-muted-foreground">
                    at {fire.price}
                  </span>
                )}
                {/*
                  Where it went, on the rows read back from the log. A firing
                  that reached nobody shows nothing rather than a "none" badge:
                  the absence is the answer, and the row above already says the
                  alert fired.
                */}
                {fire.delivered?.map((channel) => (
                  <span
                    key={channel}
                    className="shrink-0 rounded bg-muted px-1 text-[10px] leading-4 text-muted-foreground"
                  >
                    {channel}
                  </span>
                ))}
              </div>
            </div>
          ))
        )}
      </div>
    </PanelShell>
  )
}
