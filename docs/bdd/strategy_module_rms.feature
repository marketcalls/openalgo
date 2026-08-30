Feature: Strategy module and risk management
  The /strategy surface runs multi-leg option baskets and signal-driven legs with
  end-to-end risk management. Two kinds share one engine: a batch enters and exits
  every leg together, a signal moves one leg per alert. Every risk decision comes
  from the shared services/risk core, and every order goes out through one dispatch
  point. Scenarios below are grouped by the property they protect.

  # Source: blueprints/strategy_module.py:1609, services/strategy_module/webhook.py:608
  Scenario: An inbound alert is validated before it reaches the engine
    Given a strategy has a webhook token
    When an alert arrives on that token
    Then the token, kill switch, IP allowlist, payload, action, mode, live opt-in,
      duplicate window and cooling-off window are each checked in that order
    And every outcome is written to the webhook audit trail with its own result label

  # Source: services/strategy_module/webhook.py:608, blueprints/strategy_module.py:1609
  Scenario: An unknown token cannot be distinguished from a malformed one
    Given a token that resolves to no strategy
    When it is presented to the webhook
    Then the result label, message and status are identical to a malformed token
    And the response is produced by the route rather than the application 404 handler
    And the miss does not count towards an IP ban

  # Source: blueprints/strategy_module.py:1609, utils/traffic_logger.py:107
  Scenario: The webhook token is not written anywhere it could be read back
    Given the URL token is the entire credential
    When a webhook request is logged
    Then the credential segment of the path is masked in the traffic log
    And the stored audit payload carries no token-shaped value
    And the rate limiter is keyed on the token digest rather than the token
    And an oversized Content-Length is refused before the body is read

  # Source: database/strategy_module_db.py:895, services/strategy_module/engine.py:190
  Scenario: Two starts racing produce exactly one run
    Given a strategy that is stopped
    When two callers start it at the same instant
    Then a single conditional update claims the strategy
    And one caller opens a run and the other is refused
    And only one set of entry orders reaches the broker

  # Source: services/strategy_module/engine.py:190, services/strategy_module/symbol_resolver.py:302
  Scenario: Every leg resolves before anything is claimed
    Given a basket in which one leg cannot be resolved to a contract
    When the strategy is started
    Then no run row is created, the strategy is not claimed, and no order is placed
    And the failure names the leg and the reason

  # Source: services/strategy_module/order_dispatch.py:77
  Scenario: A leg is sent a product its venue accepts
    Given a strategy configured with one product for every leg
    When an order is built for a leg
    Then MIS is sent unchanged as an intraday product
    And any other product is sent as NRML on a derivatives venue and CNC on cash
    And a basket mixing a cash leg and an option leg is therefore legal

  # Source: services/place_order_service.py:119, services/strategy_module/order_dispatch.py:99
  Scenario: A live run is not diverted by the platform analyzer toggle
    Given a live run holding real positions
    When an operator switches the platform-wide analyzer mode on
    Then the run's subsequent orders still reach the broker
    And no exit is answered by the sandbox on behalf of a real position

  # Source: services/strategy_module/state.py:194, services/strategy_module/engine.py:781
  Scenario: One leg cannot be sent two exits
    Given an open leg
    When two rules fire on it before the first exit order returns
    Then the claim and the duplicate check happen in one hold of the run lock
    And exactly one covering order is placed

  # Source: services/strategy_module/state.py:194, services/strategy_module/engine.py:781
  Scenario: An exit the broker refused stays retryable
    Given an exit order the broker rejected
    When a later stop, stop loss, target or square-off reaches that leg
    Then the leg is not treated as having an exit in flight
    And another exit can be placed for the position that is still held

  # Source: services/strategy_module/engine.py:781
  Scenario: A stop whose exits were refused leaves the run open
    Given a running strategy whose exit orders are all rejected by the broker
    When a stop is requested
    Then the run is not finalised and its prices stay subscribed
    And a run_stop_failed event is recorded at critical severity
    And the caller is told which legs were refused

  # Source: services/strategy_module/engine.py:501, services/strategy_module/order_events.py:59
  Scenario: A fill is applied once, to the order it belongs to, at a usable price
    Given an order update carrying a fill
    When it is applied to a leg
    Then a repeat of the same fill changes nothing
    And a price that is not strictly positive and finite seeds no leg
    And the leg is resized to the quantity that actually filled
    And a fill naming an order the leg is not waiting on is ignored

  # Source: services/strategy_module/engine.py:501, services/strategy_module/state.py:194
  Scenario: A signal flip does not abandon the position it opens
    Given a leg held long
    When a short entry squares the long and opens a short before the close fills
    Then the outgoing long is tracked separately until its own fill settles it
    And the short remains open, priced and evaluated for risk

  # Source: services/risk/aggregate.py:67, services/strategy_module/risk_adapter.py:136
  Scenario: Risk decisions come from the shared core, never a second evaluator
    Given a leg with a stop, a target and a trailing configuration
    When a price arrives
    Then the leg is translated into the core's own types and the core decides
    And a position's realized P&L counts whether or not it is currently open

  # Source: services/strategy_module/engine.py:964, services/strategy_module/session.py:39
  Scenario: The daily loss limit is measured across the session, not one run
    Given a strategy with a daily loss limit that has already been reached
      across runs that finished earlier today
    When a further run is open and a price arrives
    Then the run is squared off and stopped with reason daily_loss_limit
    And the session boundary used is the platform session reset, not midnight

  # Source: services/strategy_module/scheduler.py:254
  Scenario: An intraday strategy is always given a square-off
    Given a strategy with an exit time and the scheduler switched off
    When its jobs are synchronised
    Then a square-off job is installed on weekdays at that exit time
    And no start job is installed

  # Source: services/strategy_module/signals.py:297, services/strategy_module/symbol_resolver.py:302
  Scenario: A signal leg must name a contract that exists
    Given a signal leg naming a base symbol on a derivatives exchange
    When an entry signal arrives
    Then the signal is refused and no order is placed
    And the refusal names what should be configured instead

  # Source: services/strategy_module/signals.py:297
  Scenario: A repeated signal is a no-op rather than a second position
    Given a leg already held on the side a signal asks for
    When that signal arrives again
    Then the response is a success carrying a note
    And no order is placed, because reporting failure would invite a retry

  # Source: database/strategy_module_db.py:1135, services/strategy_module/engine.py:501
  Scenario: A stopped run records the P&L its exit fills produced
    Given a run stopped before its exit orders filled
    When those fills arrive
    Then the run row is reconciled from its own order rows
    And a run whose order rows record no completed round trip is left unchanged

  # Source: services/strategy_module/recovery.py:246
  Scenario: A restart recovers open runs from orders and checkpoints
    Given the process restarted while runs were open
    When recovery runs
    Then identity and disposition come from the order rows
    And volatile risk state comes from the checkpoint
    And a rejected order is never upgraded by a checkpoint
    And a run that cannot be recovered is finalised rather than wedging startup

  # Source: services/strategy_module/broadcast.py:522, blueprints/strategy_module.py:1609
  Scenario: A page watching a strategy is pushed to rather than polling
    Given a browser viewing one strategy
    When it joins that strategy's room
    Then ownership is checked on the join
    And snapshot, delta, event, order, run and terminal frames are pushed
    And a frame older than the last one received is discarded
    And the periodic read remains as a fallback until frames actually arrive

  # Source: services/strategy_module/views.py:178
  Scenario: A position row cannot be divided between its owners
    Given a contract this strategy holds that is also held from another source
    When the strategy's positions are read from the broker
    Then the row is reported as shared rather than attributed to this strategy
    And the strategy's own profit and loss is taken from its fills instead
