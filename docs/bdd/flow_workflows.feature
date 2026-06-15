Feature: Flow workflows
  Flow manages workflow graphs, activation, manual execution, webhooks, schedules, and monitoring.

  # Source: blueprints/flow.py:33, database/flow_db.py:78
  Scenario: User lists saved workflows
    Given workflow records exist
    When the workflow list endpoint is requested
    Then graph metadata and active state can be returned
    And persisted workflow fields come from the flow database model

  # Source: blueprints/flow.py:186, services/flow_scheduler_service.py:39
  Scenario: User activates a workflow
    Given a workflow has valid configuration
    When the activation endpoint is called
    Then the workflow active flag is updated
    And scheduler jobs can be created when schedule nodes require them

  # Source: blueprints/flow.py:303, services/flow_executor_service.py:26
  Scenario: User executes a workflow manually
    Given a workflow graph exists
    When manual execution is requested
    Then the executor enforces locks and execution limits
    And an execution record is created

  # Source: blueprints/flow.py:600, blueprints/flow.py:524
  Scenario: Flow webhook validates shared secret when required
    Given a workflow has webhook authentication enabled
    When a webhook request arrives
    Then the secret is compared using the configured auth type
    And unauthorized requests are rejected

  # Source: blueprints/flow.py:631, services/flow_price_monitor_service.py:38
  Scenario: Flow monitor reports price alert worker state
    Given price alert monitoring is configured
    When monitor status is requested
    Then current monitor state is returned
    And price conditions are polled by the monitor service
