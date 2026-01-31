import React from 'react';
import { TrendingUp, Activity } from 'lucide-react';
import StrategyDetails from './StrategyDetails';

interface SymbolMetaData {
    tokenNumber?: string;
    symbolName?: string;
    isn?: string;
    lotSize?: number;
    series?: string;
    exchange?: string;
    instrumentType?: string;
}

interface WatchlistStock {
    symbol: string;
    volume: string;
    ltp: number;
    change: number;
    changePercent: number;
}

interface StrategyConfig {
    brokerName: string | null;
    exchange: string | null;
    strategyType: string | null;
    strategyId: string | null;
    strategyName: string | null;
    positionType: string | null;
    timeInForce: string | null;
    indicators: any[];
    strategyParameters: Record<string, any>;
    riskManagement: {
        maxPositionSize: number | null;
        maxDailyLoss: number | null;
    };
    filterSymbols: string[];
}

interface RightSidebarProps {
    darkMode: boolean;
    isStrategyStarted: boolean;
    config: StrategyConfig;
    availableSymbols: SymbolMetaData[];
    watchlist: WatchlistStock[];
}

const RightSidebar: React.FC<RightSidebarProps> = ({
    darkMode,
    isStrategyStarted,
    config,
    availableSymbols,
    watchlist
}) => {
    if (!isStrategyStarted) {
        // Show Strategy Details before starting
        return (
            <div className={`w-80 border-l ${darkMode ? 'border-gray-700' : 'border-gray-200'}`}>
                <StrategyDetails config={config} />
            </div>
        );
    }

    // Show Market Watch after starting
    return (
        <div className={`w-80 border-l ${darkMode ? 'border-gray-700 bg-gray-800' : 'border-gray-200 bg-gray-50'} flex flex-col`}>
            {/* Header */}
            <div className={`p-4 border-b ${darkMode ? 'border-gray-700' : 'border-gray-200'}`}>
                <div className="flex items-center gap-2 mb-2">
                    <TrendingUp className={`w-5 h-5 ${darkMode ? 'text-green-400' : 'text-green-600'}`} />
                    <h2 className={`text-sm font-semibold ${darkMode ? 'text-white' : 'text-gray-900'}`}>
                        Market Watch
                    </h2>
                </div>
                <p className={`text-xs ${darkMode ? 'text-gray-400' : 'text-gray-600'}`}>
                    {config.filterSymbols && config.filterSymbols.length > 0
                        ? `Monitoring ${config.filterSymbols.length} selected symbols`
                        : 'Live prices • Auto-refresh'
                    }
                </p>
            </div>

            {/* Symbols List */}
            <div className="flex-1 overflow-y-auto hide-scrollbar p-4 space-y-3">
                {config.filterSymbols && config.filterSymbols.length > 0 ? (
                    // Show only selected symbols
                    availableSymbols
                        .filter(symbol => symbol.tokenNumber && config.filterSymbols.includes(symbol.tokenNumber))
                        .map((symbol, index) => (
                            <div
                                key={`${symbol.tokenNumber}-${index}`}
                                className={`p-3 rounded-lg border transition-all cursor-pointer ${darkMode
                                    ? 'bg-gray-700 border-gray-600 hover:bg-gray-650'
                                    : 'bg-white border-gray-200 hover:bg-gray-50'
                                }`}
                            >
                                <div className="flex items-start justify-between mb-2">
                                    <div>
                                        <div className={`font-semibold text-sm ${darkMode ? 'text-white' : 'text-gray-900'}`}>
                                            {symbol.symbolName || 'N/A'}
                                        </div>
                                        <div className={`text-xs ${darkMode ? 'text-gray-400' : 'text-gray-600'}`}>
                                            {symbol.isn || 'N/A'}
                                        </div>
                                    </div>
                                    <Activity className={`w-4 h-4 ${darkMode ? 'text-blue-400' : 'text-blue-600'}`} />
                                </div>

                                <div className="flex items-end justify-between">
                                    <div className={`text-xs ${darkMode ? 'text-gray-500' : 'text-gray-600'}`}>
                                        Lot: {symbol.lotSize || 0}
                                    </div>
                                    <div className="text-right">
                                        <div className={`text-xs px-2 py-0.5 rounded ${darkMode ? 'bg-gray-600 text-gray-300' : 'bg-gray-200 text-gray-700'}`}>
                                            {symbol.series || 'N/A'}
                                        </div>
                                    </div>
                                </div>
                            </div>
                        ))
                ) : (
                    // Show all WATCHLIST symbols if no filter
                    watchlist.map((stock, index) => (
                        <div
                            key={`${stock.symbol}-${index}`}
                            className={`p-3 rounded-lg border transition-all cursor-pointer ${darkMode
                                ? 'bg-gray-700 border-gray-600 hover:bg-gray-650'
                                : 'bg-white border-gray-200 hover:bg-gray-50'
                            }`}
                        >
                            <div className="flex items-start justify-between mb-2">
                                <div>
                                    <div className={`font-semibold text-sm ${darkMode ? 'text-white' : 'text-gray-900'}`}>
                                        {stock.symbol}
                                    </div>
                                    <div className={`text-xs ${darkMode ? 'text-gray-400' : 'text-gray-600'}`}>
                                        Vol: {stock.volume}
                                    </div>
                                </div>
                                <Activity className={`w-4 h-4 ${stock.change >= 0 ? 'text-green-500' : 'text-red-500'}`} />
                            </div>

                            <div className="flex items-end justify-between">
                                <div className={`text-lg font-bold ${darkMode ? 'text-white' : 'text-gray-900'}`}>
                                    ₹{stock.ltp.toFixed(2)}
                                </div>
                                <div className="text-right">
                                    <div className={`text-sm font-medium ${stock.change >= 0 ? 'text-green-500' : 'text-red-500'}`}>
                                        {stock.change >= 0 ? '+' : ''}{stock.change.toFixed(2)}
                                    </div>
                                    <div className={`text-xs ${stock.changePercent >= 0 ? 'text-green-500' : 'text-red-500'}`}>
                                        {stock.changePercent >= 0 ? '+' : ''}{stock.changePercent.toFixed(2)}%
                                    </div>
                                </div>
                            </div>
                        </div>
                    ))
                )}
            </div>
        </div>
    );
};

export default RightSidebar;