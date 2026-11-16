Feature: Orders and Action Center
  Order APIs support live execution, analyzer execution, and semi-auto approval workflows.

  # Source: restx_api/place_order.py:25, services/place_order_service.py:287
  Scenario: Place order validates input and resolves broker auth
    Given an API client has a valid API key
    When the client submits a place order request
    Then the request schema is validated
    And the service resolves the broker before execution

  # Source: restx_api/place_smart_order.py:28, services/place_smart_order_service.py:148
  Scenario: Smart order uses analyzer or live execution based on analyzer mode
    Given a smart order payload includes position size
    When analyzer mode is enabled
    Then the order is routed to sandbox smart order logic
    And live mode routes to the broker smart order API

  # Source: restx_api/basket_order.py:29, services/basket_order_service.py:184
  Scenario: Basket order executes BUY orders before SELL orders
    Given a basket contains BUY and SELL legs
    When the basket order service executes it
    Then BUY orders are sorted ahead of SELL orders
    And live execution occurs in bounded batches

  # Source: restx_api/split_order.py:28, services/split_order_service.py:23
  Scenario: Split order enforces child-order limits
    Given a split order request specifies a large quantity
    When the service computes child orders
    Then no more than 100 child orders are allowed
    And live child orders use the configured order rate delay

  # Source: blueprints/orders.py:995, services/pending_order_execution_service.py:14
  Scenario: Action Center approval executes a pending order
    Given an order is queued in semi-auto mode
    When the user approves the pending order
    Then the pending row is marked approved
    And execution is attempted immediately through the pending order execution service

  # Source: services/pending_order_execution_service.py:145
  Scenario Outline: Action Center dispatches every queueable extended order type
    Given an approved "<api_type>" row exists in Action Center
    When the pending order execution service dispatches the row
    Then "<service>" is called with resolved API-key and broker authentication
    And the "<identifier>" execution reference is persisted

    Examples:
      | api_type | service | identifier |
      | optionsmultiorder | place_options_multiorder | child order IDs |
      | placegttorder | place_gtt_order | trigger ID |

  # Source: blueprints/orders.py:1102, database/action_center_db.py:169
  Scenario: Action Center approve-all processes pending orders
    Given multiple pending orders are available
    When the user approves all pending orders
    Then each eligible pending order is marked approved
    And each approved order is submitted for execution

  # Source: database/action_center_db.py:claim_pending_order_for_execution, services/pending_order_execution_service.py:execute_approved_order
  Scenario: Concurrent approvals cannot send the same pending order twice
    Given a pending order has been approved
    When two execution attempts race to claim it
    Then only one can mark it submitting and contact the broker
    And a submitting row left by a restart is not automatically resent

  # Source: utils/httpx_client.py:watch_for_unanswered_writes, services/place_order_service.py
  Scenario: A lost reply does not prove an order was rejected
    Given a live place order write may have reached the broker
    When its reply is lost through the shared transport
    Then the service reports that the order may have been placed
    And the caller is told to check the order book before placing it again
    And the transport does not automatically retry the write
