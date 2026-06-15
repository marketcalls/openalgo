Feature: Automation webhooks and Python strategies
  External automation routes convert webhook or strategy events into OpenAlgo actions.

  # Source: blueprints/chartink.py:787, blueprints/chartink.py:67
  Scenario: Chartink webhook queues regular or smart orders
    Given a Chartink strategy is active
    When a webhook payload arrives with an action keyword
    Then symbols are mapped
    And the request is queued through the Chartink rate-limited workers

  # Source: blueprints/strategy.py:871, blueprints/strategy.py:87
  Scenario: Strategy webhook validates mode and trading hours
    Given a saved strategy has mappings and an API key
    When a webhook request arrives
    Then strategy mode and trading windows are validated
    And order payloads are queued if allowed

  # Source: blueprints/tv_json.py:22, restx_api/place_order.py:25
  Scenario: TradingView JSON route accepts order automation payloads
    Given an external client sends a TradingView JSON request
    When the payload maps to an OpenAlgo action
    Then the route can call the same order API behavior used by RESTX order placement

  # Source: blueprints/gc_json.py:22, restx_api/place_order.py:25
  Scenario: GoCharting route accepts order automation payloads
    Given an external client sends a GoCharting request
    When the payload maps to an OpenAlgo action
    Then the route can call OpenAlgo order placement behavior

  # Source: blueprints/python_strategy.py:1761, blueprints/python_strategy.py:1907
  Scenario: Python Strategy can start and schedule a strategy
    Given a Python strategy exists
    When the user starts or schedules the strategy
    Then the strategy lifecycle route updates runtime state
    And scheduling is stored through the strategy scheduler path
