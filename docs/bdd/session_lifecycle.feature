Feature: Multi-session lifecycle and broker-session rollover
  App sessions are device-specific while all devices share the installation's active broker session and feed.

  # Source: database/auth_db.py:327, database/auth_db.py:330
  Scenario: Active sessions are capped and same-IP sessions are replaced
    Given the same user signs in from multiple devices
    When a new active session is registered
    Then a prior row for the same user and IP is replaced
    And no more than five active-session rows are retained

  # Source: blueprints/auth.py:921, database/auth_db.py:400
  Scenario: Session polling updates a throttled liveness heartbeat
    Given an authenticated app session has a session ID
    When the SPA polls session status
    Then active_sessions.last_seen is refreshed at most once every 30 seconds
    And the session response reports the current active-session count

  # Source: database/auth_db.py:504, database/auth_db.py:516
  Scenario: Resuming an unchanged broker token preserves the shared feed
    Given another device resumes the same broker token and feed token
    When the auth row is upserted
    Then plaintext token equality is detected despite Fernet ciphertext changes
    And cross-process feed teardown is skipped for the unchanged broker session

  # Source: blueprints/auth.py:969, blueprints/auth.py:981
  Scenario: Expired broker token preserves the app session for reconnect
    Given the app session remains valid but the broker token is unavailable
    When session status is requested
    Then the user remains authenticated in the app
    And broker_session_expired tells the UI to offer broker reconnect

  # Source: blueprints/auth.py:766, database/auth_db.py:412
  Scenario: Password change revokes every active device session
    Given the user changes the account password successfully
    When the password update is committed
    Then all active-session rows for the user are cleared
    And a force-logout event is emitted before the current session is cleared
