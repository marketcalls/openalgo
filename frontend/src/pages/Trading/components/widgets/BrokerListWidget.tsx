import { useThemeStore } from "@/stores/themeStore";
import type { BrokerInfo } from "..";

interface BrokerListWidgetProps {
    brokers: BrokerInfo[];
    selectedBroker: string | null;
    onSelect: (brokerName: string) => void;
}

export default function BrokerListWidget({ brokers, selectedBroker, onSelect }: BrokerListWidgetProps) {
    const { mode } = useThemeStore()
    const darkMode = mode === 'dark';

   return (
        <div className="grid grid-cols-2 gap-3 my-4">
            {brokers.map((broker) => (
                <button
                    key={broker.brokerId}
                    onClick={() => onSelect(broker.brokerName)}
                    className={`p-4 rounded-lg border text-left transition-all ${
                        selectedBroker === broker.brokerName
                            ? darkMode
                                ? 'bg-blue-600/20 border-blue-500 ring-2 ring-blue-500'
                                : 'bg-blue-50 border-blue-500 ring-2 ring-blue-500'
                            : darkMode
                                ? 'bg-gray-800 border-gray-600 hover:border-gray-500'
                                : 'bg-white border-gray-300 hover:border-gray-400'
                    }`}
                >
                    <div className="flex items-center gap-3">
                        <div className="flex-shrink-0">
                            {broker.icon ? (
                                <img 
                                    src={broker.icon} 
                                    alt={broker.brokerName}
                                    className="w-10 h-10 rounded-lg object-contain"
                                    onError={(e) => {
                                        const target = e.target as HTMLImageElement;
                                        target.style.display = 'none';
                                        const fallback = target.nextElementSibling as HTMLElement;
                                        if (fallback) fallback.style.display = 'flex';
                                    }}
                                />
                            ) : null}
                            <div 
                                className={`w-10 h-10 rounded-lg flex items-center justify-center font-bold text-sm ${
                                    broker.icon ? 'hidden' : ''
                                } ${
                                    darkMode ? 'bg-gray-700 text-gray-300' : 'bg-gray-200 text-gray-700'
                                }`}
                            >
                                {broker.brokerName.substring(0, 2).toUpperCase()}
                            </div>
                        </div>
                        <div className="flex-1 min-w-0">
                            <div className={`font-semibold text-sm mb-0.5 ${
                                darkMode ? 'text-white' : 'text-gray-900'
                            }`}>
                                {broker.brokerName}
                            </div>
                            {broker.description && (
                                <p className={`text-xs truncate ${
                                    darkMode ? 'text-gray-400' : 'text-gray-600'
                                }`}>
                                    {broker.description}
                                </p>
                            )}
                            {broker.supportedExchanges && broker.supportedExchanges.length > 0 ? (
                                <div className={`text-xs mt-1 ${
                                    darkMode ? 'text-gray-500' : 'text-gray-500'
                                }`}>
                                    {broker.supportedExchanges.join(', ')}
                                </div>
                            ) : (
                                <div className={`text-xs mt-1 ${
                                    darkMode ? 'text-gray-500' : 'text-gray-500'
                                }`}>
                                    All Exchanges
                                </div>
                            )}
                        </div>
                    </div>
                </button>
            ))}
        </div>
    );
}