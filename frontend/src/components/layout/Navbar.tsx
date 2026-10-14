import { BookOpen, Menu } from 'lucide-react'
import { useState } from 'react'
import { Link, useLocation } from 'react-router'
import { Button } from '@/components/ui/button'
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

        {/* Desktop Navigation.
            Icon-only between md and xl so all 9 items fit portrait monitors
            and small laptops (768-1280px wide) without squashing or pushing
            the profile menu off-screen; full labels from xl up (issue #1384).

            From xl the labels appear but the bar does not grow to match: inside
            Layout it shares the page `container`, which Tailwind caps at 1280px
            for every viewport from 1280px to 1535px. Nine labelled items are
            986px and the logo plus the right-hand controls take 394px, so the
            row needed 1412px and had 1248px (issue #1507). Below 2xl the items
            therefore use px-1.5 with tighter gaps, and the right-hand controls
            keep their tighter gap and the short mode wording already used below
            lg (203px instead of 255px). The padding is deliberately tighter
            than it needs to be on the fonts we develop against: this row is
            laid out with fixed spacing but rendered in whatever the OS resolves
            for `system-ui`, and the widest common face (DejaVu Sans, a Linux
            default) runs ~7% wider than macOS. px-2 left only 2px of slack
            there; px-1.5 leaves ~38px. At 2xl and above nothing changes, and
            e2e/navbar-fit.spec.ts asserts the row never overflows. */}
        <nav className="hidden md:flex items-center gap-0.5 2xl:gap-1">
          {navItems.map((item) => {
            const active = isActive(item.href)
            const className = cn(
              'flex items-center gap-1.5 2xl:gap-2 rounded-md px-1.5 2xl:px-3 py-2 text-sm font-medium transition-colors',
              active
                ? 'bg-primary text-primary-foreground'
                : 'text-muted-foreground hover:bg-muted hover:text-foreground'
            )
            const content = (
              <>
                <item.icon className="h-4 w-4 shrink-0" />
                <span className="hidden xl:inline">{item.label}</span>
              </>
            )
            // Flask-served pages (e.g. /trading) need a full page load,
            // not client-side routing.
            return item.external ? (
              <a
                key={item.href}
                href={item.href}
                title={item.label}
                className={className}
                aria-current={active ? 'page' : undefined}
              >
                {content}
              </a>
            ) : (
              <Link
                key={item.href}
                to={item.href}
                title={item.label}
                className={className}
                aria-current={active ? 'page' : undefined}
              >
                {content}
              </Link>
            )
          })}
        </nav>

        {/* Right Side: shared with the charting terminal's toolbar row. */}
        <div className="ml-auto flex items-center gap-1 2xl:gap-2">
          <AccountControls />
        </div>
      </div>
    </nav>
  )
}
