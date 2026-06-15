Feature: Setup and authenticated user session
  OpenAlgo requires initial setup, session login, optional TOTP, and explicit logout.

  # Source: blueprints/auth.py:131, blueprints/core.py:20
  Scenario: New installation exposes setup state before login
    Given the application has started
    When the client requests the setup status
    Then the response indicates whether initial setup is required
    And setup can be submitted through the setup route

  # Source: blueprints/auth.py:253, database/auth_db.py:834
  Scenario: User logs in with configured credentials
    Given setup has completed
    When the user submits valid login credentials
    Then the session is established
    And protected web routes can read the authenticated session

  # Source: blueprints/auth.py:358, blueprints/auth.py:432
  Scenario: Login can require TOTP verification
    Given two-factor authentication is configured
    When the user submits login credentials
    Then the user must complete the TOTP step
    And the 2FA status endpoint can report the current configuration

  # Source: blueprints/auth.py:921, app.py:445
  Scenario: Session status reflects expiry policy
    Given a user has an authenticated session
    When the session status endpoint is requested
    Then the response reflects session state
    And expired sessions trigger broker token revocation during request handling

  # Source: blueprints/auth.py:1190, app.py:388
  Scenario: Logout is available through the exempt logout route
    Given the user is authenticated
    When the user requests logout
    Then the session is cleared
    And the logout route is included in CSRF exemptions
