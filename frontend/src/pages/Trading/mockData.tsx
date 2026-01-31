import type { BrokerInfo, IndicatorConfig, StrategyParameter,SymbolMetaData } from "./components";

// Mock data
export const STRATEGIES = [
    { id: 1, name: 'VWAP Mean Reversion', status: 'active' },
    { id: 2, name: 'Momentum Breakout', status: 'inactive' },
];

export const BROKERS = [
    { id: 'zerodha', name: 'Zerodha', connected: true },
    { id: 'upstox', name: 'Upstox', connected: false },
    { id: 'angel', name: 'Angel One', connected: false },
    { id: 'fyers', name: 'Fyers', connected: false }
];

export const WATCHLIST = [
    { symbol: 'RELIANCE', ltp: 2456.75, change: 1.23, changePercent: 2.45, volume: '2.3M' },
    { symbol: 'TCS', ltp: 3567.90, change: -12.30, changePercent: -1.15, volume: '1.8M' },
    { symbol: 'INFY', ltp: 1456.20, change: 23.45, changePercent: 3.21, volume: '3.1M' },
    { symbol: 'HDFCBANK', ltp: 1678.50, change: 8.90, changePercent: 0.89, volume: '4.2M' },
    { symbol: 'ICICIBANK', ltp: 987.30, change: -5.60, changePercent: -0.78, volume: '2.7M' },

    { symbol: 'RELIANCE', ltp: 2456.75, change: 1.23, changePercent: 2.45, volume: '2.3M' },
    { symbol: 'TCS', ltp: 3567.90, change: -12.30, changePercent: -1.15, volume: '1.8M' },
    { symbol: 'INFY', ltp: 1456.20, change: 23.45, changePercent: 3.21, volume: '3.1M' },
    { symbol: 'HDFCBANK', ltp: 1678.50, change: 8.90, changePercent: 0.89, volume: '4.2M' },
    { symbol: 'ICICIBANK', ltp: 987.30, change: -5.60, changePercent: -0.78, volume: '2.7M' }
];

export const ORDERS = [
    { id: 1, symbol: 'RELIANCE', type: 'BUY', qty: 10, price: 2450.00, status: 'Completed' },
    { id: 2, symbol: 'TCS', type: 'SELL', qty: 5, price: 3570.00, status: 'Pending' }
];

export const TRADES = [
    { id: 1, symbol: 'INFY', entry: 1430.00, exit: 1456.20, qty: 20, pnl: 524.00 },
    { id: 2, symbol: 'HDFC', entry: 1670.00, exit: 1678.50, qty: 15, pnl: 127.50 }
];

export const POSITIONS = [
    { symbol: 'RELIANCE', qty: 10, avgPrice: 2445.00, ltp: 2456.75, pnl: 117.50, pnlPercent: 0.48 },
    { symbol: 'INFY', qty: -20, avgPrice: 1450.00, ltp: 1456.20, pnl: -124.00, pnlPercent: -0.43 }
];

export const MOCK_USER_STRATEGIES = [
    {
        id: 'strat-001',
        name: 'EMA Crossover Pro',
        description: 'Fast EMA crosses above slow EMA for entry signals',
        performance: '+15.3%',
        status: 'active' as const
    },
    {
        id: 'strat-002',
        name: 'RSI Momentum',
        description: 'RSI oversold/overbought with volume confirmation',
        performance: '+8.7%',
        status: 'inactive' as const
    },
    {
        id: 'strat-003',
        name: 'Breakout Scanner',
        description: 'Detects price breakouts with volatility filter',
        performance: '+22.1%',
        status: 'active' as const
    },
    {
        id: 'strat-004',
        name: 'Mean Reversion',
        description: 'Bollinger Band squeeze with mean reversion logic',
        performance: '-3.2%',
        status: 'inactive' as const
    },
    {
        id: 'strat-005',
        name: 'MACD Divergence',
        description: 'MACD divergence detection with trend confirmation',
        performance: '+11.9%',
        status: 'active' as const
    }
];


// export const MOCK_BROKERS: BrokerInfo[] = [
//     {
//         brokerName: 'ZERODHA',
//         description: 'India\'s largest broker',
//         icon: 'https://zerodha.com/static/images/logo.svg',
//         supportedExchanges: ['NSE', 'BSE']
//     },
//     {
//         brokerName: 'GROWW',
//         description: 'Simple & intuitive trading',
//         icon: 'https://assets-netstorage.groww.in/web-assets/billion_groww_desktop/prod/_next/static/media/logo.8b16c4fe.svg',
//         supportedExchanges: ['NSE', 'BSE']
//     },
//     {
//         brokerName: 'UPSTOX',
//         description: 'Low-cost trading platform',
//         icon: 'https://upstox.com/app/themes/upstox/dist/img/logo/upstox-logo.svg',
//         supportedExchanges: ['NSE', 'BSE']
//     },
//     {
//         brokerName: 'DHAN',
//         description: 'Advanced trading tools',
//         icon: 'https://dhan.co/static/dhan-logo.svg',
//         supportedExchanges: ['NSE', 'BSE']
//     },
//     {
//         brokerName: 'ANGEL_ONE',
//         description: 'Full-service broker',
//         icon: 'https://www.angelone.in/images/logo.svg',
//         supportedExchanges: ['NSE', 'BSE']
//     },
//     {
//         brokerName: 'FIVE_PAISA',
//         description: 'Discount broker',
//         icon: 'https://www.5paisa.com/images/5paisa-logo.svg',
//         supportedExchanges: ['NSE', 'BSE']
//     },
//     {
//         brokerName: 'KITE',
//         description: 'Zerodha\'s trading platform',
//         icon: 'https://kite.zerodha.com/static/images/kite-logo.svg',
//         supportedExchanges: ['NSE', 'BSE']
//     },
//     {
//         brokerName: 'MOCK',
//         description: 'Practice trading (Paper trading)',
//         icon: 'https://cdn-icons-png.flaticon.com/512/3065/3065981.png',
//         supportedExchanges: ['NSE', 'BSE']
//     }
// ];


export const MOCK_INDICATORS: IndicatorConfig[] = [
    {
        userId: 'user-001',
        indicatorPurpose: 'Trend Following',
        indicatorType: 'Moving Average',
        indicatorId: 'ind-001',
        indicatorName: 'EMA (Exponential Moving Average)',
        inputTypeDescription: 'Close Price',
        outputTypeDescription: 'Single Line',
        dataGranularityDescription: '1-minute to Daily',
        calculationDescription: 'Weighted average giving more importance to recent prices',
        signalDescription: 'Bullish when price > EMA, Bearish when price < EMA',
        indicatorDescription: 'Popular trend-following indicator that smooths price data',
        visible: true,
        indicatorParameters: {
            period: 20,
            source: 'close',
            offset: 0,
            smoothing: 2,
            adaptive: false
        }
    },
    {
        userId: 'user-001',
        indicatorPurpose: 'Momentum',
        indicatorType: 'Oscillator',
        indicatorId: 'ind-002',
        indicatorName: 'RSI (Relative Strength Index)',
        inputTypeDescription: 'Close Price',
        outputTypeDescription: 'Oscillator (0-100)',
        dataGranularityDescription: '1-minute to Weekly',
        calculationDescription: 'Measures speed and magnitude of price movements',
        signalDescription: 'Overbought > 70, Oversold < 30',
        indicatorDescription: 'Momentum oscillator measuring overbought/oversold conditions',
        visible: true,
        indicatorParameters: {
            period: 14,
            overbought: 70,
            oversold: 30,
            source: 'close',
            smoothing: 'wilder'
        }
    },
    {
        userId: 'user-001',
        indicatorPurpose: 'Trend & Momentum',
        indicatorType: 'MACD',
        indicatorId: 'ind-003',
        indicatorName: 'MACD (Moving Average Convergence Divergence)',
        inputTypeDescription: 'Close Price',
        outputTypeDescription: 'Multiple Lines (MACD, Signal, Histogram)',
        dataGranularityDescription: '5-minute to Monthly',
        calculationDescription: 'Difference between two EMAs with signal line',
        signalDescription: 'Bullish when MACD crosses above signal, Bearish when crosses below',
        indicatorDescription: 'Shows relationship between two moving averages',
        visible: true,
        indicatorParameters: {
            fastPeriod: 12,
            slowPeriod: 26,
            signalPeriod: 9,
            source: 'close',
            histogram: true
        }
    },
    {
        userId: 'user-001',
        indicatorPurpose: 'Volatility',
        indicatorType: 'Bands',
        indicatorId: 'ind-004',
        indicatorName: 'Bollinger Bands',
        inputTypeDescription: 'Close Price',
        outputTypeDescription: 'Three Lines (Upper, Middle, Lower)',
        dataGranularityDescription: '1-minute to Daily',
        calculationDescription: 'SMA with standard deviation bands',
        signalDescription: 'Price touching upper band = overbought, lower band = oversold',
        indicatorDescription: 'Volatility indicator with upper and lower bands',
        visible: true,
        indicatorParameters: {
            period: 20,
            standardDeviation: 2,
            source: 'close',
            offset: 0,
            basis: 'SMA'
        }
    },
    {
        userId: 'user-001',
        indicatorPurpose: 'Volume',
        indicatorType: 'Volume Indicator',
        indicatorId: 'ind-005',
        indicatorName: 'Volume Weighted Average Price (VWAP)',
        inputTypeDescription: 'Price & Volume',
        outputTypeDescription: 'Single Line',
        dataGranularityDescription: 'Intraday only',
        calculationDescription: 'Average price weighted by volume',
        signalDescription: 'Price above VWAP = bullish, below = bearish',
        indicatorDescription: 'Shows average price weighted by trading volume',
        visible: true,
        indicatorParameters: {
            source: 'hlc3',
            anchor: 'session',
            offset: 0,
            hideBands: false,
            bandMultiplier: 1
        }
    },
    {
        userId: 'user-001',
        indicatorPurpose: 'Momentum',
        indicatorType: 'Oscillator',
        indicatorId: 'ind-006',
        indicatorName: 'Stochastic Oscillator',
        inputTypeDescription: 'High, Low, Close',
        outputTypeDescription: 'Two Lines (%K and %D)',
        dataGranularityDescription: '1-minute to Weekly',
        calculationDescription: 'Compares closing price to price range over period',
        signalDescription: 'Overbought > 80, Oversold < 20',
        indicatorDescription: 'Momentum indicator comparing close to high-low range',
        visible: true,
        indicatorParameters: {
            kPeriod: 14,
            dPeriod: 3,
            smooth: 3,
            overbought: 80,
            oversold: 20
        }
    }
];


export const MOCK_STRATEGY_PARAMETERS: StrategyParameter[] = [
    {
        key: 'maxPositionSize',
        label: 'Max Position Size',
        value: 10000,
        type: 'number',
        description: 'Maximum position size per trade in rupees',
        min: 1000,
        max: 100000
    },
    {
        key: 'riskPerTrade',
        label: 'Risk Per Trade (%)',
        value: 2,
        type: 'number',
        description: 'Maximum risk percentage per trade',
        min: 0.5,
        max: 5
    },
    {
        key: 'stopLossPercentage',
        label: 'Stop Loss (%)',
        value: 1.5,
        type: 'number',
        description: 'Stop loss percentage from entry price',
        min: 0.5,
        max: 10
    },
    {
        key: 'takeProfitPercentage',
        label: 'Take Profit (%)',
        value: 3,
        type: 'number',
        description: 'Take profit percentage from entry price',
        min: 1,
        max: 20
    },
    {
        key: 'trailingStopLoss',
        label: 'Enable Trailing Stop Loss',
        value: true,
        type: 'boolean',
        description: 'Enable trailing stop loss to lock in profits'
    },
    {
        key: 'trailingStopPercentage',
        label: 'Trailing Stop (%)',
        value: 1,
        type: 'number',
        description: 'Trailing stop loss percentage',
        min: 0.5,
        max: 5
    },
    {
        key: 'maxDailyLoss',
        label: 'Max Daily Loss',
        value: 5000,
        type: 'number',
        description: 'Maximum allowed loss per day in rupees',
        min: 1000,
        max: 50000
    },
    {
        key: 'maxDailyTrades',
        label: 'Max Daily Trades',
        value: 5,
        type: 'number',
        description: 'Maximum number of trades per day',
        min: 1,
        max: 20
    },
    {
        key: 'orderType',
        label: 'Order Type',
        value: 'LIMIT',
        type: 'select',
        options: ['MARKET', 'LIMIT', 'STOP_LOSS', 'STOP_LOSS_LIMIT'],
        description: 'Default order type for entries'
    },
    {
        key: 'partialProfitEnabled',
        label: 'Enable Partial Profit Booking',
        value: false,
        type: 'boolean',
        description: 'Book partial profits at predefined levels'
    },
    {
        key: 'partialProfitPercentage',
        label: 'Partial Profit at (%)',
        value: 2,
        type: 'number',
        description: 'Book 50% profit at this percentage',
        min: 1,
        max: 10
    },
    {
        key: 'reEntryEnabled',
        label: 'Enable Re-Entry',
        value: true,
        type: 'boolean',
        description: 'Allow re-entry after stop loss hit'
    },
    {
        key: 'maxReEntries',
        label: 'Max Re-Entries',
        value: 2,
        type: 'number',
        description: 'Maximum re-entry attempts per day',
        min: 1,
        max: 5
    },
    {
        key: 'cooldownPeriod',
        label: 'Cooldown Period (minutes)',
        value: 15,
        type: 'number',
        description: 'Wait time before re-entry after stop loss',
        min: 5,
        max: 60
    },
    {
        key: 'pyramidingEnabled',
        label: 'Enable Pyramiding',
        value: false,
        type: 'boolean',
        description: 'Add to winning positions'
    }
];


export const MOCK_STRATEGY_DETAILS: Record<string, any> = {
    'strat-001': {
        id: 'strat-001',
        name: 'EMA Crossover Pro',
        intro: 'This strategy uses exponential moving averages to identify trend changes. When the fast EMA crosses above the slow EMA, it generates a buy signal. The strategy is designed for intraday trading on liquid stocks with proper risk management.',
        entryCondition: 'Entry signal is generated when Fast EMA (9-period) crosses above Slow EMA (21-period) with volume confirmation. Price must be above both EMAs and the previous candle should be bullish.',
        filterCondition: 'Strategy applies to selected symbols: RELIANCE, TCS, INFY, HDFC. Minimum volume of 1 million shares required. Stock price should be between ₹100 and ₹5000.',
        stopLossCondition: '1.5% stop loss from entry price. If trailing stop loss is enabled, it will trail by 1% once the position moves into profit.',
        targetCondition: '3% profit target from entry price. Partial profit booking at 2% (50% quantity). Maximum 5 trades per day with 15 minutes cooldown between trades.',
        selectedIndicators: [
            {
                indicatorId: 'ind-001',
                indicatorName: 'EMA Fast',
                indicatorType: 'Moving Average',
                parameters: {
                    period: 9,
                    source: 'close'
                }
            },
            {
                indicatorId: 'ind-002',
                indicatorName: 'EMA Slow',
                indicatorType: 'Moving Average',
                parameters: {
                    period: 21,
                    source: 'close'
                }
            },
            {
                indicatorId: 'ind-003',
                indicatorName: 'Volume',
                indicatorType: 'Volume Indicator',
                parameters: {
                    period: 20,
                    type: 'simple'
                }
            }
        ],
        selectedSymbols: [
            'RELIANCE',
            'TCS',
            'INFY',
            'HDFC'
        ]
    },
    'strat-002': {
        id: 'strat-002',
        name: 'RSI Momentum',
        intro: 'RSI-based momentum strategy that identifies oversold and overbought conditions. The strategy waits for RSI to reach extreme levels with strong volume confirmation before executing trades.',
        entryCondition: 'Buy when RSI falls below 30 (oversold) and shows signs of reversal. Sell when RSI rises above 70 (overbought). Volume must be 1.5x above the 20-period average for confirmation.',
        filterCondition: 'No specific symbol filter. Strategy scans all NSE stocks with minimum daily volume of 500K shares. Excludes penny stocks below ₹50.',
        stopLossCondition: '2% stop loss from entry price. No trailing stop loss. Position will be exited immediately if stop loss is hit.',
        targetCondition: '4% profit target from entry price. No partial profit booking. Maximum 8 trades per day with 10 minutes cooldown period.',
        selectedIndicators: [
            {
                indicatorId: 'ind-004',
                indicatorName: 'RSI',
                indicatorType: 'Oscillator',
                parameters: {
                    period: 14,
                    overbought: 70,
                    oversold: 30
                }
            },
            {
                indicatorId: 'ind-005',
                indicatorName: 'Volume Profile',
                indicatorType: 'Volume',
                parameters: {
                    period: 20,
                    multiplier: 1.5
                }
            }
        ],
        selectedSymbols: []
    },
    'strat-003': {
        id: 'strat-003',
        name: 'Breakout Scanner',
        intro: 'Identifies consolidation patterns and trades breakouts with proper risk management. The strategy uses Bollinger Bands to detect squeeze patterns and ATR for volatility-based stop loss placement.',
        entryCondition: 'Entry when price breaks and closes above the upper Bollinger Band with volume spike. The breakout candle must have volume at least 2x the average. Previous resistance level should be broken with strong momentum.',
        filterCondition: 'Limited to banking and metal stocks: TATASTEEL, SBIN, AXISBANK. Stocks must have ATR > 2% for sufficient volatility. Market cap above ₹10,000 crores.',
        stopLossCondition: '2.5% stop loss from entry or below the consolidation low, whichever is closer. Trailing stop loss enabled at 1.5% once position is 3% in profit.',
        targetCondition: '5% profit target from entry price. Partial profit of 50% quantity at 3%. No re-entry allowed on the same symbol for the day after exit.',
        selectedIndicators: [
            {
                indicatorId: 'ind-006',
                indicatorName: 'Bollinger Bands',
                indicatorType: 'Volatility',
                parameters: {
                    period: 20,
                    standardDeviation: 2
                }
            },
            {
                indicatorId: 'ind-007',
                indicatorName: 'ATR',
                indicatorType: 'Volatility',
                parameters: {
                    period: 14
                }
            },
            {
                indicatorId: 'ind-008',
                indicatorName: 'Volume',
                indicatorType: 'Volume',
                parameters: {
                    period: 20,
                    multiplier: 2
                }
            }
        ],
        selectedSymbols: [
            'TATASTEEL',
            'SBIN',
            'AXISBANK'
        ]
    }
};

export const mockBrokers: BrokerInfo[] = [
    {
        brokerId: 1,
        brokerName: "ZERODHA",
        brokerCode: "ZERO",
        icon: "https://zerodha.com/static/images/logo.svg",
        description: "",
        supportedExchanges: ["NSE", "BSE"],
        active: true
    },
    {
        brokerId: 2,
        brokerName: "UPSTOX",
        brokerCode: "UPSTOX",
        icon: "https://upstox.com/landing-page-assets/upstox-logo.svg",
        description: "",
        supportedExchanges: ["NSE", "BSE"],
        active: true
    }
];

export const mockSymbolMetaData: SymbolMetaData[] = [
    {
        tokenNumber: "2885",
        isn: "INE002A01018",
        symbolName: "RELIANCE",
        series: "EQ",
        expiry: null,
        upperPrice: 3000,
        lowerPrice: 2200,
        tickSize: 0.05,
        lotSize: 1,
        strikePrice: 0,
        exchange: "NSE",
        segment: "EQ"
    },
    {
        tokenNumber: "11536",
        isn: "INE467B01029",
        symbolName: "TCS",
        series: "EQ",
        expiry: null,
        upperPrice: 4200,
        lowerPrice: 3000,
        tickSize: 0.05,
        lotSize: 1,
        strikePrice: 0,
        exchange: "NSE",
        segment: "EQ"
    },
    {
        tokenNumber: "500209",
        isn: "INE009A01021",
        symbolName: "INFY",
        series: "EQ",
        expiry: null,
        upperPrice: 2000,
        lowerPrice: 1300,
        tickSize: 0.05,
        lotSize: 1,
        strikePrice: 0,
        exchange: "BSE",
        segment: "EQ"
    },
    {
        tokenNumber: "123456",
        isn: "NIFTYFUT24FEB",
        symbolName: "NIFTY",
        series: "FUTIDX",
        expiry: "2024-02-29",
        upperPrice: 23000,
        lowerPrice: 18000,
        tickSize: 0.05,
        lotSize: 50,
        strikePrice: 0,
        exchange: "NSE",
        segment: "FUT"
    },
    {
        tokenNumber: "654321",
        isn: "BANKNIFTY24FEB45000CE",
        symbolName: "BANKNIFTY",
        series: "OPTIDX",
        expiry: "2024-02-29",
        upperPrice: 1200,
        lowerPrice: 0,
        tickSize: 0.05,
        lotSize: 15,
        strikePrice: 45000,
        exchange: "NSE",
        segment: "OPT"
    }
];


