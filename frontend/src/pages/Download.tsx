import { Apple, Download as DownloadIcon, Monitor } from 'lucide-react'
import { useState } from 'react'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'

interface DownloadItem {
  platform: string
  version: string
  url: string
  label: string
}

const downloads: Record<string, DownloadItem[]> = {
  mac: [
    {
      platform: 'Mac Universal',
      version: 'v0.1.0',
      url: 'https://github.com/marketcalls/fastscalper-tauri/releases/download/v0.1.0/fastscalper_0.1.0_universal.dmg',
      label: 'Download DMG',
    },
    {
      platform: 'Mac Universal (Portable)',
      version: 'v0.1.0',
      url: 'https://github.com/marketcalls/fastscalper-tauri/releases/download/v0.1.0/fastscalper_0.1.0_universal_mac.zip',
      label: 'Download ZIP',
    },
  ],
  linux: [
    {
      platform: 'Ubuntu / Debian',
      version: 'v0.1.0',
      url: 'https://github.com/marketcalls/fastscalper-tauri/releases/download/v0.1.0/fastscalper_0.1.0_amd64.deb',
      label: 'Download DEB',
    },
    {
      platform: 'Fedora / Red Hat',
      version: 'v0.1.0',
      url: 'https://github.com/marketcalls/fastscalper-tauri/releases/download/v0.1.0/fastscalper-0.1.0-1.x86_64.rpm',
      label: 'Download RPM',
    },
    {
      platform: 'AppImage',
      version: 'v0.1.0',
      url: 'https://github.com/marketcalls/fastscalper-tauri/releases/download/v0.1.0/fastscalper_0.1.0_amd64.AppImage',
      label: 'Download AppImage',
    },
  ],
  windows: [
    {
      platform: 'Windows (MSI)',
      version: 'v0.1.0',
      url: 'https://github.com/marketcalls/fastscalper-tauri/releases/download/v0.1.0/fastscalper_0.1.0_x64_en-US.msi',
      label: 'Download MSI',
    },
    {
      platform: 'Windows (EXE)',
      version: 'v0.1.0',
      url: 'https://github.com/marketcalls/fastscalper-tauri/releases/download/v0.1.0/fastscalper_0.1.0_x64-setup.exe',
      label: 'Download EXE',
    },
  ],
}

const versions = ['0.1.0']

export default function Download() {
  const [selectedVersion, setSelectedVersion] = useState('0.1.0')
  const [selectedPlatform, setSelectedPlatform] = useState('mac')

  return (
    <div className="container mx-auto px-4 py-8 max-w-4xl">
      <h1 className="text-4xl font-bold text-center mb-8">
        FastScalper <span className="text-primary">Desktop</span>
      </h1>

      <Card>
        <CardHeader>
          <div className="flex flex-col sm:flex-row justify-between items-start sm:items-center gap-4">
            <CardTitle>Available Downloads</CardTitle>
            <Select value={selectedVersion} onValueChange={setSelectedVersion}>
              <SelectTrigger className="w-[180px]">
                <SelectValue placeholder="Select version" />
              </SelectTrigger>
              <SelectContent>
                {versions.map((v) => (
                  <SelectItem key={v} value={v}>
                    Version {v}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
        </CardHeader>
        <CardContent>
          <Tabs value={selectedPlatform} onValueChange={setSelectedPlatform}>
            <TabsList className="grid w-full grid-cols-3 mb-6">
              <TabsTrigger value="mac" className="flex items-center gap-2">
                <Apple className="h-4 w-4" />
                macOS
              </TabsTrigger>
              <TabsTrigger value="linux" className="flex items-center gap-2">
                <svg className="h-4 w-4" fill="currentColor" viewBox="0 0 24 24">
                  <path d="M12 2a10 10 0 1 0 0 20 10 10 0 0 0 0-20zm0 18a8 8 0 1 1 0-16 8 8 0 0 1 0 16z" />
                </svg>
                Linux
              </TabsTrigger>
              <TabsTrigger value="windows" className="flex items-center gap-2">
                <Monitor className="h-4 w-4" />
                Windows
              </TabsTrigger>
            </TabsList>

            {Object.entries(downloads).map(([platform, items]) => (
              <TabsContent key={platform} value={platform}>
                <div className="rounded-md border">
                  <Table>
                    <TableHeader>
                      <TableRow>
                        <TableHead>Platform</TableHead>
                        <TableHead>Version</TableHead>
                        <TableHead className="text-right">Download</TableHead>
                      </TableRow>
                    </TableHeader>
                    <TableBody>
                      {items.map((item, index) => (
                        <TableRow key={index}>
                          <TableCell className="font-medium">{item.platform}</TableCell>
                          <TableCell>{item.version}</TableCell>
                          <TableCell className="text-right">
                            <Button size="sm" asChild>
                              <a href={item.url} target="_blank" rel="noopener noreferrer">
                                <DownloadIcon className="h-4 w-4 mr-2" />
                                {item.label}
                              </a>
                            </Button>
                          </TableCell>
                        </TableRow>
                      ))}
                    </TableBody>
                  </Table>
                </div>
              </TabsContent>
            ))}
          </Tabs>
        </CardContent>
      </Card>
    </div>
  )
}
