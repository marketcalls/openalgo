import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom';
import { Providers } from '@/app/providers';
import { Layout } from '@/components/layout/Layout';
import { FullWidthLayout } from '@/components/layout/FullWidthLayout';
import { AuthSync } from '@/components/auth/AuthSync';

// Pages
import Home from '@/pages/Home';
import Setup from '@/pages/Setup';
import Login from '@/pages/Login';
import BrokerSelect from '@/pages/BrokerSelect';
import Dashboard from '@/pages/Dashboard';
import Positions from '@/pages/Positions';
import OrderBook from '@/pages/OrderBook';
import TradeBook from '@/pages/TradeBook';
import Holdings from '@/pages/Holdings';
import Token from '@/pages/Token';
import Search from '@/pages/Search';
import ApiKey from '@/pages/ApiKey';
import Playground from '@/pages/Playground';
// Phase 4 Pages
import TradingView from '@/pages/TradingView';
import GoCharting from '@/pages/GoCharting';
import PnLTracker from '@/pages/PnLTracker';
import Sandbox from '@/pages/Sandbox';
import SandboxPnL from '@/pages/SandboxPnL';
import Analyzer from '@/pages/Analyzer';
import WebSocketTest from '@/pages/WebSocketTest';
import Platforms from '@/pages/Platforms';
// Phase 6 Pages - Strategy
import { StrategyIndex, NewStrategy, ViewStrategy, ConfigureSymbols } from '@/pages/strategy';
// Phase 6 Pages - Python Strategy
import { PythonStrategyIndex, NewPythonStrategy, EditPythonStrategy, PythonStrategyLogs } from '@/pages/python-strategy';
// Phase 6 Pages - Chartink
import { ChartinkIndex, NewChartinkStrategy, ViewChartinkStrategy, ConfigureChartinkSymbols } from '@/pages/chartink';
// Phase 7 Pages - Admin
import { AdminIndex, FreezeQty, Holidays, MarketTimings } from '@/pages/admin';
// Phase 7 Pages - Telegram
import { TelegramIndex, TelegramConfig, TelegramUsers, TelegramAnalytics } from '@/pages/telegram';

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

            {/* Broker auth route - requires basic login */}
            {/* Note: /<broker>/callback routes are handled by Flask (brlogin_bp) */}
            <Route path="/broker" element={<BrokerSelect />} />

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
              <Route path="/chartink/:strategyId/configure" element={<ConfigureChartinkSymbols />} />
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
            </Route>

            {/* Full-width protected routes */}
            <Route element={<FullWidthLayout />}>
              <Route path="/playground" element={<Playground />} />
            </Route>

            {/* Catch-all redirect */}
            <Route path="*" element={<Navigate to="/dashboard" replace />} />
          </Routes>
        </AuthSync>
      </BrowserRouter>
    </Providers>
  );
}

export default App;
