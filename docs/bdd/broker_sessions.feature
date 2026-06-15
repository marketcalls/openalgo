Feature: Broker sessions and credentials
  OpenAlgo connects user API keys to broker sessions and broker credential metadata.

  # Source: blueprints/auth.py:510, database/auth_db.py:917
  Scenario: User selects and authenticates a broker
    Given the user is logged in
    When the broker login route is used
    Then the selected broker is associated with the user session
    And API key broker lookup can resolve the active broker

  # Source: blueprints/brlogin.py:39, utils/plugin_loader.py:65
  Scenario: Broker callback completes broker-specific auth
    Given a broker redirects to the callback route
    When the callback payload is handled
    Then the broker-specific auth module processes the response
    And broker tokens are stored through the auth database layer

  # Source: blueprints/brlogin.py:890, blueprints/brlogin.py:969
  Scenario: Broker-specific login helpers expose additional auth steps
    Given a broker requires a special login flow
    When the user invokes the broker helper route
    Then the route handles the broker-specific initiation or OTP step
    And the result can be used by the broker auth flow

  # Source: blueprints/broker_credentials.py:121, blueprints/broker_credentials.py:358
  Scenario: Broker credential and capability APIs expose configured broker metadata
    Given broker plugins are present
    When the credentials or capabilities endpoints are requested
    Then the response includes broker-specific credential requirements
    And capability metadata is derived from plugin configuration
