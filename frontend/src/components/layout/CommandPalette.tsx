import {
  BarChart3,
  Bell,
  BookOpen,
  ChevronRight,
  ClipboardList,
  Clock,
  Code2,
  Database,
  FileBarChart,
  FileStack,
  FileText,
  FlaskConical,
  Gauge,
  GitBranch,
  Hash,
  Key,
  LayoutDashboard,
  MessageCircle,
  MessageSquare,
  Search,
  Settings,
  Sparkles,
  Terminal,
  TrendingUp,
  User,
  Workflow,
  Wrench,
  Zap,
} from 'lucide-react'
import { useEffect, useState } from 'react'
import { useLocation, useNavigate } from 'react-router-dom'
import {
  CommandDialog,
  CommandEmpty,
  CommandGroup,
  CommandInput,
  CommandItem,
  CommandList,
  CommandSeparator,
  CommandShortcut,
} from '@/components/ui/command'

// ─── Route catalogue ────────────────────────────────────────────────────────

interface CommandEntry {
  id: string
  label: string
  description?: string
  href: string
  icon: React.ElementType
  group: string
  keywords?: string[]
}

const COMMANDS: CommandEntry[] = [
  // Main
  {
    id: 'dashboard',
    label: 'Dashboard',
    description: 'Overview of your portfolio',
    href: '/dashboard',
    icon: LayoutDashboard,
    group: 'Main',
    keywords: ['home', 'overview', 'portfolio'],
  },
  {
    id: 'orderbook',
    label: 'Order Book',
    description: 'View and manage your orders',
    href: '/orderbook',
    icon: ClipboardList,
    group: 'Main',
    keywords: ['orders', 'buy', 'sell', 'pending'],
  },
  {
    id: 'tradebook',
    label: 'Trade Book',
    description: 'Executed trades history',
    href: '/tradebook',
    icon: FileText,
    group: 'Main',
    keywords: ['trades', 'executed', 'history'],
  },
  {
    id: 'positions',
    label: 'Positions',
    description: 'Open positions & P&L',
    href: '/positions',
    icon: TrendingUp,
    group: 'Main',
    keywords: ['pnl', 'profit', 'loss', 'open positions'],
  },
  {
    id: 'holdings',
    label: 'Holdings',
    description: 'Long-term holdings',
    href: '/holdings',
    icon: Database,
    group: 'Main',
    keywords: ['stocks', 'equity', 'portfolio holdings'],
  },
  {
    id: 'action-center',
    label: 'Action Center',
    description: 'Quick trading actions & alerts',
    href: '/action-center',
    icon: Bell,
    group: 'Main',
    keywords: ['alerts', 'notifications', 'quick trade'],
  },

  // Search / Symbols
  {
    id: 'search-token',
    label: 'Symbol Search',
    description: 'Search for symbols & tokens',
    href: '/search/token',
    icon: Search,
    group: 'Search',
    keywords: ['token', 'symbol', 'search', 'lookup', 'fno', 'nse', 'bse'],
  },

  // Platforms
  {
    id: 'platforms',
    label: 'Platforms',
    description: 'Connect trading platforms',
    href: '/platforms',
    icon: Zap,
    group: 'Platforms',
    keywords: ['tradingview', 'gocharting', 'webhook', 'connect'],
  },
  {
    id: 'tradingview',
    label: 'TradingView',
    description: 'TradingView webhook integration',
    href: '/tradingview',
    icon: BarChart3,
    group: 'Platforms',
    keywords: ['webhook', 'alerts', 'pine script'],
  },
  {
    id: 'gocharting',
    label: 'GoCharting',
    description: 'GoCharting integration',
    href: '/gocharting',
    icon: BarChart3,
    group: 'Platforms',
    keywords: ['charts', 'webhook'],
  },
  {
    id: 'pnl-tracker',
    label: 'PnL Tracker',
    description: 'Profit & loss tracking',
    href: '/pnl-tracker',
    icon: TrendingUp,
    group: 'Platforms',
    keywords: ['profit', 'loss', 'pnl', 'tracker'],
  },

  // Tools
  {
    id: 'tools',
    label: 'Tools Hub',
    description: 'All analytical tools',
    href: '/tools',
    icon: Wrench,
    group: 'Tools',
    keywords: ['options', 'iv', 'oi', 'gex', 'tools'],
  },
  {
    id: 'optionchain',
    label: 'Option Chain',
    description: 'Live option chain viewer',
    href: '/optionchain',
    icon: Hash,
    group: 'Tools',
    keywords: ['options', 'chain', 'strikes', 'expiry'],
  },
  {
    id: 'ivchart',
    label: 'IV Chart',
    description: 'Implied volatility chart',
    href: '/ivchart',
    icon: BarChart3,
    group: 'Tools',
    keywords: ['implied volatility', 'iv', 'options'],
  },
  {
    id: 'ivsmile',
    label: 'IV Smile',
    description: 'Volatility smile visualizer',
    href: '/ivsmile',
    icon: Sparkles,
    group: 'Tools',
    keywords: ['smile', 'volatility', 'skew'],
  },
  {
    id: 'volsurface',
    label: 'Vol Surface',
    description: 'Volatility surface 3D view',
    href: '/volsurface',
    icon: BarChart3,
    group: 'Tools',
    keywords: ['volatility', 'surface', '3d'],
  },
  {
    id: 'oitracker',
    label: 'OI Tracker',
    description: 'Open interest tracker',
    href: '/oitracker',
    icon: BarChart3,
    group: 'Tools',
    keywords: ['open interest', 'oi', 'futures'],
  },
  {
    id: 'oiprofile',
    label: 'OI Profile',
    description: 'Open interest profile',
    href: '/oiprofile',
    icon: BarChart3,
    group: 'Tools',
    keywords: ['oi profile', 'distribution'],
  },
  {
    id: 'maxpain',
    label: 'Max Pain',
    description: 'Options max pain analysis',
    href: '/maxpain',
    icon: Wrench,
    group: 'Tools',
    keywords: ['max pain', 'options analysis'],
  },
  {
    id: 'gex',
    label: 'GEX Dashboard',
    description: 'Gamma exposure dashboard',
    href: '/gex',
    icon: BarChart3,
    group: 'Tools',
    keywords: ['gamma', 'exposure', 'gex', 'dealers'],
  },
  {
    id: 'straddle',
    label: 'Straddle Chart',
    description: 'Options straddle chart',
    href: '/straddle',
    icon: BarChart3,
    group: 'Tools',
    keywords: ['straddle', 'strangle', 'options'],
  },
  {
    id: 'straddlepnl',
    label: 'Custom Straddle P&L',
    description: 'Custom straddle P&L analysis',
    href: '/straddlepnl',
    icon: TrendingUp,
    group: 'Tools',
    keywords: ['straddle', 'pnl', 'custom'],
  },
  {
    id: 'strategybuilder',
    label: 'Strategy Builder',
    description: 'Build options strategies',
    href: '/strategybuilder',
    icon: Workflow,
    group: 'Tools',
    keywords: ['strategy', 'builder', 'payoff', 'options strategy'],
  },
  {
    id: 'historify',
    label: 'Historify',
    description: 'Historical data downloader',
    href: '/historify',
    icon: Database,
    group: 'Tools',
    keywords: ['historical', 'data', 'candles', 'ohlcv'],
  },
  {
    id: 'playground',
    label: 'API Playground',
    description: 'Interactive API testing',
    href: '/playground',
    icon: Terminal,
    group: 'Tools',
    keywords: ['api', 'test', 'playground', 'rest'],
  },
  {
    id: 'analyzer',
    label: 'Log Analyzer',
    description: 'Analyze strategy logs',
    href: '/analyzer',
    icon: FileBarChart,
    group: 'Tools',
    keywords: ['logs', 'analyze', 'sandbox'],
  },

  // Strategies
  {
    id: 'strategy',
    label: 'Webhook Strategies',
    description: 'Manage webhook-based strategies',
    href: '/strategy',
    icon: Code2,
    group: 'Strategy',
    keywords: ['webhook', 'strategy', 'automate'],
  },
  {
    id: 'python',
    label: 'Python Strategies',
    description: 'Python algorithmic strategies',
    href: '/python',
    icon: Code2,
    group: 'Strategy',
    keywords: ['python', 'algo', 'algorithm', 'code'],
  },
  {
    id: 'chartink',
    label: 'Chartink Strategies',
    description: 'Chartink scanner automation',
    href: '/chartink',
    icon: BarChart3,
    group: 'Strategy',
    keywords: ['chartink', 'scanner', 'screener'],
  },
  {
    id: 'flow',
    label: 'Flow Editor',
    description: 'Visual trading flow builder',
    href: '/flow',
    icon: GitBranch,
    group: 'Strategy',
    keywords: ['flow', 'visual', 'automation', 'node'],
  },
  {
    id: 'sandbox',
    label: 'Sandbox',
    description: 'Paper trading environment',
    href: '/sandbox',
    icon: FlaskConical,
    group: 'Strategy',
    keywords: ['paper', 'test', 'simulate', 'sandbox'],
  },

  // Logs
  {
    id: 'logs',
    label: 'Logs',
    description: 'System & strategy logs',
    href: '/logs',
    icon: FileBarChart,
    group: 'Logs & Monitoring',
    keywords: ['logs', 'system', 'activity'],
  },
  {
    id: 'logs-live',
    label: 'Live Logs',
    description: 'Real-time log stream',
    href: '/logs/live',
    icon: FileBarChart,
    group: 'Logs & Monitoring',
    keywords: ['live', 'real-time', 'logs'],
  },
  {
    id: 'logs-security',
    label: 'Security Dashboard',
    description: 'Security events & anomalies',
    href: '/logs/security',
    icon: Settings,
    group: 'Logs & Monitoring',
    keywords: ['security', 'audit', 'breach'],
  },
  {
    id: 'logs-traffic',
    label: 'Traffic Dashboard',
    description: 'API traffic & usage stats',
    href: '/logs/traffic',
    icon: BarChart3,
    group: 'Logs & Monitoring',
    keywords: ['traffic', 'api calls', 'rate limit'],
  },
  {
    id: 'logs-latency',
    label: 'Latency Dashboard',
    description: 'Order latency metrics',
    href: '/logs/latency',
    icon: Gauge,
    group: 'Logs & Monitoring',
    keywords: ['latency', 'speed', 'performance'],
  },
  {
    id: 'health',
    label: 'Health Monitor',
    description: 'System health & status',
    href: '/health',
    icon: Gauge,
    group: 'Logs & Monitoring',
    keywords: ['health', 'status', 'uptime'],
  },

  // Settings
  {
    id: 'profile',
    label: 'Profile',
    description: 'User profile & settings',
    href: '/profile',
    icon: User,
    group: 'Settings',
    keywords: ['user', 'settings', 'account', 'profile'],
  },
  {
    id: 'apikey',
    label: 'API Key',
    description: 'Manage your API keys',
    href: '/apikey',
    icon: Key,
    group: 'Settings',
    keywords: ['api', 'key', 'token', 'secret'],
  },
  {
    id: 'master-contract',
    label: 'Master Contract',
    description: 'Download & update symbol master',
    href: '/master-contract',
    icon: FileStack,
    group: 'Settings',
    keywords: ['master', 'contract', 'symbols', 'download'],
  },
  {
    id: 'telegram',
    label: 'Telegram Bot',
    description: 'Configure Telegram notifications',
    href: '/telegram',
    icon: MessageSquare,
    group: 'Settings',
    keywords: ['telegram', 'bot', 'notification', 'alert'],
  },
  {
    id: 'whatsapp',
    label: 'WhatsApp Bot',
    description: 'WhatsApp trading notifications',
    href: '/whatsapp',
    icon: MessageCircle,
    group: 'Settings',
    keywords: ['whatsapp', 'bot', 'notification'],
  },
  {
    id: 'admin',
    label: 'Admin',
    description: 'Platform administration',
    href: '/admin',
    icon: Settings,
    group: 'Settings',
    keywords: ['admin', 'holidays', 'freeze', 'timings'],
  },
]

// ─── Group order & colours ────────────────────────────────────────────────────
const GROUP_ORDER = ['Main', 'Search', 'Platforms', 'Tools', 'Strategy', 'Logs & Monitoring', 'Settings']

const GROUP_COLORS: Record<string, string> = {
  Main: 'text-blue-500',
  Search: 'text-purple-500',
  Platforms: 'text-orange-500',
  Tools: 'text-green-500',
  Strategy: 'text-pink-500',
  'Logs & Monitoring': 'text-yellow-500',
  Settings: 'text-slate-400',
}

// ─── Recent pages ─────────────────────────────────────────────────────────────
const RECENT_KEY = 'openalgo_recent_pages'
const MAX_RECENT = 5

function loadRecent(): string[] {
  try {
    return JSON.parse(localStorage.getItem(RECENT_KEY) ?? '[]')
  } catch {
    return []
  }
}

function saveRecent(href: string) {
  const prev = loadRecent().filter((h) => h !== href)
  const next = [href, ...prev].slice(0, MAX_RECENT)
  localStorage.setItem(RECENT_KEY, JSON.stringify(next))
}

// ─── Single result row ────────────────────────────────────────────────────────
function CommandRow({
  cmd,
  group,
  onSelect,
  badge,
}: {
  cmd: CommandEntry
  group: string
  onSelect: () => void
  badge?: string
}) {
  const Icon = cmd.icon
  const colorClass = GROUP_COLORS[group] ?? 'text-muted-foreground'
  return (
    <CommandItem
      key={cmd.id}
      value={`${cmd.label} ${cmd.description ?? ''} ${(cmd.keywords ?? []).join(' ')}`}
      onSelect={onSelect}
      className="group flex items-center gap-3 py-2.5 px-3 cursor-pointer rounded-lg"
      id={`cmd-palette-item-${cmd.id}`}
    >
      {/* Icon bubble */}
      <span
        className={`flex h-8 w-8 shrink-0 items-center justify-center rounded-md bg-muted transition-colors group-data-[selected=true]:bg-primary/10 ${colorClass}`}
      >
        <Icon className="h-4 w-4" />
      </span>

      {/* Text */}
      <span className="flex flex-col min-w-0 flex-1">
        <span className="text-sm font-medium leading-tight">{cmd.label}</span>
        {cmd.description && (
          <span className="text-xs text-muted-foreground truncate">{cmd.description}</span>
        )}
      </span>

      {/* Badge (e.g. group label for recent) */}
      {badge && (
        <span className="shrink-0 rounded border px-1.5 py-0.5 text-[10px] text-muted-foreground bg-muted">
          {badge}
        </span>
      )}

      {/* Arrow */}
      <ChevronRight className="h-3.5 w-3.5 opacity-0 group-data-[selected=true]:opacity-50 transition-opacity shrink-0 text-muted-foreground" />
    </CommandItem>
  )
}

// ─── Component ────────────────────────────────────────────────────────────────

interface CommandPaletteProps {
  open: boolean
  onOpenChange: (open: boolean) => void
}

export function CommandPalette({ open, onOpenChange }: CommandPaletteProps) {
  const navigate = useNavigate()
  const location = useLocation()
  const [query, setQuery] = useState('')
  const [recentHrefs, setRecentHrefs] = useState<string[]>([])

  // Track current page in recents whenever the route changes
  useEffect(() => {
    const path = location.pathname
    const match = COMMANDS.find((c) => c.href === path || path.startsWith(c.href + '/'))
    if (match) saveRecent(match.href)
  }, [location.pathname])

  // Load recents & reset query when opened
  useEffect(() => {
    if (open) {
      setQuery('')
      setRecentHrefs(loadRecent())
    }
  }, [open])

  const handleSelect = (cmd: CommandEntry) => {
    saveRecent(cmd.href)
    onOpenChange(false)
    navigate(cmd.href)
  }

  const handleExternalSelect = () => {
    onOpenChange(false)
    window.open('https://docs.openalgo.in', '_blank', 'noopener,noreferrer')
  }

  // Recent commands (excluding current page)
  const recentCmds = recentHrefs
    .filter((h) => h !== location.pathname)
    .map((h) => COMMANDS.find((c) => c.href === h))
    .filter((c): c is CommandEntry => !!c)
    .slice(0, MAX_RECENT)

  // Group commands
  const grouped = GROUP_ORDER.reduce<Record<string, CommandEntry[]>>((acc, group) => {
    acc[group] = COMMANDS.filter((c) => c.group === group)
    return acc
  }, {})

  const isSearching = query.trim().length > 0

  return (
    <CommandDialog
      open={open}
      onOpenChange={onOpenChange}
      title="Navigate OpenAlgo"
      description="Search pages, tools and modules"
      className="max-w-2xl"
      showCloseButton={false}
    >
      <CommandInput
        autoFocus
        placeholder="Search pages, tools, modules…"
        value={query}
        onValueChange={setQuery}
      />

      <CommandList className="max-h-[480px] scrollbar-thin">
        <CommandEmpty>
          <div className="flex flex-col items-center gap-3 py-8 text-muted-foreground">
            <Search className="h-10 w-10 opacity-20" />
            <div className="text-center">
              <p className="text-sm font-medium">No results for &ldquo;{query}&rdquo;</p>
              <p className="text-xs opacity-60 mt-1">Try a different keyword or browse by group</p>
            </div>
          </div>
        </CommandEmpty>

        {/* ── Recent pages (only when not searching) ── */}
        {!isSearching && recentCmds.length > 0 && (
          <>
            <CommandGroup heading="Recently Visited">
              {recentCmds.map((cmd) => (
                <CommandRow
                  key={`recent-${cmd.id}`}
                  cmd={{ ...cmd, icon: Clock }}
                  group={cmd.group}
                  onSelect={() => handleSelect(cmd)}
                  badge={cmd.group}
                />
              ))}
            </CommandGroup>
            <CommandSeparator />
          </>
        )}

        {/* ── All groups ── */}
        {GROUP_ORDER.map((group, gi) => {
          const items = grouped[group] ?? []
          if (!items.length) return null
          return (
            <span key={group}>
              {gi > 0 && !isSearching && recentCmds.length === 0 && gi === 1 ? null : (
                gi > 0 ? <CommandSeparator /> : null
              )}
              <CommandGroup heading={group}>
                {items.map((cmd) => (
                  <CommandRow
                    key={cmd.id}
                    cmd={cmd}
                    group={group}
                    onSelect={() => handleSelect(cmd)}
                  />
                ))}
              </CommandGroup>
            </span>
          )
        })}

        {/* ── Docs ── */}
        <CommandSeparator />
        <CommandGroup heading="Help">
          <CommandItem
            value="documentation docs openalgo help guide"
            onSelect={handleExternalSelect}
            className="group flex items-center gap-3 py-2.5 px-3 cursor-pointer rounded-lg"
            id="cmd-palette-item-docs"
          >
            <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-md bg-muted text-cyan-500">
              <BookOpen className="h-4 w-4" />
            </span>
            <span className="flex flex-col min-w-0 flex-1">
              <span className="text-sm font-medium leading-tight">Documentation</span>
              <span className="text-xs text-muted-foreground">Open docs.openalgo.in</span>
            </span>
            <CommandShortcut>↗</CommandShortcut>
          </CommandItem>
        </CommandGroup>
      </CommandList>

      {/* ── Footer ── */}
      <div className="flex items-center justify-between border-t px-4 py-2 text-[11px] text-muted-foreground bg-muted/30">
        <span className="flex items-center gap-3">
          <span className="flex items-center gap-1">
            <kbd className="rounded border bg-background px-1.5 py-0.5 font-mono text-[10px]">↑↓</kbd>
            navigate
          </span>
          <span className="flex items-center gap-1">
            <kbd className="rounded border bg-background px-1.5 py-0.5 font-mono text-[10px]">↵</kbd>
            open
          </span>
          <span className="flex items-center gap-1">
            <kbd className="rounded border bg-background px-1.5 py-0.5 font-mono text-[10px]">Esc</kbd>
            close
          </span>
        </span>
        <span className="flex items-center gap-1 opacity-50">
          <kbd className="rounded border bg-background px-1.5 py-0.5 font-mono text-[10px]">Ctrl</kbd>
          <kbd className="rounded border bg-background px-1.5 py-0.5 font-mono text-[10px]">K</kbd>
          to open anywhere
        </span>
      </div>
    </CommandDialog>
  )
}
