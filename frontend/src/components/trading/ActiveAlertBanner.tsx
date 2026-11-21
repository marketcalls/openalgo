import { BellRing, VolumeX } from 'lucide-react'
import { useEffect, useState } from 'react'
import { Button } from '@/components/ui/button'
import { alertSoundManager, type RingingAlertInfo } from '@/lib/trading/alertSoundManager'

export function ActiveAlertBanner() {
  const [ringing, setRinging] = useState<readonly RingingAlertInfo[]>([])

  useEffect(() => {
    return alertSoundManager.subscribe((active) => {
      setRinging(active)
    })
  }, [])

  if (ringing.length === 0) return null

  const latest = ringing[ringing.length - 1]
  const count = ringing.length

  return (
    <div
      role="alert"
      aria-live="assertive"
      className="fixed top-4 left-1/2 z-50 flex -translate-x-1/2 items-center gap-3 rounded-lg border border-red-500/50 bg-background/95 px-4 py-2.5 shadow-2xl backdrop-blur transition-all duration-200 animate-in fade-in slide-in-from-top-2"
    >
      <div className="flex items-center gap-2 text-red-500">
        <span className="relative flex h-3 w-3">
          <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-red-400 opacity-75" />
          <span className="relative inline-flex h-3 w-3 rounded-full bg-red-500" />
        </span>
        <BellRing className="h-5 w-5 animate-bounce" />
      </div>

      <div className="max-w-[320px] text-xs sm:max-w-md">
        <div className="flex items-center gap-1.5 font-semibold text-foreground">
          <span>{latest?.title || 'Persistent Alert Ringing'}</span>
          {count > 1 && (
            <span className="rounded bg-red-500/20 px-1.5 py-0.5 text-[10px] text-red-400">
              +{count - 1} more
            </span>
          )}
        </div>
        <p className="text-[11px] text-muted-foreground">
          Sound: <span className="capitalize">{latest?.soundName}</span> • Continuous ringing until
          dismissed
        </p>
      </div>

      <div className="flex items-center gap-1.5 pl-2">
        <Button
          size="sm"
          variant="destructive"
          onClick={() => alertSoundManager.dismissAll()}
          className="h-8 gap-1.5 px-3 text-xs font-semibold shadow"
          title="Stop all ringing sounds"
        >
          <VolumeX className="h-4 w-4" />
          STOP / DISMISS
        </Button>
      </div>
    </div>
  )
}
