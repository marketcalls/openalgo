import { BarChart3, BookOpen, LogOut, Moon, Sun, Zap } from 'lucide-react'
import { useState } from 'react'
import { useNavigate } from 'react-router'
import { authApi } from '@/api/auth'
import { LogoutConfirmDialog } from '@/components/auth/LogoutConfirmDialog'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import { useProfileMenuItems } from '@/hooks/useProfileMenuItems'
import { cn } from '@/lib/utils'
import { useAuthStore } from '@/stores/authStore'
import { useThemeStore } from '@/stores/themeStore'
import { showToast } from '@/utils/toast'

/**
 * The account end of the app's header: the broker, which mode the platform is
 * in, the switch between Live and Analyze, light or dark, and the profile menu.
 *
 * One component in two places. The navbar shows it on every page, and the
 * charting terminal, which gives the whole viewport to the chart and has no
 * navbar, shows it at the end of its toolbar row. Both run the same mode
 * switch, the same warnings and the same logout, so the terminal cannot drift
 * into a second idea of what switching mode means.
 *
 * `variant` changes metrics only. The navbar keeps its own spacing and the
 * breakpoints its fit test holds it to; the toolbar sizes everything to the
 * terminal's 28px controls.
 */
export function AccountControls({ variant = 'navbar' }: { variant?: 'navbar' | 'toolbar' }) {
  const navigate = useNavigate()
  const [showLogoutDialog, setShowLogoutDialog] = useState(false)
  const { mode, appMode, toggleMode, toggleAppMode, isTogglingMode } = useThemeStore()
  const { user, logout } = useAuthStore()
  const toolbar = variant === 'toolbar'

  // Profile menu filtered by broker capabilities (shared hook, issue #1480)
  const filteredProfileMenuItems = useProfileMenuItems()

  const handleLogout = async () => {
    try {
      await authApi.logout()
      logout()
      navigate('/login')
      showToast.success('Logged out successfully')
    } catch {
      logout()
      navigate('/login')
    }
  }

  const handleModeToggle = async () => {
    const result = await toggleAppMode()
    if (result.success) {
      const newMode = useThemeStore.getState().appMode
      showToast.success(`Switched to ${newMode === 'live' ? 'Live' : 'Analyze'} mode`)

      // Show warning toast when enabling analyzer mode (like old UI)
      if (newMode === 'analyzer') {
        setTimeout(() => {
          showToast.warning('Analyzer (Sandbox) mode is for testing purposes only', undefined, {
            duration: 10000,
          })
        }, 2000)
      }
    } else {
      showToast.error(result.message || 'Failed to toggle mode')
    }
  }

  // The toolbar's quiet button: its glyph on the toolbar surface, a fill on hover.
  const iconButton = toolbar
    ? 'h-7 w-7 rounded-md text-foreground/80 hover:bg-accent hover:text-foreground dark:hover:bg-accent'
    : 'h-8 w-8'
  const glyph = 'h-4 w-4'
  const modeLabel = appMode === 'live' ? 'Live' : 'Analyze'

  return (
    <>
      {/* Broker badge: hidden below lg to keep the bar within narrow
          (portrait/small-laptop) widths */}
      {user?.broker && (
        <Badge
          variant="outline"
          className={cn(
            'hidden lg:flex',
            toolbar ? 'h-6 px-2 text-[11px] font-medium text-muted-foreground' : 'text-xs'
          )}
        >
          {user.broker}
        </Badge>
      )}

      {/* Mode Badge */}
      <Badge
        variant={appMode === 'live' ? 'default' : 'secondary'}
        className={cn(
          toolbar ? 'h-6 px-2 text-[11px]' : 'text-xs',
          appMode === 'analyzer' && 'bg-purple-500 hover:bg-purple-600 text-white'
        )}
      >
        {/* The toolbar shares its row with the whole chart toolbar, so the long
            wording waits for a wider screen there than in the navbar. */}
        <span className={toolbar ? 'hidden min-[1800px]:inline' : 'hidden 2xl:inline'}>
          {modeLabel} Mode
        </span>
        <span className={toolbar ? 'min-[1800px]:hidden' : '2xl:hidden'}>{modeLabel}</span>
      </Badge>

      {/* Mode Toggle */}
      <Button
        variant="ghost"
        size="icon"
        className={iconButton}
        onClick={handleModeToggle}
        disabled={isTogglingMode}
        title={`Switch to ${appMode === 'live' ? 'Analyze' : 'Live'} mode`}
        aria-label={`Switch to ${appMode === 'live' ? 'Analyze' : 'Live'} mode`}
      >
        {isTogglingMode ? (
          <div className="h-4 w-4 animate-spin rounded-full border-2 border-current border-t-transparent" />
        ) : appMode === 'live' ? (
          <Zap className={glyph} />
        ) : (
          <BarChart3 className={glyph} />
        )}
      </Button>

      {/* Theme Toggle */}
      <Button
        variant="ghost"
        size="icon"
        className={iconButton}
        onClick={toggleMode}
        disabled={appMode !== 'live'}
        title={mode === 'light' ? 'Switch to dark mode' : 'Switch to light mode'}
        aria-label={mode === 'light' ? 'Switch to dark mode' : 'Switch to light mode'}
      >
        {mode === 'light' ? <Sun className={glyph} /> : <Moon className={glyph} />}
      </Button>

      {/* Profile Dropdown */}
      <DropdownMenu>
        <DropdownMenuTrigger asChild>
          <Button
            variant="ghost"
            size="icon"
            className={cn(
              'rounded-full bg-primary text-primary-foreground',
              toolbar
                ? 'ml-0.5 h-7 w-7 hover:bg-primary/90 hover:text-primary-foreground dark:hover:bg-primary/90'
                : 'h-8 w-8'
            )}
            aria-label="Open user menu"
          >
            <span className={toolbar ? 'text-[13px] font-semibold' : 'text-sm font-medium'}>
              {user?.username?.[0]?.toUpperCase() || 'O'}
            </span>
          </Button>
        </DropdownMenuTrigger>
        <DropdownMenuContent align="end" className="w-56">
          {filteredProfileMenuItems.map((item) =>
            item.external ? (
              <DropdownMenuItem key={item.href} asChild className="cursor-pointer">
                <a href={item.href} className="flex items-center">
                  <item.icon className="h-4 w-4 mr-2" />
                  {item.label}
                </a>
              </DropdownMenuItem>
            ) : (
              <DropdownMenuItem
                key={item.href}
                onSelect={() => navigate(item.href)}
                className="cursor-pointer"
              >
                <item.icon className="h-4 w-4 mr-2" />
                {item.label}
              </DropdownMenuItem>
            )
          )}
          <DropdownMenuItem asChild>
            <a
              href="https://docs.openalgo.in"
              target="_blank"
              rel="noopener noreferrer"
              className="flex items-center gap-2"
            >
              <BookOpen className="h-4 w-4" />
              Docs
            </a>
          </DropdownMenuItem>
          <DropdownMenuSeparator />
          <DropdownMenuItem
            onClick={() => setShowLogoutDialog(true)}
            className="text-destructive focus:text-destructive"
          >
            <LogOut className="h-4 w-4 mr-2" />
            Logout
          </DropdownMenuItem>
        </DropdownMenuContent>
      </DropdownMenu>

      <LogoutConfirmDialog
        open={showLogoutDialog}
        onOpenChange={setShowLogoutDialog}
        onConfirm={handleLogout}
      />
    </>
  )
}
