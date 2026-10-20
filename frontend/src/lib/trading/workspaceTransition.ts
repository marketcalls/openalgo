export interface PreparedWorkspaceGrid {
  ready: Promise<void>
  destroy(): void
}

interface Preparation<T extends PreparedWorkspaceGrid> {
  controller: AbortController
  grid: T | null
  released: boolean
}

/** Stop waiting immediately on cancellation while consuming any late rejection. */
function owned<T>(promise: Promise<T>, signal: AbortSignal): Promise<T> {
  return new Promise<T>((resolve, reject) => {
    const cancel = () => reject(signal.reason)
    const cleanup = () => signal.removeEventListener('abort', cancel)
    promise.then(
      (value) => {
        cleanup()
        resolve(value)
      },
      (error) => {
        cleanup()
        reject(error)
      }
    )
    if (signal.aborted) cancel()
    else signal.addEventListener('abort', cancel, { once: true })
  })
}

/** A page/account owns one coordinator; failed preparations leave its current grid intact. */
export class WorkspaceTransition<T extends PreparedWorkspaceGrid> {
  private current: T | null
  private pending: Preparation<T> | null = null
  private closed = false
  private readonly onPending: (pending: boolean) => void
  private readonly onCleanupError: (error: unknown) => void

  constructor(
    initial: T | null = null,
    onPending: (pending: boolean) => void = () => {},
    onCleanupError: (error: unknown) => void = (error) =>
      console.error('Workspace cleanup failed', error)
  ) {
    this.current = initial
    this.onPending = onPending
    this.onCleanupError = onCleanupError
  }

  async open(
    prepare: (signal: AbortSignal) => T,
    persist: (signal: AbortSignal) => Promise<unknown>,
    publish: (grid: T) => void
  ): Promise<T> {
    if (this.closed) throw new Error('Workspace owner is closed')
    this.cancel()
    const operation: Preparation<T> = {
      controller: new AbortController(),
      grid: null,
      released: false,
    }
    this.pending = operation
    this.onPending(true)
    const { signal } = operation.controller
    try {
      const grid = prepare(signal)
      if (grid === this.current) throw new Error('Prepare a new grid before switching workspaces')
      operation.grid = grid
      await owned(grid.ready, signal)
      this.assertCurrent(operation)
      // Storage must honor this signal until its atomic commit point.
      await owned(persist(signal), signal)
      this.assertCurrent(operation)
      const previous = this.current
      // Publication is a synchronous host state update, after persistence succeeds.
      publish(grid)
      this.current = grid
      this.pending = null
      this.dispose(previous)
      this.onPending(false)
      return grid
    } catch (error) {
      operation.controller.abort(error)
      this.release(operation)
      if (this.pending === operation) {
        this.pending = null
        this.onPending(false)
      }
      throw error
    }
  }

  cancel(): void {
    const operation = this.pending
    if (!operation) return
    this.pending = null
    operation.controller.abort(new Error('Workspace preparation was cancelled'))
    this.release(operation)
    this.onPending(false)
  }

  destroy(): void {
    if (this.closed) return
    this.closed = true
    this.cancel()
    const current = this.current
    this.current = null
    this.dispose(current)
  }

  private assertCurrent(operation: Preparation<T>): void {
    operation.controller.signal.throwIfAborted()
    if (this.closed || this.pending !== operation)
      throw new Error('Workspace preparation was cancelled')
  }

  private release(operation: Preparation<T>): void {
    if (operation.released || !operation.grid) return
    operation.released = true
    this.dispose(operation.grid)
  }

  private dispose(grid: T | null): void {
    try {
      grid?.destroy()
    } catch (error) {
      // A cleanup failure must not roll back an already published replacement.
      this.onCleanupError(error)
    }
  }
}
