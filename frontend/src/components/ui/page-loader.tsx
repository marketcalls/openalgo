import { Loader2 } from 'lucide-react'
import { useEffect, useState } from 'react'

const MESSAGE = 'Loading...'

/**
 * How long the status region sits empty before the message goes into it.
 *
 * Several screen readers announce a live region only when its content
 * changes, not when the region appears already holding text, so the region
 * mounts empty and is filled a moment later. A load that finishes sooner
 * announces nothing, which spares a quick page change from being talked over.
 */
export const ANNOUNCE_DELAY_MS = 100

export function PageLoader() {
  const [announce, setAnnounce] = useState(false)

  useEffect(() => {
    const timer = window.setTimeout(() => setAnnounce(true), ANNOUNCE_DELAY_MS)
    return () => window.clearTimeout(timer)
  }, [])

  return (
    <div className="min-h-screen flex items-center justify-center bg-background">
      <div className="flex flex-col items-center gap-4">
        <Loader2 className="h-8 w-8 animate-spin text-primary" aria-hidden="true" />
        {/* What everyone sees, unchanged. Screen readers hear the status below. */}
        <p className="text-sm text-muted-foreground" aria-hidden="true">
          {MESSAGE}
        </p>
        {/* output is a polite status region by default, so no role is needed. */}
        <output className="sr-only">{announce ? MESSAGE : ''}</output>
      </div>
    </div>
  )
}
