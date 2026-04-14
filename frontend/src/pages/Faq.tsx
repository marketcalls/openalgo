import {
  BookOpen,
  ClipboardList,
  Download,
  HelpCircle,
  Menu,
  MessageCircle,
  Moon,
  Sun,
} from 'lucide-react'
import { useState } from 'react'
import { Link } from 'react-router-dom'
import { Footer } from '@/components/layout/Footer'
import {
  Accordion,
  AccordionContent,
  AccordionItem,
  AccordionTrigger,
} from '@/components/ui/accordion'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Sheet, SheetContent, SheetTrigger } from '@/components/ui/sheet'
import { useThemeStore } from '@/stores/themeStore'

const faqData = [
  {
    category: 'General',
    questions: [
      {
        question: 'What is OpenAlgo?',
        answer:
          'OpenAlgo is an open-source algorithmic trading platform that provides a unified API layer across 24+ Indian brokers. It enables seamless integration with TradingView, Amibroker, Excel, Python, and AI agents, allowing traders to automate their trading strategies without being locked into a single broker.',
      },
      {
        question: 'Which brokers are supported?',
        answer:
          'OpenAlgo supports 24+ Indian brokers including Zerodha, Angel One, Dhan, Fyers, ICICI Direct, HDFC Securities, Kotak Securities, Upstox, 5paisa, Alice Blue, Firstock, Flattrade, IIFL, Jainam, Mastertrust, Motilal Oswal, Nuvama, Paytm Money, Rupeezy, Samco, Shoonya (Finvasia), and more. New brokers are being added regularly.',
      },
      {
        question: 'What are the system requirements?',
        answer:
          'OpenAlgo requires Python 3.12 or higher and Node.js 20+ for the frontend. It runs on Windows, macOS, and Linux. For optimal performance, we recommend at least 4GB RAM and a stable internet connection. The application uses SQLite by default, making it lightweight and easy to deploy.',
      },
      {
        question: 'Where can I host OpenAlgo?',
        answer:
          'OpenAlgo can be hosted locally on your personal computer, on a VPS (Virtual Private Server), or in the cloud. Popular options include AWS, Google Cloud, DigitalOcean, or any Linux VPS provider. For Indian traders, hosting on an Indian VPS ensures low latency connections to broker servers.',
      },
    ],
  },
  {
    category: 'Costs & Security',
    questions: [
      {
        question: 'What are the costs involved?',
        answer:
          'OpenAlgo is completely free and open-source under the AGPL license. There are no licensing fees, subscription costs, or hidden charges. You only pay for your hosting infrastructure (if using cloud/VPS) and standard brokerage charges from your broker. Self-hosting on your own computer is completely free.',
      },
      {
        question: 'How secure is OpenAlgo?',
        answer:
          'Security is a top priority. OpenAlgo stores API credentials locally on your machine with encryption. It uses HTTPS for all communications, implements CSRF protection, rate limiting, and secure session management. Since it runs on your own infrastructure, you have complete control over your data. We recommend using strong passwords and enabling 2FA where available.',
      },
      {
        question: 'Why do I need to login daily?',
        answer:
          'Daily login is required by Indian brokers for security compliance. Broker sessions typically expire at the end of each trading day or after a set period (usually around 3 AM IST). This is a regulatory requirement, not an OpenAlgo limitation. The platform makes re-authentication quick and easy with TOTP support for most brokers.',
      },
    ],
  },
  {
    category: 'Features & Integration',
    questions: [
      {
        question: 'Which platforms can I integrate with OpenAlgo?',
        answer:
          'OpenAlgo integrates with TradingView (via webhooks), Amibroker (via AFL), GoCharting, ChartInk, MetaTrader, Excel, Google Sheets, Python, Node.js, Go, N8N, and any platform that can send HTTP webhooks. You can also use the REST API directly from any programming language.',
      },
      {
        question: 'Does OpenAlgo support paper trading?',
        answer:
          'Yes! OpenAlgo includes an Analyzer/Sandbox mode with virtual capital of Rs. 1 Crore. This allows you to test strategies in a realistic environment with proper margin calculations, auto square-off at exchange timings, and complete isolation from live trading. Perfect for testing before going live.',
      },
      {
        question: 'Can I run multiple strategies simultaneously?',
        answer:
          'Yes, OpenAlgo supports running multiple strategies simultaneously. You can create different webhook endpoints for different strategies, manage them independently, and monitor their performance through the dashboard. The Action Center allows you to control execution modes for each strategy.',
      },
      {
        question: 'Does OpenAlgo provide real-time market data?',
        answer:
          'Yes, OpenAlgo includes a unified WebSocket server that streams real-time market data from your broker. This data is used for live position tracking, P&L updates, and can be accessed by your strategies. The data is normalized across all brokers for consistent handling.',
      },
    ],
  },
  {
    category: 'Licensing & Usage',
    questions: [
      {
        question: 'Can I use OpenAlgo for my proprietary trading strategies?',
        answer:
          'Yes, you can use OpenAlgo for your personal or proprietary trading strategies. The AGPL license allows free use for personal trading. However, if you modify OpenAlgo and provide it as a service to others, you must make your modifications open source.',
      },
      {
        question: 'Can I rebrand OpenAlgo for commercial use?',
        answer:
          'Under the AGPL license, you can modify OpenAlgo, but any derivative work must also be open source and credit the original project. For commercial licensing options that allow rebranding without open-source requirements, please contact the OpenAlgo team.',
      },
      {
        question: 'Can I charge others for using my OpenAlgo setup?',
        answer:
          'If you provide OpenAlgo as a service to others (even if modified), the AGPL license requires you to share your source code. For commercial service offerings without this requirement, commercial licensing options are available.',
      },
      {
        question: 'Can I integrate OpenAlgo with GPT/AI assistants?',
        answer:
          'Yes! OpenAlgo provides REST APIs that can be called from AI assistants, chatbots, or any automated system. You can build AI-powered trading assistants that use OpenAlgo to execute trades based on natural language commands or AI analysis.',
      },
    ],
  },
]

export default function Faq() {
  const { mode, toggleMode } = useThemeStore()
  const [mobileMenuOpen, setMobileMenuOpen] = useState(false)

  const navLinks = [
    { href: '/', label: 'Home', internal: true },
    { href: '/faq', label: 'FAQ', internal: true },
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

      {/* Main Content */}
      <main className="flex-1">
        <div className="container mx-auto px-4 py-12">
          {/* Header */}
          <div className="text-center mb-12">
            <h1 className="text-4xl lg:text-5xl font-bold mb-4">Frequently Asked Questions</h1>
            <p className="text-lg text-muted-foreground max-w-2xl mx-auto">
              Find answers to common questions about OpenAlgo, its features, security, and licensing.
            </p>
          </div>

          {/* FAQ Categories */}
          <div className="max-w-4xl mx-auto space-y-8">
            {faqData.map((category) => (
              <Card key={category.category}>
                <CardHeader>
                  <CardTitle>{category.category}</CardTitle>
                  <CardDescription>
                    {category.category === 'General' && 'Basic information about OpenAlgo'}
                    {category.category === 'Costs & Security' &&
                      'Pricing, security, and compliance details'}
                    {category.category === 'Features & Integration' &&
                      'Platform capabilities and integrations'}
                    {category.category === 'Licensing & Usage' &&
                      'License terms and usage guidelines'}
                  </CardDescription>
                </CardHeader>
                <CardContent>
                  <Accordion type="single" collapsible className="w-full">
                    {category.questions.map((faq, index) => (
                      <AccordionItem key={index} value={`${category.category}-${index}`}>
                        <AccordionTrigger className="text-left">{faq.question}</AccordionTrigger>
                        <AccordionContent className="text-muted-foreground">
                          {faq.answer}
                        </AccordionContent>
                      </AccordionItem>
                    ))}
                  </Accordion>
                </CardContent>
              </Card>
            ))}
          </div>

          {/* Resources Section */}
          <div className="max-w-4xl mx-auto mt-16">
            <h2 className="text-2xl font-bold text-center mb-8">Need More Help?</h2>
            <div className="grid md:grid-cols-3 gap-6">
              <Card className="text-center">
                <CardHeader>
                  <BookOpen className="h-10 w-10 mx-auto text-primary" />
                  <CardTitle className="text-lg">Documentation</CardTitle>
                </CardHeader>
                <CardContent>
                  <p className="text-sm text-muted-foreground mb-4">
                    Comprehensive guides and API references
                  </p>
                  <Button variant="outline" asChild>
                    <a href="https://docs.openalgo.in" target="_blank" rel="noopener noreferrer">
                      Read Docs
                    </a>
                  </Button>
                </CardContent>
              </Card>

              <Card className="text-center">
                <CardHeader>
                  <MessageCircle className="h-10 w-10 mx-auto text-primary" />
                  <CardTitle className="text-lg">Discord Community</CardTitle>
                </CardHeader>
                <CardContent>
                  <p className="text-sm text-muted-foreground mb-4">
                    Join our active community for support
                  </p>
                  <Button variant="outline" asChild>
                    <a href="https://openalgo.in/discord" target="_blank" rel="noopener noreferrer">
                      Join Discord
                    </a>
                  </Button>
                </CardContent>
              </Card>

              <Card className="text-center">
                <CardHeader>
                  <svg
                    className="h-10 w-10 mx-auto text-primary"
                    fill="currentColor"
                    viewBox="0 0 24 24"
                  >
                    <path d="M12 0c-6.626 0-12 5.373-12 12 0 5.302 3.438 9.8 8.207 11.387.599.111.793-.261.793-.577v-2.234c-3.338.726-4.033-1.416-4.033-1.416-.546-1.387-1.333-1.756-1.333-1.756-1.089-.745.083-.729.083-.729 1.205.084 1.839 1.237 1.839 1.237 1.07 1.834 2.807 1.304 3.492.997.107-.775.418-1.305.762-1.604-2.665-.305-5.467-1.334-5.467-5.931 0-1.311.469-2.381 1.236-3.221-.124-.303-.535-1.524.117-3.176 0 0 1.008-.322 3.301 1.23.957-.266 1.983-.399 3.003-.404 1.02.005 2.047.138 3.006.404 2.291-1.552 3.297-1.23 3.297-1.23.653 1.653.242 2.874.118 3.176.77.84 1.235 1.911 1.235 3.221 0 4.609-2.807 5.624-5.479 5.921.43.372.823 1.102.823 2.222v3.293c0 .319.192.694.801.576 4.765-1.589 8.199-6.086 8.199-11.386 0-6.627-5.373-12-12-12z" />
                  </svg>
                  <CardTitle className="text-lg">GitHub</CardTitle>
                </CardHeader>
                <CardContent>
                  <p className="text-sm text-muted-foreground mb-4">
                    Report issues or contribute to the project
                  </p>
                  <Button variant="outline" asChild>
                    <a
                      href="https://github.com/marketcalls/openalgo"
                      target="_blank"
                      rel="noopener noreferrer"
                    >
                      View GitHub
                    </a>
                  </Button>
                </CardContent>
              </Card>
            </div>
          </div>
        </div>
      </main>

      {/* Footer */}
      <Footer />
    </div>
  )
}
