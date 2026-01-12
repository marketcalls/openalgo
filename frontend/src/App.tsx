import { BrowserRouter, Route, Routes } from 'react-router-dom'
import { Providers } from '@/app/providers'
import { AuthSync } from '@/components/auth/AuthSync'
import { FullWidthLayout } from '@/components/layout/FullWidthLayout'
import { Layout } from '@/components/layout/Layout'
import ActionCenter from '@/pages/ActionCenter'
import Analyzer from '@/pages/Analyzer'
import ApiKey from '@/pages/ApiKey'
// Phase 7 Pages - Admin
import { AdminIndex, FreezeQty, Holidays, MarketTimings } from '@/pages/admin'
import BrokerSelect from '@/pages/BrokerSelect'
// Broker TOTP
import BrokerTOTP from '@/pages/BrokerTOTP'
// Phase 6 Pages - Chartink
import {
  ChartinkIndex,
  ConfigureChartinkSymbols,
  NewChartinkStrategy,
  ViewChartinkStrategy,
} from '@/pages/chartink'
import Dashboard from '@/pages/Dashboard'
import Download from '@/pages/Download'
import GoCharting from '@/pages/GoCharting'
import Holdings from '@/pages/Holdings'
// Pages
import Home from '@/pages/Home'
import Login from '@/pages/Login'
import LiveLogs from '@/pages/Logs'
// Phase 7 Pages - Settings
import LogsIndex from '@/pages/LogsIndex'
// Phase 7 Pages - Monitoring
import { LatencyDashboard, SecurityDashboard, TrafficDashboard } from '@/pages/monitoring'
import NotFound from '@/pages/NotFound'
import OrderBook from '@/pages/OrderBook'
import Platforms from '@/pages/Platforms'
import Playground from '@/pages/Playground'
import PnLTracker from '@/pages/PnLTracker'
import Positions from '@/pages/Positions'
import Profile from '@/pages/Profile'
// Phase 6 Pages - Python Strategy
import {
  EditPythonStrategy,
  NewPythonStrategy,
  PythonStrategyIndex,
  PythonStrategyLogs,
} from '@/pages/python-strategy'
// Public Pages
import ResetPassword from '@/pages/ResetPassword'
import Sandbox from '@/pages/Sandbox'
import SandboxPnL from '@/pages/SandboxPnL'
import Search from '@/pages/Search'
import ServerError from '@/pages/ServerError'
import Setup from '@/pages/Setup'
// Phase 6 Pages - Strategy
import { ConfigureSymbols, NewStrategy, StrategyIndex, ViewStrategy } from '@/pages/strategy'
import Token from '@/pages/Token'
import TradeBook from '@/pages/TradeBook'
// Phase 4 Pages
import TradingView from '@/pages/TradingView'
// Phase 7 Pages - Telegram
import { TelegramAnalytics, TelegramConfig, TelegramIndex, TelegramUsers } from '@/pages/telegram'
import WebSocketTest from '@/pages/WebSocketTest'

function App() {
  return (
    <Providers>
      <BrowserRouter>
        <AuthSync>
          <Routes>
            {/* Public routes */}
            <Route path="/" element={<Home />} />
            <Route path="/setup" element={<Setup />} />
            <Route path="/login" element={<Login />} />
            <Route path="/reset-password" element={<ResetPassword />} />
            <Route path="/download" element={<Download />} />
            <Route path="/error" element={<ServerError />} />

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
              <Route path="/websocket/test" element={<WebSocketTest />} />
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
              {/* Phase 6: Chartink Strategies */}
              <Route path="/chartink" element={<ChartinkIndex />} />
              <Route path="/chartink/new" element={<NewChartinkStrategy />} />
              <Route path="/chartink/:strategyId" element={<ViewChartinkStrategy />} />
              <Route
                path="/chartink/:strategyId/configure"
                element={<ConfigureChartinkSymbols />}
              />
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
              {/* Phase 7: Settings & Action Center */}
              <Route path="/profile" element={<Profile />} />
              <Route path="/action-center" element={<ActionCenter />} />
            </Route>

            {/* Full-width protected routes */}
            <Route element={<FullWidthLayout />}>
              <Route path="/playground" element={<Playground />} />
            </Route>

            {/* 404 Not Found */}
            <Route path="*" element={<NotFound />} />
          </Routes>
        </AuthSync>
      </BrowserRouter>
    </Providers>
  )
}

export default App
