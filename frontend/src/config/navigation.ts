import {
  BarChart3,
  Bell,
  BookOpen,
  ClipboardList,
  Code2,
  Database,
  FileBarChart,
  FileStack,
  FileText,
  FlaskConical,
  Key,
  Layers,
  LayoutDashboard,
  type LucideIcon,
  MessageSquare,
  Search,
  Settings,
  TrendingUp,
  User,
  Workflow,
  Wrench,
} from 'lucide-react'

export interface NavItem {
  href: string
  label: string
  icon: LucideIcon
}

// Main navigation items shown in desktop navbar
export const navItems: NavItem[] = [
  { href: '/dashboard', label: 'Dashboard', icon: LayoutDashboard },
  { href: '/orderbook', label: 'Orderbook', icon: ClipboardList },
  { href: '/tradebook', label: 'Tradebook', icon: FileText },
  { href: '/positions', label: 'Positions', icon: TrendingUp },
  { href: '/action-center', label: 'Action Center', icon: Bell },
  { href: '/platforms', label: 'Platforms', icon: Layers },
  { href: '/strategy', label: 'Strategy', icon: Code2 },
  { href: '/logs', label: 'Logs', icon: FileBarChart },
  { href: '/tools', label: 'Tools', icon: Wrench },
]

// Items shown in mobile bottom navigation
export const bottomNavItems: NavItem[] = [
  { href: '/dashboard', label: 'Dashboard', icon: LayoutDashboard },
  { href: '/orderbook', label: 'Orderbook', icon: ClipboardList },
  { href: '/tradebook', label: 'Tradebook', icon: FileText },
  { href: '/positions', label: 'Positions', icon: TrendingUp },
  { href: '/strategy', label: 'Strategy', icon: Code2 },
]

// Paths in bottom nav (for filtering mobile sheet items)
const bottomNavPaths = bottomNavItems.map((item) => item.href)

// Secondary items for mobile sheet (items not in bottom nav)
export const mobileSheetItems = navItems.filter((item) => !bottomNavPaths.includes(item.href))

// Profile dropdown menu items
export const profileMenuItems: NavItem[] = [
  { href: '/profile', label: 'Profile', icon: User },
  { href: '/apikey', label: 'API Key', icon: Key },
  { href: '/master-contract', label: 'Master Contract', icon: FileStack },
  { href: '/telegram', label: 'Telegram Bot', icon: MessageSquare },
  { href: '/holdings', label: 'Holdings', icon: ClipboardList },
  { href: '/flow', label: 'Flow Editor', icon: Workflow },
  { href: '/python', label: 'Python Strategies', icon: Code2 },
  { href: '/pnl-tracker', label: 'PnL Tracker', icon: BarChart3 },
  { href: '/historify', label: 'Historify', icon: Database },
  { href: '/search/token', label: 'Search', icon: Search },
  { href: '/sandbox', label: 'Sandbox', icon: FlaskConical },
  { href: '/admin', label: 'Admin', icon: Settings },
]

// External links
export const externalLinks = {
  docs: { href: 'https://docs.openalgo.in', label: 'Docs', icon: BookOpen },
}

// Shared utility to check if a route is active
// Uses startsWith for routes with nested pages (like /strategy/*)
export function isActiveRoute(pathname: string, href: string): boolean {
  if (href === '/strategy') {
    return pathname.startsWith('/strategy')
  }
  return pathname === href
}
