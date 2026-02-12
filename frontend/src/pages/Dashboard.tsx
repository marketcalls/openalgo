import { BarChart3, BookOpen, FileText, MessageCircle, Search, Zap } from 'lucide-react'
import { useCallback, useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { Badge } from '@/components/ui/badge'
import { Card, CardContent } from '@/components/ui/card'
import { cn } from '@/lib/utils'
import { onModeChange } from '@/stores/themeStore'

interface MarginData {
  availablecash: string
  collateral: string
  m2munrealized: string
  m2mrealized: string
  utiliseddebits: string
}

interface MasterContractStatus {
  status: 'pending' | 'downloading' | 'success' | 'error'
  message?: string
  total_symbols?: number
}

// Format number in Indian format with Cr/L suffixes
function formatIndianNumber(value: string | number): string {
  const num = typeof value === 'string' ? parseFloat(value) : value
  if (Number.isNaN(num)) return '0.00'

  const isNegative = num < 0
  const absNum = Math.abs(num)

  let formatted: string
  if (absNum >= 10000000) {
    // 1 Crore or more
    formatted = `${(absNum / 10000000).toFixed(2)}Cr`
  } else if (absNum >= 100000) {
    // 1 Lakh or more
    formatted = `${(absNum / 100000).toFixed(2)}L`
  } else {
    // Less than 1 Lakh - just decimal format
    formatted = absNum.toFixed(2)
  }

  return isNegative ? `-${formatted}` : formatted
}

// Get color class based on P&L value
function getPnLColor(value: string | number): string {
  const num = typeof value === 'string' ? parseFloat(value) : value
  if (num > 0) return 'text-green-600 dark:text-green-400'
  if (num < 0) return 'text-red-600 dark:text-red-400'
  return 'text-foreground'
}

function getPnLBadgeVariant(value: string | number): 'default' | 'destructive' | 'secondary' {
  const num = typeof value === 'string' ? parseFloat(value) : value
  if (num > 0) return 'default'
  if (num < 0) return 'destructive'
  return 'secondary'
}

export default function Dashboard() {
  const [marginData, setMarginData] = useState<MarginData | null>(null)
  const [isLoading, setIsLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [masterContract, setMasterContract] = useState<MasterContractStatus>({
    status: 'pending',
  })
  const [isAuthenticated, setIsAuthenticated] = useState(true) // Assume authenticated initially

  // Fetch dashboard funds data
  const fetchFundsData = useCallback(async () => {
    try {
      setIsLoading(true)
      const response = await fetch('/auth/dashboard-data', {
        credentials: 'include',
      })

      if (response.status === 401) {
        setIsAuthenticated(false)
        setIsLoading(false)
        return
      }

      const data = await response.json()

      if (data.status === 'success' && data.data) {
        setMarginData(data.data)
        setError(null)
      } else {
        setError(data.message || 'Failed to fetch margin data')
      }
    } catch (err) {
      setError('Failed to fetch margin data')
    } finally {
      setIsLoading(false)
    }
  }, [])

  useEffect(() => {
    fetchFundsData()
    // Refresh every 30 seconds
    const interval = setInterval(fetchFundsData, 30000)
    return () => clearInterval(interval)
  }, [fetchFundsData])

  // Listen for mode changes and refresh data
  useEffect(() => {
    const unsubscribe = onModeChange(() => {
      // Refresh funds data when mode changes
      fetchFundsData()
    })
    return () => unsubscribe()
  }, [fetchFundsData])

  // Check master contract status
  const checkMasterContractStatus = useCallback(async () => {
    try {
      const response = await fetch('/api/master-contract/status', {
        credentials: 'include',
        headers: { Accept: 'application/json' },
      })

      if (response.status === 401) {
        return
      }

      const data = await response.json()
      setMasterContract(data)
    } catch (_err) {
      setMasterContract({ status: 'error', message: 'Failed to check status' })
    }
  }, [])

  useEffect(() => {
    checkMasterContractStatus()

    // Poll every 5 seconds until successful
    const interval = setInterval(() => {
      setMasterContract((prev) => {
        if (prev.status === 'success') {
          return prev // Don't check again if already successful
        }
        checkMasterContractStatus()
        return prev
      })
    }, 5000)

    return () => clearInterval(interval)
  }, [checkMasterContractStatus])

  // Master Contract LED color
  const getMasterContractLedColor = () => {
    switch (masterContract.status) {
      case 'success':
        return 'bg-green-500'
      case 'downloading':
        return 'bg-yellow-500 animate-pulse'
      case 'error':
        return 'bg-red-500'
      default:
        return 'bg-gray-400 animate-pulse'
    }
  }

  const getMasterContractStatusText = () => {
    switch (masterContract.status) {
      case 'success':
        return masterContract.total_symbols
          ? `Ready (${masterContract.total_symbols} symbols)`
          : 'Ready'
      case 'downloading':
        return 'Downloading...'
      case 'error':
        return 'Error'
      default:
        return 'Checking...'
    }
  }

  const getMasterContractTextColor = () => {
    switch (masterContract.status) {
      case 'success':
        return 'text-green-600 dark:text-green-400'
      case 'downloading':
        return 'text-yellow-600 dark:text-yellow-400'
      case 'error':
        return 'text-red-600 dark:text-red-400'
      default:
        return 'text-muted-foreground'
    }
  }

  const quickAccessCards = [
    {
      href: '/search',
      label: 'OpenAlgo Symbols',
      description: 'Universal symbology across brokers',
      icon: Search,
      gradient: 'from-primary/10 to-primary/5 hover:from-primary/20 hover:to-primary/10',
      iconBg: 'bg-primary/20',
      iconColor: 'text-primary',
      borderColor: 'border-primary/20 hover:border-primary/40',
    },
    {
      href: '/logs',
      label: 'Live Logs',
      description: 'Real-time trading activity logs',
      icon: FileText,
      gradient:
        'from-violet-500/10 to-violet-500/5 hover:from-violet-500/20 hover:to-violet-500/10',
      iconBg: 'bg-violet-500/20',
      iconColor: 'text-violet-500',
      borderColor: 'border-violet-500/20 hover:border-violet-500/40',
    },
    {
      href: 'https://docs.openalgo.in',
      label: 'Documentation',
      description: 'Tutorials, API docs & features',
      icon: BookOpen,
      gradient: 'from-cyan-500/10 to-cyan-500/5 hover:from-cyan-500/20 hover:to-cyan-500/10',
      iconBg: 'bg-cyan-500/20',
      iconColor: 'text-cyan-500',
      borderColor: 'border-cyan-500/20 hover:border-cyan-500/40',
      external: true,
    },
    {
      href: '/pnl-tracker',
      label: 'P&L Tracker',
      description: 'Live intraday MTM tracker',
      icon: BarChart3,
      gradient: 'from-green-500/10 to-green-500/5 hover:from-green-500/20 hover:to-green-500/10',
      iconBg: 'bg-green-500/20',
      iconColor: 'text-green-500',
      borderColor: 'border-green-500/20 hover:border-green-500/40',
    },
    {
      href: '/telegram',
      label: 'Telegram Alerts',
      description: 'Configure telegram notifications',
      icon: MessageCircle,
      gradient: 'from-blue-500/10 to-blue-500/5 hover:from-blue-500/20 hover:to-blue-500/10',
      iconBg: 'bg-blue-500/20',
      iconColor: 'text-blue-500',
      borderColor: 'border-blue-500/20 hover:border-blue-500/40',
    },
    {
      href: '/logs/latency',
      label: 'Latency Monitor',
      description: 'Monitor order & API latency',
      icon: Zap,
      gradient:
        'from-orange-500/10 to-orange-500/5 hover:from-orange-500/20 hover:to-orange-500/10',
      iconBg: 'bg-orange-500/20',
      iconColor: 'text-orange-500',
      borderColor: 'border-orange-500/20 hover:border-orange-500/40',
    },
  ]

  // If not authenticated, show login prompt
  if (!isAuthenticated) {
    return (
      <div className="flex flex-col items-center justify-center min-h-[50vh] space-y-4">
        <h1 className="text-2xl font-bold">Session Expired</h1>
        <p className="text-muted-foreground">Please log in to access the dashboard.</p>
        <Link to="/login" className="text-primary hover:underline">
          Go to Login
        </Link>
      </div>
    )
  }

  return (
    <div className="space-y-6 md:space-y-12">
      {/* Dashboard Header */}
      <div className="flex flex-col lg:flex-row lg:items-start gap-4">
        <div className="flex-1">
          <h1 className="text-2xl md:text-3xl font-bold">Trading Dashboard</h1>
          <p className="text-muted-foreground mt-1 md:mt-2 text-sm md:text-base">
            Overview of your trading account and market positions
          </p>
        </div>
        {/* Master Contract Status Indicator */}
        <div className="flex items-center gap-2 md:gap-3 bg-muted rounded-lg px-3 md:px-4 py-2 md:py-3 w-fit lg:ml-auto lg:self-start">
          <span className="text-xs md:text-sm font-medium whitespace-nowrap">Master Contract:</span>
          <div className="flex items-center gap-2">
            <div
              className={cn('w-2.5 h-2.5 md:w-3 md:h-3 rounded-full', getMasterContractLedColor())}
            />
            <span
              className={cn('text-xs md:text-sm', getMasterContractTextColor())}
              title={masterContract.message}
            >
              {getMasterContractStatusText()}
            </span>
          </div>
        </div>
      </div>

      {/* Stats Grid */}
      <div className="grid grid-cols-1 sm:grid-cols-3 lg:grid-cols-5 gap-4 md:gap-6">
        {/* Available Balance */}
        <Card>
          <CardContent className="pt-6">
            <div className="space-y-1">
              <p className="text-sm text-muted-foreground">Available Balance</p>
              <p className="text-2xl font-bold text-primary">
                {isLoading
                  ? '...'
                  : marginData
                    ? formatIndianNumber(marginData.availablecash)
                    : '0.00'}
              </p>
              <Badge variant="secondary" className="mt-2">
                Cash Balance
              </Badge>
            </div>
          </CardContent>
        </Card>

        {/* Collateral */}
        <Card>
          <CardContent className="pt-6">
            <div className="space-y-1">
              <p className="text-sm text-muted-foreground">Collateral</p>
              <p className="text-2xl font-bold text-violet-500 dark:text-violet-400">
                {isLoading
                  ? '...'
                  : marginData
                    ? formatIndianNumber(marginData.collateral)
                    : '0.00'}
              </p>
              <Badge variant="secondary" className="mt-2">
                Total Collateral
              </Badge>
            </div>
          </CardContent>
        </Card>

        {/* Unrealized P&L */}
        <Card>
          <CardContent className="pt-6">
            <div className="space-y-1">
              <p className="text-sm text-muted-foreground">Unrealized P&L</p>
              <p
                className={cn(
                  'text-2xl font-bold',
                  marginData ? getPnLColor(marginData.m2munrealized) : ''
                )}
              >
                {isLoading
                  ? '...'
                  : marginData
                    ? formatIndianNumber(marginData.m2munrealized)
                    : '0.00'}
              </p>
              <Badge
                variant={marginData ? getPnLBadgeVariant(marginData.m2munrealized) : 'secondary'}
                className="mt-2"
              >
                Mark to Market
              </Badge>
            </div>
          </CardContent>
        </Card>

        {/* Realized P&L */}
        <Card>
          <CardContent className="pt-6">
            <div className="space-y-1">
              <p className="text-sm text-muted-foreground">Realized P&L</p>
              <p
                className={cn(
                  'text-2xl font-bold',
                  marginData ? getPnLColor(marginData.m2mrealized) : ''
                )}
              >
                {isLoading
                  ? '...'
                  : marginData
                    ? formatIndianNumber(marginData.m2mrealized)
                    : '0.00'}
              </p>
              <Badge
                variant={marginData ? getPnLBadgeVariant(marginData.m2mrealized) : 'secondary'}
                className="mt-2"
              >
                Booked P&L
              </Badge>
            </div>
          </CardContent>
        </Card>

        {/* Utilised Margin */}
        <Card>
          <CardContent className="pt-6">
            <div className="space-y-1">
              <p className="text-sm text-muted-foreground">Utilised Margin</p>
              <p className="text-2xl font-bold text-cyan-500 dark:text-cyan-400">
                {isLoading
                  ? '...'
                  : marginData
                    ? formatIndianNumber(marginData.utiliseddebits)
                    : '0.00'}
              </p>
              <Badge
                variant="outline"
                className="mt-2 border-cyan-500/50 text-cyan-600 dark:text-cyan-400"
              >
                Used Margin
              </Badge>
            </div>
          </CardContent>
        </Card>
      </div>

      {/* Error Alert */}
      {error && (
        <Card className="border-destructive bg-destructive/5">
          <CardContent className="pt-6">
            <p className="text-destructive text-sm">{error}</p>
          </CardContent>
        </Card>
      )}

      {/* Quick Access Tools */}
      <div>
        <h2 className="text-xl md:text-2xl font-semibold mb-4 md:mb-6">Quick Access</h2>
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-4 md:gap-5">
          {quickAccessCards.map((card) => {
            const cardClasses = cn(
              'block rounded-lg border transition-all duration-300 hover:shadow-lg',
              `bg-gradient-to-br ${card.gradient}`,
              card.borderColor
            )

            const cardContent = (
              <div className="p-4 md:p-5">
                <div className="flex items-start gap-3 md:gap-4">
                  <div className={cn('p-2.5 md:p-3 rounded-lg flex-shrink-0', card.iconBg)}>
                    <card.icon className={cn('h-5 w-5 md:h-6 md:w-6', card.iconColor)} />
                  </div>
                  <div className="flex-1 min-w-0">
                    <h3 className="font-semibold mb-1 text-base md:text-lg">{card.label}</h3>
                    <p className="text-sm text-muted-foreground">{card.description}</p>
                  </div>
                </div>
              </div>
            )

            if (card.external) {
              return (
                <a
                  key={card.href}
                  href={card.href}
                  target="_blank"
                  rel="noopener noreferrer"
                  className={cardClasses}
                >
                  {cardContent}
                </a>
              )
            }

            return (
              <Link key={card.href} to={card.href} className={cardClasses}>
                {cardContent}
              </Link>
            )
          })}
        </div>
      </div>
    </div>
  )
}
