import { BrowserRouter, Routes, Route } from 'react-router-dom'
import { Providers } from '@/app/providers'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { useThemeStore } from '@/stores/themeStore'
import { Moon, Sun } from 'lucide-react'

function HomePage() {
  const { mode, toggleMode, appMode } = useThemeStore()

  return (
    <div className="min-h-screen bg-background p-8">
      <div className="max-w-4xl mx-auto space-y-8">
        <div className="flex items-center justify-between">
          <h1 className="text-4xl font-bold text-foreground">
            OpenAlgo v2.0
          </h1>
          <Button variant="outline" size="icon" onClick={toggleMode}>
            {mode === 'light' ? <Moon className="h-5 w-5" /> : <Sun className="h-5 w-5" />}
          </Button>
        </div>

        <Card>
          <CardHeader>
            <CardTitle>Frontend Setup Complete</CardTitle>
            <CardDescription>
              React 19 + Vite 7 + Tailwind CSS 4 + shadcn/ui
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="grid grid-cols-2 gap-4">
              <div className="p-4 rounded-lg bg-muted">
                <p className="text-sm text-muted-foreground">Theme Mode</p>
                <p className="text-lg font-semibold capitalize">{mode}</p>
              </div>
              <div className="p-4 rounded-lg bg-muted">
                <p className="text-sm text-muted-foreground">App Mode</p>
                <p className="text-lg font-semibold capitalize">{appMode}</p>
              </div>
            </div>

            <div className="flex gap-2 flex-wrap">
              <Button>Primary Button</Button>
              <Button variant="secondary">Secondary</Button>
              <Button variant="outline">Outline</Button>
              <Button variant="destructive">Destructive</Button>
            </div>

            <div className="flex gap-2 flex-wrap">
              <span className="inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium bg-green-500 text-white">
                +2.5% Profit
              </span>
              <span className="inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium bg-red-500 text-white">
                -1.2% Loss
              </span>
              <span className="inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium bg-blue-500 text-white">
                BUY
              </span>
              <span className="inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium bg-orange-500 text-white">
                SELL
              </span>
            </div>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>Installed Packages</CardTitle>
          </CardHeader>
          <CardContent>
            <ul className="space-y-1 text-sm">
              <li>✅ React 19.2.3</li>
              <li>✅ Vite 7.3.1</li>
              <li>✅ Tailwind CSS 4.1.18</li>
              <li>✅ shadcn/ui (22 components)</li>
              <li>✅ Zustand (state management)</li>
              <li>✅ TanStack Query (server state)</li>
              <li>✅ React Router DOM</li>
              <li>✅ Axios (API client)</li>
              <li>✅ Lucide React (icons)</li>
            </ul>
          </CardContent>
        </Card>
      </div>
    </div>
  )
}

function App() {
  return (
    <Providers>
      <BrowserRouter>
        <Routes>
          <Route path="/" element={<HomePage />} />
        </Routes>
      </BrowserRouter>
    </Providers>
  )
}

export default App
