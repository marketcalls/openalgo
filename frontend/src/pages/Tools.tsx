import { ArrowRight } from 'lucide-react'
import { Link } from 'react-router-dom'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'

const tools = [
  {
    title: 'Option Chain',
    description: 'Real-time option chain with live Greeks, OI data, and quick order placement',
    href: '/optionchain',
    color: 'bg-emerald-500',
  },
  {
    title: 'Option Greeks',
    description: 'Historical IV, Delta, Theta, Vega, and Gamma charts for ATM options',
    href: '/ivchart',
    color: 'bg-violet-500',
  },
  {
    title: 'OI Tracker',
    description: 'Open Interest analysis with CE/PE OI bars, PCR overlay, and ATM strike marker',
    href: '/oitracker',
    color: 'bg-blue-500',
  },
  {
    title: 'Max Pain',
    description: 'Max Pain strike calculation with visual pain distribution across strikes',
    href: '/maxpain',
    color: 'bg-amber-500',
  },
  {
    title: 'Straddle Chart',
    description: 'Dynamic ATM Straddle chart with rolling strike, Spot, and Synthetic Futures overlay',
    href: '/straddle',
    color: 'bg-teal-500',
  },
  {
    title: 'Vol Surface',
    description: '3D Implied Volatility surface across strikes and expiries using live option chain data',
    href: '/volsurface',
    color: 'bg-rose-500',
  },
  {
    title: 'GEX Dashboard',
    description: 'Gamma Exposure analysis with OI Walls, Net GEX per strike, and top gamma strikes',
    href: '/gex',
    color: 'bg-indigo-500',
  },
  {
    title: 'IV Smile',
    description: 'Implied Volatility smile with Call/Put IV curves, ATM IV, and skew analysis',
    href: '/ivsmile',
    color: 'bg-cyan-500',
  },
  {
    title: 'OI Profile',
    description: 'Futures candlestick with OI butterfly and daily OI change across strikes',
    href: '/oiprofile',
    color: 'bg-orange-500',
  },
]

export default function Tools() {
  return (
    <div className="py-6 space-y-6">
      {/* Header */}
      <div>
        <h1 className="text-2xl font-bold">Tools</h1>
        <p className="text-muted-foreground mt-1">
          Analytical tools for options trading and market analysis
        </p>
      </div>

      {/* Tool Cards Grid */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
        {tools.map((tool) => (
          <Link key={tool.href} to={tool.href}>
            <Card className="h-full hover:shadow-lg transition-shadow cursor-pointer group">
              <CardHeader>
                <div className="flex items-center justify-between">
                  <div
                    className={`w-10 h-10 rounded-lg ${tool.color} flex items-center justify-center`}
                  >
                    <span className="text-white font-bold text-sm">
                      {tool.title.split(' ').map((w) => w[0]).join('')}
                    </span>
                  </div>
                </div>
                <CardTitle className="flex items-center gap-2 group-hover:text-primary transition-colors">
                  {tool.title}
                  <ArrowRight className="h-4 w-4 opacity-0 group-hover:opacity-100 transition-opacity" />
                </CardTitle>
                <CardDescription>{tool.description}</CardDescription>
              </CardHeader>
              <CardContent>
                <div className="text-sm text-muted-foreground">
                  Click to open {tool.title}
                </div>
              </CardContent>
            </Card>
          </Link>
        ))}
      </div>
    </div>
  )
}
