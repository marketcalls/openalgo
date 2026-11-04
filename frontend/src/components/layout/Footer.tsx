import { Monitor } from 'lucide-react'
import { useEffect, useState } from 'react'
import { Link } from 'react-router'
import { BRAND } from '@/brand/brand'
import { Badge } from '@/components/ui/badge'
import { cn } from '@/lib/utils'
import { useSessionStore } from '@/stores/sessionStore'

interface FooterProps {
  className?: string
}

export function Footer({ className }: FooterProps) {
  const [version, setVersion] = useState<string>('')
  const activeSessionCount = useSessionStore((s) => s.activeSessionCount)

  useEffect(() => {
    const fetchVersion = async () => {
      try {
        const response = await fetch('/auth/app-info')
        const data = await response.json()
        if (data.status === 'success') {
          setVersion(data.version)
        }
      } catch (_error) {}
    }

    fetchVersion()
  }, [])

  return (
    <footer className={cn('mt-auto border-t bg-muted/30', className)}>
      <div className="container mx-auto px-4 py-6">
        <div className="flex flex-col md:flex-row items-center justify-center gap-2 md:gap-4 text-sm text-muted-foreground">
          <div className="flex items-center gap-2">
            <a
              href={BRAND.makerUrl}
              className="text-foreground hover:underline font-medium"
              target="_blank"
              rel="noopener noreferrer"
            >
              {BRAND.endorsement}
            </a>
          </div>
          <span className="text-center">{BRAND.tagline}</span>
          {version && (
            <>
              <span className="hidden md:inline">|</span>
              <Badge variant="secondary" className="gap-1">
                <span className="opacity-75">v</span>
                <span>{version}</span>
              </Badge>
            </>
          )}
          {activeSessionCount > 0 && (
            <>
              <span className="hidden md:inline">|</span>
              <Badge variant="outline" className="gap-1">
                <Monitor className="h-3 w-3" />
                <span>
                  {activeSessionCount} {activeSessionCount === 1 ? 'session' : 'sessions'}
                </span>
              </Badge>
            </>
          )}
        </div>

        <div className="flex flex-wrap items-center justify-center gap-x-4 gap-y-1 mt-3 text-xs text-muted-foreground">
          <Link to="/about" className="hover:underline">
            About
          </Link>
          <a
            href={BRAND.supportUrl}
            target="_blank"
            rel="noopener noreferrer"
            className="hover:underline"
          >
            Get support
          </a>
          <span>
            {BRAND.attribution} (
            <a
              href={BRAND.sourceUrl}
              target="_blank"
              rel="noopener noreferrer"
              className="hover:underline"
            >
              source code
            </a>
            )
          </span>
        </div>

        <div className="mt-1 text-center text-xs text-muted-foreground">
          Contact:{' '}
          <a href={`mailto:${BRAND.supportEmail}`} className="hover:underline">
            {BRAND.supportEmail}
          </a>
          {' · '}
          <a
            href={BRAND.supportTelegramUrl}
            target="_blank"
            rel="noopener noreferrer"
            className="hover:underline"
          >
            Telegram
          </a>
        </div>
      </div>
    </footer>
  )
}
