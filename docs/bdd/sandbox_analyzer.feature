Feature: Analyzer and sandbox mode
  Analyzer mode routes supported trading and account calls to sandbox services.

  # Source: restx_api/analyzer.py:28, database/settings_db.py:82
  Scenario: Analyzer status can be queried through RESTX
    Given the application is running
    When an API client requests analyzer status
    Then the response reflects the persisted analyzer setting
    And the setting is read from the settings database

  # Source: restx_api/analyzer.py:63, blueprints/settings.py:17
  Scenario: Analyzer mode can be toggled
    Given a user or API client is authorized
    When analyzer toggle is requested
    Then the setting is updated
    And settings routes can expose the same mode state

  # Source: blueprints/sandbox.py:96, services/sandbox_service.py:25
  Scenario: Sandbox dashboard reads sandbox trading state
    Given analyzer mode has generated sandbox activity
    When the sandbox dashboard is requested
    Then sandbox orders, trades, positions, holdings, or funds can be shown
    And sandbox service calls verify the API key

  # Source: blueprints/sandbox.py:455, database/sandbox_db.py:406
  Scenario: Sandbox configuration uses default trading parameters
    Given sandbox configuration has not been customized
    When config is read or reset
    Then default capital, intervals, square-off times, leverage, and GTT config are available

  # Source: restx_api/place_order.py:25, services/place_order_service.py:148
  Scenario: Analyzer mode routes order placement to sandbox
    Given analyzer mode is enabled
    When an API client places an order
    Then the live broker order API is bypassed
    And sandbox order placement handles the request
