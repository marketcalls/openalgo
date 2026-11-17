import { Apple, Download as DownloadIcon, ExternalLink, Monitor } from 'lucide-react'
import { type ReactNode, useState } from 'react'
import { Link } from 'react-router'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'

type Platform = 'windows' | 'mac' | 'linux'

interface DownloadItem {
  platform: string
  url: string
  label: string
}

interface ExplainerSection {
  title: string
  items: ReactNode[]
}

interface Product {
  id: string
  name: string
  version: string
  license: string
  description: ReactNode
  releaseUrl: string
  checksumsUrl?: string
  /** Installers per operating system, shown as tabs. */
  downloads?: Record<Platform, DownloadItem[]>
  /** A single download that is not tied to one operating system. */
  files?: DownloadItem[]
  sections: ExplainerSection[]
  requirements?: ReactNode[]
  installSteps?: ReactNode[]
  notes?: ReactNode[]
}

function Code({ children }: { children: ReactNode }) {
  return (
    <code className="rounded bg-muted px-1 py-0.5 font-mono text-xs text-foreground">
      {children}
    </code>
  )
}

function ExternalTextLink({ href, children }: { href: string; children: ReactNode }) {
  return (
    <a
      href={href}
      target="_blank"
      rel="noopener noreferrer"
      className="text-primary underline-offset-4 hover:underline"
    >
      {children}
    </a>
  )
}

const OPENALGO_DESKTOP_VERSION = '1.0.5'
const openalgoDesktopBase = `https://github.com/marketcalls/openalgo-desktop/releases/download/v${OPENALGO_DESKTOP_VERSION}`
const openalgoDesktopFile = (suffix: string) =>
  `${openalgoDesktopBase}/OpenAlgo.Desktop_${OPENALGO_DESKTOP_VERSION}_${suffix}`

const FASTSCALPER_VERSION = '0.1.0'
const fastscalperBase = `https://github.com/marketcalls/fastscalper-tauri/releases/download/v${FASTSCALPER_VERSION}`

const CHROME_PLUGIN_VERSION = '1.0'
const EXCEL_ADDIN_VERSION = '1.0.7'

const products: Product[] = [
  {
    id: 'openalgo-desktop',
    name: 'OpenAlgo Desktop',
    version: OPENALGO_DESKTOP_VERSION,
    license: 'AGPL-3.0',
    description:
      'OpenAlgo on your own computer. Install, sign in, connect your broker and trade. There is no server to set up, no Python to install and no .env file: every setting and credential is entered inside the app.',
    releaseUrl: `https://github.com/marketcalls/openalgo-desktop/releases/tag/v${OPENALGO_DESKTOP_VERSION}`,
    checksumsUrl: `${openalgoDesktopBase}/SHA256SUMS.txt`,
    downloads: {
      windows: [
        {
          platform: 'Windows 10 / 11 (x64)',
          url: openalgoDesktopFile('x64-setup.exe'),
          label: 'Download EXE',
        },
      ],
      mac: [
        {
          platform: 'macOS Apple Silicon (M1 and later)',
          url: openalgoDesktopFile('aarch64.dmg'),
          label: 'Download DMG',
        },
        {
          platform: 'macOS Intel',
          url: openalgoDesktopFile('x64.dmg'),
          label: 'Download DMG',
        },
      ],
      linux: [
        {
          platform: 'Ubuntu / Debian x64',
          url: openalgoDesktopFile('amd64.deb'),
          label: 'Download DEB',
        },
        {
          platform: 'AppImage x64',
          url: openalgoDesktopFile('amd64.AppImage'),
          label: 'Download AppImage',
        },
        {
          platform: 'Ubuntu / Debian ARM64',
          url: openalgoDesktopFile('arm64.deb'),
          label: 'Download DEB',
        },
        {
          platform: 'AppImage ARM64',
          url: openalgoDesktopFile('aarch64.AppImage'),
          label: 'Download AppImage',
        },
      ],
    },
    sections: [
      {
        title: 'Works like OpenAlgo web',
        items: [
          'The same screens, REST API and market data WebSocket, on the same addresses (127.0.0.1:5000 and 8765).',
          'Connects to all 38 brokers of OpenAlgo web, Delta Exchange for crypto among them.',
          'TradingView, Amibroker, Excel, the Python SDK and MCP clients connect to it unchanged.',
        ],
      },
      {
        title: 'Built in',
        items: [
          'Strategy module with stop, target and trailing stop rules.',
          'Flow, the no-code workflow builder, new in 1.0.5.',
          'Charting terminal and scalping terminal.',
          'Options tools: option chain, Greeks, OI tracker, strategy builder and more.',
          'Sandbox mode (analyzer mode) for trying a strategy without real orders.',
        ],
      },
      {
        title: 'Safety',
        items: [
          'Broker credentials and keys are stored encrypted, with a key locked by your OpenAlgo password.',
          'Updates are signed and checked before they install.',
          'Free and open source.',
        ],
      },
    ],
    notes: [
      'The installers are not code-signed yet, so Windows and macOS show a warning the first time the app is opened.',
      <>
        On an Apple Silicon Mac, if macOS says the app &quot;is damaged and can&apos;t be
        opened&quot;, the file is not damaged: the app is not yet notarized by Apple. Do not move it
        to the Trash. In Terminal, run{' '}
        <Code>xattr -dr com.apple.quarantine &quot;/Applications/OpenAlgo Desktop.app&quot;</Code>{' '}
        and open the app again.{' '}
        <ExternalTextLink href="https://docs.openalgo.in/openalgo-desktop/install-on-macos">
          Step by step guide
        </ExternalTextLink>
        .
      </>,
      'Python Strategies stay on OpenAlgo web.',
      'Already installed? OpenAlgo Desktop offers new versions as an in-app update.',
    ],
  },
  {
    id: 'fastscalper',
    name: 'FastScalper Desktop',
    version: FASTSCALPER_VERSION,
    license: 'MIT',
    description:
      'A lightweight desktop app for quick scalping orders. It sends every order through your OpenAlgo, so it works with whichever broker you are logged in to.',
    releaseUrl: `https://github.com/marketcalls/fastscalper-tauri/releases/tag/v${FASTSCALPER_VERSION}`,
    downloads: {
      windows: [
        {
          platform: 'Windows (MSI)',
          url: `${fastscalperBase}/fastscalper_${FASTSCALPER_VERSION}_x64_en-US.msi`,
          label: 'Download MSI',
        },
        {
          platform: 'Windows (EXE)',
          url: `${fastscalperBase}/fastscalper_${FASTSCALPER_VERSION}_x64-setup.exe`,
          label: 'Download EXE',
        },
      ],
      mac: [
        {
          platform: 'Mac Universal',
          url: `${fastscalperBase}/fastscalper_${FASTSCALPER_VERSION}_universal.dmg`,
          label: 'Download DMG',
        },
        {
          platform: 'Mac Universal (Portable)',
          url: `${fastscalperBase}/fastscalper_${FASTSCALPER_VERSION}_universal_mac.zip`,
          label: 'Download ZIP',
        },
      ],
      linux: [
        {
          platform: 'Ubuntu / Debian',
          url: `${fastscalperBase}/fastscalper_${FASTSCALPER_VERSION}_amd64.deb`,
          label: 'Download DEB',
        },
        {
          platform: 'Fedora / Red Hat',
          url: `${fastscalperBase}/fastscalper-${FASTSCALPER_VERSION}-1.x86_64.rpm`,
          label: 'Download RPM',
        },
        {
          platform: 'AppImage',
          url: `${fastscalperBase}/fastscalper_${FASTSCALPER_VERSION}_amd64.AppImage`,
          label: 'Download AppImage',
        },
      ],
    },
    sections: [
      {
        title: 'Trading',
        items: [
          'One-click Long Entry, Long Exit, Short Entry and Short Exit (LE, LX, SE, SX).',
          'CNC, MIS and NRML products.',
          'Voice alerts confirm each order, and can be turned off.',
        ],
      },
      {
        title: 'Settings',
        items: [
          'API key and host URL of your OpenAlgo.',
          'Exchange and product.',
          'Settings are kept between sessions.',
        ],
      },
      {
        title: 'Platforms',
        items: [
          'Windows.',
          'Intel and Apple Silicon Macs (one universal build).',
          'Ubuntu, Debian and Fedora.',
        ],
      },
    ],
  },
  {
    id: 'chrome-plugin',
    name: 'Chrome Plugin',
    version: CHROME_PLUGIN_VERSION,
    license: 'MIT',
    description:
      'Trade from your browser. The extension adds a small row of LE, LX, SE and SX buttons to any web page you are reading, and sends each order to your OpenAlgo.',
    releaseUrl: `https://github.com/marketcalls/openalgo-chrome/releases/tag/v${CHROME_PLUGIN_VERSION}`,
    files: [
      {
        platform: 'Chrome extension (Windows, macOS, Linux)',
        url: `https://github.com/marketcalls/openalgo-chrome/releases/download/v${CHROME_PLUGIN_VERSION}/openalgo-chrome.zip`,
        label: 'Download ZIP',
      },
    ],
    sections: [
      {
        title: 'What it does',
        items: [
          'Long Entry, Long Exit, Short Entry and Short Exit buttons on any web page.',
          'A compact bar you can drag anywhere on the screen.',
          'A notification after each order, so you see the result at once.',
        ],
      },
      {
        title: 'Settings',
        items: [
          'Host URL and API key of your OpenAlgo.',
          'Symbol, exchange (NSE, BSE, NFO, BFO, MCX, CDS), product (MIS, NRML, CNC) and quantity.',
        ],
      },
    ],
    installSteps: [
      <>
        Download <Code>openalgo-chrome.zip</Code> and unzip it.
      </>,
      <>
        Open <Code>chrome://extensions</Code> in Chrome.
      </>,
      'Turn on Developer mode, at the top right.',
      <>
        Click Load unpacked and select the unzipped <Code>openalgo-chrome</Code> folder.
      </>,
      'Open the extension settings from its menu (the three vertical dots), fill in every field and click Save before placing an order.',
    ],
    notes: [
      'The extension is not on the Chrome Web Store yet, which is why it is loaded with Developer mode.',
    ],
  },
  {
    id: 'excel-addin',
    name: 'Excel Add-in',
    version: EXCEL_ADDIN_VERSION,
    license: 'MIT',
    description:
      'Trade and analyse from Microsoft Excel. 82 worksheet functions cover orders, market data, option chains and Greeks, and stream live prices into cells.',
    releaseUrl: `https://github.com/marketcalls/OpenAlgo-Excel/releases/tag/v${EXCEL_ADDIN_VERSION}`,
    files: [
      {
        platform: 'Windows installer (32-bit and 64-bit Excel)',
        url: `https://github.com/marketcalls/OpenAlgo-Excel/releases/download/v${EXCEL_ADDIN_VERSION}/OpenAlgoSetup.exe`,
        label: 'Download EXE',
      },
    ],
    sections: [
      {
        title: 'Orders',
        items: [
          'Place, modify and cancel orders from a cell.',
          'Smart, basket, split, options and GTT orders, and closing positions.',
        ],
      },
      {
        title: 'Market data and options',
        items: [
          'Quotes, market depth and historical candles.',
          'Live LTP, quote and depth streamed into cells.',
          'Option chain, Greeks and synthetic futures.',
        ],
      },
      {
        title: 'Account',
        items: [
          'Funds, order book, trade book, positions, holdings and margin.',
          'Switch between sandbox mode and live trading.',
          'Telegram and WhatsApp notifications.',
        ],
      },
    ],
    requirements: [
      'Windows with Microsoft Excel (Microsoft 365 recommended).',
      <>
        The{' '}
        <ExternalTextLink href="https://dotnet.microsoft.com/en-us/download/dotnet/8.0">
          .NET 8 Desktop Runtime
        </ExternalTextLink>
        .
      </>,
    ],
    installSteps: [
      'Install the .NET 8 Desktop Runtime, then restart your computer.',
      <>
        Run <Code>OpenAlgoSetup.exe</Code>. It picks the 32-bit or 64-bit add-in to match your
        Excel.
      </>,
      <>
        In any cell, enter <Code>=oa_api(&quot;your_api_key&quot;)</Code> once. If OpenAlgo is not
        at http://127.0.0.1:5000, add the address:{' '}
        <Code>
          =oa_api(&quot;your_api_key&quot;, &quot;v1&quot;, &quot;https://your-host&quot;)
        </Code>
        . The key is saved for later sessions.
      </>,
    ],
    notes: [
      <>
        An order formula sends its order whenever Excel calculates it.{' '}
        <Code>=oa_trading_enabled(FALSE)</Code> stops order functions from sending, for example
        before a full recalculation.
      </>,
      'Upgrading from 1.0.6 or earlier? A few function names changed: the release notes list the old and new names.',
      <>
        Every function is described in the{' '}
        <ExternalTextLink href="https://docs.openalgo.in/trading-platform/excel">
          Excel documentation
        </ExternalTextLink>
        .
      </>,
    ],
  },
]

const platformOrder: Platform[] = ['windows', 'mac', 'linux']

function detectPlatform(): Platform {
  if (typeof navigator === 'undefined') return 'windows'
  const ua = navigator.userAgent.toLowerCase()
  if (ua.includes('mac')) return 'mac'
  if (ua.includes('linux') && !ua.includes('android')) return 'linux'
  return 'windows'
}

function PlatformLabel({ platform }: { platform: Platform }) {
  if (platform === 'mac') {
    return (
      <>
        <Apple className="h-4 w-4" />
        macOS
      </>
    )
  }
  if (platform === 'linux') {
    return (
      <>
        <svg className="h-4 w-4" fill="currentColor" viewBox="0 0 24 24" aria-hidden="true">
          <path d="M12 2a10 10 0 1 0 0 20 10 10 0 0 0 0-20zm0 18a8 8 0 1 1 0-16 8 8 0 0 1 0 16z" />
        </svg>
        Linux
      </>
    )
  }
  return (
    <>
      <Monitor className="h-4 w-4" />
      Windows
    </>
  )
}

function DownloadTable({ items, version }: { items: DownloadItem[]; version: string }) {
  return (
    <div className="rounded-md border">
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>Platform</TableHead>
            <TableHead className="hidden sm:table-cell">Version</TableHead>
            <TableHead className="text-right">Download</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {items.map((item) => (
            <TableRow key={item.url}>
              <TableCell className="whitespace-normal font-medium">{item.platform}</TableCell>
              <TableCell className="hidden sm:table-cell">v{version}</TableCell>
              <TableCell className="w-px text-right">
                <Button size="sm" asChild>
                  <a href={item.url} target="_blank" rel="noopener noreferrer">
                    <DownloadIcon className="mr-2 h-4 w-4" />
                    {item.label}
                  </a>
                </Button>
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </div>
  )
}

function ListBlock({
  title,
  items,
  ordered,
}: {
  title: string
  items: ReactNode[]
  ordered?: boolean
}) {
  const ListTag = ordered ? 'ol' : 'ul'
  return (
    <div className="space-y-2">
      <h3 className="text-sm font-semibold">{title}</h3>
      <ListTag
        className={`space-y-1.5 pl-5 text-sm text-muted-foreground ${ordered ? 'list-decimal' : 'list-disc'}`}
      >
        {items.map((item, index) => (
          <li key={index}>{item}</li>
        ))}
      </ListTag>
    </div>
  )
}

function ProductDownloads({ product }: { product: Product }) {
  const [selectedPlatform, setSelectedPlatform] = useState<Platform>(detectPlatform)

  return (
    <Card id={product.id} className="scroll-mt-24">
      <CardHeader>
        <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
          <div className="space-y-1.5">
            <div className="flex flex-wrap items-center gap-2">
              <CardTitle className="text-2xl">{product.name}</CardTitle>
              <Badge variant="secondary">v{product.version}</Badge>
              <Badge variant="outline">{product.license}</Badge>
            </div>
            <CardDescription>{product.description}</CardDescription>
          </div>
          <Button variant="outline" size="sm" asChild className="shrink-0">
            <a href={product.releaseUrl} target="_blank" rel="noopener noreferrer">
              <ExternalLink className="mr-2 h-4 w-4" />
              Release notes
            </a>
          </Button>
        </div>
      </CardHeader>
      <CardContent className="space-y-6">
        <div className="grid gap-6 sm:grid-cols-2 lg:grid-cols-3">
          {product.sections.map((section) => (
            <ListBlock key={section.title} title={section.title} items={section.items} />
          ))}
        </div>

        {(product.requirements || product.installSteps) && (
          <div className="grid gap-6 sm:grid-cols-2">
            {product.requirements && (
              <ListBlock title="Requirements" items={product.requirements} />
            )}
            {product.installSteps && (
              <ListBlock title="How to install" items={product.installSteps} ordered />
            )}
          </div>
        )}

        {product.downloads && (
          <Tabs
            value={selectedPlatform}
            onValueChange={(value) => setSelectedPlatform(value as Platform)}
          >
            <TabsList className="mb-6 grid w-full grid-cols-3">
              {platformOrder.map((platform) => (
                <TabsTrigger key={platform} value={platform} className="flex items-center gap-2">
                  <PlatformLabel platform={platform} />
                </TabsTrigger>
              ))}
            </TabsList>

            {platformOrder.map((platform) => (
              <TabsContent key={platform} value={platform}>
                <DownloadTable
                  items={product.downloads?.[platform] ?? []}
                  version={product.version}
                />
              </TabsContent>
            ))}
          </Tabs>
        )}

        {product.files && <DownloadTable items={product.files} version={product.version} />}

        {product.notes && <ListBlock title="Good to know" items={product.notes} />}

        {product.checksumsUrl && (
          <p className="text-sm text-muted-foreground">
            To check a download, compare its checksum with{' '}
            <ExternalTextLink href={product.checksumsUrl}>SHA256SUMS.txt</ExternalTextLink>.
          </p>
        )}
      </CardContent>
    </Card>
  )
}

export default function Download() {
  return (
    <div className="container mx-auto max-w-4xl px-4 py-8">
      <h1 className="mb-3 text-center text-4xl font-bold">
        Download <span className="text-primary">OpenAlgo</span>
      </h1>
      <p className="mx-auto mb-6 max-w-2xl text-center text-muted-foreground">
        OpenAlgo Desktop runs the whole platform on your own computer. FastScalper, the Chrome
        Plugin and the Excel Add-in are companion apps that place orders through an OpenAlgo you
        already run, on your computer or on your server.
      </p>

      <nav aria-label="Downloads" className="mb-8 flex flex-wrap justify-center gap-2">
        {products.map((product) => (
          <Button key={product.id} variant="outline" size="sm" asChild>
            <a href={`#${product.id}`}>{product.name}</a>
          </Button>
        ))}
      </nav>

      <div className="space-y-8">
        <ProductDownloads product={products[0]} />

        <Card className="border-dashed">
          <CardHeader>
            <CardTitle className="text-lg">Before you use a companion app</CardTitle>
            <CardDescription>
              FastScalper, the Chrome Plugin and the Excel Add-in need these from your OpenAlgo.
              OpenAlgo Desktop needs none of them: it is OpenAlgo.
            </CardDescription>
          </CardHeader>
          <CardContent>
            <ol className="list-decimal space-y-1.5 pl-5 text-sm text-muted-foreground">
              <li>OpenAlgo running, on this computer or on your server.</li>
              <li>
                An API key, from the{' '}
                <Link to="/apikey" className="text-primary underline-offset-4 hover:underline">
                  API Key
                </Link>{' '}
                page.
              </li>
              <li>
                The host URL of your OpenAlgo, for example <Code>http://127.0.0.1:5000</Code>.
              </li>
              <li>Your broker logged in to OpenAlgo.</li>
            </ol>
          </CardContent>
        </Card>

        {products.slice(1).map((product) => (
          <ProductDownloads key={product.id} product={product} />
        ))}
      </div>
    </div>
  )
}
