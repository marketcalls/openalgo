# Enhanced Trade Management Tool - Requirements Document

## Introduction

This document outlines the requirements for enhancing OpenAlgo's trade management capabilities with a comprehensive dual-level risk management system. The enhancement will transform OpenAlgo from a simple order execution platform into a professional-grade trading system with automated risk management at both individual trade and portfolio levels.

The system will provide real-time monitoring of active trades, automatic execution of stop-loss and target orders, trailing stop-loss functionality, and portfolio-level risk controls. This will enable traders to implement sophisticated risk management strategies while maintaining the platform's ease of use.

## Requirements

### Requirement 1: Individual Trade Risk Management

**User Story:** As a trader, I want to set stop-loss and target levels for each individual trade, so that I can automatically exit positions when my risk or profit objectives are met.

#### Acceptance Criteria

1. WHEN a trader places an order THEN the system SHALL allow setting individual stop-loss percentage or points below entry price
2. WHEN a trader places an order THEN the system SHALL allow setting individual target percentage or points above entry price
3. WHEN the market price hits the individual stop-loss level THEN the system SHALL automatically place a market exit order for that specific trade
4. WHEN the market price hits the individual target level THEN the system SHALL automatically place a market exit order for that specific trade
5. WHEN an individual trade is exited THEN the system SHALL update the trade status and calculate realized P&L
6. WHEN a trader views active trades THEN the system SHALL display current stop-loss and target levels for each position

### Requirement 2: Trailing Stop-Loss Functionality

**User Story:** As a trader, I want trailing stop-loss functionality for my trades, so that I can protect profits while allowing positions to continue running in favorable directions.

#### Acceptance Criteria

1. WHEN a trader enables trailing stop-loss for a trade THEN the system SHALL track the highest price (for long positions) or lowest price (for short positions)
2. WHEN the market moves favorably THEN the system SHALL automatically adjust the stop-loss level by the specified trailing amount
3. WHEN the trailing stop-loss is triggered THEN the system SHALL place an immediate market exit order
4. WHEN the market moves against the position THEN the system SHALL NOT adjust the trailing stop-loss level
5. WHEN a trader views active trades THEN the system SHALL display the current trailing stop-loss level
6. WHEN trailing stop-loss is enabled THEN the system SHALL support both percentage and points-based trailing

### Requirement 3: Portfolio-Level Risk Management

**User Story:** As a trader, I want portfolio-level risk controls for my entire strategy, so that I can limit overall losses and lock in profits across all positions simultaneously.

#### Acceptance Criteria

1. WHEN a strategy has portfolio stop-loss enabled THEN the system SHALL monitor total unrealized P&L across all active trades
2. WHEN total portfolio P&L hits the portfolio stop-loss level THEN the system SHALL immediately close ALL active positions in the strategy
3. WHEN a strategy has portfolio target enabled THEN the system SHALL monitor total unrealized P&L for profit-taking
4. WHEN total portfolio P&L hits the portfolio target level THEN the system SHALL immediately close ALL active positions in the strategy
5. WHEN portfolio trailing stop-loss is enabled THEN the system SHALL track the highest portfolio P&L and adjust the stop-loss level accordingly
6. WHEN portfolio-level exits are triggered THEN the system SHALL log the reason and update all affected trades

### Requirement 4: Fund Allocation and Position Sizing

**User Story:** As a trader, I want to allocate specific capital to each strategy and control position sizing, so that I can manage risk and capital deployment professionally.

#### Acceptance Criteria

1. WHEN creating or editing a strategy THEN the system SHALL allow setting allocated funds amount
2. WHEN placing trades THEN the system SHALL calculate position size based on the configured method (fixed quantity, fixed value, or percentage allocation)
3. WHEN using percentage allocation THEN the system SHALL calculate trade size as a percentage of available allocated funds
4. WHEN using fixed value THEN the system SHALL calculate quantity based on current market price to achieve the target trade value
5. WHEN maximum open positions limit is reached THEN the system SHALL prevent new trade entries
6. WHEN daily loss limit is exceeded THEN the system SHALL prevent new trade entries for the day

### Requirement 5: Real-Time Market Data Integration

**User Story:** As a trader, I want real-time price monitoring for my active trades, so that stop-loss and target conditions are evaluated immediately when market conditions change.

#### Acceptance Criteria

1. WHEN a trade becomes active THEN the system SHALL automatically subscribe to real-time price feeds for that symbol
2. WHEN real-time price updates are received THEN the system SHALL evaluate all stop-loss and target conditions within 100 milliseconds
3. WHEN WebSocket connection is lost THEN the system SHALL automatically reconnect and restore subscriptions
4. WHEN the application restarts THEN the system SHALL recover all active trade monitoring from the database
5. WHEN no active trades exist for a symbol THEN the system SHALL unsubscribe from that symbol's price feed
6. WHEN multiple trades exist for the same symbol THEN the system SHALL use a single subscription to optimize performance

### Requirement 6: Trade Monitoring Dashboard

**User Story:** As a trader, I want a comprehensive dashboard to monitor all my active trades and portfolio performance, so that I can track my positions and risk levels in real-time.

#### Acceptance Criteria

1. WHEN viewing the trade dashboard THEN the system SHALL display portfolio-level P&L, allocated funds, and active trade count
2. WHEN viewing active trades THEN the system SHALL show symbol, quantity, entry price, current LTP, unrealized P&L, stop-loss level, and target level
3. WHEN prices update THEN the system SHALL refresh the dashboard with live P&L calculations
4. WHEN portfolio risk levels are approached THEN the system SHALL display warning indicators
5. WHEN individual or portfolio exits occur THEN the system SHALL show real-time alerts with exit details
6. WHEN viewing trade history THEN the system SHALL display completed trades with entry/exit prices, P&L, and exit reasons

### Requirement 7: Strategy Configuration Interface

**User Story:** As a trader, I want to configure risk management settings at the strategy level, so that all trades within that strategy automatically inherit the appropriate risk controls.

#### Acceptance Criteria

1. WHEN creating or editing a strategy THEN the system SHALL provide toggles for enabling individual stop-loss, target, and trailing stop-loss
2. WHEN individual risk controls are enabled THEN the system SHALL allow setting default percentages or points values
3. WHEN creating or editing a strategy THEN the system SHALL provide toggles for enabling portfolio-level stop-loss, target, and trailing stop-loss
4. WHEN portfolio risk controls are enabled THEN the system SHALL allow setting values in absolute amounts or percentages of allocated funds
5. WHEN fund allocation is configured THEN the system SHALL provide options for position sizing methods
6. WHEN risk settings are saved THEN the system SHALL validate that all values are within reasonable ranges

### Requirement 8: Safety and Recovery Features

**User Story:** As a trader, I want the system to handle failures gracefully and protect my active trades, so that monitoring continues even during system restarts or network issues.

#### Acceptance Criteria

1. WHEN the application starts THEN the system SHALL recover all active trades from the database and restore monitoring
2. WHEN WebSocket connections fail THEN the system SHALL implement exponential backoff reconnection with subscription restoration
3. WHEN attempting to delete a strategy with active trades THEN the system SHALL warn the user and provide options to close positions or transfer trades
4. WHEN database writes fail THEN the system SHALL continue monitoring in memory and retry database operations
5. WHEN broker API calls fail THEN the system SHALL implement retry logic with appropriate delays
6. WHEN system crashes occur THEN all trade states SHALL be preserved in the database for recovery

### Requirement 9: API Integration and Automation

**User Story:** As a developer or advanced trader, I want REST API endpoints for trade management, so that I can integrate with external systems or build custom interfaces.

#### Acceptance Criteria

1. WHEN calling the create trade API THEN the system SHALL accept order ID and risk parameters to enable monitoring
2. WHEN calling the update trade API THEN the system SHALL allow modification of stop-loss, target, and trailing stop-loss levels
3. WHEN calling the active trades API THEN the system SHALL return all active trades with current status and P&L
4. WHEN calling the exit trade API THEN the system SHALL immediately close the specified position
5. WHEN calling the trade history API THEN the system SHALL return completed trades with filtering options
6. WHEN API authentication fails THEN the system SHALL return appropriate error codes and messages

### Requirement 10: Performance and Scalability

**User Story:** As a trader with multiple active positions, I want the system to handle high-frequency price updates efficiently, so that my trades are monitored without performance degradation.

#### Acceptance Criteria

1. WHEN processing price updates THEN the system SHALL handle at least 1000 price ticks per second without delays
2. WHEN multiple trades exist for the same symbol THEN the system SHALL batch process all related trades in a single operation
3. WHEN database operations are required THEN the system SHALL use connection pooling and prepared statements
4. WHEN memory usage grows THEN the system SHALL implement cleanup of completed trades and old data
5. WHEN concurrent users access the system THEN the system SHALL maintain response times under 200ms for dashboard updates
6. WHEN system load increases THEN the system SHALL gracefully degrade non-critical features while maintaining core monitoring