import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom';
import { Providers } from '@/app/providers';
import { Layout } from '@/components/layout/Layout';
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
