Feature: Account state, margin, and market depth
  Account APIs use the active broker in live mode and the sandbox managers where analyzer behavior is supported.

  # Source: restx_api/funds.py:24, restx_api/orderbook.py:23, restx_api/tradebook.py:23, restx_api/positionbook.py:23, restx_api/holdings.py:23
  Scenario Outline: Account collection endpoint authenticates the API key
    Given an API client submits an OpenAlgo API key
    When it posts to "<path>"
    Then the corresponding account service verifies or resolves the active session
    And the result uses the normalized wrapper response

    Examples:
      | path |
      | /api/v1/funds |
      | /api/v1/orderbook |
      | /api/v1/tradebook |
      | /api/v1/positionbook |
      | /api/v1/holdings |

  # Source: restx_api/margin.py:24, restx_api/schemas.py:317
  Scenario: Margin request validates every proposed position
    Given a margin request contains one or more positions
    When symbol, exchange, action, product, price type, or quantity is invalid
    Then schema validation rejects the request
    And valid positions are sent to the active broker margin service

  # Source: services/funds_service.py:20, services/positionbook_service.py:20, services/holdings_service.py:20
  Scenario: Analyzer mode routes supported account reads to sandbox state
    Given analyzer mode is enabled
    When funds, positions, or holdings are requested
    Then the response comes from the sandbox managers
    And the live broker account module is not called

  # Source: restx_api/openposition.py:25, services/openposition_service.py:24
  Scenario: Open-position lookup is scoped by symbol exchange and product
    Given a request includes strategy, symbol, exchange, and product
    When open position is requested
    Then those fields identify the position to inspect
    And analyzer and live mode use their respective position sources

  # Source: restx_api/depth.py:23, services/depth_service.py:13
  Scenario: REST depth returns a broker snapshot
    Given a valid symbol and exchange are submitted
    When market depth is requested
    Then the service returns the current normalized depth snapshot
    And continuous updates require a WebSocket Depth subscription
