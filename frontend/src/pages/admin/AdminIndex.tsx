import {
  Activity,
  ArrowRight,
  Calendar,
  Clock,
  Settings,
  Shield,
  Snowflake,
  Zap,
} from 'lucide-react'
import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { adminApi } from '@/api/admin'
import { Badge } from '@/components/ui/badge'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import type { AdminStats } from '@/types/admin'

export default function AdminIndex() {
  const [stats, setStats] = useState<AdminStats | null>(null)
  const [isLoading, setIsLoading] = useState(true)

  useEffect(() => {
    const fetchStats = async () => {
      try {
        const data = await adminApi.getStats()
        setStats(data)
      } catch (error) {
      } finally {
        setIsLoading(false)
      }
    }

    fetchStats()
  }, [])

  const adminCards = [
    {
      title: 'Freeze Quantity',
      description: 'Manage F&O freeze quantity limits for order splitting',
      icon: Snowflake,
      href: '/admin/freeze',
      count: stats?.freeze_count,
      countLabel: 'entries',
      color: 'bg-blue-500',
    },
    {
      title: 'Market Holidays',
      description: 'View and manage market holidays for all exchanges',
      icon: Calendar,
      href: '/admin/holidays',
      count: stats?.holiday_count,
      countLabel: 'holidays',
      color: 'bg-green-500',
    },
    {
      title: 'Market Timings',
      description: 'Configure trading session timings for each exchange',
      icon: Clock,
      href: '/admin/timings',
      count: 7,
      countLabel: 'exchanges',
      color: 'bg-purple-500',
    },
    {
      title: 'Security Dashboard',
      description: 'Monitor IP bans, API abuse, and security threats',
      icon: Shield,
      href: '/logs/security',
      countLabel: 'monitoring',
      color: 'bg-red-500',
    },
    {
      title: 'Traffic Dashboard',
      description: 'Monitor HTTP traffic and API request logs',
      icon: Activity,
      href: '/logs/traffic',
      countLabel: 'monitoring',
      color: 'bg-cyan-500',
    },
    {
      title: 'Latency Dashboard',
      description: 'Monitor order execution and API latency',
      icon: Zap,
      href: '/logs/latency',
      countLabel: 'monitoring',
      color: 'bg-orange-500',
    },
  ]

  if (isLoading) {
    return (
      <div className="flex items-center justify-center py-16">
        <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-primary"></div>
      </div>
    )
  }

  return (
    <div className="py-6 space-y-6">
      {/* Header */}
      <div>
        <h1 className="text-2xl font-bold flex items-center gap-2">
          <Settings className="h-6 w-6" />
          Admin Dashboard
        </h1>
        <p className="text-muted-foreground mt-1">
          Manage system settings, market data, and configurations
        </p>
      </div>

      {/* Admin Cards Grid */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
        {adminCards.map((card) => (
          <Link key={card.href} to={card.href}>
            <Card className="h-full hover:shadow-lg transition-shadow cursor-pointer group">
              <CardHeader>
                <div className="flex items-center justify-between">
                  <div
                    className={`w-10 h-10 rounded-lg ${card.color} flex items-center justify-center`}
                  >
                    <card.icon className="h-5 w-5 text-white" />
                  </div>
                  {card.count !== undefined && (
                    <Badge variant="secondary">
                      {card.count} {card.countLabel}
                    </Badge>
                  )}
                </div>
                <CardTitle className="flex items-center gap-2 group-hover:text-primary transition-colors">
                  {card.title}
                  <ArrowRight className="h-4 w-4 opacity-0 group-hover:opacity-100 transition-opacity" />
                </CardTitle>
                <CardDescription>{card.description}</CardDescription>
              </CardHeader>
              <CardContent>
                <div className="text-sm text-muted-foreground">
                  Click to manage {card.title.toLowerCase()}
                </div>
              </CardContent>
            </Card>
          </Link>
        ))}
      </div>

      {/* Info Section */}
      <Card>
        <CardHeader>
          <CardTitle>About Admin Settings</CardTitle>
        </CardHeader>
        <CardContent className="prose prose-sm dark:prose-invert max-w-none">
          <p className="text-muted-foreground">
            The admin dashboard provides tools to manage critical system configurations:
          </p>
          <ul className="text-muted-foreground space-y-2 list-disc list-inside">
            <li>
              <strong>Freeze Quantity:</strong> Set maximum order quantities for F&O instruments.
              Orders exceeding these limits will be automatically split.
            </li>
            <li>
              <strong>Market Holidays:</strong> Maintain the holiday calendar for all supported
              exchanges (NSE, BSE, NFO, BFO, MCX, CDS, BCD).
            </li>
            <li>
              <strong>Market Timings:</strong> Configure trading session timings for each exchange,
              including special sessions like Muhurat trading.
            </li>
          </ul>
        </CardContent>
      </Card>
    </div>
  )
}
