import {
  Activity,
  ArrowRight,
  ClipboardList,
  Clock,
  FileText,
  FlaskConical,
  HeartPulse,
  Shield,
} from 'lucide-react'
import { Link } from 'react-router-dom'
import { Badge } from '@/components/ui/badge'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'

export default function LogsIndex() {
  const logCards = [
    {
      title: 'Live Logs',
      description: 'View real-time API order logs with request and response data',
      icon: ClipboardList,
      href: '/logs/live',
      color: 'bg-blue-500',
      countLabel: 'orders',
    },
    {
      title: 'Sandbox Logs',
      description: 'Track and test your trading strategies before going live',
      icon: FlaskConical,
      href: '/logs/sandbox',
      color: 'bg-purple-500',
      countLabel: 'testing',
    },
    {
      title: 'Latency Monitor',
      description: 'Track order execution latency and performance metrics',
      icon: Clock,
      href: '/logs/latency',
      color: 'bg-orange-500',
      countLabel: 'monitoring',
    },
    {
      title: 'Traffic Monitor',
      description: 'Monitor HTTP requests, endpoints, and response times',
      icon: Activity,
      href: '/logs/traffic',
      color: 'bg-cyan-500',
      countLabel: 'monitoring',
    },
    {
      title: 'Security Logs',
      description: 'Monitor security events, banned IPs, and threat activity',
      icon: Shield,
      href: '/logs/security',
      color: 'bg-red-500',
      countLabel: 'security',
    },
    {
      title: 'Health Monitor',
      description: 'Track system health, file descriptors, memory, and connections',
      icon: HeartPulse,
      href: '/health',
      color: 'bg-green-500',
      countLabel: 'health',
    },
  ]

  return (
    <div className="py-6 space-y-6">
      {/* Header */}
      <div>
        <h1 className="text-2xl font-bold flex items-center gap-2">
          <FileText className="h-6 w-6" />
          Logs & Monitoring
        </h1>
        <p className="text-muted-foreground mt-1">
          Access trading logs, monitor system performance, and track security events
        </p>
      </div>

      {/* Log Cards Grid */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
        {logCards.map((card) => (
          <Link key={card.href} to={card.href}>
            <Card className="h-full hover:shadow-lg transition-shadow cursor-pointer group">
              <CardHeader>
                <div className="flex items-center justify-between">
                  <div
                    className={`w-10 h-10 rounded-lg ${card.color} flex items-center justify-center`}
                  >
                    <card.icon className="h-5 w-5 text-white" />
                  </div>
                  <Badge variant="secondary">{card.countLabel}</Badge>
                </div>
                <CardTitle className="flex items-center gap-2 group-hover:text-primary transition-colors">
                  {card.title}
                  <ArrowRight className="h-4 w-4 opacity-0 group-hover:opacity-100 transition-opacity" />
                </CardTitle>
                <CardDescription>{card.description}</CardDescription>
              </CardHeader>
              <CardContent>
                <div className="text-sm text-muted-foreground">
                  Click to view {card.title.toLowerCase()}
                </div>
              </CardContent>
            </Card>
          </Link>
        ))}
      </div>
    </div>
  )
}
