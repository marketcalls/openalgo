import { Link, useLocation } from 'react-router-dom'
import { bottomNavItems, isActiveRoute } from '@/config/navigation'
import { cn } from '@/lib/utils'

export function MobileBottomNav() {
  const location = useLocation()

  return (
    <nav className="md:hidden fixed bottom-0 left-0 right-0 z-50 border-t bg-background/95 backdrop-blur supports-[backdrop-filter]:bg-background/60 safe-area-bottom">
      <div className="flex items-center justify-around h-16">
        {bottomNavItems.map((item) => {
          const active = isActiveRoute(location.pathname, item.href)
          return (
            <Link
              key={item.href}
              to={item.href}
              className={cn(
                'flex flex-col items-center justify-center gap-1 min-w-[64px] min-h-[44px] px-3 py-2 rounded-lg transition-colors touch-manipulation',
                active
                  ? 'text-primary'
                  : 'text-muted-foreground hover:text-foreground active:bg-muted'
              )}
            >
              <item.icon className="h-5 w-5" />
              <span className="text-[10px] font-medium">{item.label}</span>
            </Link>
          )
        })}
      </div>
    </nav>
  )
}
