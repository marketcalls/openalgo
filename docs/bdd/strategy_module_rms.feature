Feature: Strategy module and risk management
  The /strategy surface runs multi-leg baskets and signal-driven legs with
  durable order ownership, confirmed-flat stopping and restart-safe risk
  management. Scenarios are grouped by the money or operator truth they protect.

  # Source: test/test_strategy_module_webhook.py:890, test/test_strategy_module_docs.py:335
  Scenario: Every admitted webhook outcome is validated and audited
    Given a strategy has a webhook token
    When an alert is admitted past route preflight on that token
    Then token, kill switch, IP allowlist, payload, action, mode, live opt-in,
      duplicate window and cooling-off are checked in order
    And every accepted or rejected outcome has its own audit result label
    But Route preflight refusals are not durable webhook audit rows

  # Source: test/test_strategy_module_webhook.py:365
  Scenario: An unknown token cannot be distinguished from a malformed one
    Given a token resolves to no strategy
    When it is presented to the public webhook
    Then its label, message and status match a malformed token
    And the route answers JSON without counting the miss toward an IP ban

  # Source: test/test_strategy_module_webhook.py:911
  Scenario: The webhook token is not written anywhere it can be read back
    Given the URL token is the complete credential
    When a request, audit row or response is produced
    Then the plaintext token appears in none of them
    And only its digest is used for lookup and rate-limit identity

  # Source: test/test_strategy_module_qa_edges.py:646
  Scenario: Two starts racing produce exactly one run
    Given a stopped strategy
    When two callers start it at the same instant
    Then a single conditional update claims it
    And only one set of entry orders reaches the broker

  # Source: test/test_strategy_module_engine.py:143
  Scenario: Every batch leg resolves before anything is claimed
    Given one configured leg cannot resolve to a listed contract
    When the batch strategy starts
    Then no run row, strategy claim or broker order is created
    And the failure names the leg and reason

  # Source: test/test_strategy_module_qa_segments.py:719
  Scenario: Every leg is sent a product its venue accepts
    Given one strategy product applies to cash and derivative legs
    When an order is built
    Then MIS remains MIS
    And carry is NRML on derivatives and CNC on cash
    And the literal product sent is persisted with the order

  # Source: test/test_strategy_module_order_dispatch.py:284
  Scenario: A run mode cannot be diverted by the analyzer toggle
    Given a live run is holding broker positions
    When the platform analyzer toggle changes
    Then subsequent live exits still reach the broker
    And a sandbox run still uses the sandbox book and execution pipe

  # Source: services/strategy_module/engine.py:524, test/test_strategy_module_engine.py:318, test/test_strategy_module_scheduler.py:730
  Scenario: Durable intent and acknowledgement surround every broker call
    Given the engine is about to place an entry or exit
    When it dispatches the order
    Then the pending intent row already exists with its exact owner reference
    And the broker acknowledgement write is checked and retried once
    And persistent acknowledgement failure emits structured exact-row order_ack_unrecorded facts
    And the dispatch call immediately binds only that row or keeps the run reserved
    And a bounded shared sweep repairs every ordinary open run and folds broker status

  # Source: test/test_strategy_module_order_events.py:197
  Scenario: Each fill is applied once to the exact order it names
    Given the same completed fill arrives from more than one broker channel
    When the order-update subscriber applies those events
    Then the first event changes only the order and position_ref it names
    And every repeat changes neither exposure nor realized P&L

  # Source: test/test_strategy_residual_safety.py:145
  Scenario: A signal flip settles only the owner its fill names
    Given a leg has an outgoing superseded side and a live replacement side
    When the retried outgoing exit fills
    Then only the superseded position_ref is reduced
    And the replacement remains open and evaluated for risk

  # Source: test/test_strategy_module_engine.py:717
  Scenario: One exact owner cannot be sent two covering exits
    Given an open position owner
    When two risk rules fire before the first exit returns
    Then claim and duplicate detection happen under one run-lock hold
    And exactly one covering order is placed

  # Source: test/test_strategy_module_qa_edges.py:754
  Scenario: An accepted stop remains pending until confirmed flat
    Given a running strategy with filled positions
    When its stop request and exit acknowledgements succeed
    Then the stop timestamp and reason are durable before dispatch
    And the response says stop_pending true while exits are working
    And the run stays current, subscribed and managed

  # Source: test/test_strategy_module_qa_edges.py:961
  Scenario: The final exit fill performs terminal stop finalization
    Given a run has a durable pending stop
    When the last exact owner quantity fills flat
    Then stopped_at, stop_reason and strategy release commit atomically
    And one run_stopped event is emitted
    And the pending-stop fields are cleared

  # Source: test/test_strategy_module_order_events.py:254
  Scenario: A terminal partial entry is real exposure
    Given an entry partially filled before it was cancelled or rejected
    When the terminal update arrives during a pending stop
    Then positive filled_qty is the quantity held regardless of status
    And only that exact quantity is exited
    And requested quantity is never used to open the opposite side

  # Source: test/test_strategy_module_order_events.py:306
  Scenario: Unpriced exposure remains managed and visibly unavailable
    Given a terminal partial fill has positive quantity but no usable price
    When it reaches the engine and operator views
    Then the exact position quantity remains managed
    And average price and P&L are unavailable rather than fabricated as zero

  # Source: test/test_strategy_module_order_events.py:825
  Scenario: An asynchronous rejected stop exit remains retryable
    Given a stop exit was accepted and later rejected or cancelled
    When its terminal update arrives
    Then only that exact owner claim is released
    And run_stop_failed is recorded at critical severity
    And the pending run stays open for another exit attempt

  # Source: test/test_strategy_module_signals.py:602
  Scenario: A durable stop gates new signal entries but permits exit retries
    Given a signal run has stop_requested_reason populated
    When entry and exit alerts arrive
    Then a new entry claim is refused under the run lock
    And an alert targeting exposure still held can retry its exit

  # Source: test/test_strategy_module_signals.py:1072
  Scenario: A normal signal round trip keeps one platform-session run
    Given a signal leg opens and exits for a risk reason
    When it becomes flat before the session ends
    Then the platform-session run remains open
    And a later alert reuses its P&L, peak, trough and audit history

  # Source: services/strategy_module/risk_adapter.py:100, services/strategy_module/risk_adapter.py:216
  Scenario: Every strategy risk decision comes from the shared core
    Given a held leg and run have configured stops, targets and trailing rules
    When a usable market price reaches the engine
    Then the adapter translates both levels into the shared risk types
    And the shared position and aggregate evaluators make the decisions

  # Source: test/test_strategy_module_qa_edges.py:812, frontend/src/pages/strategy/Detail.test.tsx:524
  Scenario: An overall target preserves trigger, execution and terminal truth
    Given a multi-leg basket is marked from rolling latest-known one-symbol ticks
    And those marks reach its overall target without promising a simultaneous snapshot
    When MARKET exits fill at the available bid or ask and confirm every owner flat
    Then overall_target_hit precedes every accepted leg_exit_placed event
    And run_stopped follows those placements with stop_reason overall_target
    And the finalized run keeps fill-derived realized P&L separately from its marked peak
    And stopped views show zero unrealized and ignore an older checkpoint

  # Source: test/test_strategy_module_qa_edges.py:547
  Scenario: The daily loss limit spans the platform session
    Given earlier runs already reached the strategy daily loss limit
    When a later run receives a price
    Then it is stopped for daily_loss_limit
    And the boundary is the platform session reset rather than midnight

  # Source: test/test_strategy_module_scheduler.py:281
  Scenario: An intraday strategy always receives a square-off job
    Given an intraday strategy has an exit time and scheduling is disabled
    When jobs are synchronized
    Then a weekday square-off is installed at that time
    And no start job is installed

  # Source: test/test_strategy_module_qa_segments.py:1888, test/test_strategy_module_webhook_e2e.py:233
  Scenario: A signal must name a listed contract and never doubles a held side
    Given a derivatives signal leg names only a base symbol or repeats its held side
    When its entry alert arrives
    Then a base symbol is refused before placement
    And a repeated exact-contract signal is a successful no-op

  # Source: test/test_strategy_module_recovery.py:680
  Scenario: Recovery restores a live and superseded owner independently
    Given a crash occurs while a flip holds an outgoing and replacement side
    When the open run is recovered
    Then order rows are grouped by exact position_ref
    And both owners recover with independent quantities, exits and risk state

  # Source: test/test_strategy_module_recovery.py:957
  Scenario: Proven unrepresentable exposure remains database open
    Given durable rows prove more than two held owner references on one leg
    When recovery cannot fit them into live plus superseded state
    Then the run is not hydrated and not finalised
    And the strategy remains reserved
    And recovery_failed requests manual reconciliation at critical severity

  # Source: test/test_strategy_module_recovery.py:1439
  Scenario: Exact durable break-even overrides a stale checkpoint
    Given every reference group has usable priced entry and exit fills
    And those fills sum to exactly zero realized P&L
    When recovery reads a stale nonzero checkpoint
    Then the exact durable zero is authoritative

  # Source: test/test_strategy_module_recovery.py:1527
  Scenario: Incomplete valuation retains only known P&L
    Given durable fills prove exposure but one fill has no usable price
    And no checkpoint witnessed the same owner shape and quantities
    When the run recovers
    Then the known priced portion is retained
    And a critical recovery_succeeded event requests manual P&L reconciliation

  # Source: test/test_strategy_module_recovery.py:1899
  Scenario: Malformed recovery with no proven exposure cannot wedge startup
    Given an open run has malformed state but no durable evidence of exposure
    When it cannot be reconstructed
    Then it is finalised with recovery_failed
    And recovery continues for every other open run

  # Source: frontend/src/pages/strategy/useStrategyLive.test.tsx:246
  Scenario: A stale strategy socket returns to periodic reads
    Given the strategy page once received a live frame
    When that socket becomes silent beyond the recency window
    Then periodic reads resume
    And fresh REST state replaces the stale frame and run id

  # Source: test/test_strategy_module_views.py:765
  Scenario: Broker books follow the run mode rather than analyzer state
    Given a current or selected strategy run
    When its orderbook, tradebook or positions are requested
    Then a live run reads the broker and a sandbox run reads sandbox
    And account rows are narrowed to the strategy's durable orders or contracts

  # Source: frontend/src/pages/strategy/Detail.test.tsx:364
  Scenario: No run means broker truth was not requested
    Given a strategy has no current or historical run
    When an operator opens a broker-backed tab
    Then no broker request is made
    And the page labels recorded rows as strategy audit rather than broker-empty truth

  # Source: frontend/src/pages/strategy/Detail.test.tsx:165
  Scenario: Broker numerics preserve zero and expose unavailable values
    Given a broker row contains zero, missing, malformed and non-finite numerics
    When the Detail page normalizes it
    Then real zero remains zero
    And every unusable quantity, price and P&L value renders unavailable

  # Source: frontend/src/pages/strategy/Detail.test.tsx:1085, frontend/src/pages/strategy/strategy_module.test.ts:133
  Scenario: Broker order and trade truth keeps local reconciliation context
    Given broker rows and recorded strategy orders can match, differ or be ambiguous
    When the page reconciles them by broker order id
    Then broker values remain primary
    And multiple trade fills aggregate quantity and weighted price before comparison
    And local-only, ambiguous, mismatch and rejection context remain visible

  # Source: frontend/src/pages/strategy/Detail.test.tsx:787, frontend/src/pages/strategy/Detail.test.tsx:875, frontend/src/pages/strategy/strategy_module.test.ts:412, test/test_strategy_module_views.py:441
  Scenario: Position fallback preserves exposure without inventing valuation
    Given local audit has explicit positive fills in working or terminal statuses
    When the broker positionbook is unavailable
    Then lifetime orders preserve residual owners from earlier runs
    And side and exact filled quantity remain visible
    And unpriced average, realized and unrealized values remain unavailable
    And a prior-run live frame never values the current run's fallback
    And a broker contract shared with another source is not attributed to this strategy

  # Source: test/test_strategy_module_lifecycle_api.py:232
  Scenario: Close all records an attempt rather than proof of flatness
    Given an operator calls close_all
    When its intent event is written before the stop and broker results
    Then close_all_manual proves the request or attempt
    And only confirmed-flat run_stopped proves the broker position is gone
