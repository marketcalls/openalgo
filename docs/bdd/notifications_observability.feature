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
