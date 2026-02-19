import { InboxIcon } from 'lucide-react'

interface EmptyStateProps {
  title?: string
  description?: string
  icon?: React.ReactNode
}

export function EmptyState({
  title = 'No data',
  description = 'Nothing to display yet.',
  icon,
}: EmptyStateProps) {
  return (
    <div className="flex flex-col items-center justify-center py-12 text-center text-muted-foreground">
      {icon || <InboxIcon className="h-10 w-10 mb-3 opacity-40" />}
      <p className="text-sm font-medium">{title}</p>
      <p className="text-xs mt-1">{description}</p>
    </div>
  )
}
