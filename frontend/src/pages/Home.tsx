import {
  ArrowRight,
  Blocks,
  BookOpen,
  Bot,
  CandlestickChart,
  ClipboardList,
  Download,
  GraduationCap,
  HelpCircle,
  LogIn,
  Menu,
  MessageCircle,
  Moon,
  Server,
  ShieldCheck,
  Sigma,
  Sparkles,
  Sun,
  Wand2,
  Zap,
} from 'lucide-react'
import { useState } from 'react'
import { Link } from 'react-router'
import { Footer } from '@/components/layout/Footer'
import { Button } from '@/components/ui/button'
import { Card, CardContent } from '@/components/ui/card'
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
  SheetTrigger,
} from '@/components/ui/sheet'
import { tools } from '@/lib/tools'
import { useThemeStore } from '@/stores/themeStore'

const integrations = [
  'Amibroker',
  'TradingView',
  'GoCharting',
  'Python',
  'MetaTrader',
  'N8N',
  'Java',
  'Go',
  '.NET',
  'Node.js',
  'Rust',
  'ChartInk',
  'Excel',
  'Google Sheets',
  'OpenClaw',
  'Telegram',
]

// Open Varsity (openalgo.in/learn) course count, shown in the hero pill.
const VARSITY_COURSES = 13

// The surfaces that share one broker session and feed inside a single
// self-hosted instance. Counts come from the code: tools.length is the /tools
// registry, nodeTypes in components/flow/nodes is the Flow palette, and the
// indicator count is what openalgo-charts ships.
const platformDesks = [
  {
    icon: Server,
    title: 'Self-hosted algo trading',
    desc: 'A unified broker API and execution engine on your own server, driven from TradingView, Amibroker, ChartInk, Excel, Python or MCP.',
  },
  {
    icon: CandlestickChart,
    title: 'Charting platform',
    desc: 'Chart-based trading in the built-in terminal: fire and manage orders from the chart itself, with 91 indicators on real market data.',
  },
  {
    icon: Blocks,
    title: 'No-code strategy builder',
    desc: 'Flow is a drag-and-drop canvas: wire 61 node types from triggers to indicators, conditions and orders, then activate it to run on its own.',
  },
  {
    icon: Sigma,
    title: 'Options trading platform',
    desc: `${tools.length} built-in tools: option chain, Greeks, OI tracker, max pain, vol surface, GEX, IV smile, straddles and arbitrage, plus portfolio and SIP backtesters.`,
  },
  {
    icon: Zap,
    title: 'Scalping platform',
    desc: 'A keyboard-driven scalping terminal: arrow keys fire CE and PE orders, F6 flattens every position and F7 cancels every pending order.',
  },
  {
    icon: ShieldCheck,
    title: 'Sandbox testing',
    desc: 'Analyzer mode runs any strategy against real market data with 1 crore of sandbox capital and exchange-aligned auto square-off.',
  },
]

export default function Home() {
  const { mode, toggleMode } = useThemeStore()
  const [mobileMenuOpen, setMobileMenuOpen] = useState(false)

  const navLinks = [
    { href: '/', label: 'Home', internal: true },
    { href: '/faq', label: 'FAQ', internal: true },
    { href: 'https://www.openalgo.in/learn', label: 'Varsity', internal: false },
    { href: 'https://openalgo.in/discord', label: 'Community', internal: false },
    { href: 'https://openalgo.in/roadmap', label: 'Roadmap', internal: false },
    { href: 'https://docs.openalgo.in', label: 'Docs', internal: false },
  ]

  return (
    <div className="min-h-screen bg-background flex flex-col">
      {/* Navbar */}
      <header className="sticky top-0 z-30 h-16 w-full border-b bg-background/90 backdrop-blur">
        <nav className="container mx-auto px-4 flex h-full items-center justify-between">
          {/* Logo */}
          <div className="flex items-center gap-2">
            {/* Mobile menu button */}
            <Sheet open={mobileMenuOpen} onOpenChange={setMobileMenuOpen}>
              <SheetTrigger asChild className="lg:hidden">
                <Button variant="ghost" size="icon" aria-label="Open menu">
                  <Menu className="h-5 w-5" />
                </Button>
              </SheetTrigger>
              <SheetContent side="left" className="w-80">
                <SheetHeader className="sr-only">
                  <SheetTitle>Navigation Menu</SheetTitle>
                  <SheetDescription>Main navigation and quick access links</SheetDescription>
                </SheetHeader>
                <div className="flex items-center gap-2 mb-8">
                  <img src="/logo.png" alt="OpenAlgo" className="h-8 w-8" />
                  <span className="text-xl font-semibold">OpenAlgo</span>
                </div>
                <div className="flex flex-col gap-2">
                  <Link
                    to="/"
                    className="flex items-center gap-2 px-4 py-2 rounded-md hover:bg-accent"
                    onClick={() => setMobileMenuOpen(false)}
                  >
                    <svg
                      xmlns="http://www.w3.org/2000/svg"
                      className="h-5 w-5"
                      fill="none"
                      viewBox="0 0 24 24"
                      stroke="currentColor"
                    >
                      <path
                        strokeLinecap="round"
                        strokeLinejoin="round"
                        strokeWidth={2}
                        d="M3 12l2-2m0 0l7-7 7 7M5 10v10a1 1 0 001 1h3m10-11l2 2m-2-2v10a1 1 0 01-1 1h-3m-6 0a1 1 0 001-1v-4a1 1 0 011-1h2a1 1 0 011 1v4a1 1 0 001 1m-6 0h6"
                      />
                    </svg>
                    Home
                  </Link>
                  <Link
                    to="/faq"
                    className="flex items-center gap-2 px-4 py-2 rounded-md hover:bg-accent"
                    onClick={() => setMobileMenuOpen(false)}
                  >
                    <HelpCircle className="h-5 w-5" />
                    FAQ
                  </Link>
                  <Link
                    to="/download"
                    className="flex items-center gap-2 px-4 py-2 rounded-md bg-primary text-primary-foreground hover:bg-primary/90"
                    onClick={() => setMobileMenuOpen(false)}
                  >
                    <Download className="h-5 w-5" />
                    Download
                  </Link>
                  <a
                    href="https://www.openalgo.in/learn"
                    target="_blank"
                    rel="noopener noreferrer"
                    className="flex items-center gap-2 px-4 py-2 rounded-md hover:bg-accent"
                  >
                    <GraduationCap className="h-5 w-5" />
                    Varsity
                  </a>
                  <a
                    href="https://openalgo.in/discord"
                    target="_blank"
                    rel="noopener noreferrer"
                    className="flex items-center gap-2 px-4 py-2 rounded-md hover:bg-accent"
                  >
                    <MessageCircle className="h-5 w-5" />
                    Community
                  </a>
                  <a
                    href="https://openalgo.in/roadmap"
                    target="_blank"
                    rel="noopener noreferrer"
                    className="flex items-center gap-2 px-4 py-2 rounded-md hover:bg-accent"
                  >
                    <ClipboardList className="h-5 w-5" />
                    Roadmap
                  </a>
                  <a
                    href="https://docs.openalgo.in"
                    target="_blank"
                    rel="noopener noreferrer"
                    className="flex items-center gap-2 px-4 py-2 rounded-md hover:bg-accent"
                  >
                    <BookOpen className="h-5 w-5" />
                    Docs
                  </a>
                </div>
              </SheetContent>
            </Sheet>

            <Link to="/" className="flex items-center gap-2">
              <img src="/logo.png" alt="OpenAlgo" className="h-8 w-8" />
              <span className="text-xl font-bold hidden sm:inline">OpenAlgo</span>
            </Link>
          </div>

          {/* Desktop Navigation */}
          <div className="hidden lg:flex items-center gap-1">
            {navLinks.map((link) =>
              link.internal ? (
                <Link key={link.href} to={link.href}>
                  <Button variant="ghost" size="sm">
                    {link.label}
                  </Button>
                </Link>
              ) : (
                <a key={link.href} href={link.href} target="_blank" rel="noopener noreferrer">
                  <Button variant="ghost" size="sm">
                    {link.label}
                  </Button>
                </a>
              )
            )}
          </div>

          {/* Right side */}
          <div className="flex items-center gap-2">
            <Link to="/download">
              <Button size="sm">Download</Button>
            </Link>
            <Button
              variant="ghost"
              size="icon"
              onClick={toggleMode}
              aria-label={mode === 'dark' ? 'Switch to light mode' : 'Switch to dark mode'}
            >
              {mode === 'dark' ? <Sun className="h-5 w-5" /> : <Moon className="h-5 w-5" />}
            </Button>
          </div>
        </nav>
      </header>

      <main className="flex-1">
        {/* Hero Section */}
        <section className="container mx-auto px-4 pt-20 pb-16 sm:pt-28 sm:pb-20">
          <div className="text-center max-w-4xl mx-auto">
            <a
              href="https://www.openalgo.in/learn"
              target="_blank"
              rel="noopener noreferrer"
              className="inline-flex items-center gap-2 rounded-full border border-border bg-card/60 px-4 py-1.5 text-xs font-semibold uppercase tracking-[0.2em] mb-8 shadow-sm transition-colors hover:border-emerald-500/40 hover:bg-card"
            >
              <span className="h-1.5 w-1.5 rounded-full bg-emerald-400 shadow-[0_0_8px] shadow-emerald-400/60" />
              <span className="text-amber-700 dark:text-amber-500">New Here</span>
              <span className="text-muted-foreground">
                - Learn Free on Open Varsity, {VARSITY_COURSES} Courses
              </span>
              <ArrowRight className="h-3.5 w-3.5 text-muted-foreground" />
            </a>
            <h1 className="text-5xl sm:text-6xl lg:text-7xl font-bold tracking-tight mb-6">
              <span className="block text-foreground">Your Personal</span>
              <span className="block text-primary">Algo Trading Platform</span>
            </h1>
            <p className="text-lg sm:text-xl font-semibold mb-6 text-primary">
              Community Driven Algo Trading Platform
            </p>
            <p className="text-base sm:text-lg text-muted-foreground max-w-2xl mx-auto mb-10">
              Test and Execute your Trading ideas, Connect your favorite Trading Platforms, AI
              Driven Strategy Development, with a built-in Options &amp; Portfolio Analytics Suite -
              option chains and Greeks, portfolio and SIP backtesting - across 30+ Brokers.
            </p>
            <div className="flex flex-col sm:flex-row gap-4 justify-center">
              <Button size="lg" asChild>
                <Link to="/login">
                  <LogIn className="mr-2 h-5 w-5" />
                  Login
                </Link>
              </Button>
              <Button size="lg" variant="outline" asChild>
                <Link to="/download">
                  <Download className="mr-2 h-5 w-5" />
                  Download
                </Link>
              </Button>
            </div>
          </div>
        </section>

        {/* Integrates With */}
        <section className="container mx-auto px-4 py-12 sm:py-16">
          <p className="text-center text-xs sm:text-sm font-semibold uppercase tracking-[0.25em] text-amber-700 dark:text-amber-500 mb-6">
            Integrates With
          </p>
          <div className="flex flex-wrap justify-center gap-2 sm:gap-3 max-w-4xl mx-auto">
            {integrations.map((name) => (
              <span
                key={name}
                className="rounded-full border border-border bg-card/60 px-4 py-2 text-sm text-foreground/90 shadow-sm"
              >
                {name}
              </span>
            ))}
          </div>
        </section>

        {/* One platform, many desks */}
        <section className="container mx-auto px-4 py-16 sm:py-20">
          <div className="text-center max-w-3xl mx-auto mb-12">
            <span className="inline-flex items-center gap-1.5 rounded-full border border-amber-500/30 bg-amber-500/10 px-3 py-1 text-xs font-semibold uppercase tracking-wider text-amber-700 dark:text-amber-500 mb-6">
              <Server className="h-3.5 w-3.5" />
              One platform, many desks
            </span>
            <h2 className="text-3xl sm:text-4xl lg:text-5xl font-bold tracking-tight mb-4">
              Not just an algo trading platform.
              <span className="block text-muted-foreground">A complete trading desk.</span>
            </h2>
            <p className="text-base sm:text-lg text-muted-foreground">
              Execution is only the starting point. Charting, no-code strategy building, options
              analytics, scalping and sandbox testing all run inside the same self-hosted stack.
            </p>
          </div>

          <div className="grid gap-5 sm:grid-cols-2 lg:grid-cols-3 max-w-6xl mx-auto">
            {platformDesks.map((desk) => (
              <Card key={desk.title} className="h-full transition-colors hover:border-amber-400/40">
                <CardContent className="space-y-3">
                  <div className="flex h-11 w-11 items-center justify-center rounded-xl bg-amber-500/10 text-amber-700 dark:text-amber-500">
                    <desk.icon className="h-5 w-5" />
                  </div>
                  <h3 className="font-bold text-base">{desk.title}</h3>
                  <p className="text-sm text-muted-foreground leading-relaxed">{desk.desc}</p>
                </CardContent>
              </Card>
            ))}
          </div>
        </section>

        {/* Trade & Research With Your AI */}
        <section className="container mx-auto px-4 py-16 sm:py-20">
          <div className="text-center max-w-3xl mx-auto mb-12">
            <span className="inline-flex items-center gap-1.5 rounded-full border border-emerald-500/30 bg-emerald-500/10 px-3 py-1 text-xs font-semibold uppercase tracking-wider text-emerald-700 dark:text-emerald-400 mb-6">
              <Sparkles className="h-3.5 w-3.5" />
              Made for AI
            </span>
            <h2 className="text-3xl sm:text-4xl lg:text-5xl font-bold tracking-tight mb-4">
              Trade & Research With Your AI
            </h2>
            <p className="text-base sm:text-lg text-muted-foreground">
              Two simple ways to bring AI into your trading - talk to your account like a trading
              desk, or give your AI a toolkit to chart, scan, and backtest for you.
            </p>
          </div>

          <div className="grid gap-6 md:grid-cols-2 max-w-6xl mx-auto">
            {/* OpenAlgo MCP card */}
            <Card className="group transition-colors hover:border-purple-400/40">
              <CardContent className="space-y-4">
                <div className="flex items-start gap-4">
                  <div className="flex h-12 w-12 shrink-0 items-center justify-center rounded-xl bg-purple-500/10 text-purple-400">
                    <Bot className="h-6 w-6" />
                  </div>
                  <div>
                    <h3 className="text-xl font-bold flex items-center gap-2">
                      OpenAlgo MCP
                      <ArrowRight className="h-5 w-5 transition-transform group-hover:translate-x-0.5" />
                    </h3>
                    <p className="text-xs font-semibold uppercase tracking-wider text-muted-foreground mt-1">
                      Trade by Chatting
                    </p>
                  </div>
                </div>
                <p className="text-sm text-muted-foreground leading-relaxed">
                  Connect your OpenAlgo account to Claude, Cursor, Windsurf, or ChatGPT. Place
                  orders, check positions, and pull live prices by simply asking - no dashboards, no
                  clicks.
                </p>
                <div className="flex flex-wrap gap-2 pt-2">
                  {[
                    '25+ built-in actions',
                    'Claude / Cursor / Windsurf / ChatGPT',
                    'Runs on your computer',
                  ].map((tag) => (
                    <span
                      key={tag}
                      className="rounded-md bg-muted px-2.5 py-1 text-xs text-neutral-600 dark:text-neutral-400"
                    >
                      {tag}
                    </span>
                  ))}
                </div>
              </CardContent>
            </Card>

            {/* OpenAlgo Skills card */}
            <Card className="group transition-colors hover:border-emerald-400/40">
              <CardContent className="space-y-4">
                <div className="flex items-start gap-4">
                  <div className="flex h-12 w-12 shrink-0 items-center justify-center rounded-xl bg-emerald-500/10 text-emerald-400">
                    <Wand2 className="h-6 w-6" />
                  </div>
                  <div>
                    <h3 className="text-xl font-bold flex items-center gap-2">
                      OpenAlgo Skills
                      <ArrowRight className="h-5 w-5 transition-transform group-hover:translate-x-0.5" />
                    </h3>
                    <p className="text-xs font-semibold uppercase tracking-wider text-muted-foreground mt-1">
                      Chart, Scan & Backtest
                    </p>
                  </div>
                </div>
                <p className="text-sm text-muted-foreground leading-relaxed">
                  Ready-made trading abilities you can drop into your AI assistant - charts,
                  scanners, custom indicators, and backtests with real brokerage costs. Works with
                  40+ AI apps.
                </p>
                <div className="flex flex-wrap gap-2 pt-2">
                  {['100+ indicators', '12 ready-made strategies', 'India / US / Crypto'].map(
                    (tag) => (
                      <span
                        key={tag}
                        className="rounded-md bg-muted px-2.5 py-1 text-xs text-neutral-600 dark:text-neutral-400"
                      >
                        {tag}
                      </span>
                    )
                  )}
                </div>
              </CardContent>
            </Card>
          </div>
        </section>
      </main>

      {/* Footer */}
      <Footer />
    </div>
  )
}
