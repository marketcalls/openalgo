import type { Bar, IPrimitive } from 'openalgo-charts'

export interface ProfileMenuAction {
  label: string
  sessionLabel: string
  run(): void
}

interface DataPrimitive extends IPrimitive {
  setBars(bars: readonly Bar[]): void
  warning?(): string | null
  contextMenuAt?(x: number, y: number): ProfileMenuAction | null
}

interface ProfileLayerOptions {
  host: {
    addPrimitive(primitive: IPrimitive): void
    removePrimitive(primitive: IPrimitive): void
  }
  load(): Promise<DataPrimitive>
  readBars(): readonly Bar[]
  onError(error: unknown): void
  onWarning?(message: string): void
}

/** Owns lazy profile attachment and coalesces ticks for one chart lifetime. */
export class ProfileLayer {
  readonly ready: Promise<void>
  private primitive: DataPrimitive | null = null
  private timer: ReturnType<typeof setTimeout> | null = null
  private disposed = false
  private lastWarning: string | null = null
  private readonly options: ProfileLayerOptions

  constructor(options: ProfileLayerOptions) {
    this.options = options
    this.ready = this.attach()
  }

  private async attach(): Promise<void> {
    try {
      const primitive = await this.options.load()
      if (this.disposed) return
      primitive.setBars(this.options.readBars())
      this.options.host.addPrimitive(primitive)
      this.primitive = primitive
      this.reportWarning()
    } catch (error) {
      if (!this.disposed) this.options.onError(error)
    }
  }

  refresh(immediate = false): void {
    if (this.disposed || !this.primitive) return
    if (immediate) {
      this.cancelPending()
      try {
        this.primitive.setBars(this.options.readBars())
        this.reportWarning()
      } catch (error) {
        this.dispose()
        this.options.onError(error)
      }
    } else if (this.timer === null) {
      this.timer = setTimeout(() => {
        this.timer = null
        this.refresh(true)
      }, 100)
    }
  }

  contextMenuAt(x: number, y: number): ProfileMenuAction | null {
    const primitive = this.primitive
    if (this.disposed || !primitive) return null
    const action = primitive.contextMenuAt?.(x, y)
    if (!action) return null
    return {
      ...action,
      run: () => {
        if (!this.disposed && this.primitive === primitive) action.run()
      },
    }
  }

  private cancelPending(): void {
    if (this.timer !== null) clearTimeout(this.timer)
    this.timer = null
  }

  dispose(): void {
    if (this.disposed) return
    this.disposed = true
    this.cancelPending()
    if (this.primitive) this.options.host.removePrimitive(this.primitive)
    this.primitive = null
  }

  private reportWarning(): void {
    const warning = this.primitive?.warning?.() ?? null
    if (warning && warning !== this.lastWarning) this.options.onWarning?.(warning)
    this.lastWarning = warning
  }
}
