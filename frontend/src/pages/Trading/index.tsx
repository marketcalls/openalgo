import { useState, useRef, useEffect } from 'react';
import { BROKERS, WATCHLIST, MOCK_USER_STRATEGIES, MOCK_INDICATORS, MOCK_STRATEGY_PARAMETERS, mockBrokers } from './mockData';
import IndicatorParameterWidget from './components/widgets/IndicatorParameterWidget';
import Modal from './components/widgets/Modal';
// import { getAllSymbols } from '../../services/Register';
// import { getAllBroker } from '../../services/broker';
import ChatArea from './components/widgets/ChatArea';
import RightSidebar from './components/widgets/RightSidebar';
import TopSection from './components/widgets/TopSection';
import { useThemeStore } from '@/stores/themeStore';
import type { BrokerInfo, IndicatorConfig, Message, StrategyConfig } from './components';
import type { SymbolMetaData } from './types';

export default function Trading() {

    const configRef = useRef<StrategyConfig>({
        brokerName: null,
        exchange: null,
        strategyType: null,
        strategyId: null,
        strategyName: null,
        positionType: null,
        timeInForce: null,
        indicators: [],
        strategyParameters: {},
        riskManagement: {
            maxPositionSize: null,
            maxDailyLoss: null
        },
        filterSymbols: []
    });

    const storedState = localStorage.getItem("openalgo-auth");
    console.log(storedState, 'storedState')

    const { mode, appMode } = useThemeStore()
    const darkMode = mode === 'dark' || appMode === 'analyzer';
    const userName = storedState
        ? JSON.parse(storedState)?.state?.user?.username || ""
        : "";
    const [_strategyConfig, setStrategyConfig] = useState<StrategyConfig>({
        brokerName: null,
        exchange: null,
        strategyType: null,
        strategyId: null,
        strategyName: null,
        positionType: null,
        timeInForce: null,
        indicators: [],
        strategyParameters: {},
        riskManagement: {
            maxPositionSize: null,
            maxDailyLoss: null
        },
        filterSymbols: []
    });
    const [activeStrategy, setActiveStrategy] = useState(0);
    // const [strategies, setStrategies] = useState(STRATEGIES);

    const [strategies, setStrategies] = useState([
        { id: 1, name: 'Untitled', status: 'inactive' }
    ]);
    const [selectedBroker,] = useState(BROKERS[0]);
    const [inputValue, setInputValue] = useState('');
    const [activeTab, setActiveTab] = useState('orders');
    const [panelHeight, setPanelHeight] = useState(250);
    const [isResizing, setIsResizing] = useState(false);
    const [isPanelVisible, setIsPanelVisible] = useState(false);

    // const textareaRef = useRef<HTMLTextAreaElement>(null);
    const messagesEndRef = useRef<HTMLDivElement>(null);
    const resizeStartY = useRef(0);
    const resizeStartHeight = useRef(0);
    const [selectedStrategyType, setSelectedStrategyType] = useState<string | null>(null);
    const [selectedStrategy, setSelectedStrategy] = useState<string | null>(null);
    const [selectedBrokerName, setSelectedBrokerName] = useState<string | null>(null);
    const [selectedExchange, setSelectedExchange] = useState<string | null>(null);
    const [availableBrokers, setAvailableBrokers] = useState<BrokerInfo[]>([]);
    const [selectedPositionType, setSelectedPositionType] = useState<string | null>(null);
    const [selectedTimeInForce, setSelectedTimeInForce] = useState<string | null>(null);
    // const [selectedIndicatorIds, setSelectedIndicatorIds] = useState<string[]>([]);
    // const [configuringIndicatorId, setConfiguringIndicatorId] = useState<string | null>(null);
    const [indicatorConfigs, setIndicatorConfigs] = useState<IndicatorConfig[]>(MOCK_INDICATORS);
    const [isParameterModalOpen, setIsParameterModalOpen] = useState(false);
    const [currentConfigIndicatorId, setCurrentConfigIndicatorId] = useState<string | null>(null);
    const [availableSymbols] = useState<SymbolMetaData[]>([]);
    const [selectedSymbolsList] = useState<string[]>([]);
    const [_symbolsLoading] = useState(false);
    const [brokersLoading, setBrokersLoading] = useState(false);
    const [isStrategyStarted, setIsStrategyStarted] = useState(false);
    const [isStrategyInfoOpen, setIsStrategyInfoOpen] = useState(false);
    const [currentStrategyId, setCurrentStrategyId] = useState<string>('');

    // Fetch brokers on component mount
    useEffect(() => {
        const fetchBrokers = async () => {
            try {
                setBrokersLoading(true);
                // const brokers = await getAllBroker();

                // Use mock data instead of API
                const brokers = mockBrokers;

                // Filter only brokers where active is explicitly true
                const activeBrokers = brokers.filter(
                    (broker: BrokerInfo) => broker.active === true
                );

                setAvailableBrokers(activeBrokers);

                // If no active brokers found, show error message
                if (activeBrokers.length === 0) {
                    setMessages([
                        {
                            id: 1,
                            type: 'ai',
                            content: `**Welcome to AI Trading Assistant, ${userName}! 🚀**\n\n⚠️ No active brokers available at the moment. Please contact support or try again later.`,
                        }
                    ]);
                }
            } catch (error) {
                console.error('Error fetching brokers:', error);
                setMessages([
                    {
                        id: 1,
                        type: 'ai',
                        content: `**Welcome to AI Trading Assistant, ${userName}! 🚀**\n\n⚠️ Unable to load brokers at the moment. Please refresh the page or contact support if the issue persists.`
                    }
                ]);
            } finally {
                setBrokersLoading(false);
            }
        };

        fetchBrokers();
    }, []);

    useEffect(() => {
        if (availableBrokers.length > 0) {
            const defaultBroker = availableBrokers[0];

            setSelectedBrokerName(defaultBroker.brokerName);
            configRef.current.brokerName = defaultBroker.brokerName;

            showExchangeSelection(defaultBroker);
        }
    }, [availableBrokers]);

    const showExchangeSelection = (broker: any) => {
        const exchanges =
            broker.supportedExchanges && broker.supportedExchanges.length > 0
                ? broker.supportedExchanges
                : ['NSE', 'BSE'];

        const exchangeMessage: Message = {
            id: Date.now(),
            type: 'ai',
            content: `**Welcome to AI Trading Assistant, ${userName}! 🚀**\n\n` +
                `You're trading with ${broker.brokerName} 🎯\n\n` +
                `${broker.description || 'Professional trading platform'}\n\n` +
                `Please choose your exchange:`,
            widget: {
                type: 'radio',
                data: {
                    options: exchanges.map((exchange: any) => ({
                        value: exchange,
                        label: exchange,
                        description:
                            exchange === 'NSE'
                                ? 'National Stock Exchange'
                                : exchange === 'BSE'
                                    ? 'Bombay Stock Exchange'
                                    : `${exchange} Exchange`
                    })),
                    onSelect: (exchange: string) => handleExchangeSelect(exchange)
                }
            }
        };

        setMessages([exchangeMessage]);
    };

    // Update initial messages state to show loading
    const [messages, setMessages] = useState<Message[]>([
        {
            id: 1,
            type: 'ai',
            content: `**Welcome to AI Trading Assistant, ${userName}! 🚀**\n\nLoading available brokers...`
        }
    ]);

    // Auto-scroll messages
    useEffect(() => {
        messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
    }, [messages]);

    // Handle send message
    const handleSend = () => {
        if (!inputValue.trim()) return;

        const userMessage: Message = {
            id: Date.now(),
            type: 'user',
            content: inputValue
        };

        setMessages(prev => [...prev, userMessage]);
        setInputValue('');

        // Simulate AI response
        setTimeout(() => {
            const aiMessage: Message = {
                id: Date.now() + 1,
                type: 'ai',
                content: `I understand you want to: "${inputValue}"\n\nLet me help you with that. What specific details would you like to configure?`
            };
            setMessages(prev => [...prev, aiMessage]);
        }, 1000);
    };

    // Handle resize
    const handleMouseDown = (e: any) => {
        setIsResizing(true);
        resizeStartY.current = e.clientY;
        resizeStartHeight.current = panelHeight;
    };

    useEffect(() => {
        const handleMouseMove = (e: any) => {
            if (!isResizing) return;
            const delta = resizeStartY.current - e.clientY;
            const newHeight = Math.max(150, Math.min(500, resizeStartHeight.current + delta));
            setPanelHeight(newHeight);
        };

        const handleMouseUp = () => {
            setIsResizing(false);
        };

        if (isResizing) {
            document.addEventListener('mousemove', handleMouseMove);
            document.addEventListener('mouseup', handleMouseUp);
        }

        return () => {
            document.removeEventListener('mousemove', handleMouseMove);
            document.removeEventListener('mouseup', handleMouseUp);
        };
    }, [isResizing]);

    // const Stat: React.FC<StatProps> = ({ label, value, positive }) => (
    //     <div className="flex items-center gap-1 whitespace-nowrap">
    //         <span className="opacity-70 font-semibold">{label}:</span>
    //         <span
    //             className={`font-bold ${positive ? 'text-green-500' : 'text-red-500'
    //                 }`}
    //         >
    //             {value}
    //         </span>
    //     </div>
    // );

    // Update handleBrokerSelect 
    // const handleBrokerSelect = (brokerName: string) => {
    //     setSelectedBrokerName(brokerName);
    //     configRef.current.brokerName = brokerName;

    //     const broker = availableBrokers.find(b => b.brokerName === brokerName);

    //     if (broker) {
    //         // If broker has supported exchanges, show exchange selection
    //         if (broker.supportedExchanges && broker.supportedExchanges.length > 0) {
    //             const exchangeMessage: Message = {
    //                 id: Date.now(),
    //                 type: 'ai',
    //                 content: `**Great! You've selected ${brokerName} 🎯**\n\n${broker.description || 'Professional trading platform'}\n\nNow, please choose your exchange:`,
    //                 widget: {
    //                     type: 'radio',
    //                     data: {
    //                         options: broker.supportedExchanges.map(exchange => ({
    //                             value: exchange,
    //                             label: exchange,
    //                             description: exchange === 'NSE'
    //                                 ? 'National Stock Exchange'
    //                                 : exchange === 'BSE'
    //                                     ? 'Bombay Stock Exchange'
    //                                     : `${exchange} Exchange`
    //                         })),
    //                         onSelect: (exchange: string) => handleExchangeSelect(exchange)
    //                     }
    //                 }
    //             };
    //             setMessages(prev => [...prev, exchangeMessage]);
    //         } else {
    //             // If no supported exchanges, use default (NSE, BSE)
    //             const defaultExchangeMessage: Message = {
    //                 id: Date.now(),
    //                 type: 'ai',
    //                 content: `**Great! You've selected ${brokerName} 🎯**\n\n${broker.description || 'Professional trading platform'}\n\nThis broker supports all exchanges. Please choose your exchange:`,
    //                 widget: {
    //                     type: 'radio',
    //                     data: {
    //                         options: [
    //                             {
    //                                 value: 'NSE',
    //                                 label: 'NSE',
    //                                 description: 'National Stock Exchange'
    //                             },
    //                             {
    //                                 value: 'BSE',
    //                                 label: 'BSE',
    //                                 description: 'Bombay Stock Exchange'
    //                             }
    //                         ],
    //                         onSelect: (exchange: string) => handleExchangeSelect(exchange)
    //                     }
    //                 }
    //             };
    //             setMessages(prev => [...prev, defaultExchangeMessage]);
    //         }
    //     } else {
    //         console.error('Broker not found:', brokerName);
    //         console.error('Available broker names:', availableBrokers.map(b => b.brokerName));
    //     }
    // };

    // Update exchange selection handler
    const handleExchangeSelect = (exchange: string) => {
        setSelectedExchange(exchange);
        configRef.current.exchange = exchange;
        setStrategyConfig(prev => ({ ...prev, exchange }));

        const strategyTypeMessage: Message = {
            id: Date.now(),
            type: 'ai',
            content: `**Perfect! ${exchange} selected ✅**\n\nNow, how would you like to proceed with your strategy?`,
            widget: {
                type: 'radio',
                data: {
                    options: [
                        {
                            value: 'suggest',
                            label: 'Suggest me a strategy',
                            description: 'AI will analyze market conditions and recommend strategies'
                        },
                        {
                            value: 'own',
                            label: 'I will choose my own',
                            description: 'Select from your existing strategies'
                        }
                    ],
                    onSelect: (value: string) => handleStrategyTypeSelect(value)
                }
            }
        };
        setMessages(prev => [...prev, strategyTypeMessage]);
    };

    // Update strategy type selection handler
    const handleStrategyTypeSelect = (value: string) => {
        setSelectedStrategyType(value);
        configRef.current.strategyType = value;
        setStrategyConfig(prev => ({ ...prev, strategyType: value }));

        if (value === 'own') {
            const strategyListMessage: Message = {
                id: Date.now(),
                type: 'ai',
                content: '**Great choice! 📊**\n\nHere are your existing strategies. Select one to continue:',
                widget: {
                    type: 'strategy-list',
                    data: {
                        strategies: MOCK_USER_STRATEGIES,
                        onSelect: (strategyId: string) => handleStrategySelect(strategyId)
                    }
                }
            };
            setMessages(prev => [...prev, strategyListMessage]);
        } else {
            // For 'suggest', skip to position type
            setTimeout(() => askPositionType(), 500);
        }
    };

    // Update strategy selection handler
    const handleStrategySelect = (strategyId: string) => {
        setSelectedStrategy(strategyId);
        configRef.current.strategyId = strategyId;
        setStrategyConfig(prev => ({ ...prev, strategyId }));

        const strategy = MOCK_USER_STRATEGIES.find(s => s.id === strategyId);

        // Update strategy name in config and tab
        if (strategy) {
            configRef.current.strategyName = strategy.name;
            updateStrategyName(strategy.name);
        }

        const confirmMessage: Message = {
            id: Date.now(),
            type: 'ai',
            content: `**Excellent! You've selected "${strategy?.name}" ✅**\n\nPerformance: ${strategy?.performance}\n\nLet's configure the trading parameters.`
        };
        setMessages(prev => [...prev, confirmMessage]);

        setTimeout(() => askPositionType(), 500);
    };

    // Add this function here
    const askPositionType = () => {
        const positionTypeMessage: Message = {
            id: Date.now(),
            type: 'ai',
            content: '**What type of position would you like? 📈**\n\nChoose your trading style:',
            widget: {
                type: 'radio',
                data: {
                    options: [
                        {
                            value: 'INTRADAY',
                            label: 'Intraday',
                            description: 'Buy and sell on the same day. Positions auto-square off at market close.'
                        },
                        {
                            value: 'DELIVERY',
                            label: 'Delivery',
                            description: 'Hold positions for multiple days. Shares delivered to your demat account.'
                        }
                    ],
                    onSelect: (value: string) => handlePositionTypeSelect(value)
                }
            }
        };
        setMessages(prev => [...prev, positionTypeMessage]);
    };

    // Handle position type selection
    const handlePositionTypeSelect = (positionType: string) => {
        setSelectedPositionType(positionType);
        configRef.current.positionType = positionType;
        setStrategyConfig(prev => ({ ...prev, positionType }));

        const timeInForceMessage: Message = {
            id: Date.now(),
            type: 'ai',
            content: `**${positionType} selected! ⏱️**\n\nNow, set your Time in Force - how long should your orders stay active?`,
            widget: {
                type: 'radio',
                data: {
                    options: [
                        {
                            value: 'IOC',
                            label: 'IOC (Immediate-or-Cancel)',
                            description: 'Execute immediately at best price, cancel unfilled portion instantly.'
                        },
                        {
                            value: 'DAY',
                            label: 'DAY',
                            description: 'Order remains active until executed or until market close.'
                        }
                    ],
                    onSelect: (value: string) => handleTimeInForceSelect(value)
                }
            }
        };
        setMessages(prev => [...prev, timeInForceMessage]);
    };

    // Handle time in force selection
    const handleTimeInForceSelect = (timeInForce: string) => {
        handleFinalizeIndicators()
        setSelectedTimeInForce(timeInForce);
        // configRef.current.timeInForce = timeInForce;
        // setStrategyConfig(prev => ({ ...prev, timeInForce }));

        // const indicatorMessage: Message = {
        //     id: Date.now(),
        //     type: 'ai',
        //     content: `**Time in Force set to ${timeInForce}! 📊**\n\nNow, let's configure your technical indicators. Review and customize the parameters for each indicator:`,
        //     widget: {
        //         type: 'indicator-list',
        //         data: {
        //             indicators: indicatorConfigs,
        //             onConfigureParameters: () => handleFinalizeIndicators()
        //         }
        //     }
        // };
        // setMessages(prev => [...prev, indicatorMessage]);
    };

    // Update handleConfigureIndicator
    // const handleConfigureIndicator = (indicatorId: string) => {
    //     setCurrentConfigIndicatorId(indicatorId);
    //     setIsParameterModalOpen(true);
    // };

    // Update handleSaveIndicatorParameters
    const handleSaveIndicatorParameters = (indicatorId: string, parameters: Record<string, any>) => {
        setIndicatorConfigs(prev =>
            prev.map(ind =>
                ind.indicatorId === indicatorId
                    ? { ...ind, indicatorParameters: parameters }
                    : ind
            )
        );

        setIsParameterModalOpen(false);
        setCurrentConfigIndicatorId(null);
    };

    // Update handleCancelIndicatorConfig
    const handleCancelIndicatorConfig = () => {
        setIsParameterModalOpen(false);
        setCurrentConfigIndicatorId(null);
    };

    // Update handleFinalizeIndicators to ask for strategy parameters
    const handleFinalizeIndicators = () => {
        // All indicators are included with visible: true (since there's no toggle)
        const allIndicatorsConfig = indicatorConfigs.map(ind => ({
            ...ind,
            visible: true // All indicators are active by default
        }));

        configRef.current.indicators = allIndicatorsConfig;
        setStrategyConfig(prev => ({ ...prev, indicators: allIndicatorsConfig }));

        // Ask for strategy parameters
        const strategyParamsMessage: Message = {
            id: Date.now(),
            type: 'ai',
            content: `Now, let's set up your strategy parameters for risk management and trading rules:`,
            widget: {
                type: 'strategy-parameters',
                data: {
                    parameters: MOCK_STRATEGY_PARAMETERS,
                    onSave: (parameters: Record<string, any>) => handleSaveStrategyParameters(parameters)
                }
            }
        };
        setMessages(prev => [...prev, strategyParamsMessage]);
    };

    // Update handleSaveStrategyParameters to show risk management widget
    const handleSaveStrategyParameters = (parameters: Record<string, any>) => {
        configRef.current.strategyParameters = parameters;
        setStrategyConfig(prev => ({ ...prev, strategyParameters: parameters }));

        // Ask for risk management
        const riskManagementMessage: Message = {
            id: Date.now(),
            type: 'ai',
            content: `**Strategy Parameters Saved! ✅**\n\nNow, let's configure your risk management settings. These are mandatory safeguards to protect your capital:`,
            widget: {
                type: 'risk-management',
                data: {
                    onSave: (riskConfig: { maxPositionSize: number; maxDailyLoss: number }) =>
                    {
                        handleSaveRiskManagement(riskConfig);
                        handleSaveSymbols([]);
                    }
                }
            }
        };
        setMessages(prev => [...prev, riskManagementMessage]);
    };

    // Keep the handleSaveRiskManagement function as is
    const handleSaveRiskManagement = async (riskConfig: { maxPositionSize: number; maxDailyLoss: number }) => {
        configRef.current.riskManagement = riskConfig;
        setStrategyConfig(prev => ({ ...prev, riskManagement: riskConfig }));

        // Show loading message
        // const loadingMessage: Message = {
        //     id: Date.now(),
        //     type: 'ai',
        //     content: `**Risk Management Saved! ✅**\n\nFetching available symbols from exchange...`
        // };
        // setMessages(prev => [...prev, loadingMessage]);

        // Fetch symbols
        // try {
        //     setSymbolsLoading(true);
        //     // const symbolsData = await getAllSymbols();
        //     const symbolsData: any = mockSymbolMetaData
        //     setAvailableSymbols(symbolsData);

        //     // If there are pre-selected symbols in config, use them
        //     const preSelectedSymbols = configRef.current.filterSymbols || [];
        //     setSelectedSymbolsList(preSelectedSymbols);

        //     const symbolFilterMessage: Message = {
        //         id: Date.now(),
        //         type: 'ai',
        //         content: `**${symbolsData.length} Symbols Loaded! 🎯**\n\nSelect the symbols you want to trade with this strategy:`,
        //         widget: {
        //             type: 'symbol-filter',
        //             data: {
        //                 symbols: symbolsData,
        //                 selectedSymbols: preSelectedSymbols,
        //                 loading: false,
        //                 onToggle: (symbol: string) => handleSymbolToggle(symbol),
        //                 onSave: (selectedSymbols: string[]) => handleSaveSymbols(selectedSymbols)
        //             }
        //         }
        //     };
        //     setMessages(prev => [...prev, symbolFilterMessage]);
        // } catch (error) {
        //     console.error('Error fetching symbols:', error);
        //     const errorMessage: Message = {
        //         id: Date.now(),
        //         type: 'ai',
        //         content: `**Error loading symbols** ❌\n\nFailed to fetch symbols from exchange. Please try again or contact support.`
        //     };
        //     setMessages(prev => [...prev, errorMessage]);
        // } finally {
        //     setSymbolsLoading(false);
        // }
    };

    // const handleSymbolToggle = (tokenNumber: string) => {
    //     setSelectedSymbolsList(prev => {
    //         if (prev.includes(tokenNumber)) {
    //             return prev.filter(s => s !== tokenNumber);
    //         } else {
    //             return [...prev, tokenNumber];
    //         }
    //     });
    // };

    // Update handleSaveSymbols to accept empty array
    
    const handleSaveSymbols = (selectedTokens: string[]) => {
        configRef.current.filterSymbols = selectedTokens;
        setStrategyConfig(prev => ({ ...prev, filterSymbols: selectedTokens }));

        const finalConfig = configRef.current;
        console.log('Final Strategy Configuration with Symbols:', finalConfig);

        const strategyName = finalConfig.strategyId
            ? MOCK_USER_STRATEGIES.find(s => s.id === finalConfig.strategyId)?.name
            : 'AI Suggested';

        const totalIndicators = finalConfig.indicators.length;

        const summaryMessage: Message = {
            id: Date.now(),
            type: 'ai',
            content: `**${selectedTokens.length > 0 ? 'Symbols Saved!' : 'Proceeding with Entry Condition!'} ✅**\n\n**Configuration Summary:**\n• Broker: ${finalConfig.brokerName}\n• Exchange: ${finalConfig.exchange}\n• Strategy: ${strategyName}\n• Position Type: ${finalConfig.positionType}\n• Time in Force: ${finalConfig.timeInForce}\n• Indicators: ${totalIndicators} configured\n• ${selectedTokens.length > 0 ? `Symbols: ${selectedTokens.length} selected` : 'Symbol Filter: Using entry condition'}\n• Max Position Size: ₹${finalConfig.riskManagement.maxPositionSize?.toLocaleString()}\n• Max Daily Loss: ₹${finalConfig.riskManagement.maxDailyLoss?.toLocaleString()}\n\nYour strategy is ready to deploy!`,
            widget: {
                type: 'start-strategy',
                data: {
                    strategyConfig: finalConfig,
                    onStart: () => handleStartStrategy()
                }
            }
        };
        setMessages(prev => [...prev, summaryMessage]);
    };

    // Add this after handleSaveSymbols function
    const updateStrategyName = (name: string) => {
        const updatedStrategies = strategies.map((strategy, index) => {
            if (index === activeStrategy) {
                return { ...strategy, name: name };
            }
            return strategy;
        });
        setStrategies(updatedStrategies);
    };

    // Update handleStartStrategy to set isStrategyStarted
    // const handleStartStrategy = () => {
    //     const finalConfig = configRef.current;

    //     console.log('Starting Strategy with Config:', finalConfig);

    //     // Mark strategy as started
    //     setIsStrategyStarted(true);

    //     const successMessage: Message = {
    //         id: Date.now(),
    //         type: 'ai',
    //         content: `**🎉 Strategy Running Successfully! 🎉**\n\n**Status:** ✅ LIVE\n\nYour strategy has been deployed and is now actively monitoring the market!\n\n**Active Monitoring:**\n• ${finalConfig.filterSymbols.length > 0 ? `${finalConfig.filterSymbols.length} symbols being tracked` : 'All symbols matching entry conditions being tracked'}\n• ${finalConfig.indicators.length} technical indicators analyzing market\n• Risk limits enforced in real-time\n• All signals being processed\n\n**What's Happening Now:**\n✓ Connected to ${finalConfig.brokerName} (${finalConfig.exchange})\n✓ Scanning for entry signals\n✓ Monitoring ${finalConfig.positionType} positions\n✓ Risk management active\n\n**Safety Features:**\n🛡️ Max Position: ₹${finalConfig.riskManagement.maxPositionSize?.toLocaleString()}\n🛡️ Daily Loss Limit: ₹${finalConfig.riskManagement.maxDailyLoss?.toLocaleString()}\n\nYou can monitor your strategy's performance in real-time. Orders will be executed automatically based on your configured rules.\n\n**Need to make changes?** You can pause the strategy anytime from the control panel above.`
    //     };

    //     setMessages(prev => [...prev, successMessage]);

    //     // Update the active strategy status in the tabs
    //     setStrategies(prev =>
    //         prev.map((s, idx) =>
    //             idx === activeStrategy
    //                 ? { ...s, status: 'active' }
    //                 : s
    //         )
    //     );
    // };

    const handleStartStrategy = () => {
        const finalConfig = configRef.current;

        console.log('Starting Strategy with Config:', finalConfig);

        // Mark strategy as started
        setIsStrategyStarted(true);

        // Initial success message
        const successMessage: Message = {
            id: Date.now(),
            type: 'ai',
            content: `**🎉 Strategy Deployed Successfully! 🎉**\n\n**Status:** ✅ LIVE\n\nYour strategy is now active and monitoring the market...`
        };
        setMessages(prev => [...prev, successMessage]);

        // Update the active strategy status in the tabs
        setStrategies(prev =>
            prev.map((s, idx) =>
                idx === activeStrategy
                    ? { ...s, status: 'active' }
                    : s
            )
        );

        // Simulate live trading flow with realistic delays
        setTimeout(() => {
            const waitingMessage: Message = {
                id: Date.now(),
                type: 'ai',
                content: `⏳ **Waiting for entry condition to meet...**\n\nScanning market for signals based on your configured indicators.`
            };
            setMessages(prev => [...prev, waitingMessage]);
        }, 2000);

        setTimeout(() => {
            const entrySignalMessage: Message = {
                id: Date.now(),
                type: 'ai',
                content: `🎯 **Entry signal detected!**\n\nConditions met for ${finalConfig.filterSymbols.length > 0 ? 'selected symbol' : 'entry criteria'}.`
            };
            setMessages(prev => [...prev, entrySignalMessage]);
        }, 5000);

        setTimeout(() => {
            const positionOpenMessage: Message = {
                id: Date.now(),
                type: 'ai',
                content: `✅ **Position opened successfully!**\n\n📊 **Trade Details:**\n• Quantity: 10\n• Entry Price: ₹101.90\n• Position Value: ₹1,019.00\n• Stop Loss: ₹${(101.90 * (1 - (finalConfig.strategyParameters?.stopLossPercentage || 1.5) / 100)).toFixed(2)}\n• Target: ₹${(101.90 * (1 + (finalConfig.strategyParameters?.takeProfitPercentage || 3) / 100)).toFixed(2)}`
            };
            setMessages(prev => [...prev, positionOpenMessage]);
        }, 7000);

        setTimeout(() => {
            const monitoringMessage: Message = {
                id: Date.now(),
                type: 'ai',
                content: `👀 **Monitoring position...**\n\nWaiting for profit target or stop loss to trigger.`
            };
            setMessages(prev => [...prev, monitoringMessage]);
        }, 10000);

        setTimeout(() => {
            const targetReachedMessage: Message = {
                id: Date.now(),
                type: 'ai',
                content: `🎊 **Great! We reached our target!**\n\n✨ Target price of ₹${(101.90 * (1 + (finalConfig.strategyParameters?.takeProfitPercentage || 3) / 100)).toFixed(2)} achieved!`
            };
            setMessages(prev => [...prev, targetReachedMessage]);
        }, 15000);

        setTimeout(() => {
            const exitingMessage: Message = {
                id: Date.now(),
                type: 'ai',
                content: `🔄 **Trying to exit position...**\n\nPlacing exit order at market price.`
            };
            setMessages(prev => [...prev, exitingMessage]);
        }, 17000);

        setTimeout(() => {
            const exitedMessage: Message = {
                id: Date.now(),
                type: 'ai',
                content: `✅ **Successfully exited!**\n\n📊 **Exit Details:**\n• Quantity: 10\n• Exit Price: ₹105.90\n• Exit Value: ₹1,059.00`
            };
            setMessages(prev => [...prev, exitedMessage]);
        }, 19000);

        setTimeout(() => {
            const profitMessage: Message = {
                id: Date.now(),
                type: 'ai',
                content: `💰 **Trade Summary**\n\n**Profit Breakdown:**\n• Entry: 10 @ ₹101.90 = ₹1,019.00\n• Exit: 10 @ ₹105.90 = ₹1,059.00\n• **Gross Profit: ₹40.00**\n• Brokerage & Taxes: ₹8.00\n• **Net Profit: ₹32.00** 🎉\n\n${finalConfig.strategyParameters?.reEntryEnabled ? '**Re-entry is enabled.** Do you want to re-run this strategy?' : 'Strategy will continue monitoring for new signals.'}`
            };
            setMessages(prev => [...prev, profitMessage]);
        }, 21000);

        if (finalConfig.strategyParameters?.reEntryEnabled) {
            setTimeout(() => {
                const reRunMessage: Message = {
                    id: Date.now(),
                    type: 'ai',
                    content: `🔄 **Trade Completed Successfully!**\n\nWould you like to continue running the strategy?`,
                    widget: {
                        type: 're-run-confirmation',
                        data: {
                            profit: 32.00,
                            onConfirm: () => handleReRun(),
                            onStop: () => handleStopStrategy()
                        }
                    }
                };
                setMessages(prev => [...prev, reRunMessage]);
            }, 23000);
        }

        // Add handlers
        const handleReRun = () => {
            const confirmMessage: Message = {
                id: Date.now(),
                type: 'ai',
                content: `✅ **Strategy continues...**\n\nMonitoring market for next entry signal.`
            };
            setMessages(prev => [...prev, confirmMessage]);
        };

        const handleStopStrategy = () => {
            setIsStrategyStarted(false);
            setStrategies(prev =>
                prev.map((s, idx) =>
                    idx === activeStrategy
                        ? { ...s, status: 'inactive' }
                        : s
                )
            );

            const stopMessage: Message = {
                id: Date.now(),
                type: 'ai',
                content: `⏹️ **Strategy Stopped**\n\nYour strategy has been stopped successfully. Final profit: ₹32.00`
            };
            setMessages(prev => [...prev, stopMessage]);
        };
    };

    useEffect(() => {
        // Ensure activeStrategy index is valid
        if (activeStrategy >= strategies.length) {
            setActiveStrategy(Math.max(0, strategies.length - 1));
        }
    }, [strategies.length, activeStrategy]);


    return (
        <div className={`h-full flex flex-col ${darkMode ? 'bg-gray-900' : 'bg-white'}`}>

            {strategies[activeStrategy] && (
                <TopSection
                    darkMode={darkMode}
                    strategies={strategies}
                    activeStrategy={activeStrategy}
                    setActiveStrategy={setActiveStrategy}
                    setStrategies={setStrategies}
                    selectedBroker={selectedBroker}
                    configRef={configRef}
                    isStrategyInfoOpen={isStrategyInfoOpen}
                    setIsStrategyInfoOpen={setIsStrategyInfoOpen}
                    currentStrategyId={currentStrategyId}
                    setCurrentStrategyId={setCurrentStrategyId}
                />
            )}

            {/* Main Content Area: Chat + Watchlist */}
            <div className="flex-1 flex overflow-hidden max-h-[75vh]">
                <ChatArea
                    messages={messages}
                    inputValue={inputValue}
                    setInputValue={setInputValue}
                    handleSend={handleSend}
                    isPanelVisible={isPanelVisible}
                    setIsPanelVisible={setIsPanelVisible}
                    activeTab={activeTab}
                    setActiveTab={setActiveTab}
                    panelHeight={panelHeight}
                    handleMouseDown={handleMouseDown}
                    selectedStrategyType={selectedStrategyType}
                    selectedExchange={selectedExchange}
                    selectedPositionType={selectedPositionType}
                    selectedTimeInForce={selectedTimeInForce}
                    selectedBrokerName={selectedBrokerName}
                    selectedStrategy={selectedStrategy}
                    brokersLoading={brokersLoading}
                    selectedSymbolsList={selectedSymbolsList}
                    handleFinalizeIndicators={handleFinalizeIndicators}
                />

                <RightSidebar
                    darkMode={darkMode}
                    isStrategyStarted={isStrategyStarted}
                    config={configRef.current}
                    availableSymbols={availableSymbols}
                    watchlist={WATCHLIST}
                />
            </div>

            <Modal
                isOpen={isParameterModalOpen}
                onClose={handleCancelIndicatorConfig}
                title={currentConfigIndicatorId ? indicatorConfigs.find(ind => ind.indicatorId === currentConfigIndicatorId)?.indicatorName : ''}
            >
                {currentConfigIndicatorId && (() => {
                    // Get the latest indicator from indicatorConfigs state
                    const indicator = indicatorConfigs.find(ind => ind.indicatorId === currentConfigIndicatorId);
                    return indicator ? (
                        <IndicatorParameterWidget
                            indicator={indicator}
                            onSave={handleSaveIndicatorParameters}
                            onCancel={handleCancelIndicatorConfig}
                        />
                    ) : null;
                })()}
            </Modal>
        </div>
    );
} 