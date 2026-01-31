import { Send, Sparkles, Loader2 } from 'lucide-react';
import { useRef, useEffect } from 'react';
import RadioWidget from './RadioWidget';
import BrokerListWidget from './BrokerListWidget';
import StrategyListWidget from './StrategyListWidget';
import IndicatorListWidget from './IndicatorListWidget';
import StrategyParametersWidget from './StrategyParametersWidget';
import RiskManagementWidget from './RiskManagementWidget';
import SymbolFilterWidget from './SymbolFilterWidget';
import StartStrategyWidget from './StartStrategyWidget';
import ReRunConfirmationWidget from './ReRunConfirmationWidget';
import { ORDERS, TRADES, POSITIONS } from '../../mockData';
import type { Message } from '..';
import { useThemeStore } from '@/stores/themeStore';

interface ChatAreaProps {
    messages: Message[];
    inputValue: string;
    setInputValue: (value: string) => void;
    handleSend: () => void;
    isPanelVisible: boolean;
    setIsPanelVisible: (visible: boolean) => void;
    activeTab: string;
    setActiveTab: (tab: string) => void;
    panelHeight: number;
    handleMouseDown: (e: React.MouseEvent) => void;
    // Widget props
    selectedStrategyType: string | null;
    selectedExchange: string | null;
    selectedPositionType: string | null;
    selectedTimeInForce: string | null;
    selectedBrokerName: string | null;
    selectedStrategy: string | null;
    brokersLoading: boolean;
    selectedSymbolsList: string[];
    handleFinalizeIndicators: () => void;
}

export default function ChatArea({
    messages,
    inputValue,
    setInputValue,
    handleSend,
    isPanelVisible,
    setIsPanelVisible,
    activeTab,
    setActiveTab,
    panelHeight,
    handleMouseDown,
    selectedStrategyType,
    selectedExchange,
    selectedPositionType,
    selectedTimeInForce,
    selectedBrokerName,
    selectedStrategy,
    brokersLoading,
    selectedSymbolsList,
    handleFinalizeIndicators
}: ChatAreaProps) {
    const { mode } = useThemeStore()
    const darkMode = mode === 'dark';
    const textareaRef = useRef<HTMLTextAreaElement>(null);
    const messagesEndRef = useRef<HTMLDivElement>(null);

    // Auto-scroll messages
    useEffect(() => {
        messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
    }, [messages]);

    return (
        <div className="flex-1 flex flex-col">
            {/* Messages Area */}
            <div className="flex-1 overflow-y-auto hide-scrollbar">
                <div className="max-w-3xl mx-auto px-6 py-8">
                    {messages.map((message) => (
                        <div key={message.id} className="mb-6">
                            <div className="flex gap-4">
                                <div className={`flex-shrink-0 w-8 h-8 rounded-full flex items-center justify-center ${
                                    message.type === 'user'
                                        ? darkMode ? 'bg-blue-600' : 'bg-blue-500'
                                        : darkMode ? 'bg-orange-600' : 'bg-orange-500'
                                }`}>
                                    {message.type === 'user' ? (
                                        <span className="text-white text-sm font-semibold">A</span>
                                    ) : (
                                        <Sparkles className="w-4 h-4 text-white" />
                                    )}
                                </div>
                                <div className="flex-1">
                                    {message.type === 'user' ? (
                                        <div className={`${darkMode ? 'bg-gray-800' : 'bg-gray-100'} rounded-lg p-4`}>
                                            <div className={`text-sm ${darkMode ? 'text-gray-100' : 'text-gray-900'}`}>
                                                {message.content}
                                            </div>
                                        </div>
                                    ) : (
                                        <div className="pt-1">
                                            <div className={`text-sm leading-relaxed ${darkMode ? 'text-gray-100' : 'text-gray-900'}`}>
                                                {message.content.split('\n').map((line, i) => {
                                                    if (line.trim().startsWith('**') && line.trim().endsWith('**')) {
                                                        return (
                                                            <div key={i} className={`font-semibold text-base mb-2 ${
                                                                darkMode ? 'text-white' : 'text-gray-900'
                                                            }`}>
                                                                {line.replace(/\*\*/g, '')}
                                                            </div>
                                                        );
                                                    }
                                                    if (line.trim() === '') {
                                                        return <div key={i} className="h-2"></div>;
                                                    }
                                                    return <p key={i} className="mb-2">{line}</p>;
                                                })}
                                            </div>

                                            {/* Render Widget if exists */}
                                            {message.widget && (
                                                <>
                                                    {message.widget.type === 'radio' && (
                                                        <RadioWidget
                                                            options={message.widget.data.options}
                                                            selectedValue={
                                                                message.widget.data.options[0]?.value === 'suggest' ||
                                                                message.widget.data.options[0]?.value === 'own'
                                                                    ? selectedStrategyType
                                                                    : message.widget.data.options[0]?.value === 'NSE' ||
                                                                      message.widget.data.options[0]?.value === 'BSE'
                                                                        ? selectedExchange
                                                                        : message.widget.data.options[0]?.value === 'INTRADAY' ||
                                                                          message.widget.data.options[0]?.value === 'DELIVERY'
                                                                            ? selectedPositionType
                                                                            : message.widget.data.options[0]?.value === 'IOC' ||
                                                                              message.widget.data.options[0]?.value === 'DAY'
                                                                                ? selectedTimeInForce
                                                                                : null
                                                            }
                                                            onSelect={message.widget.data.onSelect}
                                                        />
                                                    )}
                                                    {message.widget.type === 'broker-list' && (
                                                        <>
                                                            {brokersLoading ? (
                                                                <div className={`my-4 p-8 rounded-xl border text-center ${
                                                                    darkMode ? 'bg-gray-800 border-gray-700' : 'bg-white border-gray-200'
                                                                }`}>
                                                                    <Loader2 className={`w-10 h-10 mx-auto mb-3 animate-spin ${
                                                                        darkMode ? 'text-blue-400' : 'text-blue-600'
                                                                    }`} />
                                                                    <p className={`text-sm ${
                                                                        darkMode ? 'text-gray-400' : 'text-gray-600'
                                                                    }`}>
                                                                        Loading brokers...
                                                                    </p>
                                                                </div>
                                                            ) : (
                                                                <BrokerListWidget
                                                                    brokers={message.widget.data.brokers}
                                                                    selectedBroker={selectedBrokerName}
                                                                    onSelect={message.widget.data.onSelect}
                                                                />
                                                            )}
                                                        </>
                                                    )}
                                                    {message.widget.type === 'strategy-list' && (
                                                        <StrategyListWidget
                                                            strategies={message.widget.data.strategies}
                                                            selectedId={selectedStrategy}
                                                            onSelect={message.widget.data.onSelect}
                                                        />
                                                    )}
                                                    {message.widget.type === 'indicator-list' && (
                                                        <>
                                                            <IndicatorListWidget
                                                                indicators={message.widget.data.indicators}
                                                                onConfigureParameters={message.widget.data.onConfigureParameters}
                                                            />
                                                            <button
                                                                onClick={handleFinalizeIndicators}
                                                                className={`w-full mt-3 px-4 py-3 rounded-lg text-sm font-semibold transition-all ${
                                                                    darkMode
                                                                        ? 'bg-green-600 hover:bg-green-700 text-white'
                                                                        : 'bg-green-500 hover:bg-green-600 text-white'
                                                                } shadow-lg hover:shadow-xl`}
                                                            >
                                                                Continue with All Indicators →
                                                            </button>
                                                        </>
                                                    )}
                                                    {message.widget.type === 'strategy-parameters' && (
                                                        <StrategyParametersWidget
                                                            parameters={message.widget.data.parameters}
                                                            onSave={message.widget.data.onSave}
                                                        />
                                                    )}
                                                    {message.widget.type === 'risk-management' && (
                                                        <RiskManagementWidget
                                                            onSave={message.widget.data.onSave}
                                                        />
                                                    )}
                                                    {message.widget.type === 'symbol-filter' && (
                                                        <SymbolFilterWidget
                                                            symbols={message.widget.data.symbols}
                                                            selectedSymbols={selectedSymbolsList}
                                                            loading={message.widget.data.loading}
                                                            onToggle={message.widget.data.onToggle}
                                                            onSave={message.widget.data.onSave}
                                                        />
                                                    )}
                                                    {message.widget.type === 'start-strategy' && (
                                                        <StartStrategyWidget
                                                            strategyConfig={message.widget.data.strategyConfig}
                                                            onStart={message.widget.data.onStart}
                                                        />
                                                    )}
                                                    {message.widget?.type === 're-run-confirmation' && (
                                                        <ReRunConfirmationWidget
                                                            profit={message.widget.data.profit}
                                                            onConfirm={message.widget.data.onConfirm}
                                                            onStop={message.widget.data.onStop}
                                                        />
                                                    )}
                                                </>
                                            )}
                                        </div>
                                    )}
                                </div>
                            </div>
                        </div>
                    ))}
                    <div ref={messagesEndRef} />
                </div>
            </div>

            {/* Resizable Panel */}
            {isPanelVisible && (
                <div className={`border-t ${darkMode ? 'border-gray-700' : 'border-gray-200'}`}>
                    <div
                        onMouseDown={handleMouseDown}
                        className={`h-1 cursor-ns-resize ${
                            darkMode ? 'bg-gray-700 hover:bg-blue-600' : 'bg-gray-200 hover:bg-blue-400'
                        } transition-colors`}
                    />

                    <div className={`flex border-b ${darkMode ? 'border-gray-700 bg-gray-800' : 'border-gray-200 bg-gray-50'}`}>
                        {['orders', 'trades', 'positions'].map(tab => (
                            <button
                                key={tab}
                                onClick={() => setActiveTab(tab)}
                                className={`px-4 py-2 text-sm font-medium capitalize transition-colors ${
                                    activeTab === tab
                                        ? darkMode
                                            ? 'text-blue-400 border-b-2 border-blue-400'
                                            : 'text-blue-600 border-b-2 border-blue-600'
                                        : darkMode
                                            ? 'text-gray-400 hover:text-gray-200'
                                            : 'text-gray-600 hover:text-gray-900'
                                }`}
                            >
                                {tab}
                            </button>
                        ))}
                    </div>

                    <div
                        className={`overflow-y-auto hide-scrollbar ${darkMode ? 'bg-gray-800' : 'bg-white'}`}
                        style={{ height: `${panelHeight - 41}px` }}
                    >
                        {activeTab === 'orders' && (
                            <div className="p-4">
                                <table className="w-full text-sm">
                                    <thead>
                                        <tr className={`border-b ${darkMode ? 'border-gray-700' : 'border-gray-200'}`}>
                                            <th className={`text-left py-2 ${darkMode ? 'text-gray-400' : 'text-gray-600'}`}>Symbol</th>
                                            <th className={`text-left py-2 ${darkMode ? 'text-gray-400' : 'text-gray-600'}`}>Type</th>
                                            <th className={`text-right py-2 ${darkMode ? 'text-gray-400' : 'text-gray-600'}`}>Qty</th>
                                            <th className={`text-right py-2 ${darkMode ? 'text-gray-400' : 'text-gray-600'}`}>Price</th>
                                            <th className={`text-right py-2 ${darkMode ? 'text-gray-400' : 'text-gray-600'}`}>Status</th>
                                        </tr>
                                    </thead>
                                    <tbody>
                                        {ORDERS.map(order => (
                                            <tr key={order.id} className={`border-b ${darkMode ? 'border-gray-700' : 'border-gray-100'}`}>
                                                <td className={`py-2 font-medium ${darkMode ? 'text-white' : 'text-gray-900'}`}>{order.symbol}</td>
                                                <td className={`py-2 ${order.type === 'BUY' ? 'text-green-500' : 'text-red-500'}`}>{order.type}</td>
                                                <td className={`py-2 text-right ${darkMode ? 'text-gray-300' : 'text-gray-700'}`}>{order.qty}</td>
                                                <td className={`py-2 text-right ${darkMode ? 'text-gray-300' : 'text-gray-700'}`}>₹{order.price.toFixed(2)}</td>
                                                <td className={`py-2 text-right text-xs ${order.status === 'Completed' ? 'text-green-500' : 'text-yellow-500'}`}>
                                                    {order.status}
                                                </td>
                                            </tr>
                                        ))}
                                    </tbody>
                                </table>
                            </div>
                        )}

                        {activeTab === 'trades' && (
                            <div className="p-4">
                                <table className="w-full text-sm">
                                    <thead>
                                        <tr className={`border-b ${darkMode ? 'border-gray-700' : 'border-gray-200'}`}>
                                            <th className={`text-left py-2 ${darkMode ? 'text-gray-400' : 'text-gray-600'}`}>Symbol</th>
                                            <th className={`text-right py-2 ${darkMode ? 'text-gray-400' : 'text-gray-600'}`}>Entry</th>
                                            <th className={`text-right py-2 ${darkMode ? 'text-gray-400' : 'text-gray-600'}`}>Exit</th>
                                            <th className={`text-right py-2 ${darkMode ? 'text-gray-400' : 'text-gray-600'}`}>Qty</th>
                                            <th className={`text-right py-2 ${darkMode ? 'text-gray-400' : 'text-gray-600'}`}>P&L</th>
                                        </tr>
                                    </thead>
                                    <tbody>
                                        {TRADES.map(trade => (
                                            <tr key={trade.id} className={`border-b ${darkMode ? 'border-gray-700' : 'border-gray-100'}`}>
                                                <td className={`py-2 font-medium ${darkMode ? 'text-white' : 'text-gray-900'}`}>{trade.symbol}</td>
                                                <td className={`py-2 text-right ${darkMode ? 'text-gray-300' : 'text-gray-700'}`}>₹{trade.entry.toFixed(2)}</td>
                                                <td className={`py-2 text-right ${darkMode ? 'text-gray-300' : 'text-gray-700'}`}>₹{trade.exit.toFixed(2)}</td>
                                                <td className={`py-2 text-right ${darkMode ? 'text-gray-300' : 'text-gray-700'}`}>{trade.qty}</td>
                                                <td className={`py-2 text-right font-medium ${trade.pnl >= 0 ? 'text-green-500' : 'text-red-500'}`}>
                                                    ₹{trade.pnl.toFixed(2)}
                                                </td>
                                            </tr>
                                        ))}
                                    </tbody>
                                </table>
                            </div>
                        )}

                        {activeTab === 'positions' && (
                            <div className="p-4">
                                <table className="w-full text-sm">
                                    <thead>
                                        <tr className={`border-b ${darkMode ? 'border-gray-700' : 'border-gray-200'}`}>
                                            <th className={`text-left py-2 ${darkMode ? 'text-gray-400' : 'text-gray-600'}`}>Symbol</th>
                                            <th className={`text-right py-2 ${darkMode ? 'text-gray-400' : 'text-gray-600'}`}>Qty</th>
                                            <th className={`text-right py-2 ${darkMode ? 'text-gray-400' : 'text-gray-600'}`}>Avg Price</th>
                                            <th className={`text-right py-2 ${darkMode ? 'text-gray-400' : 'text-gray-600'}`}>LTP</th>
                                            <th className={`text-right py-2 ${darkMode ? 'text-gray-400' : 'text-gray-600'}`}>P&L</th>
                                            <th className={`text-right py-2 ${darkMode ? 'text-gray-400' : 'text-gray-600'}`}>P&L%</th>
                                        </tr>
                                    </thead>
                                    <tbody>
                                        {POSITIONS.map(position => (
                                            <tr key={position.symbol} className={`border-b ${darkMode ? 'border-gray-700' : 'border-gray-100'}`}>
                                                <td className={`py-2 font-medium ${darkMode ? 'text-white' : 'text-gray-900'}`}>{position.symbol}</td>
                                                <td className={`py-2 text-right ${position.qty > 0 ? 'text-green-500' : 'text-red-500'}`}>
                                                    {position.qty > 0 ? '+' : ''}{position.qty}
                                                </td>
                                                <td className={`py-2 text-right ${darkMode ? 'text-gray-300' : 'text-gray-700'}`}>₹{position.avgPrice.toFixed(2)}</td>
                                                <td className={`py-2 text-right ${darkMode ? 'text-gray-300' : 'text-gray-700'}`}>₹{position.ltp.toFixed(2)}</td>
                                                <td className={`py-2 text-right font-medium ${position.pnl >= 0 ? 'text-green-500' : 'text-red-500'}`}>
                                                    ₹{position.pnl.toFixed(2)}
                                                </td>
                                                <td className={`py-2 text-right font-medium ${position.pnlPercent >= 0 ? 'text-green-500' : 'text-red-500'}`}>
                                                    {position.pnlPercent >= 0 ? '+' : ''}{position.pnlPercent.toFixed(2)}%
                                                </td>
                                            </tr>
                                        ))}
                                    </tbody>
                                </table>
                            </div>
                        )}
                    </div>
                </div>
            )}

            {/* Input Area */}
            <div className={`p-4 ${
                isPanelVisible
                    ? darkMode ? 'bg-gray-800 border-gray-700' : 'bg-white border-gray-200'
                    : 'bg-transparent'
            } ${isPanelVisible ? 'border-t' : ''}`}>
                <div className="max-w-3xl mx-auto">
                    <div className={`flex items-end gap-3 rounded-2xl border ${
                        darkMode ? 'border-gray-600 bg-gray-700' : 'border-gray-300 bg-gray-50'
                    } px-4 py-3`}>
                        <textarea
                            ref={textareaRef}
                            value={inputValue}
                            onChange={(e) => setInputValue(e.target.value)}
                            onKeyDown={(e) => {
                                if (e.key === 'Enter' && !e.shiftKey) {
                                    e.preventDefault();
                                    handleSend();
                                }
                            }}
                            placeholder="Ask AI for market insights, place orders, or manage positions..."
                            className={`flex-1 resize-none outline-none bg-transparent text-sm ${
                                darkMode ? 'text-white placeholder-gray-400' : 'text-gray-900 placeholder-gray-500'
                            }`}
                            rows={1}
                        />
                        <button
                            onClick={() => setIsPanelVisible(!isPanelVisible)}
                            className={`flex-shrink-0 p-2 rounded-lg transition-colors ${
                                darkMode
                                    ? 'bg-gray-700 hover:bg-gray-600 text-gray-300'
                                    : 'bg-gray-200 hover:bg-gray-300 text-gray-600'
                            }`}
                            title={isPanelVisible ? 'Hide Panel' : 'Show Panel'}
                        >
                            <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 6a2 2 0 012-2h2a2 2 0 012 6v2a2 2 0 01-2 2H6a2 2 0 01-2-2V6zM14 6a2 2 0 012-2h2a2 2 0 012 2v2a2 2 0 01-2 2h-2a2 2 0 01-2-2V6zM4 16a2 2 0 012-2h2a2 2 0 012 2v2a2 2 0 01-2 2H6a2 2 0 01-2-2v-2zM14 16a2 2 0 012-2h2a2 2 0 012 2v2a2 2 0 01-2 2h-2a2 2 0 01-2-2v-2z" />
                            </svg>
                        </button>
                        <button
                            onClick={handleSend}
                            disabled={!inputValue.trim()}
                            className={`flex-shrink-0 p-2 rounded-lg transition-colors ${
                                inputValue.trim()
                                    ? darkMode
                                        ? 'bg-blue-600 hover:bg-blue-700 text-white'
                                        : 'bg-blue-500 hover:bg-blue-600 text-white'
                                    : darkMode
                                        ? 'bg-gray-600 text-gray-400 cursor-not-allowed'
                                        : 'bg-gray-200 text-gray-400 cursor-not-allowed'
                            }`}
                        >
                            <Send className="w-4 h-4" />
                        </button>
                    </div>
                </div>
            </div>
        </div>
    );
}