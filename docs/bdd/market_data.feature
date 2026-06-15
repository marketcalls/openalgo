Feature: Market data and history
  Market data APIs validate symbols, use broker data modules, and can read local historical data.

  # Source: restx_api/quotes.py:26, services/quotes_service.py:13
  Scenario: Quote request validates exchange and symbol
    Given an API client submits a quote request
    When the symbol or exchange is not valid
    Then the service rejects the request before broker access
    And valid symbols are sent to the broker data module

  # Source: restx_api/multiquotes.py:26, services/quotes_service.py:208
  Scenario: Multiquotes returns per-symbol errors
    Given a multiquotes request contains valid and invalid symbols
    When the request is processed
    Then invalid symbols are reported individually
    And valid symbols can still be fetched

  # Source: restx_api/history.py:26, services/history_service.py:144
  Scenario: History can read from local Historify data
    Given a history request specifies source db
    When matching local data exists
    Then candles are returned from DuckDB
    And missing local data returns a not found response

  # Source: restx_api/option_chain.py:86, services/option_chain_service.py:219
  Scenario: Option chain builds rows around ATM
    Given an underlying symbol and expiry are provided
    When the option chain service runs
    Then it derives ATM from underlying LTP
    And it fetches CE and PE quotes for selected strikes

  # Source: restx_api/instruments.py:39, restx_api/search.py:26
  Scenario: Instrument and search endpoints expose contract discovery
    Given the master contract cache is available
    When the client searches instruments
    Then matching symbols and instruments can be returned
    And the API stays under the RESTX prefix
