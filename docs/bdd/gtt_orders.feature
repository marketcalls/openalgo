Feature: GTT orders
  GTT APIs are available through RESTX and depend on broker-specific GTT modules.

  # Source: restx_api/place_gtt_order.py:25, services/place_gtt_order_service.py:34
  Scenario: Place GTT uses broker GTT API when available
    Given the active broker has a GTT module
    When an API client submits a place GTT request
    Then the request is validated
    And the broker GTT placement API is called

  # Source: restx_api/modify_gtt_order.py:25, services/modify_gtt_order_service.py:51
  Scenario: Modify GTT returns analyzer unsupported in analyzer mode
    Given analyzer mode is enabled
    When an API client submits a modify GTT request
    Then the service returns an unsupported response
    And no broker GTT module is called

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
    When an API client requests the GTT orderbook
    Then the service imports the broker GTT API
    And a missing broker GTT module produces a not implemented response
