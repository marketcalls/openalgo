export type StatProps = {
    label: string;
    value: string | number;
    positive?: boolean;
};

export interface RadioOption {
    value: string;
    label: string;
    description?: string;
}

export interface RadioWidgetData {
    type: 'radio';
    data: {
        options: RadioOption[];
        onSelect: (value: string) => void;
    };
}

export interface Strategy {
    id: string;
    name: string;
    description: string;
    performance: string;
    status: 'active' | 'inactive';
}

export interface StrategyListWidgetData {
    type: 'strategy-list';
    data: {
        strategies: Strategy[];
        onSelect: (strategyId: string) => void;
    };
}


export interface BrokerListWidgetData {
    type: 'broker-list';
    data: {
        brokers: BrokerInfo[];
        onSelect: (brokerName: string) => void;
    };
}

export interface Message {
    id: number;
    type: 'user' | 'ai';
    content: string;
    widget?: WidgetData;
}

// Strategy Configuration State
export interface StrategyConfig {
    brokerName: string | null;
    exchange: string | null;
    strategyType: string | null; // 'suggest' or 'own'
    strategyId: string | null;
    positionType: string | null; // 'INTRADAY' or 'DELIVERY'
    timeInForce: string | null; // 'IOC' or 'DAY'
    strategyName: string | null;
}


export interface IndicatorConfig {
    userId: string;
    indicatorPurpose: string;
    indicatorType: string;
    indicatorId: string;
    indicatorName: string;
    inputTypeDescription: string;
    outputTypeDescription: string;
    dataGranularityDescription: string;
    calculationDescription: string;
    signalDescription: string;
    indicatorDescription: string;
    visible: boolean;
    indicatorParameters: Record<string, any>;
}


export interface IndicatorParameterWidgetData {
    type: 'indicator-parameters';
    data: {
        indicator: IndicatorConfig;
        onSave: (indicatorId: string, parameters: Record<string, any>) => void;
        onCancel: () => void;
    };
}

// Update StrategyConfig
export interface StrategyConfig {
    brokerName: string | null;
    exchange: string | null;
    strategyType: string | null;
    strategyId: string | null;
    positionType: string | null;
    timeInForce: string | null;
    indicators: IndicatorConfig[];
}

export interface StrategyParameter {
    key: string;
    label: string;
    value: any;
    type: 'number' | 'text' | 'boolean' | 'select';
    options?: string[]; // For select type
    description?: string;
    min?: number;
    max?: number;
}

export interface StrategyParametersWidgetData {
    type: 'strategy-parameters';
    data: {
        parameters: StrategyParameter[];
        onSave: (parameters: Record<string, any>) => void;
    };
}

// Update StrategyConfig
export interface StrategyConfig {
    brokerName: string | null;
    exchange: string | null;
    strategyType: string | null;
    strategyId: string | null;
    positionType: string | null;
    timeInForce: string | null;
    indicators: IndicatorConfig[];
    strategyParameters: Record<string, any>;
}


export interface RiskManagementWidgetData {
    type: 'risk-management';
    data: {
        onSave: (riskConfig: { maxPositionSize: number; maxDailyLoss: number }) => void;
    };
}

// Update StrategyConfig
export interface StrategyConfig {
    brokerName: string | null;
    exchange: string | null;
    strategyType: string | null;
    strategyId: string | null;
    positionType: string | null;
    timeInForce: string | null;
    indicators: IndicatorConfig[];
    strategyParameters: Record<string, any>;
    riskManagement: {
        maxPositionSize: number | null;
        maxDailyLoss: number | null;
    };
}


export interface SymbolMetaData {
    tokenNumber: string;
    isn: string;
    symbolName: string;
    series: string;
    expiry: string | null;
    upperPrice: number;
    lowerPrice: number;
    tickSize: number;
    lotSize: number;
    strikePrice: number;
    exchange: string;
    segment: string;
}


export interface SymbolFilterWidgetData {
    type: 'symbol-filter';
    data: {
        symbols: SymbolMetaData[];
        selectedSymbols: string[];
        loading: boolean;
        onToggle: (symbol: string) => void;
        onSave: (selectedSymbols: string[]) => void;
    };
}


// Update StrategyConfig
export interface StrategyConfig {
    brokerName: string | null;
    exchange: string | null;
    strategyType: string | null;
    strategyId: string | null;
    positionType: string | null;
    timeInForce: string | null;
    indicators: IndicatorConfig[];
    strategyParameters: Record<string, any>;
    riskManagement: {
        maxPositionSize: number | null;
        maxDailyLoss: number | null;
    };
    filterSymbols: string[];
}

export interface StartStrategyWidgetData {
    type: 'start-strategy';
    data: {
        strategyConfig: StrategyConfig;
        onStart: () => void;
    };
}

export interface BrokerInfo {
    brokerId: number;
    brokerName: string;
    brokerCode: string | null;
    icon: string | null;
    description: string | null;
    supportedExchanges: string[];
    active: boolean | null;
}

export interface IndicatorListWidgetData {
    type: 'indicator-list';
    data: {
        indicators: IndicatorConfig[];
        onConfigureParameters: (indicatorId: string) => void;
    };
}

export interface SymbolFilterWidgetData {
    type: 'symbol-filter';
    data: {
        symbols: SymbolMetaData[];
        selectedSymbols: string[];
        loading: boolean;
        onToggle: (symbol: string) => void;
        onSave: (selectedSymbols: string[]) => void; // Can accept empty array
    };
}

export interface ReRunConfirmationWidgetData {
    type: 're-run-confirmation';
    data: {
        profit: number;
        onConfirm: () => void;
        onStop: () => void;
    };
}

export type WidgetData = 
    | RadioWidgetData 
    | StrategyListWidgetData 
    | BrokerListWidgetData 
    | IndicatorListWidgetData
    | IndicatorParameterWidgetData
    | StrategyParametersWidgetData
    | RiskManagementWidgetData
    | SymbolFilterWidgetData
    | StartStrategyWidgetData
    | ReRunConfirmationWidgetData;