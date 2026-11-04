import { ArrowLeft, ExternalLink, LifeBuoy, Scale, Send } from 'lucide-react'
import { Link } from 'react-router'
import { BrandLockup } from '@/brand/BrandLockup'
import { BRAND } from '@/brand/brand'
import { Footer } from '@/components/layout/Footer'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'

/**
 * About page. Holds the AGPL-3.0 attribution and the source-code offer that
 * section 13 requires for network users, so it must stay reachable without
 * logging in. The only page, with brand.ts, allowed to name OpenAlgo
 * (see scripts/brand-check.mjs).
 */
export default function About() {
  return (
    <div className="min-h-screen flex flex-col">
      <header className="border-b">
        <div className="container mx-auto px-4 h-14 flex items-center justify-between">
          <Link to="/" className="flex items-center gap-2">
            <BrandLockup />
          </Link>
          <Button variant="ghost" size="sm" asChild>
            <Link to="/dashboard" className="flex items-center gap-2">
              <ArrowLeft className="h-4 w-4" />
              Back to the app
            </Link>
          </Button>
        </div>
      </header>

      <main className="flex-1 container mx-auto px-4 py-10 max-w-3xl space-y-6">
        <div>
          <h1 className="text-3xl font-bold mb-2">About {BRAND.displayName}</h1>
          <p className="text-lg text-muted-foreground">{BRAND.tagline}</p>
        </div>

        <Card>
          <CardHeader>
            <CardTitle>What this is</CardTitle>
            <CardDescription>{BRAND.endorsement}</CardDescription>
          </CardHeader>
          <CardContent className="space-y-3 text-sm leading-relaxed">
            <p>
              {BRAND.productName} connects your broker account to your trading strategies. It places
              orders from TradingView, ChartInk and Amibroker alerts, runs Python and no-code
              strategies, manages risk on open positions, and includes options analytics and
              charting tools.
            </p>
            <p>
              {BRAND.makerName} installs {BRAND.productName} on your computer or server, connects
              your broker, builds and maintains your strategies, and supports you when something
              needs attention.
            </p>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <LifeBuoy className="h-5 w-5" />
              Support
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-3 text-sm">
            <p>
              For help with your installation, your broker connection or a strategy, contact us.
            </p>
            <div className="flex flex-wrap gap-2">
              <Button variant="outline" asChild>
                <a
                  href={BRAND.supportUrl}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="flex items-center gap-2"
                >
                  Get support
                  <ExternalLink className="h-4 w-4" />
                </a>
              </Button>
              <Button variant="outline" asChild>
                <a
                  href={BRAND.supportTelegramUrl}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="flex items-center gap-2"
                >
                  <Send className="h-4 w-4" />
                  Message us on Telegram
                </a>
              </Button>
            </div>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <Scale className="h-5 w-5" />
              License and source code
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-3 text-sm leading-relaxed">
            <p>
              {BRAND.productName} is open-source software based on{' '}
              <a
                href={BRAND.upstreamUrl}
                target="_blank"
                rel="noopener noreferrer"
                className="underline"
              >
                {BRAND.upstreamName}
              </a>
              . It is distributed under the GNU Affero General Public License, version 3 (
              {BRAND.licenseName}), and the original copyright notices are retained.
            </p>
            <p>
              You are entitled to the complete source code of the version you are using. It is
              available at{' '}
              <a
                href={BRAND.sourceUrl}
                target="_blank"
                rel="noopener noreferrer"
                className="underline break-all"
              >
                {BRAND.sourceUrl}
              </a>
              .
            </p>
          </CardContent>
        </Card>
      </main>

      <Footer />
    </div>
  )
}
