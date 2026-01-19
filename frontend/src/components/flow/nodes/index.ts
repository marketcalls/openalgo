// components/flow/nodes/index.ts
// Export all node components and types
// Currently using BaseNode as placeholder for all node types
// Specific node components will be added in Phase 6

import { BaseNode } from './BaseNode'

// All node types map to BaseNode for now
// Will be replaced with specific implementations in Phase 6
export const nodeTypes = {
  // Triggers
  start: BaseNode,
  priceAlert: BaseNode,
  webhookTrigger: BaseNode,
  httpRequest: BaseNode,

  // Order Actions
  placeOrder: BaseNode,
  smartOrder: BaseNode,
  optionsOrder: BaseNode,
  optionsMultiOrder: BaseNode,
  basketOrder: BaseNode,
  splitOrder: BaseNode,
  modifyOrder: BaseNode,
  cancelOrder: BaseNode,
  cancelAllOrders: BaseNode,
  closePositions: BaseNode,

  // Conditions
  timeCondition: BaseNode,
  positionCheck: BaseNode,
  fundCheck: BaseNode,
  priceCondition: BaseNode,
  timeWindow: BaseNode,

  // Logic Gates
  andGate: BaseNode,
  orGate: BaseNode,
  notGate: BaseNode,

  // Market Data
  getQuote: BaseNode,
  getDepth: BaseNode,
  history: BaseNode,
  multiQuotes: BaseNode,
  symbol: BaseNode,
  expiry: BaseNode,

  // Options Data
  optionSymbol: BaseNode,
  optionChain: BaseNode,
  syntheticFuture: BaseNode,
  optionGreeks: BaseNode,

  // Order/Position Info
  getOrderStatus: BaseNode,
  openPosition: BaseNode,
  orderBook: BaseNode,
  tradeBook: BaseNode,
  positionBook: BaseNode,

  // WebSocket Streaming
  subscribeLtp: BaseNode,
  subscribeQuote: BaseNode,
  subscribeDepth: BaseNode,
  unsubscribe: BaseNode,

  // Risk Management
  holdings: BaseNode,
  funds: BaseNode,
  margin: BaseNode,

  // Calendar
  holidays: BaseNode,
  timings: BaseNode,

  // Utilities
  variable: BaseNode,
  mathExpression: BaseNode,
  log: BaseNode,
  telegramAlert: BaseNode,
  delay: BaseNode,
  waitUntil: BaseNode,
  group: BaseNode,
}

export { BaseNode }
