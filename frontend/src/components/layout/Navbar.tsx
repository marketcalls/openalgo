import { Link, useLocation, useNavigate } from 'react-router-dom';
import { useState } from 'react';
import {
  LayoutDashboard,
  ClipboardList,
  FileText,
  TrendingUp,
  Bell,
  Layers,
  Code2,
  FileBarChart,
  Menu,
  Sun,
  Moon,
  LogOut,
  Key,
  User,
  Settings,
  MessageSquare,
  Search,
  FlaskConical,
  BookOpen,
  Zap,
  BarChart3,
} from 'lucide-react';
import { cn } from '@/lib/utils';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu';
import { Sheet, SheetContent, SheetTrigger } from '@/components/ui/sheet';
import { useThemeStore } from '@/stores/themeStore';
import { useAuthStore } from '@/stores/authStore';
import { authApi } from '@/api/auth';
import { toast } from 'sonner';

const navItems = [
  { href: '/dashboard', label: 'Dashboard', icon: LayoutDashboard },
  { href: '/orderbook', label: 'Orderbook', icon: ClipboardList },
  { href: '/tradebook', label: 'Tradebook', icon: FileText },
  { href: '/positions', label: 'Positions', icon: TrendingUp },
  { href: '/action-center', label: 'Action Center', icon: Bell },
  { href: '/platforms', label: 'Platforms', icon: Layers },
  { href: '/strategy', label: 'Strategy', icon: Code2 },
  { href: '/logs', label: 'Logs', icon: FileBarChart },
];

export function Navbar() {
  const location = useLocation();
  const navigate = useNavigate();
  const [mobileOpen, setMobileOpen] = useState(false);
  const { mode, appMode, toggleMode, toggleAppMode, isTogglingMode } = useThemeStore();
  const { user, logout } = useAuthStore();

  const handleLogout = async () => {
    try {
      await authApi.logout();
      logout();
      navigate('/login');
      toast.success('Logged out successfully');
    } catch {
      logout();
      navigate('/login');
    }
  };

  const handleModeToggle = async () => {
    const result = await toggleAppMode();
    if (result.success) {
      const newMode = useThemeStore.getState().appMode;
      toast.success(`Switched to ${newMode === 'live' ? 'Live' : 'Analyze'} mode`);

      // Show warning toast when enabling analyzer mode (like old UI)
      if (newMode === 'analyzer') {
        setTimeout(() => {
          toast.warning('⚠️ Analyzer (Sandbox) mode is for testing purposes only', {
            duration: 20000,
          });
        }, 2000);
      }
    } else {
      toast.error(result.message || 'Failed to toggle mode');
    }
  };

  const isActive = (href: string) => location.pathname === href;

  return (
    <nav className="sticky top-0 z-50 w-full border-b bg-background/95 backdrop-blur supports-[backdrop-filter]:bg-background/60">
      <div className="container mx-auto px-4 flex h-14 items-center">
        {/* Mobile Menu */}
        <Sheet open={mobileOpen} onOpenChange={setMobileOpen}>
          <SheetTrigger asChild className="lg:hidden">
            <Button variant="ghost" size="icon" className="mr-2">
              <Menu className="h-5 w-5" />
              <span className="sr-only">Toggle menu</span>
            </Button>
          </SheetTrigger>
          <SheetContent side="left" className="w-72">
            <div className="flex flex-col gap-4 py-4">
              <Link to="/dashboard" className="flex items-center gap-2 px-2" onClick={() => setMobileOpen(false)}>
                <img src="/logo.png" alt="OpenAlgo" className="h-8 w-8" />
                <span className="font-semibold">OpenAlgo</span>
              </Link>
              <nav className="flex flex-col gap-1">
                {navItems.map((item) => (
                  <Link
                    key={item.href}
                    to={item.href}
                    onClick={() => setMobileOpen(false)}
                    className={cn(
                      'flex items-center gap-3 rounded-lg px-3 py-2 text-sm transition-colors',
                      isActive(item.href)
                        ? 'bg-primary text-primary-foreground'
                        : 'hover:bg-muted'
                    )}
                  >
                    <item.icon className="h-4 w-4" />
                    {item.label}
                  </Link>
                ))}
              </nav>
            </div>
          </SheetContent>
        </Sheet>

        {/* Logo */}
        <Link to="/dashboard" className="flex items-center gap-2 mr-6">
          <img src="/logo.png" alt="OpenAlgo" className="h-8 w-8" />
          <span className="hidden font-semibold sm:inline-block">OpenAlgo</span>
        </Link>

        {/* Desktop Navigation */}
        <nav className="hidden lg:flex items-center gap-1">
          {navItems.map((item) => (
            <Link
              key={item.href}
              to={item.href}
              className={cn(
                'flex items-center gap-2 rounded-md px-3 py-2 text-sm font-medium transition-colors',
                isActive(item.href)
                  ? 'bg-primary text-primary-foreground'
                  : 'text-muted-foreground hover:bg-muted hover:text-foreground'
              )}
            >
              {item.label}
            </Link>
          ))}
        </nav>

        {/* Right Side */}
        <div className="ml-auto flex items-center gap-1 sm:gap-2">
          {/* Broker Badge */}
          {user?.broker && (
            <Badge variant="outline" className="hidden sm:flex text-xs">
              {user.broker}
            </Badge>
          )}

          {/* Mode Badge */}
          <Badge
            variant={appMode === 'live' ? 'default' : 'secondary'}
            className={cn(
              'text-xs',
              appMode === 'analyzer' && 'bg-purple-500 hover:bg-purple-600 text-white'
            )}
          >
            <span className="hidden sm:inline">{appMode === 'live' ? 'Live Mode' : 'Analyze Mode'}</span>
            <span className="sm:hidden">{appMode === 'live' ? 'Live' : 'Analyze'}</span>
          </Badge>

          {/* Mode Toggle */}
          <Button
            variant="ghost"
            size="icon"
            className="h-8 w-8"
            onClick={handleModeToggle}
            disabled={isTogglingMode}
            title={`Switch to ${appMode === 'live' ? 'Analyze' : 'Live'} mode`}
          >
            {isTogglingMode ? (
              <div className="h-4 w-4 animate-spin rounded-full border-2 border-current border-t-transparent" />
            ) : appMode === 'live' ? (
              <Zap className="h-4 w-4" />
            ) : (
              <BarChart3 className="h-4 w-4" />
            )}
          </Button>

          {/* Theme Toggle */}
          <Button
            variant="ghost"
            size="icon"
            className="h-8 w-8"
            onClick={toggleMode}
            disabled={appMode !== 'live'}
            title={mode === 'light' ? 'Switch to dark mode' : 'Switch to light mode'}
          >
            {mode === 'light' ? (
              <Sun className="h-4 w-4" />
            ) : (
              <Moon className="h-4 w-4" />
            )}
          </Button>

          {/* Profile Dropdown */}
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <Button variant="ghost" size="icon" className="h-8 w-8 rounded-full bg-primary text-primary-foreground">
                <span className="text-sm font-medium">
                  {user?.username?.[0]?.toUpperCase() || 'O'}
                </span>
              </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end" className="w-56">
              <DropdownMenuItem onSelect={() => navigate('/profile')} className="cursor-pointer">
                <User className="h-4 w-4 mr-2" />
                Profile
              </DropdownMenuItem>
              <DropdownMenuItem onSelect={() => navigate('/apikey')} className="cursor-pointer">
                <Key className="h-4 w-4 mr-2" />
                API Key
              </DropdownMenuItem>
              <DropdownMenuItem onSelect={() => navigate('/telegram')} className="cursor-pointer">
                <MessageSquare className="h-4 w-4 mr-2" />
                Telegram Bot
              </DropdownMenuItem>
              <DropdownMenuItem onSelect={() => navigate('/holdings')} className="cursor-pointer">
                <ClipboardList className="h-4 w-4 mr-2" />
                Holdings
              </DropdownMenuItem>
              <DropdownMenuItem onSelect={() => navigate('/python')} className="cursor-pointer">
                <Code2 className="h-4 w-4 mr-2" />
                Python Strategies
              </DropdownMenuItem>
              <DropdownMenuItem onSelect={() => navigate('/pnl-tracker')} className="cursor-pointer">
                <BarChart3 className="h-4 w-4 mr-2" />
                PnL Tracker
              </DropdownMenuItem>
              <DropdownMenuItem onSelect={() => navigate('/search/token')} className="cursor-pointer">
                <Search className="h-4 w-4 mr-2" />
                Search
              </DropdownMenuItem>
              <DropdownMenuItem onSelect={() => navigate('/sandbox')} className="cursor-pointer">
                <FlaskConical className="h-4 w-4 mr-2" />
                Sandbox
              </DropdownMenuItem>
              <DropdownMenuItem onSelect={() => navigate('/admin')} className="cursor-pointer">
                <Settings className="h-4 w-4 mr-2" />
                Admin
              </DropdownMenuItem>
              <DropdownMenuItem asChild>
                <a href="https://docs.openalgo.in" target="_blank" rel="noopener noreferrer" className="flex items-center gap-2">
                  <BookOpen className="h-4 w-4" />
                  Docs
                </a>
              </DropdownMenuItem>
              <DropdownMenuSeparator />
              <DropdownMenuItem onClick={handleLogout} className="text-destructive focus:text-destructive">
                <LogOut className="h-4 w-4 mr-2" />
                Logout
              </DropdownMenuItem>
            </DropdownMenuContent>
          </DropdownMenu>
        </div>
      </div>
    </nav>
  );
}
