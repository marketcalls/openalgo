// import React from 'react';
// import { Circle } from 'lucide-react';
// import StrategyInfoModal from './StrategyInfoModal';

// interface Strategy {
//     id: number;
//     name: string;
//     status: string;
// }

// interface Broker {
//     connected: boolean;
// }

// interface StrategyConfig {
//     strategyId: string | null;
//     [key: string]: any;
// }

// interface TopSectionProps {
//     darkMode: boolean;
//     strategies: Strategy[];
//     activeStrategy: number;
//     setActiveStrategy: (index: number) => void;
//     setStrategies: (strategies: Strategy[]) => void;
//     selectedBroker: Broker;
//     configRef: React.RefObject<StrategyConfig>;
//     isStrategyInfoOpen: boolean;
//     setIsStrategyInfoOpen: (open: boolean) => void;
//     currentStrategyId: string;
//     setCurrentStrategyId: (id: string) => void;
// }

// // Stat Component
// const Stat: React.FC<{ label: string; value: string; positive?: boolean }> = ({ label, value, positive }) => (
//     <div className="flex items-center gap-1">
//         <span className="text-[10px] opacity-60">{label}:</span>
//         <span className={`font-semibold ${positive ? 'text-green-400' : ''}`}>{value}</span>
//     </div>
// );

// const TopSection: React.FC<TopSectionProps> = ({
//     darkMode,
//     strategies,
//     activeStrategy,
//     setActiveStrategy,
//     setStrategies,
//     selectedBroker,
//     configRef,
//     isStrategyInfoOpen,
//     setIsStrategyInfoOpen,
//     currentStrategyId,
//     setCurrentStrategyId
// }) => {
//     return (
//         <div className={`border-b ${darkMode ? 'border-gray-700 bg-gray-900' : 'border-gray-200 bg-gray-50'} px-4 py-2.5`}>
//             {/* First Row: Strategy Tabs + Stats + PANIC Buttons */}
//             <div className="flex items-center gap-2 flex-1 min-w-0 overflow-x-auto hide-scrollbar">
//                 {/* Left: Strategy Tabs with Add Button */}
//                 <div className="flex items-center gap-2 overflow-x-auto hide-scrollbar">
//                     {strategies.map((strategy, index) => (
//                         <div key={strategy.id} className="relative group">
//                             <button
//                                 onClick={() => setActiveStrategy(index)}
//                                 className={`px-3 py-1.5 rounded-t-lg text-xs font-semibold whitespace-nowrap transition-all flex items-center gap-2 ${activeStrategy === index
//                                     ? darkMode
//                                         ? 'bg-gray-900 text-white border-t border-l border-r border-gray-700'
//                                         : 'bg-white text-gray-900 border-t border-l border-r border-gray-300'
//                                     : darkMode
//                                         ? 'bg-gray-800 text-gray-400 hover:bg-gray-750 hover:text-gray-300'
//                                         : 'bg-gray-100 text-gray-600 hover:bg-gray-200 hover:text-gray-900'
//                                     }`}
//                             >
//                                 <div className="relative flex-shrink-0">
//                                     <Circle
//                                         className={`w-1.5 h-1.5 ${strategy.status === 'active' ? 'fill-green-400 text-green-400' :
//                                             strategy.status === 'paused' ? 'fill-yellow-400 text-yellow-400' :
//                                                 'fill-gray-400 text-gray-400'
//                                             }`}
//                                     />
//                                     {strategy.status === 'active' && (
//                                         <div className="absolute inset-0 animate-ping">
//                                             <Circle className="w-1.5 h-1.5 fill-green-400 text-green-400 opacity-75" />
//                                         </div>
//                                     )}
//                                 </div>
//                                 <span className="hidden sm:inline">{strategy.name}</span>
//                                 <span className="sm:hidden">{strategy.name.split(' ')[0]}</span>
//                                 {strategies.length > 1 && (
//                                     <button
//                                         onClick={(e) => {
//                                             e.stopPropagation();
//                                             const newStrategies = strategies.filter(s => s.id !== strategy.id);
//                                             setStrategies(newStrategies);
//                                             if (activeStrategy >= newStrategies.length) {
//                                                 setActiveStrategy(newStrategies.length - 1);
//                                             }
//                                         }}
//                                         className="ml-1 opacity-0 group-hover:opacity-100 transition-opacity"
//                                     >
//                                         <svg className="w-3 h-3 hover:text-red-500" fill="none" viewBox="0 0 24 24" stroke="currentColor">
//                                             <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
//                                         </svg>
//                                     </button>
//                                 )}
//                             </button>
//                         </div>
//                     ))}

//                     {/* Add New Strategy Tab Button */}
//                     {strategies.length < 5 && (
//                         <button
//                             onClick={() => {
//                                 const newStrategy = {
//                                     id: Date.now(),
//                                     name: `Strategy ${strategies.length + 1}`,
//                                     status: 'inactive'
//                                 };
//                                 setStrategies([...strategies, newStrategy]);
//                                 setActiveStrategy(strategies.length);
//                             }}
//                             className={`px-2.5 py-1.5 rounded-t-lg text-xs font-semibold transition-all flex items-center gap-1 ${darkMode
//                                 ? 'bg-gray-800 text-gray-400 hover:bg-gray-750 hover:text-gray-300'
//                                 : 'bg-gray-100 text-gray-600 hover:bg-gray-200 hover:text-gray-900'
//                                 }`}
//                             title="Add new strategy"
//                         >
//                             <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
//                                 <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 4v16m8-8H4" />
//                             </svg>
//                         </button>
//                     )}
//                 </div>

//                 {/* Live Stats Section */}
//                 <div
//                     className={`flex items-center gap-4 px-3 py-1.5 rounded-full border text-xs flex-shrink-0 ${darkMode
//                         ? 'border-blue-500/30 bg-blue-500/5 text-blue-300'
//                         : 'border-blue-300/40 bg-blue-50 text-blue-700'
//                         }`}
//                 >
//                     <Stat label="O" value="127.45" />
//                     <Stat label="C" value="129.80" />
//                     <Stat label="R" value="+245.50" positive />
//                     <Stat label="U" value="+132.20" positive />
//                 </div>

//                 {/* Right: PANIC Buttons - Extreme Right */}
//                 <div className="flex items-center gap-3 flex-shrink-0 ml-auto">
//                     {/* Exit All Button */}
//                     <button
//                         onClick={() => {
//                             // Handle exit all
//                         }}
//                         className={`px-4 py-2 rounded-lg text-xs font-black uppercase tracking-wider transition-all flex items-center gap-2 border-2 ${darkMode
//                             ? 'bg-gradient-to-br from-orange-600 via-orange-700 to-red-700 hover:from-orange-700 hover:via-orange-800 hover:to-red-800 text-white border-orange-400 shadow-lg shadow-orange-500/50'
//                             : 'bg-gradient-to-br from-orange-500 via-orange-600 to-red-600 hover:from-orange-600 hover:via-orange-700 hover:to-red-700 text-white border-orange-300 shadow-lg shadow-orange-400/50'
//                             } transform hover:scale-110 active:scale-95 animate-pulse`}
//                         title="⚠️ EXIT ALL POSITIONS"
//                     >
//                         <svg className="w-4 h-4 animate-pulse" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={3}>
//                             <path strokeLinecap="round" strokeLinejoin="round" d="M17 16l4-4m0 0l-4-4m4 4H7m6 4v1a3 3 0 01-3 3H6a3 3 0 01-3-3V7a3 3 0 013-3h4a3 3 0 013 3v1" />
//                         </svg>
//                         <span className="font-black">EXIT ALL</span>
//                         <span className="text-[10px] font-bold px-1.5 py-0.5 bg-white/20 rounded">⚠️</span>
//                     </button>

//                     {/* Stop All Button */}
//                     <button
//                         onClick={() => {
//                             // Handle stop all
//                         }}
//                         className={`px-4 py-2 rounded-lg text-xs font-black uppercase tracking-wider transition-all flex items-center gap-2 border-2 ${darkMode
//                             ? 'bg-gradient-to-br from-red-600 via-red-700 to-red-900 hover:from-red-700 hover:via-red-800 hover:to-black text-white border-red-400 shadow-lg shadow-red-500/50'
//                             : 'bg-gradient-to-br from-red-500 via-red-600 to-red-800 hover:from-red-600 hover:via-red-700 hover:to-red-900 text-white border-red-300 shadow-lg shadow-red-400/50'
//                             } transform hover:scale-110 active:scale-95 animate-pulse`}
//                         title="🛑 STOP ALL STRATEGIES"
//                     >
//                         <svg className="w-4 h-4 animate-pulse" fill="currentColor" viewBox="0 0 20 20">
//                             <rect x="3" y="3" width="14" height="14" rx="2" />
//                         </svg>
//                         <span className="font-black">STOP ALL</span>
//                         <span className="text-[10px] font-bold px-1.5 py-0.5 bg-white/20 rounded">🛑</span>
//                     </button>
//                 </div>
//             </div>

//             {/* Second Row: Broker, Status & Control */}
//             <div className="flex items-center justify-between">
//                 <div className="flex items-center gap-3 mt-2">
//                     {/* Connection Status */}
//                     <div className={`flex items-center gap-1.5 px-2 py-0.5 rounded-full ${selectedBroker.connected
//                         ? darkMode ? 'bg-green-500/20' : 'bg-green-50'
//                         : darkMode ? 'bg-red-500/20' : 'bg-red-50'
//                         }`}>
//                         <div className="relative">
//                             <div className={`w-1.5 h-1.5 rounded-full ${selectedBroker.connected ? 'bg-green-500' : 'bg-red-500'
//                                 }`} />
//                             {selectedBroker.connected && (
//                                 <div className="absolute inset-0 animate-ping">
//                                     <div className="w-1.5 h-1.5 rounded-full bg-green-500 opacity-75" />
//                                 </div>
//                             )}
//                         </div>
//                         <span className={`text-[9px] font-bold uppercase ${selectedBroker.connected
//                             ? 'text-green-600 dark:text-green-400'
//                             : 'text-red-600 dark:text-red-400'
//                             }`}>
//                             {selectedBroker.connected ? 'LIVE' : 'OFF'}
//                         </span>
//                     </div>

//                     {/* Live P and L stat */}
//                     <div
//                         className={`flex items-center gap-3 px-3 py-1 rounded-md border flex-shrink-0 ${darkMode
//                             ? 'border-blue-500/30 bg-blue-500/5'
//                             : 'border-blue-300/30 bg-blue-50/40'
//                             }`}
//                     >
//                         {/* Open */}
//                         <div className="flex items-center gap-0.5">
//                             <span className={`text-[10px] font-medium ${darkMode ? 'text-gray-400' : 'text-gray-600'}`}>
//                                 Open:
//                             </span>
//                             <span className={`text-[11px] font-semibold ${darkMode ? 'text-blue-400' : 'text-blue-600'}`}>
//                                 127.45
//                             </span>
//                         </div>

//                         {/* Close */}
//                         <div className="flex items-center gap-0.5">
//                             <span className={`text-[10px] font-medium ${darkMode ? 'text-gray-400' : 'text-gray-600'}`}>
//                                 Close:
//                             </span>
//                             <span className={`text-[11px] font-semibold ${darkMode ? 'text-blue-400' : 'text-blue-600'}`}>
//                                 129.80
//                             </span>
//                         </div>

//                         {/* Realized P&L */}
//                         <div className="flex items-center gap-0.5">
//                             <span className={`text-[10px] font-medium ${darkMode ? 'text-gray-400' : 'text-gray-600'}`}>
//                                 Realised P&amp;L:
//                             </span>
//                             <span
//                                 className={`text-[11px] font-semibold ${245.5 >= 0
//                                     ? darkMode ? 'text-green-400' : 'text-green-600'
//                                     : darkMode ? 'text-red-400' : 'text-red-600'
//                                     }`}
//                             >
//                                 +245.50
//                             </span>
//                         </div>

//                         {/* Unrealized P&L */}
//                         <div className="flex items-center gap-0.5">
//                             <span className={`text-[10px] font-medium ${darkMode ? 'text-gray-400' : 'text-gray-600'}`}>
//                                 Unrealised P&amp;L:
//                             </span>
//                             <span
//                                 className={`text-[11px] font-semibold ${132.2 >= 0
//                                     ? darkMode ? 'text-green-400' : 'text-green-600'
//                                     : darkMode ? 'text-red-400' : 'text-red-600'
//                                     }`}
//                             >
//                                 +132.20
//                             </span>
//                         </div>
//                     </div>

//                     {/* Start/Stop Current Strategy */}
//                     <div className="flex items-center gap-2">
//                         <button
//                             onClick={() => {
//                                 console.log('Toggle strategy:', strategies[activeStrategy].name);
//                             }}
//                             className={`px-3 py-1 rounded text-[11px] font-bold uppercase tracking-wide transition-all flex items-center gap-1.5 ${strategies[activeStrategy].status === 'active'
//                                 ? darkMode
//                                     ? 'bg-gradient-to-r from-red-600 to-red-700 hover:from-red-700 hover:to-red-800 text-white'
//                                     : 'bg-gradient-to-r from-red-500 to-red-600 hover:from-red-600 hover:to-red-700 text-white'
//                                 : darkMode
//                                     ? 'bg-gradient-to-r from-green-600 to-green-700 hover:from-green-700 hover:to-green-800 text-white'
//                                     : 'bg-gradient-to-r from-green-500 to-green-600 hover:from-green-600 hover:to-green-700 text-white'
//                                 } shadow-sm`}
//                         >
//                             {strategies[activeStrategy].status === 'active' ? (
//                                 <>
//                                     <svg className="w-2.5 h-2.5" fill="currentColor" viewBox="0 0 20 20">
//                                         <rect x="6" y="4" width="2.5" height="12" rx="1" />
//                                         <rect x="11.5" y="4" width="2.5" height="12" rx="1" />
//                                     </svg>
//                                     Stop
//                                 </>
//                             ) : (
//                                 <>
//                                     <svg className="w-2.5 h-2.5" fill="currentColor" viewBox="0 0 20 20">
//                                         <path d="M6.3 2.841A1.5 1.5 0 004 4.11V15.89a1.5 1.5 0 002.3 1.269l9.344-5.89a1.5 1.5 0 000-2.538L6.3 2.84z" />
//                                     </svg>
//                                     Start
//                                 </>
//                             )}
//                         </button>

//                         <button
//                             onClick={() => {
//                                 const strategyId = configRef.current?.strategyId || String(strategies[activeStrategy].id);
//                                 setCurrentStrategyId(strategyId);
//                                 setIsStrategyInfoOpen(true);
//                             }}
//                             className={`px-3 py-1 rounded text-[11px] font-bold uppercase tracking-wide transition-all flex items-center gap-1.5 ${darkMode
//                                 ? 'bg-blue-600 hover:bg-blue-700 text-white'
//                                 : 'bg-blue-500 hover:bg-blue-600 text-white'
//                                 } shadow-sm`}
//                             title="View Strategy Details"
//                         >
//                             <svg className="w-2.5 h-2.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
//                                 <path strokeLinecap="round" strokeLinejoin="round" d="M13 16h-1v-4h-1m1-4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
//                             </svg>
//                             Strategy Info
//                         </button>

//                         {/* Strategy Info Modal */}
//                         <StrategyInfoModal
//                             isOpen={isStrategyInfoOpen}
//                             onClose={() => setIsStrategyInfoOpen(false)}
//                             strategyId={currentStrategyId}
//                         />

//                         <button
//                             onClick={() => {
//                                 console.log('Exit strategy:', strategies[activeStrategy].name);
//                             }}
//                             className={`px-3 py-1 rounded text-[11px] font-bold uppercase tracking-wide transition-all ${darkMode
//                                 ? 'bg-orange-600 hover:bg-orange-700 text-white'
//                                 : 'bg-orange-500 hover:bg-orange-600 text-white'
//                                 } shadow-sm`}
//                         >
//                             Exit
//                         </button>
//                     </div>
//                 </div>
//             </div>
//         </div>
//     );
// };

// export default TopSection;

import React from 'react';
import { Circle } from 'lucide-react';
import StrategyInfoModal from './StrategyInfoModal';

interface Strategy {
    id: number;
    name: string;
    status: string;
}

interface Broker {
    connected: boolean;
}

interface StrategyConfig {
    strategyId: string | null;
    strategyName?: string | null;
    [key: string]: any;
}

interface TopSectionProps {
    darkMode: boolean;
    strategies: Strategy[];
    activeStrategy: number;
    setActiveStrategy: (index: number) => void;
    setStrategies: (strategies: Strategy[]) => void;
    selectedBroker: Broker;
    configRef: React.RefObject<StrategyConfig>;
    isStrategyInfoOpen: boolean;
    setIsStrategyInfoOpen: (open: boolean) => void;
    currentStrategyId: string;
    setCurrentStrategyId: (id: string) => void;
}

// Stat Component
const Stat: React.FC<{ label: string; value: string; positive?: boolean }> = ({ label, value, positive }) => (
    <div className="flex items-center gap-1">
        <span className="text-[10px] opacity-60">{label}:</span>
        <span className={`font-semibold ${positive ? 'text-green-400' : ''}`}>{value}</span>
    </div>
);

const TopSection: React.FC<TopSectionProps> = ({
    darkMode,
    strategies,
    activeStrategy,
    setActiveStrategy,
    setStrategies,
    selectedBroker,
    configRef,
    isStrategyInfoOpen,
    setIsStrategyInfoOpen,
    currentStrategyId,
    setCurrentStrategyId
}) => {
    // Get strategy name from config or use default
    const getStrategyName = (index: number) => {
        if (index === activeStrategy && configRef.current?.strategyName) {
            return configRef.current.strategyName;
        }
        return strategies[index]?.name || 'Untitled';
    };

    return (
        <div className={`border-b ${darkMode ? 'border-gray-700 bg-gray-900' : 'border-gray-200 bg-gray-50'} px-4 py-2.5`}>
            {/* First Row: Strategy Tabs + Stats + PANIC Buttons */}
            <div className="flex items-center gap-2 flex-1 min-w-0 overflow-x-auto hide-scrollbar">
                {/* Left: Strategy Tabs with Add Button */}
                <div className="flex items-center gap-2 overflow-x-auto hide-scrollbar">
                    {strategies.map((strategy, index) => (
                        <div key={strategy.id} className="relative group">
                            <button
                                onClick={() => setActiveStrategy(index)}
                                className={`px-3 py-1.5 rounded-t-lg text-xs font-semibold whitespace-nowrap transition-all flex items-center gap-2 ${activeStrategy === index
                                    ? darkMode
                                        ? 'bg-gray-900 text-white border-t border-l border-r border-gray-700'
                                        : 'bg-white text-gray-900 border-t border-l border-r border-gray-300'
                                    : darkMode
                                        ? 'bg-gray-800 text-gray-400 hover:bg-gray-750 hover:text-gray-300'
                                        : 'bg-gray-100 text-gray-600 hover:bg-gray-200 hover:text-gray-900'
                                    }`}
                            >
                                <div className="relative flex-shrink-0">
                                    <Circle
                                        className={`w-1.5 h-1.5 ${strategy.status === 'active' ? 'fill-green-400 text-green-400' :
                                            strategy.status === 'paused' ? 'fill-yellow-400 text-yellow-400' :
                                                'fill-gray-400 text-gray-400'
                                            }`}
                                    />
                                    {strategy.status === 'active' && (
                                        <div className="absolute inset-0 animate-ping">
                                            <Circle className="w-1.5 h-1.5 fill-green-400 text-green-400 opacity-75" />
                                        </div>
                                    )}
                                </div>
                                <span className="hidden sm:inline">{getStrategyName(index)}</span>
                                <span className="sm:hidden">{getStrategyName(index).split(' ')[0]}</span>
                                {strategies.length > 1 && (
                                    <button
                                        onClick={(e) => {
                                            e.stopPropagation();
                                            const newStrategies = strategies.filter(s => s.id !== strategy.id);
                                            setStrategies(newStrategies);
                                            if (activeStrategy >= newStrategies.length) {
                                                setActiveStrategy(newStrategies.length - 1);
                                            }
                                        }}
                                        className="ml-1 opacity-0 group-hover:opacity-100 transition-opacity"
                                    >
                                        <svg className="w-3 h-3 hover:text-red-500" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                                            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
                                        </svg>
                                    </button>
                                )}
                            </button>
                        </div>
                    ))}

                    {/* Add New Strategy Tab Button */}
                    {strategies.length < 5 && (
                        <button
                            onClick={() => {
                                const newStrategy = {
                                    id: Date.now(),
                                    name: 'Untitled',
                                    status: 'inactive'
                                };
                                setStrategies([...strategies, newStrategy]);
                                setActiveStrategy(strategies.length);
                            }}
                            className={`px-2.5 py-1.5 rounded-t-lg text-xs font-semibold transition-all flex items-center gap-1 ${darkMode
                                ? 'bg-gray-800 text-gray-400 hover:bg-gray-750 hover:text-gray-300'
                                : 'bg-gray-100 text-gray-600 hover:bg-gray-200 hover:text-gray-900'
                                }`}
                            title="Add new strategy"
                        >
                            <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 4v16m8-8H4" />
                            </svg>
                        </button>
                    )}
                </div>

                {/* Live Stats Section */}
                <div
                    className={`flex items-center gap-4 px-3 py-1.5 rounded-full border text-xs flex-shrink-0 ${darkMode
                        ? 'border-blue-500/30 bg-blue-500/5 text-blue-300'
                        : 'border-blue-300/40 bg-blue-50 text-blue-700'
                        }`}
                >
                    <Stat label="O" value="127.45" />
                    <Stat label="C" value="129.80" />
                    <Stat label="R" value="+245.50" positive />
                    <Stat label="U" value="+132.20" positive />
                </div>

                {/* Right: PANIC Buttons - Extreme Right */}
                <div className="flex items-center gap-3 flex-shrink-0 ml-auto">
                    {/* Exit All Button */}
                    <button
                        onClick={() => {
                            // Handle exit all
                        }}
                        className={`px-4 py-2 rounded-lg text-xs font-black uppercase tracking-wider transition-all flex items-center gap-2 border-2 ${darkMode
                            ? 'bg-gradient-to-br from-orange-600 via-orange-700 to-red-700 hover:from-orange-700 hover:via-orange-800 hover:to-red-800 text-white border-orange-400 shadow-lg shadow-orange-500/50'
                            : 'bg-gradient-to-br from-orange-500 via-orange-600 to-red-600 hover:from-orange-600 hover:via-orange-700 hover:to-red-700 text-white border-orange-300 shadow-lg shadow-orange-400/50'
                            } transform hover:scale-110 active:scale-95 animate-pulse`}
                        title="⚠️ EXIT ALL POSITIONS"
                    >
                        <svg className="w-4 h-4 animate-pulse" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={3}>
                            <path strokeLinecap="round" strokeLinejoin="round" d="M17 16l4-4m0 0l-4-4m4 4H7m6 4v1a3 3 0 01-3 3H6a3 3 0 01-3-3V7a3 3 0 013-3h4a3 3 0 013 3v1" />
                        </svg>
                        <span className="font-black">EXIT ALL</span>
                        <span className="text-[10px] font-bold px-1.5 py-0.5 bg-white/20 rounded">⚠️</span>
                    </button>

                    {/* Stop All Button */}
                    <button
                        onClick={() => {
                            // Handle stop all
                        }}
                        className={`px-4 py-2 rounded-lg text-xs font-black uppercase tracking-wider transition-all flex items-center gap-2 border-2 ${darkMode
                            ? 'bg-gradient-to-br from-red-600 via-red-700 to-red-900 hover:from-red-700 hover:via-red-800 hover:to-black text-white border-red-400 shadow-lg shadow-red-500/50'
                            : 'bg-gradient-to-br from-red-500 via-red-600 to-red-800 hover:from-red-600 hover:via-red-700 hover:to-red-900 text-white border-red-300 shadow-lg shadow-red-400/50'
                            } transform hover:scale-110 active:scale-95 animate-pulse`}
                        title="🛑 STOP ALL STRATEGIES"
                    >
                        <svg className="w-4 h-4 animate-pulse" fill="currentColor" viewBox="0 0 20 20">
                            <rect x="3" y="3" width="14" height="14" rx="2" />
                        </svg>
                        <span className="font-black">STOP ALL</span>
                        <span className="text-[10px] font-bold px-1.5 py-0.5 bg-white/20 rounded">🛑</span>
                    </button>
                </div>
            </div>

            {/* Second Row: Broker, Status & Control */}
            <div className="flex items-center justify-between">
                <div className="flex items-center gap-3 mt-2">
                    {/* Connection Status */}
                    <div className={`flex items-center gap-1.5 px-2 py-0.5 rounded-full ${selectedBroker.connected
                        ? darkMode ? 'bg-green-500/20' : 'bg-green-50'
                        : darkMode ? 'bg-red-500/20' : 'bg-red-50'
                        }`}>
                        <div className="relative">
                            <div className={`w-1.5 h-1.5 rounded-full ${selectedBroker.connected ? 'bg-green-500' : 'bg-red-500'
                                }`} />
                            {selectedBroker.connected && (
                                <div className="absolute inset-0 animate-ping">
                                    <div className="w-1.5 h-1.5 rounded-full bg-green-500 opacity-75" />
                                </div>
                            )}
                        </div>
                        <span className={`text-[9px] font-bold uppercase ${selectedBroker.connected
                            ? 'text-green-600 dark:text-green-400'
                            : 'text-red-600 dark:text-red-400'
                            }`}>
                            {selectedBroker.connected ? 'LIVE' : 'OFF'}
                        </span>
                    </div>

                    {/* Live P and L stat */}
                    <div
                        className={`flex items-center gap-3 px-3 py-1 rounded-md border flex-shrink-0 ${darkMode
                            ? 'border-blue-500/30 bg-blue-500/5'
                            : 'border-blue-300/30 bg-blue-50/40'
                            }`}
                    >
                        {/* Open */}
                        <div className="flex items-center gap-0.5">
                            <span className={`text-[10px] font-medium ${darkMode ? 'text-gray-400' : 'text-gray-600'}`}>
                                Open:
                            </span>
                            <span className={`text-[11px] font-semibold ${darkMode ? 'text-blue-400' : 'text-blue-600'}`}>
                                127.45
                            </span>
                        </div>

                        {/* Close */}
                        <div className="flex items-center gap-0.5">
                            <span className={`text-[10px] font-medium ${darkMode ? 'text-gray-400' : 'text-gray-600'}`}>
                                Close:
                            </span>
                            <span className={`text-[11px] font-semibold ${darkMode ? 'text-blue-400' : 'text-blue-600'}`}>
                                129.80
                            </span>
                        </div>

                        {/* Realized P&L */}
                        <div className="flex items-center gap-0.5">
                            <span className={`text-[10px] font-medium ${darkMode ? 'text-gray-400' : 'text-gray-600'}`}>
                                Realised P&amp;L:
                            </span>
                            <span
                                className={`text-[11px] font-semibold ${245.5 >= 0
                                    ? darkMode ? 'text-green-400' : 'text-green-600'
                                    : darkMode ? 'text-red-400' : 'text-red-600'
                                    }`}
                            >
                                +245.50
                            </span>
                        </div>

                        {/* Unrealized P&L */}
                        <div className="flex items-center gap-0.5">
                            <span className={`text-[10px] font-medium ${darkMode ? 'text-gray-400' : 'text-gray-600'}`}>
                                Unrealised P&amp;L:
                            </span>
                            <span
                                className={`text-[11px] font-semibold ${132.2 >= 0
                                    ? darkMode ? 'text-green-400' : 'text-green-600'
                                    : darkMode ? 'text-red-400' : 'text-red-600'
                                    }`}
                            >
                                +132.20
                            </span>
                        </div>
                    </div>

                    {/* Start/Stop Current Strategy */}
                    <div className="flex items-center gap-2">
                        <button
                            onClick={() => {
                                console.log('Toggle strategy:', strategies[activeStrategy].name);
                            }}
                            className={`px-3 py-1 rounded text-[11px] font-bold uppercase tracking-wide transition-all flex items-center gap-1.5 ${strategies[activeStrategy].status === 'active'
                                ? darkMode
                                    ? 'bg-gradient-to-r from-red-600 to-red-700 hover:from-red-700 hover:to-red-800 text-white'
                                    : 'bg-gradient-to-r from-red-500 to-red-600 hover:from-red-600 hover:to-red-700 text-white'
                                : darkMode
                                    ? 'bg-gradient-to-r from-green-600 to-green-700 hover:from-green-700 hover:to-green-800 text-white'
                                    : 'bg-gradient-to-r from-green-500 to-green-600 hover:from-green-600 hover:to-green-700 text-white'
                                } shadow-sm`}
                        >
                            {strategies[activeStrategy].status === 'active' ? (
                                <>
                                    <svg className="w-2.5 h-2.5" fill="currentColor" viewBox="0 0 20 20">
                                        <rect x="6" y="4" width="2.5" height="12" rx="1" />
                                        <rect x="11.5" y="4" width="2.5" height="12" rx="1" />
                                    </svg>
                                    Stop
                                </>
                            ) : (
                                <>
                                    <svg className="w-2.5 h-2.5" fill="currentColor" viewBox="0 0 20 20">
                                        <path d="M6.3 2.841A1.5 1.5 0 004 4.11V15.89a1.5 1.5 0 002.3 1.269l9.344-5.89a1.5 1.5 0 000-2.538L6.3 2.84z" />
                                    </svg>
                                    Start
                                </>
                            )}
                        </button>

                        <button
                            onClick={() => {
                                const strategyId = configRef.current?.strategyId || String(strategies[activeStrategy].id);
                                setCurrentStrategyId(strategyId);
                                setIsStrategyInfoOpen(true);
                            }}
                            className={`px-3 py-1 rounded text-[11px] font-bold uppercase tracking-wide transition-all flex items-center gap-1.5 ${darkMode
                                ? 'bg-blue-600 hover:bg-blue-700 text-white'
                                : 'bg-blue-500 hover:bg-blue-600 text-white'
                                } shadow-sm`}
                            title="View Strategy Details"
                        >
                            <svg className="w-2.5 h-2.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                                <path strokeLinecap="round" strokeLinejoin="round" d="M13 16h-1v-4h-1m1-4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
                            </svg>
                            Strategy Info
                        </button>

                        {/* Strategy Info Modal */}
                        <StrategyInfoModal
                            isOpen={isStrategyInfoOpen}
                            onClose={() => setIsStrategyInfoOpen(false)}
                            strategyId={currentStrategyId}
                        />

                        <button
                            onClick={() => {
                                console.log('Exit strategy:', strategies[activeStrategy].name);
                            }}
                            className={`px-3 py-1 rounded text-[11px] font-bold uppercase tracking-wide transition-all ${darkMode
                                ? 'bg-orange-600 hover:bg-orange-700 text-white'
                                : 'bg-orange-500 hover:bg-orange-600 text-white'
                                } shadow-sm`}
                        >
                            Exit
                        </button>
                    </div>
                </div>
            </div>
        </div>
    );
};

export default TopSection;