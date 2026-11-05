import { BookOpen, ChevronDown, Menu } from 'lucide-react'
import { useCallback, useState, useSyncExternalStore } from 'react'
import { Link, useLocation } from 'react-router'
import { Button } from '@/components/ui/button'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
  SheetTrigger,
} from '@/components/ui/sheet'
import { isActiveRoute, mobileSheetItems, navItems } from '@/config/navigation'
import { useProfileMenuItems } from '@/hooks/useProfileMenuItems'
import { cn } from '@/lib/utils'
import { AccountControls } from './AccountControls'

// Desktop tab: full bar height so the current-page underline lands on the
// navbar's bottom border. bg-primary is the foreground in Live and the violet
// accent in Analyze.
const TAB =
  'relative flex items-center whitespace-nowrap px-2.5 xl:px-3 text-sm font-medium transition-colors outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-ring'
const TAB_IDLE = 'text-muted-foreground hover:text-foreground'
const TAB_CURRENT =
  'text-foreground after:absolute after:inset-x-2.5 xl:after:inset-x-3 after:-bottom-px after:h-0.5 after:rounded-t-full after:bg-primary'

// Literal class names, so Tailwind sees them when it scans this file.
const COLLAPSE = { lg: 'hidden lg:flex', xl: 'hidden xl:flex' } as const
// Tailwind v4's lg and xl breakpoints.
const BREAKPOINT_QUERY = { lg: '(min-width: 64rem)', xl: '(min-width: 80rem)' } as const

function useMediaQuery(query: string) {
  const subscribe = useCallback(
    (onChange: () => void) => {
      const mql = window.matchMedia(query)
      mql.addEventListener('change', onChange)
      return () => mql.removeEventListener('change', onChange)
    },
    [query]
  )
  return useSyncExternalStore(subscribe, () => window.matchMedia(query).matches)
}

interface NavbarProps {
  /**
   * Span the full viewport instead of the centred, width-capped container.
   *
   * Pages rendered inside Layout share its `container mx-auto`, so the nav
   * lines up with the content below it and this stays false. Full-bleed pages
   * under FullWidthLayout render this navbar themselves and have no such
   * container, so a capped nav floats inset above edge-to-edge content -- on a
   * 1920px screen Tailwind caps `container` at 1536px, leaving ~192px of gutter
   * each side while the page fills the width.
   */
  fluid?: boolean
}

export function Navbar({ fluid = false }: NavbarProps = {}) {
  const location = useLocation()
  const [mobileOpen, setMobileOpen] = useState(false)

  // Profile menu filtered by broker capabilities (shared hook, issue #1480)
  const filteredProfileMenuItems = useProfileMenuItems()

  const isActive = (href: string) => isActiveRoute(location.pathname, href)

  const shown = {
    lg: useMediaQuery(BREAKPOINT_QUERY.lg),
    xl: useMediaQuery(BREAKPOINT_QUERY.xl),
  }
  const overflowItems = navItems.filter((item) => item.collapseBelow && !shown[item.collapseBelow])
  const moreActive = overflowItems.some((item) => isActive(item.href))

  return (
    <nav className="sticky top-0 z-50 w-full border-b bg-background/95 backdrop-blur supports-[backdrop-filter]:bg-background/60">
      <div
        data-testid="navbar-row"
        className={cn('px-4 flex h-14 items-center', fluid ? 'w-full' : 'container mx-auto')}
      >
        {/* Mobile Menu */}
        <Sheet open={mobileOpen} onOpenChange={setMobileOpen}>
          <SheetTrigger asChild className="md:hidden">
            <Button variant="ghost" size="icon" className="mr-2 min-h-[44px] min-w-[44px]">
              <Menu className="h-5 w-5" />
              <span className="sr-only">Toggle menu</span>
            </Button>
          </SheetTrigger>
          <SheetContent side="left" className="w-72 overflow-y-auto">
            {/* Visually hidden but accessible for screen readers */}
            <SheetHeader className="sr-only">
              <SheetTitle>Navigation Menu</SheetTitle>
              <SheetDescription>Main navigation and quick access links</SheetDescription>
            </SheetHeader>
            <div className="flex flex-col gap-4 py-4">
              <Link
                to="/dashboard"
                className="flex items-center gap-2 px-2"
                onClick={() => setMobileOpen(false)}
              >
                <img src="/logo.png" alt="OpenAlgo" className="h-8 w-8" />
                <span className="font-semibold">OpenAlgo</span>
              </Link>

              {/* Secondary nav items (not in bottom nav) */}
              <nav className="flex flex-col gap-1">
                <div className="px-3 py-2 text-xs font-medium text-muted-foreground uppercase tracking-wider">
                  Navigation
                </div>
                {mobileSheetItems.map((item) => {
                  const active = isActive(item.href)
                  const cls = cn(
                    'flex items-center gap-3 rounded-lg px-3 py-3 text-sm transition-colors min-h-[44px] touch-manipulation',
                    active ? 'bg-primary text-primary-foreground' : 'hover:bg-muted active:bg-muted'
                  )
                  const inner = (
                    <>
                      <item.icon className="h-4 w-4" />
                      {item.label}
                    </>
                  )
                  return item.external ? (
                    <a
                      key={item.href}
                      href={item.href}
                      onClick={() => setMobileOpen(false)}
                      className={cls}
                      aria-current={active ? 'page' : undefined}
                    >
                      {inner}
                    </a>
                  ) : (
                    <Link
                      key={item.href}
                      to={item.href}
                      onClick={() => setMobileOpen(false)}
                      className={cls}
                      aria-current={active ? 'page' : undefined}
                    >
                      {inner}
                    </Link>
                  )
                })}
              </nav>

              {/* Profile menu items for mobile access */}
              <nav className="flex flex-col gap-1 border-t pt-4">
                <div className="px-3 py-2 text-xs font-medium text-muted-foreground uppercase tracking-wider">
                  Quick Access
                </div>
                {filteredProfileMenuItems.map((item) => {
                  const active = isActive(item.href)
                  return (
                    <Link
                      key={item.href}
                      to={item.href}
                      onClick={() => setMobileOpen(false)}
                      className={cn(
                        'flex items-center gap-3 rounded-lg px-3 py-3 text-sm transition-colors min-h-[44px] touch-manipulation',
                        active
                          ? 'bg-primary text-primary-foreground'
                          : 'hover:bg-muted active:bg-muted'
                      )}
                      aria-current={active ? 'page' : undefined}
                    >
                      <item.icon className="h-4 w-4" />
                      {item.label}
                    </Link>
                  )
                })}
                <a
                  href="https://docs.openalgo.in"
                  target="_blank"
                  rel="noopener noreferrer"
                  className="flex items-center gap-3 rounded-lg px-3 py-3 text-sm transition-colors min-h-[44px] touch-manipulation hover:bg-muted active:bg-muted"
                  onClick={() => setMobileOpen(false)}
                >
                  <BookOpen className="h-4 w-4" />
                  Docs
                </a>
              </nav>
            </div>
          </SheetContent>
        </Sheet>

        {/* Logo */}
        <Link to="/dashboard" className="flex items-center gap-2 mr-6">
          <img src="/logo.png" alt="OpenAlgo" className="h-8 w-8" />
          <span className="hidden font-semibold sm:inline-block">OpenAlgo</span>
        </Link>

        {/* Desktop Navigation: text tabs, the current page underlined on the
            bar's bottom edge.

            Labels only, no icons. Nine icon-and-label items were 986px and
            overflowed twice (issues #1384 and #1507); before that the bar fell
            back to bare icons below xl, which nobody could tell apart. Instead
            each item names the breakpoint it needs (`collapseBelow` in
            config/navigation.ts) and below that it moves under More: three
            items from md, five from lg, all nine from xl, where More goes away.

            Inside Layout the bar shares the page `container`, which Tailwind
            caps at 1280px for every viewport from 1280px to 1535px, so xl is
            the tightest case. The row is laid out with fixed spacing but
            rendered in whatever the OS resolves for `system-ui`, and the widest
            common face (DejaVu Sans, a Linux default) runs ~7% wider than
            macOS; keep slack for it. e2e/navbar-fit.spec.ts asserts the row
            never overflows. */}
        <nav className="hidden md:flex self-stretch">
          {navItems.map((item) => {
            const active = isActive(item.href)
            const className = cn(
              TAB,
              item.collapseBelow && COLLAPSE[item.collapseBelow],
              active ? TAB_CURRENT : TAB_IDLE
            )
            // Flask-served pages (e.g. /trading) need a full page load,
            // not client-side routing.
            return item.external ? (
              <a
                key={item.href}
                href={item.href}
                className={className}
                aria-current={active ? 'page' : undefined}
              >
                {item.label}
              </a>
            ) : (
              <Link
                key={item.href}
                to={item.href}
                className={className}
                aria-current={active ? 'page' : undefined}
              >
                {item.label}
              </Link>
            )
          })}

          {/* Hidden by CSS from xl, where every item is in the bar. Its list is
              worked out from the same breakpoints in script, so the menu never
              holds an entry that is also showing in the bar. */}
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <button
                type="button"
                className={cn(TAB, 'gap-1 xl:hidden', moreActive ? TAB_CURRENT : TAB_IDLE)}
              >
                More
                <ChevronDown className="h-3.5 w-3.5 opacity-70" />
              </button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="start" className="w-44">
              {overflowItems.map((item) => {
                const active = isActive(item.href)
                const className = cn(
                  'cursor-pointer',
                  active && 'bg-accent font-medium text-accent-foreground'
                )
                return (
                  <DropdownMenuItem key={item.href} asChild className={className}>
                    {item.external ? (
                      <a href={item.href} aria-current={active ? 'page' : undefined}>
                        {item.label}
                      </a>
                    ) : (
                      <Link to={item.href} aria-current={active ? 'page' : undefined}>
                        {item.label}
                      </Link>
                    )}
                  </DropdownMenuItem>
                )
              })}
            </DropdownMenuContent>
          </DropdownMenu>
        </nav>

        {/* Right Side: shared with the charting terminal's toolbar row. */}
        <div className="ml-auto flex items-center gap-1 2xl:gap-2">
          <AccountControls />
        </div>
      </div>
    </nav>
  )
}
