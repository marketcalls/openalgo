import { Loader2 } from 'lucide-react'

export function PageLoader() {
  return (
    <div className="min-h-screen flex items-center justify-center bg-background">
      <div className="flex flex-col items-center gap-4">
        <Loader2 className="h-8 w-8 animate-spin text-primary" aria-hidden="true" />
        {/* biome-ignore lint/a11y/useSemanticElements: accessibility status role for screen readers */}
        <p className="text-sm text-muted-foreground" role="status">
          Loading...
        </p>
      </div>
    </div>
  )
}
