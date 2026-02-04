import { Circle, Search } from 'lucide-react';
import { useState } from 'react';
import type { Strategy } from '..';
import { useThemeStore } from '@/stores/themeStore';

interface StrategyListWidgetProps {
    strategies: Strategy[];
    selectedId: string | null;
    onSelect: (id: string) => void;
}

export default function StrategyListWidget({ strategies, selectedId, onSelect }: StrategyListWidgetProps) {
    const { mode, appMode } = useThemeStore()
    const darkMode = mode === 'dark' || appMode === 'analyzer';
    const [searchQuery, setSearchQuery] = useState('');

    // Filter strategies based on search query
    const filteredStrategies = strategies.filter(strategy => 
        strategy.name.toLowerCase().includes(searchQuery.toLowerCase()) ||
        strategy.description.toLowerCase().includes(searchQuery.toLowerCase())
    );

    return (
        <div className="my-4">
            {/* Search Input */}
            <div className="mb-3 relative">
                <Search className={`absolute left-3 top-1/2 transform -translate-y-1/2 w-4 h-4 ${
                    darkMode ? 'text-gray-500' : 'text-gray-400'
                }`} />
                <input
                    type="text"
                    placeholder="Search strategies..."
                    value={searchQuery}
                    onChange={(e) => setSearchQuery(e.target.value)}
                    className={`w-full pl-10 pr-4 py-2.5 rounded-lg border text-sm ${
                        darkMode
                            ? 'bg-gray-800 border-gray-600 text-white placeholder-gray-500'
                            : 'bg-white border-gray-300 text-gray-900 placeholder-gray-400'
                    } focus:outline-none focus:ring-2 focus:ring-blue-500`}
                />
            </div>

            {/* Strategy List */}
            <div className="flex flex-col gap-2 max-h-96 overflow-y-auto hide-scrollbar">
                {filteredStrategies.length > 0 ? (
                    filteredStrategies.map((strategy) => (
                        <button
                            key={strategy.id}
                            onClick={() => onSelect(strategy.id)}
                            className={`p-3 rounded-lg border text-left transition-all ${
                                selectedId === strategy.id
                                    ? darkMode
                                        ? 'bg-blue-600/20 border-blue-500 ring-2 ring-blue-500'
                                        : 'bg-blue-50 border-blue-500 ring-2 ring-blue-500'
                                    : darkMode
                                        ? 'bg-gray-800 border-gray-600 hover:border-gray-500'
                                        : 'bg-white border-gray-300 hover:border-gray-400'
                            }`}
                        >
                            <div className="flex items-start justify-between gap-3">
                                <div className="flex-1">
                                    <div className="flex items-center gap-2 mb-1">
                                        <Circle
                                            className={`w-2 h-2 ${
                                                strategy.status === 'active'
                                                    ? 'fill-green-400 text-green-400'
                                                    : 'fill-gray-400 text-gray-400'
                                            }`}
                                        />
                                        <span className={`font-semibold text-sm ${
                                            darkMode ? 'text-white' : 'text-gray-900'
                                        }`}>
                                            {strategy.name}
                                        </span>
                                    </div>
                                    <p className={`text-xs mb-1 ${
                                        darkMode ? 'text-gray-400' : 'text-gray-600'
                                    }`}>
                                        {strategy.description}
                                    </p>
                                    <div className={`text-xs font-medium ${
                                        strategy.performance.startsWith('+')
                                            ? 'text-green-500'
                                            : 'text-red-500'
                                    }`}>
                                        Performance: {strategy.performance}
                                    </div>
                                </div>
                            </div>
                        </button>
                    ))
                ) : (
                    <div className={`text-center py-8 ${
                        darkMode ? 'text-gray-500' : 'text-gray-400'
                    }`}>
                        <Search className="w-12 h-12 mx-auto mb-2 opacity-50" />
                        <p className="text-sm">No strategies found matching "{searchQuery}"</p>
                    </div>
                )}
            </div>

            {searchQuery && filteredStrategies.length > 0 && (
                <div className={`mt-2 text-xs ${
                    darkMode ? 'text-gray-500' : 'text-gray-500'
                }`}>
                    Found {filteredStrategies.length} strateg{filteredStrategies.length === 1 ? 'y' : 'ies'}
                </div>
            )}
        </div>
    );
}