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
