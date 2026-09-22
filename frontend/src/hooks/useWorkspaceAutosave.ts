import { useCallback, useEffect, useRef, useState } from 'react'

interface Options<T> {
  identity: string | null
  enabled: boolean
  paused?: boolean
  /** Synchronous ownership guard for timers that run before React commits. */
  isPaused?(): boolean
  capture(): T
  save(snapshot: T): Promise<void>
}
interface Owner {
  identity: string | null
  live: boolean
  dirty: boolean
  baseline: string | undefined
  timer: ReturnType<typeof setTimeout> | null
  running: Promise<void> | null
}
interface View {
  identity: string | null
  status: 'Saved' | 'Unsaved' | 'Saving'
  error: string | null
}

/** Configuration notifications schedule writes; market data never starts a timer. */
export function useWorkspaceAutosave<T>(options: Options<T>) {
  const latest = useRef(options)
  latest.current = options
  const paused = useCallback(
    () => latest.current.paused === true || latest.current.isPaused?.() === true,
    []
  )
  const ownerRef = useRef<Owner | null>(null)
  const [view, setView] = useState<View>({
    identity: options.identity,
    status: options.identity ? 'Saved' : 'Unsaved',
    error: null,
  })
  const owns = useCallback(
    (owner: Owner) =>
      owner.live && ownerRef.current === owner && latest.current.identity === owner.identity,
    []
  )
  const note = useCallback(
    (owner: Owner, status: View['status'], error: string | null = null) => {
      if (owns(owner)) setView({ identity: owner.identity, status, error })
    },
    [owns]
  )
  const clear = useCallback((owner: Owner) => {
    if (owner.timer !== null) clearTimeout(owner.timer)
    owner.timer = null
  }, [])

  const flushOwner = useCallback(
    async function write(owner: Owner): Promise<void> {
      if (!owns(owner) || !owner.identity || paused()) return
      clear(owner)
      if (owner.running) {
        await owner.running
        if (owner.dirty) await write(owner)
        return
      }
      if (!owner.dirty) return
      owner.dirty = false
      const { capture, save } = latest.current
      const operation = (async () => {
        try {
          const snapshot = capture()
          const fingerprint = JSON.stringify(snapshot)
          if (fingerprint !== owner.baseline) {
            note(owner, 'Saving')
            await save(snapshot)
            if (!owns(owner)) return
            owner.baseline = fingerprint
          }
          note(owner, owner.dirty ? 'Unsaved' : 'Saved')
        } catch (error) {
          if (owns(owner)) {
            owner.dirty = true
            note(owner, 'Unsaved', error instanceof Error ? error.message : String(error))
          }
          throw error
        }
      })()
      owner.running = operation
      try {
        await operation
      } finally {
        owner.running = null
      }
      if (owns(owner) && owner.dirty && latest.current.enabled && !paused())
        owner.timer = setTimeout(() => {
          void write(owner).catch(() => {})
        }, 600)
    },
    [clear, note, owns, paused]
  )

  const schedule = useCallback(
    (owner: Owner) => {
      clear(owner)
      if (!owns(owner) || !owner.identity || !owner.dirty || paused() || owner.running) return
      owner.timer = setTimeout(() => {
        if (paused()) {
          owner.timer = null
          return
        }
        if (latest.current.enabled) void flushOwner(owner).catch(() => {})
        else if (owns(owner)) {
          owner.timer = null
          try {
            owner.dirty = JSON.stringify(latest.current.capture()) !== owner.baseline
            note(owner, owner.dirty ? 'Unsaved' : 'Saved')
          } catch (error) {
            note(owner, 'Unsaved', error instanceof Error ? error.message : String(error))
          }
        }
      }, 600)
    },
    [clear, flushOwner, note, owns, paused]
  )

  useEffect(() => {
    const owner: Owner = {
      identity: options.identity,
      live: true,
      dirty: false,
      baseline: undefined,
      timer: null,
      running: null,
    }
    ownerRef.current = owner
    note(owner, owner.identity ? 'Saved' : 'Unsaved')
    return () => {
      owner.live = false
      clear(owner)
      if (ownerRef.current === owner) ownerRef.current = null
    }
  }, [options.identity, clear, note])
  useEffect(() => {
    const owner = ownerRef.current
    if (!owner) return
    if (options.paused) clear(owner)
    else if (options.enabled || owner.dirty) schedule(owner)
  }, [options.enabled, options.paused, schedule, clear])

  const changed = useCallback(() => {
    const owner = ownerRef.current
    if (!owner || !owns(owner)) return
    owner.dirty = true
    note(owner, 'Unsaved')
    schedule(owner)
  }, [note, owns, schedule])
  const markSaved = useCallback(
    (saved?: T) => {
      const owner = ownerRef.current
      if (!owner || !owns(owner)) return
      clear(owner)
      try {
        const current = JSON.stringify(latest.current.capture())
        owner.baseline = saved === undefined ? current : JSON.stringify(saved)
        owner.dirty = current !== owner.baseline
        note(owner, owner.dirty ? 'Unsaved' : 'Saved')
        schedule(owner)
      } catch (error) {
        owner.dirty = true
        note(owner, 'Unsaved', error instanceof Error ? error.message : String(error))
      }
    },
    [clear, note, owns, schedule]
  )
  const flush = useCallback(async () => {
    const owner = ownerRef.current
    if (owner) await flushOwner(owner)
  }, [flushOwner])
  return {
    ...(view.identity === options.identity
      ? view
      : { status: options.identity ? 'Saved' : 'Unsaved', error: null }),
    changed,
    markSaved,
    flush,
  }
}
