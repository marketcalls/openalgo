Feature: Historify and market tools
  Historify manages local historical data while tool routes expose derived option analytics.

  # Source: blueprints/historify.py:29, database/historify_db.py:94
  Scenario: Historify watchlist lists tracked symbols
    Given Historify tables are initialized
    When the watchlist endpoint is requested
    Then tracked symbols are returned from the Historify database

  # Source: blueprints/historify.py:122, services/history_service.py:144
  Scenario: Historify download stores data for local history reads
    Given a user requests a historical data download
    When the download job completes
    Then local candles can later be read through history source db

  # Source: blueprints/historify.py:1238, database/historify_db.py:94
  Scenario: Historify schedules recurring downloads
    Given schedule metadata is submitted
    When a schedule is created
    Then schedule and execution data are stored in Historify tables

  # Source: blueprints/ivchart.py:23, blueprints/oitracker.py:28
  Scenario: Option analytics tools calculate IV and OI views
    Given option market data is available
    When IV chart or OI tracker data is requested
    Then the tool route returns data for the requested analytic view
