import { useState, useMemo } from 'react';
import { Search, CheckCircle, Circle, TrendingUp, Loader2, Save } from 'lucide-react';
import type { SymbolMetaData } from '..';
import { useThemeStore } from '@/stores/themeStore';

interface SymbolFilterWidgetProps {
    symbols: SymbolMetaData[];
    selectedSymbols: string[];
    loading: boolean;
    onToggle: (symbolToken: string) => void;
    onSave: (selectedSymbols: string[]) => void;
}

export default function SymbolFilterWidget({
    symbols,
    selectedSymbols,
    loading,
    onToggle,
    onSave
}: SymbolFilterWidgetProps) {
    const { mode } = useThemeStore()
    const darkMode = mode === 'dark';

    const [searchQuery, setSearchQuery] = useState('');
    const [currentPage, setCurrentPage] = useState(1);
    const itemsPerPage = 20;

    // Filter symbols based on search query
    const filteredSymbols = useMemo(() => {
        if (!searchQuery.trim()) return symbols;

        const query = searchQuery.toLowerCase();
        return symbols.filter(symbol =>
            symbol.symbolName.toLowerCase().includes(query) ||
            symbol.isn.toLowerCase().includes(query) ||
            symbol.series.toLowerCase().includes(query)
        );
    }, [symbols, searchQuery]);

    // Paginate filtered symbols
    const paginatedSymbols = useMemo(() => {
        const startIndex = (currentPage - 1) * itemsPerPage;
        const endIndex = startIndex + itemsPerPage;
        return filteredSymbols.slice(startIndex, endIndex);
    }, [filteredSymbols, currentPage]);

    const totalPages = Math.ceil(filteredSymbols.length / itemsPerPage);

    const handleSelectAll = () => {
        const allSymbolTokens = filteredSymbols.map(s => s.tokenNumber);
        allSymbolTokens.forEach(token => {
            if (!selectedSymbols.includes(token)) {
                onToggle(token);
            }
        });
    };

    const handleClearAll = () => {
        selectedSymbols.forEach(token => {
            if (filteredSymbols.some(s => s.tokenNumber === token)) {
                onToggle(token);
            }
        });
    };

    const handlePageChange = (page: number) => {
        setCurrentPage(page);
        document.querySelector('#symbol-filter-widget')?.scrollIntoView({ behavior: 'smooth', block: 'start' });
    };

    if (loading) {
        return (
            <div className={`my-4 p-12 rounded-xl border text-center ${darkMode ? 'bg-gray-800 border-gray-700' : 'bg-white border-gray-200'
                }`}>
                <Loader2 className={`w-12 h-12 mx-auto mb-4 animate-spin ${darkMode ? 'text-blue-400' : 'text-blue-600'
                    }`} />
                <p className={`text-sm ${darkMode ? 'text-gray-400' : 'text-gray-600'}`}>
                    Loading symbols from exchange...
                </p>
            </div>
        );
    }

    return (
        <div id="symbol-filter-widget" className="my-4">
            {/* Header */}
            <div className={`mb-5 p-5 rounded-xl border ${darkMode
                ? 'bg-gradient-to-r from-indigo-500/10 to-purple-500/10 border-indigo-500/30'
                : 'bg-gradient-to-r from-indigo-50 to-purple-50 border-indigo-200'
                }`}>
                <div className="flex items-start gap-4">
                    <div className={`p-3 rounded-lg ${darkMode ? 'bg-indigo-500/20' : 'bg-indigo-100'
                        }`}>
                        <TrendingUp className={`w-6 h-6 ${darkMode ? 'text-indigo-400' : 'text-indigo-600'
                            }`} />
                    </div>
                    <div className="flex-1">
                        <h3 className={`font-bold text-lg mb-2 ${darkMode ? 'text-white' : 'text-gray-900'
                            }`}>
                            Symbol Filter
                        </h3>
                        <p className={`text-sm ${darkMode ? 'text-gray-300' : 'text-gray-700'
                            }`}>
                            Select the symbols you want to trade. Your strategy will only execute on selected symbols.
                        </p>
                    </div>
                </div>
            </div>

            {/* Search and Actions Bar */}
            <div className={`mb-4 p-4 rounded-xl border ${darkMode ? 'bg-gray-800 border-gray-700' : 'bg-white border-gray-200'
                }`}>
                <div className="flex flex-col sm:flex-row gap-3 mb-3">
                    {/* Search Input */}
                    <div className="flex-1 relative">
                        <Search className={`absolute left-3 top-1/2 transform -translate-y-1/2 w-4 h-4 ${darkMode ? 'text-gray-500' : 'text-gray-400'
                            }`} />
                        <input
                            type="text"
                            placeholder="Search by symbol name, ISN, or series..."
                            value={searchQuery}
                            onChange={(e) => {
                                setSearchQuery(e.target.value);
                                setCurrentPage(1);
                            }}
                            className={`w-full pl-10 pr-4 py-2.5 rounded-lg border text-sm ${darkMode
                                ? 'bg-gray-700 border-gray-600 text-white placeholder-gray-500'
                                : 'bg-white border-gray-300 text-gray-900 placeholder-gray-400'
                                } focus:outline-none focus:ring-2 focus:ring-blue-500`}
                        />
                    </div>

                    {/* Action Buttons */}
                    <div className="flex gap-2">
                        <button
                            onClick={handleSelectAll}
                            className={`px-4 py-2 rounded-lg text-xs font-semibold transition-colors whitespace-nowrap ${darkMode
                                ? 'bg-blue-600/20 text-blue-400 hover:bg-blue-600/30'
                                : 'bg-blue-100 text-blue-700 hover:bg-blue-200'
                                }`}
                        >
                            Select All
                        </button>
                        <button
                            onClick={handleClearAll}
                            disabled={selectedSymbols.length === 0}
                            className={`px-4 py-2 rounded-lg text-xs font-semibold transition-colors whitespace-nowrap ${selectedSymbols.length === 0
                                ? darkMode
                                    ? 'bg-gray-700 text-gray-500 cursor-not-allowed'
                                    : 'bg-gray-100 text-gray-400 cursor-not-allowed'
                                : darkMode
                                    ? 'bg-red-600/20 text-red-400 hover:bg-red-600/30'
                                    : 'bg-red-100 text-red-700 hover:bg-red-200'
                                }`}
                        >
                            Clear All
                        </button>
                    </div>
                </div>

                {/* Stats */}
                <div className={`flex flex-wrap gap-4 text-xs ${darkMode ? 'text-gray-400' : 'text-gray-600'
                    }`}>
                    <span>
                        Total Symbols: <strong className={darkMode ? 'text-white' : 'text-gray-900'}>
                            {symbols.length}
                        </strong>
                    </span>
                    {searchQuery && (
                        <span>
                            Filtered: <strong className={darkMode ? 'text-white' : 'text-gray-900'}>
                                {filteredSymbols.length}
                            </strong>
                        </span>
                    )}
                    <span>
                        Selected: <strong className={selectedSymbols.length > 0 ? 'text-green-500' : darkMode ? 'text-white' : 'text-gray-900'}>
                            {selectedSymbols.length}
                        </strong>
                    </span>
                </div>
            </div>

            {/* Symbol List */}
            <div className={`rounded-xl border overflow-hidden ${darkMode ? 'bg-gray-800 border-gray-700' : 'bg-white border-gray-200'
                }`}>
                {filteredSymbols.length > 0 ? (
                    <>
                        <div className="max-h-[400px] overflow-y-auto hide-scrollbar">
                            {paginatedSymbols.map((symbol) => {
                                const isSelected = selectedSymbols.includes(symbol.tokenNumber);

                                return (
                                    <button
                                        key={symbol.tokenNumber}
                                        onClick={() => onToggle(symbol.tokenNumber)}
                                        className={`w-full p-4 border-b transition-all text-left ${darkMode ? 'border-gray-700' : 'border-gray-100'
                                            } ${isSelected
                                                ? darkMode
                                                    ? 'bg-blue-600/10 hover:bg-blue-600/15'
                                                    : 'bg-blue-50 hover:bg-blue-100'
                                                : darkMode
                                                    ? 'hover:bg-gray-750'
                                                    : 'hover:bg-gray-50'
                                            }`}
                                    >
                                        <div className="flex items-center gap-3">
                                            {/* Checkbox */}
                                            <div className="flex-shrink-0">
                                                {isSelected ? (
                                                    <CheckCircle className={`w-5 h-5 ${darkMode ? 'text-blue-400' : 'text-blue-600'
                                                        }`} />
                                                ) : (
                                                    <Circle className={`w-5 h-5 ${darkMode ? 'text-gray-600' : 'text-gray-400'
                                                        }`} />
                                                )}
                                            </div>

                                            {/* Symbol Info */}
                                            <div className="flex-1 min-w-0">
                                                <div className="flex items-center gap-2 mb-1">
                                                    <span className={`font-bold text-sm ${darkMode ? 'text-white' : 'text-gray-900'
                                                        }`}>
                                                        {symbol.symbolName}
                                                    </span>
                                                    <span className={`text-xs px-2 py-0.5 rounded-full ${darkMode
                                                        ? 'bg-gray-700 text-gray-400'
                                                        : 'bg-gray-200 text-gray-600'
                                                        }`}>
                                                        {symbol.series}
                                                    </span>
                                                    {symbol.segment && (
                                                        <span className={`text-xs px-2 py-0.5 rounded-full ${darkMode
                                                            ? 'bg-purple-500/20 text-purple-400'
                                                            : 'bg-purple-100 text-purple-600'
                                                            }`}>
                                                            {symbol.segment}
                                                        </span>
                                                    )}
                                                </div>
                                                <div className={`text-xs ${darkMode ? 'text-gray-400' : 'text-gray-600'
                                                    }`}>
                                                    <span className="font-medium">ISN:</span> {symbol.isn}
                                                    {symbol.strikePrice > 0 && (
                                                        <span className="ml-2">• Strike: ₹{symbol.strikePrice.toLocaleString()}</span>
                                                    )}
                                                    <span className="ml-2">• Lot: {symbol.lotSize}</span>
                                                </div>
                                            </div>
                                        </div>
                                    </button>
                                );
                            })}
                        </div>

                        {/* Pagination */}
                        {totalPages > 1 && (
                            <div className={`p-4 border-t flex items-center justify-between ${darkMode ? 'border-gray-700 bg-gray-750' : 'border-gray-200 bg-gray-50'
                                }`}>
                                <button
                                    onClick={() => handlePageChange(currentPage - 1)}
                                    disabled={currentPage === 1}
                                    className={`px-3 py-1.5 rounded-lg text-xs font-semibold transition-colors ${currentPage === 1
                                        ? darkMode
                                            ? 'bg-gray-700 text-gray-500 cursor-not-allowed'
                                            : 'bg-gray-200 text-gray-400 cursor-not-allowed'
                                        : darkMode
                                            ? 'bg-gray-700 text-gray-300 hover:bg-gray-600'
                                            : 'bg-gray-200 text-gray-700 hover:bg-gray-300'
                                        }`}
                                >
                                    Previous
                                </button>

                                <span className={`text-xs ${darkMode ? 'text-gray-400' : 'text-gray-600'
                                    }`}>
                                    Page {currentPage} of {totalPages}
                                </span>

                                <button
                                    onClick={() => handlePageChange(currentPage + 1)}
                                    disabled={currentPage === totalPages}
                                    className={`px-3 py-1.5 rounded-lg text-xs font-semibold transition-colors ${currentPage === totalPages
                                        ? darkMode
                                            ? 'bg-gray-700 text-gray-500 cursor-not-allowed'
                                            : 'bg-gray-200 text-gray-400 cursor-not-allowed'
                                        : darkMode
                                            ? 'bg-gray-700 text-gray-300 hover:bg-gray-600'
                                            : 'bg-gray-200 text-gray-700 hover:bg-gray-300'
                                        }`}
                                >
                                    Next
                                </button>
                            </div>
                        )}
                    </>
                ) : (
                    <div className="p-12 text-center">
                        <Search className={`w-12 h-12 mx-auto mb-3 opacity-50 ${darkMode ? 'text-gray-600' : 'text-gray-400'
                            }`} />
                        <p className={`text-sm ${darkMode ? 'text-gray-500' : 'text-gray-500'
                            }`}>
                            No symbols found matching "{searchQuery}"
                        </p>
                    </div>
                )}
            </div>

            {/* Save Button */}
            {/* <button
                onClick={() => onSave(selectedSymbols)}
                disabled={selectedSymbols.length === 0}
                className={`w-full mt-5 flex items-center justify-center gap-2 px-6 py-3.5 rounded-xl text-sm font-bold transition-all ${
                    selectedSymbols.length > 0
                        ? darkMode
                            ? 'bg-gradient-to-r from-green-600 to-emerald-600 hover:from-green-700 hover:to-emerald-700 text-white shadow-lg hover:shadow-xl'
                            : 'bg-gradient-to-r from-green-500 to-emerald-500 hover:from-green-600 hover:to-emerald-600 text-white shadow-lg hover:shadow-xl'
                        : darkMode
                            ? 'bg-gray-700 text-gray-500 cursor-not-allowed'
                            : 'bg-gray-200 text-gray-400 cursor-not-allowed'
                } transform ${selectedSymbols.length > 0 ? 'hover:scale-[1.02]' : ''}`}
            >
                <Save className="w-5 h-5" />
                {selectedSymbols.length > 0 
                    ? `Save ${selectedSymbols.length} Selected Symbol${selectedSymbols.length > 1 ? 's' : ''}`
                    : 'Select at least one symbol'
                }
            </button> */}
            <div className="flex gap-3 mt-5">
                <button
                    onClick={() => onSave(selectedSymbols)}
                    disabled={selectedSymbols.length === 0}
                    className={`flex-1 flex items-center justify-center gap-2 px-6 py-3.5 rounded-xl text-sm font-bold transition-all ${selectedSymbols.length > 0
                            ? darkMode
                                ? 'bg-gradient-to-r from-green-600 to-emerald-600 hover:from-green-700 hover:to-emerald-700 text-white shadow-lg hover:shadow-xl'
                                : 'bg-gradient-to-r from-green-500 to-emerald-500 hover:from-green-600 hover:to-emerald-600 text-white shadow-lg hover:shadow-xl'
                            : darkMode
                                ? 'bg-gray-700 text-gray-500 cursor-not-allowed'
                                : 'bg-gray-200 text-gray-400 cursor-not-allowed'
                        } transform ${selectedSymbols.length > 0 ? 'hover:scale-[1.02]' : ''}`}
                >
                    <Save className="w-5 h-5" />
                    {selectedSymbols.length > 0
                        ? `Save ${selectedSymbols.length} Selected Symbol${selectedSymbols.length > 1 ? 's' : ''}`
                        : 'No symbols selected'
                    }
                </button>

                <button
                    onClick={() => onSave([])}
                    className={`px-6 py-3.5 rounded-xl text-sm font-bold transition-all ${darkMode
                            ? 'bg-blue-600/20 hover:bg-blue-600/30 text-blue-400 border-2 border-blue-500/50'
                            : 'bg-blue-100 hover:bg-blue-200 text-blue-700 border-2 border-blue-300'
                        }`}
                >
                    Skip & Use Entry Condition
                </button>
            </div>
        </div>
    );
}