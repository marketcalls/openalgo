import { ArrowLeft, BarChart3, Bell, MessageSquare, TrendingUp, Users } from 'lucide-react'
import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { showToast } from '@/utils/toast'
import { webClient } from '@/api/client'
import { Badge } from '@/components/ui/badge'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'
import type {
  CommandStats,
  TelegramAnalytics as TelegramAnalyticsType,
  TelegramUser,
} from '@/types/telegram'

export default function TelegramAnalytics() {
  const [analytics, setAnalytics] = useState<TelegramAnalyticsType | null>(null)
  const [isLoading, setIsLoading] = useState(true)

  useEffect(() => {
    fetchAnalytics()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const fetchAnalytics = async () => {
    try {
      const response = await webClient.get<{ status: string; data: TelegramAnalyticsType }>(
        '/telegram/api/analytics'
      )
      setAnalytics(response.data.data)
    } catch (error) {
      showToast.error('Failed to load analytics', 'telegram')
    } finally {
      setIsLoading(false)
    }
  }

  const getTotalCommands = (stats: CommandStats[] | undefined | null) => {
    if (!Array.isArray(stats)) return 0
    return stats.reduce((sum, s) => sum + s.count, 0)
  }

  const getTopCommand = (stats: CommandStats[] | undefined | null) => {
    if (!Array.isArray(stats) || stats.length === 0) return null
    return stats.reduce((max, s) => (s.count > max.count ? s : max), stats[0])
  }

  const formatDate = (dateString: string | null) => {
    if (!dateString) return '-'
    return new Date(dateString).toLocaleString()
  }

  if (isLoading) {
    return (
      <div className="flex items-center justify-center py-16">
        <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-primary"></div>
      </div>
    )
  }

  if (!analytics) {
    return (
      <div className="flex items-center justify-center py-16">
        <p className="text-muted-foreground">Failed to load analytics data</p>
      </div>
    )
  }

  // Ensure arrays are safe to use
  const safeStats7d = Array.isArray(analytics.stats_7d) ? analytics.stats_7d : []
  const safeStats30d = Array.isArray(analytics.stats_30d) ? analytics.stats_30d : []
  const safeUsers = Array.isArray(analytics.users) ? analytics.users : []

  const topCommand7d = getTopCommand(safeStats7d)
  const topCommand30d = getTopCommand(safeStats30d)

  return (
    <div className="py-6 space-y-6">
      {/* Header */}
      <div>
        <div className="flex items-center gap-2 mb-2">
          <Link to="/telegram" className="text-muted-foreground hover:text-foreground">
            <ArrowLeft className="h-4 w-4" />
          </Link>
          <h1 className="text-2xl font-bold flex items-center gap-2">
            <BarChart3 className="h-6 w-6" />
            Bot Analytics
          </h1>
        </div>
        <p className="text-muted-foreground">
          View usage statistics and trends for your Telegram bot
        </p>
      </div>

      {/* Overview Stats */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        <Card>
          <CardContent className="p-4">
            <div className="flex items-center gap-3">
              <div className="w-10 h-10 rounded-lg bg-blue-500 flex items-center justify-center">
                <Users className="h-5 w-5 text-white" />
              </div>
              <div>
                <p className="text-2xl font-bold">{analytics.total_users}</p>
                <p className="text-sm text-muted-foreground">Total Users</p>
              </div>
            </div>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="p-4">
            <div className="flex items-center gap-3">
              <div className="w-10 h-10 rounded-lg bg-green-500 flex items-center justify-center">
                <Bell className="h-5 w-5 text-white" />
              </div>
              <div>
                <p className="text-2xl font-bold">{analytics.active_users}</p>
                <p className="text-sm text-muted-foreground">Active Users</p>
              </div>
            </div>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="p-4">
            <div className="flex items-center gap-3">
              <div className="w-10 h-10 rounded-lg bg-purple-500 flex items-center justify-center">
                <MessageSquare className="h-5 w-5 text-white" />
              </div>
              <div>
                <p className="text-2xl font-bold">{getTotalCommands(safeStats7d)}</p>
                <p className="text-sm text-muted-foreground">Commands (7d)</p>
              </div>
            </div>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="p-4">
            <div className="flex items-center gap-3">
              <div className="w-10 h-10 rounded-lg bg-orange-500 flex items-center justify-center">
                <TrendingUp className="h-5 w-5 text-white" />
              </div>
              <div>
                <p className="text-2xl font-bold">{getTotalCommands(safeStats30d)}</p>
                <p className="text-sm text-muted-foreground">Commands (30d)</p>
              </div>
            </div>
          </CardContent>
        </Card>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* 7-Day Stats */}
        <Card>
          <CardHeader>
            <CardTitle>Last 7 Days</CardTitle>
            <CardDescription>
              {topCommand7d
                ? `Most used: /${topCommand7d.command} (${topCommand7d.count} times)`
                : 'No commands recorded'}
            </CardDescription>
          </CardHeader>
          <CardContent>
            {safeStats7d.length === 0 ? (
              <p className="text-center text-muted-foreground py-8">
                No command data for the last 7 days
              </p>
            ) : (
              <div className="space-y-3">
                {safeStats7d.map((stat) => (
                  <div key={stat.command} className="flex items-center justify-between">
                    <div className="flex items-center gap-2">
                      <Badge variant="outline">/{stat.command}</Badge>
                    </div>
                    <div className="flex items-center gap-4">
                      <div className="w-32 bg-muted rounded-full h-2">
                        <div
                          className="bg-primary h-2 rounded-full"
                          style={{
                            width: `${(stat.count / getTotalCommands(safeStats7d)) * 100}%`,
                          }}
                        />
                      </div>
                      <span className="text-sm font-medium w-12 text-right">{stat.count}</span>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </CardContent>
        </Card>

        {/* 30-Day Stats */}
        <Card>
          <CardHeader>
            <CardTitle>Last 30 Days</CardTitle>
            <CardDescription>
              {topCommand30d
                ? `Most used: /${topCommand30d.command} (${topCommand30d.count} times)`
                : 'No commands recorded'}
            </CardDescription>
          </CardHeader>
          <CardContent>
            {safeStats30d.length === 0 ? (
              <p className="text-center text-muted-foreground py-8">
                No command data for the last 30 days
              </p>
            ) : (
              <div className="space-y-3">
                {safeStats30d.map((stat) => (
                  <div key={stat.command} className="flex items-center justify-between">
                    <div className="flex items-center gap-2">
                      <Badge variant="outline">/{stat.command}</Badge>
                    </div>
                    <div className="flex items-center gap-4">
                      <div className="w-32 bg-muted rounded-full h-2">
                        <div
                          className="bg-primary h-2 rounded-full"
                          style={{
                            width: `${(stat.count / getTotalCommands(safeStats30d)) * 100}%`,
                          }}
                        />
                      </div>
                      <span className="text-sm font-medium w-12 text-right">{stat.count}</span>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </CardContent>
        </Card>
      </div>

      {/* User Activity */}
      <Card>
        <CardHeader>
          <CardTitle>User Activity</CardTitle>
          <CardDescription>Recent user activity overview</CardDescription>
        </CardHeader>
        <CardContent>
          <div className="border rounded-md">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>User</TableHead>
                  <TableHead>OpenAlgo Account</TableHead>
                  <TableHead>Status</TableHead>
                  <TableHead>Joined</TableHead>
                  <TableHead>Last Active</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {safeUsers.length === 0 ? (
                  <TableRow>
                    <TableCell colSpan={5} className="text-center text-muted-foreground py-8">
                      No users registered yet
                    </TableCell>
                  </TableRow>
                ) : (
                  safeUsers.slice(0, 10).map((user: TelegramUser) => (
                    <TableRow key={user.telegram_id}>
                      <TableCell>
                        <div>
                          <p className="font-medium">
                            {user.telegram_username
                              ? `@${user.telegram_username}`
                              : user.first_name || 'Unknown'}
                          </p>
                        </div>
                      </TableCell>
                      <TableCell>
                        {user.openalgo_username ? (
                          <Badge variant="outline">{user.openalgo_username}</Badge>
                        ) : (
                          <span className="text-muted-foreground">-</span>
                        )}
                      </TableCell>
                      <TableCell>
                        {user.notifications_enabled ? (
                          <Badge className="bg-green-500 hover:bg-green-600">Active</Badge>
                        ) : (
                          <Badge variant="secondary">Inactive</Badge>
                        )}
                      </TableCell>
                      <TableCell className="text-sm">{formatDate(user.created_at)}</TableCell>
                      <TableCell className="text-sm">{formatDate(user.last_active)}</TableCell>
                    </TableRow>
                  ))
                )}
              </TableBody>
            </Table>
          </div>
          {safeUsers.length > 10 && (
            <div className="mt-4 text-center">
              <Link to="/telegram/users" className="text-sm text-primary hover:underline">
                View all {safeUsers.length} users
              </Link>
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  )
}
