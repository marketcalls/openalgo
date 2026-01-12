import { ArrowRight, BarChart3, Layers, Lightbulb, LineChart } from 'lucide-react'
import { Link } from 'react-router-dom'
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'

export default function Platforms() {
  const platforms = [
    {
      title: 'TradingView',
      description: 'Advanced charting with Pine Script alerts and webhook integration',
      icon: BarChart3,
      href: '/tradingview',
      color: 'bg-blue-500',
    },
    {
      title: 'GoCharting',
      description: 'Professional HTML5 charting optimized for Indian markets',
      icon: LineChart,
      href: '/gocharting',
      color: 'bg-cyan-500',
    },
    {
      title: 'Chartink',
      description: 'Custom stock screeners with technical scan automation',
      icon: Lightbulb,
      href: '/chartink',
      color: 'bg-orange-500',
    },
  ]

  return (
    <div className="py-6 space-y-6">
      {/* Header */}
      <div>
        <h1 className="text-2xl font-bold flex items-center gap-2">
          <Layers className="h-6 w-6" />
          Trading Platforms
        </h1>
        <p className="text-muted-foreground mt-1">
          Connect your favorite charting platforms with OpenAlgo for automated trading
        </p>
      </div>

      {/* Platform Cards Grid */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
        {platforms.map((platform) => (
          <Link key={platform.href} to={platform.href}>
            <Card className="h-full hover:shadow-lg transition-shadow cursor-pointer group">
              <CardHeader>
                <div className="flex items-center justify-between">
                  <div
                    className={`w-10 h-10 rounded-lg ${platform.color} flex items-center justify-center`}
                  >
                    <platform.icon className="h-5 w-5 text-white" />
                  </div>
                </div>
                <CardTitle className="flex items-center gap-2 group-hover:text-primary transition-colors">
                  {platform.title}
                  <ArrowRight className="h-4 w-4 opacity-0 group-hover:opacity-100 transition-opacity" />
                </CardTitle>
                <CardDescription>{platform.description}</CardDescription>
              </CardHeader>
              <CardContent>
                <div className="text-sm text-muted-foreground">
                  Click to configure {platform.title}
                </div>
              </CardContent>
            </Card>
          </Link>
        ))}
      </div>

      {/* Information Section */}
      <Alert>
        <Lightbulb className="h-4 w-4" />
        <AlertTitle className="font-bold">Getting Started</AlertTitle>
        <AlertDescription className="flex flex-col sm:flex-row items-start sm:items-center justify-between gap-4">
          <span>
            Each platform requires webhook configuration. Click on a platform to generate your
            webhook URLs and JSON payloads. Make sure you have set up your API key before
            configuring webhooks.
          </span>
          <Button asChild variant="outline" size="sm" className="gap-1 flex-shrink-0">
            <a href="https://docs.openalgo.in" target="_blank" rel="noopener noreferrer">
              View Documentation
            </a>
          </Button>
        </AlertDescription>
      </Alert>
    </div>
  )
}
