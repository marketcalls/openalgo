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

  # Source: blueprints/broker_config.py:list_brokers, utils/broker_setup_guide.py:guide
  Scenario: Broker discovery works before broker login
    Given the user is signed in to OpenAlgo without a broker session
    When the broker list is requested
    Then every VALID_BROKERS entry includes its fields setup hints and sign-in method
    And configured active and credential-source state are returned without full saved keys

  # Source: utils/broker_keys.py:resolve, database/broker_keys_db.py
  Scenario: Environment credentials take precedence for their named broker
    Given REDIRECT_URL names a broker and BROKER_API_KEY is set in the environment configuration
    And keys are also saved for that broker in OpenAlgo
    When its keys are resolved
    Then the environment keys are used
    And saved keys remain available for other enabled brokers

  # Source: blueprints/broker_config.py:save_broker, database/broker_keys_db.py:save_broker_keys
  Scenario: Saving a new broker does not require editing the environment
    Given the user is signed in and the broker is not configured in the environment
    When valid broker application keys are saved
    Then their encrypted values are stored in the main database bound to broker and field
    And blank key fields preserve saved values
    And a restart is not required to use the saved broker keys

  # Source: blueprints/auth.py:start_broker_login, utils/broker_login.py, database/broker_keys_db.py
  Scenario: Broker callbacks belong to a one-use server-started login
    Given a CSRF-checked request started a broker login
    When the broker callback completes within ten minutes with the required browser marker or state
    Then the pending login is consumed once
    And an unsolicited expired or reused callback cannot commit a broker session

  # Source: utils/auth_utils.py:begin_broker_login, utils/auth_utils.py:handle_auth_success, utils/broker_keys.py
  Scenario: A competing broker login does not replace keys before commit
    Given one broker session is active
    When another broker callback exchanges its token
    Then only that request sees its staged keys
    And other requests retain the active broker keys
    And new keys become process-wide only when the token commit succeeds
    And request teardown removes staged or pinned keys

  # Source: utils/broker_switch.py:refusal_for_login, utils/auth_utils.py:_commit_refusal
  Scenario: Running Live automation blocks a broker switch
    Given the previous broker has running Live automation or positions under active scalping protection
    When the user tries to log in to another broker
    Then the switch is refused before the old session ends
    And the safety check is repeated at token commit

  # Source: blueprints/broker_config.py:save_broker, blueprints/broker_config.py:forget_broker
  Scenario: Changing the active broker keys requires explicit sign-out confirmation
    Given a broker session is active and no Live automation blocks the change
    When its keys are replaced or its saved broker is forgotten
    Then sign_out=true is required
    And the broker session ends while this browser stays signed in to OpenAlgo
    And a broker configured in the environment cannot be forgotten through the saved-key API

  # Source: blueprints/broker_credentials.py:get_credentials, blueprints/broker_credentials.py:update_credentials
  Scenario: Profile server settings remain separate from broker keys
    Given the user is signed in to OpenAlgo
    When host WebSocket or ngrok settings are saved through the server-settings endpoint
    Then only those settings are written to the environment file
    And the response requires a restart

  # Source: blueprints/broker_credentials.py:get_capabilities, utils/plugin_loader.py
  Scenario: Broker capabilities follow the active broker plugin
    Given a broker session is active
    When its capabilities are requested
    Then supported exchanges and broker type come from the cached plugin metadata
