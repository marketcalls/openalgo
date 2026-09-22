import { type ChartObjects, createLinkGroup } from 'openalgo-charts'
import { parseWorkspacePayload, type WorkspacePayload } from 'openalgo-charts/workspace'
import type { TradingTerminal } from './terminal'
import { workspaceGridGeometry } from './workspaceGrid'

let generation = 0
const isolated = { crosshair: false, viewport: false, symbol: false, interval: false }

/** Created by the workspace transition, never during a React render. */
export class PreparedChartGrid {
  readonly key = `workspace-${++generation}`
  readonly payload: WorkspacePayload
  readonly geometry: ReturnType<typeof workspaceGridGeometry>
  readonly linkGroup
  readonly terminals = new Map<string, TradingTerminal>()
  readonly symbols = new Map<string, string | null>()
  readonly objects = new Map<string, ChartObjects>()
  readonly ready: Promise<void>
  private readonly initializedPanes = new Set<string>()
  private resolve!: () => void
  private reject!: (error: unknown) => void
  private closed = false
  private failure: unknown
  private locked = true

  get disposed(): boolean {
    return this.closed
  }

  constructor(input: WorkspacePayload) {
    this.payload = parseWorkspacePayload(input)
    this.geometry = workspaceGridGeometry(this.payload)
    this.linkGroup = createLinkGroup(isolated)
    this.ready = new Promise<void>((resolve, reject) => {
      this.resolve = resolve
      this.reject = reject
    })
    // Cancellation can happen before the transition starts awaiting this promise.
    void this.ready.catch(() => {})
  }

  register(id: string, terminal: TradingTerminal | null): void {
    if (this.closed) return
    if (!this.payload.panes.some((pane) => pane.id === id))
      throw new Error('Unknown workspace pane')
    this.initializedPanes.delete(id)
    if (terminal) {
      this.terminals.set(id, terminal)
      terminal.setWorkspaceTransitionLocked(this.locked)
      if (this.locked) terminal.setArmed(false)
    } else this.terminals.delete(id)
  }

  initialized(id: string, terminal: TradingTerminal): void {
    if (this.closed || this.failure || this.terminals.get(id) !== terminal) return
    this.initializedPanes.add(id)
    if (this.initializedPanes.size === this.payload.panes.length) this.resolve()
  }

  fail(error: unknown): void {
    if (this.closed) return
    this.failure = error instanceof Error ? error : new Error(String(error))
    this.reject(this.failure)
  }

  activate(sync: WorkspacePayload['sync']): void {
    this.assertReady()
    this.linkGroup.setOptions(sync)
  }

  setLocked(locked: boolean): void {
    if (this.closed) return
    this.locked = locked
    for (const terminal of this.terminals.values()) {
      terminal.setWorkspaceTransitionLocked(locked)
      if (locked) terminal.setArmed(false)
    }
  }

  capture(activePaneId: string, sync: WorkspacePayload['sync']): WorkspacePayload {
    this.assertReady()
    return parseWorkspacePayload({
      ...this.payload,
      activePaneId,
      sync,
      panes: this.payload.panes.map((pane) =>
        this.terminals.get(pane.id)!.captureWorkspacePane(pane.id)
      ),
    })
  }

  destroy(): void {
    if (this.closed) return
    this.closed = true
    this.reject(new Error('Workspace grid is closed'))
    const terminals = [...this.terminals.values()]
    this.terminals.clear()
    this.symbols.clear()
    this.objects.clear()
    this.initializedPanes.clear()
    const errors: unknown[] = []
    const release = (action: () => void) => {
      try {
        action()
      } catch (error) {
        errors.push(error)
      }
    }
    for (const terminal of terminals) {
      // One host callback must not prevent the other charts from releasing feeds.
      release(() => terminal.setWorkspaceTransitionLocked(true))
      release(() => terminal.setArmed(false))
      release(() => terminal.destroy())
    }
    release(() => this.linkGroup.destroy())
    if (errors.length) throw new AggregateError(errors, 'Workspace cleanup failed')
  }

  private assertReady(): void {
    if (this.closed) throw new Error('Workspace grid is closed')
    if (this.failure) throw this.failure
    if (this.initializedPanes.size !== this.payload.panes.length)
      throw new Error('Every workspace pane must be ready')
  }
}
