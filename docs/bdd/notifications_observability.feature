Feature: Notifications and observability
  OpenAlgo emits events, sends notifications, and records operational telemetry.

  # Source: blueprints/telegram.py:58, subscribers/telegram_subscriber.py:26
  Scenario: Telegram settings can enable order notifications
    Given Telegram integration is configured
    When order events are published
    Then successful order-related events can be sent to Telegram
    And failure and analyzer-error notifications are skipped

  # Source: blueprints/whatsapp.py:51, subscribers/whatsapp_subscriber.py:23
  Scenario: WhatsApp settings can enable order notifications
    Given WhatsApp integration is configured
    When order events are published
    Then successful order-related events can be sent to WhatsApp
    And failure and analyzer-error notifications are skipped

  # Source: restx_api/telegram_bot.py:450, restx_api/whatsapp_bot.py:92
  Scenario: Notification APIs can send direct messages
    Given notification credentials are configured
    When a RESTX notification request is sent
    Then the corresponding bot service attempts delivery
    And the response reports delivery status

  # Source: blueprints/health.py:104, database/health_db.py:1
  Scenario: Health check reports detailed operational status
    Given health monitoring is available
    When the detailed health endpoint is requested
    Then database, WebSocket, file descriptor, memory, and thread metrics can be evaluated
    And metrics are stored with pass, warn, or fail status

  # Source: services/telegram_alert_service.py:285, services/flow_openalgo_client.py:528
  Scenario: Stopping Telegram suppresses automatic event and Flow alerts
    Given Telegram configuration is persisted with is_active false
    When an order event or Flow Telegram node attempts an automatic alert
    Then the alert service skips delivery
    And explicit admin sends and the notify API remain available

  # Source: restx_api/telegram_bot.py:298
  Scenario: Telegram webhook validates its secret but does not dispatch updates yet
    Given Telegram webhook mode has a configured secret
    When an update is received with the correct secret header and an update_id
    Then the endpoint returns an empty success acknowledgement
    And no command dispatcher is invoked by the current RESTX handler

  # Source: restx_api/telegram_bot.py:385
  Scenario: Telegram REST broadcast reports its current no-op delivery counts
    Given REST broadcast is enabled and the request is authorized
    When a valid broadcast message is submitted
    Then the response reports zero successful and zero failed deliveries
    And clients do not treat the endpoint as implemented fan-out

  # Source: utils/traffic_logger.py:14, database/traffic_db.py:61
  Scenario: Traffic telemetry is written asynchronously to its own database
    Given traffic logging middleware is enabled
    When a non-exempt HTTP request completes
    Then client IP, method, path, status, duration, host, error, and user ID are submitted to a single-worker executor
    And the traffic record is stored in logs.db rather than the primary application database
