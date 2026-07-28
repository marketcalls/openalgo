Feature: Admin and security controls
  Admin routes expose diagnostics, security settings, OAuth/MCP controls, and system metadata.

  # Source: blueprints/admin.py:1447, database/health_db.py:1
  Scenario: Admin system endpoint reports runtime system details
    Given an admin user is authenticated
    When the system endpoint is requested
    Then system, process, and health-related details can be returned

  # Source: blueprints/security.py:122, utils/security_middleware.py:20
  Scenario: Security page manages IP ban data
    Given security middleware is initialized
    When an admin views security settings
    Then IP ban state can be displayed
    And banned IP checks can be applied before Flask request handling

  # Source: blueprints/security.py:412, csp.py:9
  Scenario: Security controls expose CSP and header configuration
    Given CSP hardening is enabled by environment
    When the security configuration is viewed or updated
    Then configured response headers can be inspected
    And CSP behavior remains environment-backed

  # Source: blueprints/admin.py:2165, blueprints/mcp_oauth.py:886
  Scenario: Admin can use MCP kill switch for OAuth clients
    Given Remote MCP is enabled
    When the MCP kill-switch route is called
    Then MCP client access can be disabled
    And OAuth token flow remains governed by MCP OAuth routes
