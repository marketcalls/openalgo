import { lazy, Suspense } from 'react'
import { BrowserRouter, Route, Routes } from 'react-router-dom'
import { Providers } from '@/app/providers'
import { AuthSync } from '@/components/auth/AuthSync'
import { FullWidthLayout } from '@/components/layout/FullWidthLayout'
import { Layout } from '@/components/layout/Layout'
import { PageLoader } from '@/components/ui/page-loader'

// Lazy load all pages for code splitting
// Public pages
const Home = lazy(() => import('@/pages/Home'))
const Faq = lazy(() => import('@/pages/Faq'))
const Setup = lazy(() => import('@/pages/Setup'))
const Login = lazy(() => import('@/pages/Login'))
const ResetPassword = lazy(() => import('@/pages/ResetPassword'))
const Download = lazy(() => import('@/pages/Download'))
const ServerError = lazy(() => import('@/pages/ServerError'))
const RateLimited = lazy(() => import('@/pages/RateLimited'))
const NotFound = lazy(() => import('@/pages/NotFound'))

// Broker auth
const BrokerSelect = lazy(() => import('@/pages/BrokerSelect'))
const BrokerTOTP = lazy(() => import('@/pages/BrokerTOTP'))

// Main pages
const Dashboard = lazy(() => import('@/pages/Dashboard'))
const Positions = lazy(() => import('@/pages/Positions'))
const OrderBook = lazy(() => import('@/pages/OrderBook'))
const TradeBook = lazy(() => import('@/pages/TradeBook'))
const Holdings = lazy(() => import('@/pages/Holdings'))
const Token = lazy(() => import('@/pages/Token'))
const Search = lazy(() => import('@/pages/Search'))
const ApiKey = lazy(() => import('@/pages/ApiKey'))
const Profile = lazy(() => import('@/pages/Profile'))
const MasterContract = lazy(() => import('@/pages/MasterContract'))
const ActionCenter = lazy(() => import('@/pages/ActionCenter'))

// Platform pages
const Platforms = lazy(() => import('@/pages/Platforms'))
const TradingView = lazy(() => import('@/pages/TradingView'))
const GoCharting = lazy(() => import('@/pages/GoCharting'))
const PnLTracker = lazy(() => import('@/pages/PnLTracker'))

// Sandbox & Analyzer
const Sandbox = lazy(() => import('@/pages/Sandbox'))
const SandboxPnL = lazy(() => import('@/pages/SandboxPnL'))
const Analyzer = lazy(() => import('@/pages/Analyzer'))
const WebSocketTest = lazy(() => import('@/pages/WebSocketTest'))
const Playground = lazy(() => import('@/pages/Playground'))
const Historify = lazy(() => import('@/pages/Historify'))
const HistorifyCharts = lazy(() => import('@/pages/HistorifyCharts'))

// Tools & Option Chain
const Tools = lazy(() => import('@/pages/Tools'))
const OptionChain = lazy(() => import('@/pages/OptionChain'))
const IVChart = lazy(() => import('@/pages/IVChart'))
const OITracker = lazy(() => import('@/pages/OITracker'))
const MaxPain = lazy(() => import('@/pages/MaxPain'))
const StraddleChart = lazy(() => import('@/pages/StraddleChart'))
const VolSurface = lazy(() => import('@/pages/VolSurface'))
const GEXDashboard = lazy(() => import('@/pages/GEXDashboard'))
const IVSmile = lazy(() => import('@/pages/IVSmile'))
const OIProfile = lazy(() => import('@/pages/OIProfile'))

// Strategy pages
const StrategyIndex = lazy(() => import('@/pages/strategy/StrategyIndex'))
const NewStrategy = lazy(() => import('@/pages/strategy/NewStrategy'))
const ViewStrategy = lazy(() => import('@/pages/strategy/ViewStrategy'))
const ConfigureSymbols = lazy(() => import('@/pages/strategy/ConfigureSymbols'))

// Python Strategy pages
const PythonStrategyIndex = lazy(() => import('@/pages/python-strategy/PythonStrategyIndex'))
const NewPythonStrategy = lazy(() => import('@/pages/python-strategy/NewPythonStrategy'))
const EditPythonStrategy = lazy(() => import('@/pages/python-strategy/EditPythonStrategy'))
const PythonStrategyLogs = lazy(() => import('@/pages/python-strategy/PythonStrategyLogs'))
const SchedulePythonStrategy = lazy(() => import('@/pages/python-strategy/SchedulePythonStrategy'))
const PythonStrategyGuide = lazy(() => import('@/pages/python-strategy/PythonStrategyGuide'))

// Chartink pages
const ChartinkIndex = lazy(() => import('@/pages/chartink/ChartinkIndex'))
const NewChartinkStrategy = lazy(() => import('@/pages/chartink/NewChartinkStrategy'))
const ViewChartinkStrategy = lazy(() => import('@/pages/chartink/ViewChartinkStrategy'))
const ConfigureChartinkSymbols = lazy(() => import('@/pages/chartink/ConfigureChartinkSymbols'))

// Flow pages
const FlowIndex = lazy(() => import('@/pages/flow/FlowIndex'))
const FlowEditor = lazy(() => import('@/pages/flow/FlowEditor'))
const FlowKeyboardShortcuts = lazy(() => import('@/pages/flow/FlowKeyboardShortcuts'))

// Admin pages
const AdminIndex = lazy(() => import('@/pages/admin/AdminIndex'))
const FreezeQty = lazy(() => import('@/pages/admin/FreezeQty'))
const Holidays = lazy(() => import('@/pages/admin/Holidays'))
const MarketTimings = lazy(() => import('@/pages/admin/MarketTimings'))

// Telegram pages
const TelegramIndex = lazy(() => import('@/pages/telegram/TelegramIndex'))
const TelegramConfig = lazy(() => import('@/pages/telegram/TelegramConfig'))
const TelegramUsers = lazy(() => import('@/pages/telegram/TelegramUsers'))
const TelegramAnalytics = lazy(() => import('@/pages/telegram/TelegramAnalytics'))

// Logs & Monitoring pages
const LogsIndex = lazy(() => import('@/pages/LogsIndex'))
const LiveLogs = lazy(() => import('@/pages/Logs'))
const SecurityDashboard = lazy(() => import('@/pages/monitoring/SecurityDashboard'))
const TrafficDashboard = lazy(() => import('@/pages/monitoring/TrafficDashboard'))
const LatencyDashboard = lazy(() => import('@/pages/monitoring/LatencyDashboard'))
const HealthMonitor = lazy(() => import('@/pages/HealthMonitor'))

function App() {
  return (
    <Providers>
      <BrowserRouter>
        <AuthSync>
          <Suspense fallback={<PageLoader />}>
            <Routes>
              {/* Public routes */}
              <Route path="/" element={<Home />} />
              <Route path="/faq" element={<Faq />} />
              <Route path="/setup" element={<Setup />} />
              <Route path="/login" element={<Login />} />
              <Route path="/reset-password" element={<ResetPassword />} />
              <Route path="/download" element={<Download />} />
              <Route path="/error" element={<ServerError />} />
              <Route path="/rate-limited" element={<RateLimited />} />

              {/* Broker auth routes */}
              <Route path="/broker" element={<BrokerSelect />} />
              <Route path="/broker/:broker/totp" element={<BrokerTOTP />} />
              {/* Dynamic broker TOTP routes for all supported brokers */}
              <Route path="/:broker/auth" element={<BrokerTOTP />} />

              {/* Protected routes - requires broker auth */}
              <Route element={<Layout />}>
                <Route path="/dashboard" element={<Dashboard />} />
                <Route path="/positions" element={<Positions />} />
                <Route path="/orderbook" element={<OrderBook />} />
                <Route path="/tradebook" element={<TradeBook />} />
                <Route path="/holdings" element={<Holdings />} />
                {/* Search routes - match Flask /search/* routes */}
                <Route path="/search/token" element={<Token />} />
                <Route path="/search" element={<Search />} />
                {/* API Key management */}
                <Route path="/apikey" element={<ApiKey />} />
                {/* Phase 4: Charts & Webhook Configuration */}
                <Route path="/platforms" element={<Platforms />} />
                <Route path="/tradingview" element={<TradingView />} />
                <Route path="/gocharting" element={<GoCharting />} />
                <Route path="/pnl-tracker" element={<PnLTracker />} />
                {/* Phase 4: Sandbox & Analyzer */}
                <Route path="/sandbox" element={<Sandbox />} />
                <Route path="/sandbox/mypnl" element={<SandboxPnL />} />
                <Route path="/analyzer" element={<Analyzer />} />
                <Route path="/tools" element={<Tools />} />
                <Route path="/optionchain" element={<OptionChain />} />
                <Route path="/ivchart" element={<IVChart />} />
                <Route path="/oitracker" element={<OITracker />} />
                <Route path="/maxpain" element={<MaxPain />} />
                <Route path="/straddle" element={<StraddleChart />} />
                <Route path="/volsurface" element={<VolSurface />} />
                <Route path="/gex" element={<GEXDashboard />} />
                <Route path="/ivsmile" element={<IVSmile />} />
                <Route path="/oiprofile" element={<OIProfile />} />
                <Route path="/websocket/test" element={<WebSocketTest />} />
                <Route path="/websocket/test/20" element={<WebSocketTest depthLevel={20} />} />
                <Route path="/websocket/test/30" element={<WebSocketTest depthLevel={30} />} />
                <Route path="/websocket/test/50" element={<WebSocketTest depthLevel={50} />} />
                {/* Phase 6: Webhook Strategies */}
                <Route path="/strategy" element={<StrategyIndex />} />
                <Route path="/strategy/new" element={<NewStrategy />} />
                <Route path="/strategy/:strategyId" element={<ViewStrategy />} />
                <Route path="/strategy/:strategyId/configure" element={<ConfigureSymbols />} />
                {/* Phase 6: Python Strategies */}
                <Route path="/python" element={<PythonStrategyIndex />} />
                <Route path="/python/new" element={<NewPythonStrategy />} />
                <Route path="/python/:strategyId/edit" element={<EditPythonStrategy />} />
                <Route path="/python/:strategyId/logs" element={<PythonStrategyLogs />} />
                <Route path="/python/:strategyId/schedule" element={<SchedulePythonStrategy />} />
                <Route path="/python/guide" element={<PythonStrategyGuide />} />
                {/* Phase 6: Chartink Strategies */}
                <Route path="/chartink" element={<ChartinkIndex />} />
                <Route path="/chartink/new" element={<NewChartinkStrategy />} />
                <Route path="/chartink/:strategyId" element={<ViewChartinkStrategy />} />
                <Route
                  path="/chartink/:strategyId/configure"
                  element={<ConfigureChartinkSymbols />}
                />
                {/* Flow Editor */}
                <Route path="/flow" element={<FlowIndex />} />
                <Route path="/flow/shortcuts" element={<FlowKeyboardShortcuts />} />
                {/* Phase 7: Admin */}
                <Route path="/admin" element={<AdminIndex />} />
                <Route path="/admin/freeze" element={<FreezeQty />} />
                <Route path="/admin/holidays" element={<Holidays />} />
                <Route path="/admin/timings" element={<MarketTimings />} />
                {/* Phase 7: Telegram */}
                <Route path="/telegram" element={<TelegramIndex />} />
                <Route path="/telegram/config" element={<TelegramConfig />} />
                <Route path="/telegram/users" element={<TelegramUsers />} />
                <Route path="/telegram/analytics" element={<TelegramAnalytics />} />
                {/* Phase 7: Logs & Monitoring */}
                <Route path="/logs" element={<LogsIndex />} />
                <Route path="/logs/live" element={<LiveLogs />} />
                <Route path="/logs/sandbox" element={<Analyzer />} />
                <Route path="/logs/security" element={<SecurityDashboard />} />
                <Route path="/logs/traffic" element={<TrafficDashboard />} />
                <Route path="/logs/latency" element={<LatencyDashboard />} />
                <Route path="/health" element={<HealthMonitor />} />
                {/* Phase 7: Settings & Action Center */}
                <Route path="/profile" element={<Profile />} />
                <Route path="/master-contract" element={<MasterContract />} />
                <Route path="/action-center" element={<ActionCenter />} />
              </Route>

              {/* Full-width protected routes */}
              <Route element={<FullWidthLayout />}>
                <Route path="/playground" element={<Playground />} />
                <Route path="/historify" element={<Historify />} />
                <Route path="/historify/charts" element={<HistorifyCharts />} />
                <Route path="/historify/charts/:symbol" element={<HistorifyCharts />} />
                {/* Flow Editor (full-width for canvas) */}
                <Route path="/flow/editor/:id" element={<FlowEditor />} />
              </Route>

              {/* 404 Not Found */}
              <Route path="*" element={<NotFound />} />
            </Routes>
          </Suspense>
        </AuthSync>
      </BrowserRouter>
    </Providers>
  )
}

export default App
