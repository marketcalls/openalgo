import { BarChart3, Link as LinkIcon, PackageOpen, ShieldAlert } from 'lucide-react'
import { Link } from 'react-router-dom'
import { Button } from '@/components/ui/button'

type EmptyVariant = 'no-strategies' | 'no-positions' | 'no-trades' | 'no-pnl'

interface EmptyStateProps {
  variant: EmptyVariant
}

const VARIANTS: Record<
  EmptyVariant,
  {
    icon: React.ReactNode
    title: string
    description: string
    actionLabel?: string
    actionTo?: string
  }
> = {
  'no-strategies': {
    icon: <ShieldAlert className="h-12 w-12 opacity-30" />,
    title: 'No strategies being monitored',
    description:
      'Enable risk monitoring on a strategy to see it on this dashboard.',
    actionLabel: 'Go to Strategies',
    actionTo: '/strategy',
  },
  'no-positions': {
    icon: <PackageOpen className="h-10 w-10 opacity-30" />,
    title: 'No open positions',
    description: 'Waiting for webhook signals...',
  },
  'no-trades': {
    icon: <BarChart3 className="h-10 w-10 opacity-30" />,
    title: 'No trades recorded yet',
    description: 'Trades will appear here once positions are opened and closed.',
  },
  'no-pnl': {
    icon: <ShieldAlert className="h-10 w-10 opacity-30" />,
    title: 'No P&L data',
    description: 'Start trading to see performance analytics.',
  },
}

export function EmptyState({ variant }: EmptyStateProps) {
  const config = VARIANTS[variant]

  return (
    <div className="flex flex-col items-center justify-center py-16 text-muted-foreground">
      {config.icon}
      <h3 className="mt-4 text-lg font-medium">{config.title}</h3>
      <p className="mt-1 text-sm max-w-sm text-center">{config.description}</p>
      {config.actionLabel && config.actionTo && (
        <Button variant="outline" asChild className="mt-4">
          <Link to={config.actionTo}>
            <LinkIcon className="h-4 w-4 mr-2" />
            {config.actionLabel}
          </Link>
        </Button>
      )}
      {variant === 'no-positions' && (
        <div className="flex gap-1 mt-4">
          <div className="h-1.5 w-1.5 rounded-full bg-muted-foreground/40 animate-pulse" />
          <div className="h-1.5 w-1.5 rounded-full bg-muted-foreground/40 animate-pulse [animation-delay:150ms]" />
          <div className="h-1.5 w-1.5 rounded-full bg-muted-foreground/40 animate-pulse [animation-delay:300ms]" />
        </div>
      )}
    </div>
  )
}
