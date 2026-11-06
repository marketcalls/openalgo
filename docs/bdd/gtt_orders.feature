Feature: GTT orders
  GTT APIs are available through RESTX and depend on broker-specific GTT modules.

  # Source: restx_api/place_gtt_order.py:25, services/place_gtt_order_service.py:34
  Scenario Outline: Live GTT uses each implemented broker GTT API
    Given the active broker is "<broker>"
    And analyzer mode is disabled
    When an API client submits a place GTT request
    Then the request is validated
    And the broker GTT placement API is called

    Examples:
      | broker |
      | angel |
      | dhan |
      | fyers |
      | rupeezy |
      | upstox |
      | zerodha |

  # Source: services/place_gtt_order_service.py:63
  Scenario: Place GTT rejects a broker without a GTT module
    Given the active broker has no broker-specific GTT module
    And analyzer mode is disabled
    When an API client submits a place GTT request
    Then the service returns HTTP 501
    And no unsupported broker order API is called

  # Source: restx_api/cancel_gtt_order.py:25, services/cancel_gtt_order_service.py:132
  Scenario: Cancel GTT is blocked in semi-auto live mode
    Given the API key is configured for semi-auto mode
    And analyzer mode is disabled
    When an API client submits a cancel GTT request
    Then the service blocks the request
    And the broker cancel GTT API is not called

  # Source: restx_api/gtt_orderbook.py:22, services/gtt_orderbook_service.py:13
  Scenario: GTT orderbook depends on broker GTT support
    Given a broker session is active
    And analyzer mode is disabled
    When an API client requests the GTT orderbook
    Then the service imports the broker GTT API
    And a missing broker GTT module produces a not implemented response

  # Source: services/place_gtt_order_service.py:92, services/modify_gtt_order_service.py:51, services/cancel_gtt_order_service.py:50, services/gtt_orderbook_service.py:26, sandbox/gtt_manager.py
  Scenario Outline: Analyzer mode routes GTT operations to the sandbox
    Given analyzer mode is enabled
    When the client requests "<operation>"
    Then the GTT service dispatches to the sandbox GTT manager instead of the broker
    And the response carries mode "analyze"

    Examples:
      | operation |
      | place |
      | modify |
      | cancel |
      | orderbook |

  # Source: sandbox/gtt_manager.py, sandbox/execution_engine.py
  Scenario: Active sandbox GTT fires against live market data
    Given an active sandbox GTT has valid live LTP data
    When its trigger condition is met
    Then the sandbox GTT manager places its sandbox order
    And no live broker order is submitted
