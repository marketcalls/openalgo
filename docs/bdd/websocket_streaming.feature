Feature: WebSocket streaming
  OpenAlgo uses example routes, a proxy, ZeroMQ, broker adapters, and frontend subscription management for streaming data.

  # Source: blueprints/websocket_example.py:62, websocket_proxy/server.py:542
  Scenario: WebSocket example page depends on proxy authentication
    Given the example page is opened
    When a client connects to the proxy
    Then the proxy requires authentication within the grace period
    And unauthenticated clients cannot subscribe indefinitely

  # Source: blueprints/websocket_example.py:97, websocket_proxy/server.py:794
  Scenario: Client authenticates with api_key or apikey
    Given a WebSocket client has an API key
    When it sends an authenticate action
    Then the proxy verifies the key
    And returns broker identity and supported feature flags

  # Source: blueprints/websocket_example.py:116, websocket_proxy/server.py:1136
  Scenario: Client subscribes to one or more symbols
    Given a WebSocket client is authenticated
    When it sends a subscribe action with a symbol or symbols
    Then mode is normalized to LTP, Quote, or Depth
    And subscription results are returned per symbol

  # Source: blueprints/websocket_example.py:135, websocket_proxy/server.py:1258
  Scenario: Client unsubscribes from symbols
    Given a WebSocket client has active subscriptions
    When it sends unsubscribe or unsubscribe_all
    Then the proxy removes matching subscription records
    And broker adapter unsubscribe logic can be invoked

  # Source: blueprints/websocket_example.py:217, websocket_proxy/server.py:1671
  Scenario: ZMQ delivery fans out public market data
    Given broker adapters publish market data to ZeroMQ
    When the proxy receives a public topic
    Then matching subscribed clients receive the payload
    And private order, position, and margin topics are skipped
