import { useNavigate } from 'react-router-dom'
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { Webhook, Layers, FileStack } from 'lucide-react'

interface CreateStrategyDialogProps {
  open: boolean
  onClose: () => void
}

const STRATEGY_TYPES = [
  {
    id: 'webhook',
    icon: Webhook,
    title: 'Webhook Strategy',
    description: 'For equity and signal-based trading',
    route: '/strategy/new',
  },
  {
    id: 'builder',
    icon: Layers,
    title: 'F&O Strategy Builder',
    description: 'For multi-leg options and futures',
    route: '/strategy/builder',
  },
  {
    id: 'template',
    icon: FileStack,
    title: 'From Template',
    description: 'Start with a pre-built strategy',
    route: '/strategy/templates',
  },
] as const

export function CreateStrategyDialog({ open, onClose }: CreateStrategyDialogProps) {
  const navigate = useNavigate()

  const handleSelect = (route: string) => {
    onClose()
    navigate(route)
  }

  return (
    <Dialog open={open} onOpenChange={(v) => !v && onClose()}>
      <DialogContent className="sm:max-w-[400px]">
        <DialogHeader>
          <DialogTitle>Create New Strategy</DialogTitle>
        </DialogHeader>
        <div className="space-y-3 py-2">
          {STRATEGY_TYPES.map((type) => (
            <button
              key={type.id}
              onClick={() => handleSelect(type.route)}
              className="w-full flex items-start gap-3 p-3 rounded-lg border hover:bg-accent transition-colors text-left"
            >
              <type.icon className="h-5 w-5 mt-0.5 text-muted-foreground" />
              <div>
                <div className="text-sm font-medium">{type.title}</div>
                <div className="text-xs text-muted-foreground">{type.description}</div>
              </div>
            </button>
          ))}
        </div>
      </DialogContent>
    </Dialog>
  )
}
