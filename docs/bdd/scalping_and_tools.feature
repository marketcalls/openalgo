Feature: Scalping terminal and current analytics tools
  The scalping terminal combines session-authenticated discovery, execution, streaming, and server-side risk controls.

  # Source: blueprints/scalping.py:267, blueprints/scalping.py:299, blueprints/scalping.py:432
  Scenario: Scalping instrument discovery resolves underlyings expiries and strikes
    Given a session user has an OpenAlgo API key
    When the terminal selects an F&O exchange and underlying
    Then available expiries and an ATM-centered chain can be returned
    And MCX or CDS can use the current-month future as the underlying reference

  # Source: blueprints/scalping.py:619, blueprints/scalping.py:69
  Scenario: Scalping order entry enforces server-side quantity rails
    Given a scalping order request is session authenticated
    When the action, exchange, product, quantity, or lot multiple is invalid
    Then the server rejects the order before execution
    And manual clicks are capped at 20 lots and 100000 units

  # Source: blueprints/scalping.py:713, blueprints/scalping.py:787, blueprints/scalping.py:825
  Scenario: Scalping exits can only reduce existing exposure
    Given one or more tracked positions are open
    When a leg or all legs are closed
    Then the exit action is derived from the current position side
    And the requested exit cannot increase exposure

  # Source: database/scalping_db.py:40, database/scalping_db.py:238, blueprints/scalping.py:922
  Scenario: Stop and trailing-stop state persists by mode and leg
    Given a live or analyzer position has a stop configuration
    When the stop state is saved
    Then it is keyed by symbol, exchange, product, and mode
    And malformed or non-reducible stop state is rejected

  # Source: services/scalping_risk_monitor_service.py:107, services/scalping_risk_monitor_service.py:618
  Scenario: Server risk monitor remains active after the browser leaves
    Given an active stop or target is stored
    When market-data ticks arrive after the scalping page closes
    Then the singleton monitor evaluates stop target and trailing behavior
    And a breach submits a freeze-safe risk-reducing exit

  # Source: frontend/src/pages/Scalping.tsx:49, frontend/src/pages/Scalping.tsx:121
  Scenario: Scalping charts are opt-in and browser-persisted
    Given no chart preference has been stored
    When the scalping terminal opens
    Then live charts are off by default
    And the chart toggle and 1m 5m or 15m timeframe persist in local storage

  # Source: blueprints/arbitrage.py:24, services/arbitrage_service.py:19
  Scenario: Arbitrage tool builds a futures calendar-spread universe
    Given a session user selects one or more supported derivative exchanges
    When the arbitrage universe is requested
    Then near and later futures contracts are paired by underlying
    And the response includes a de-duplicated WebSocket subscription list

  # Source: blueprints/gamma_density.py:28, services/gamma_density_service.py:17, frontend/src/pages/OIRange.tsx:1
  Scenario: Gamma Density and OI Range derive views from option-chain data
    Given an underlying exchange and DDMMMYY expiry are valid
    When gamma density or OI range is opened
    Then Gamma Density returns gamma-times-OI and convexity-zone data
    And OI Range applies its strike-range view to option-chain data
