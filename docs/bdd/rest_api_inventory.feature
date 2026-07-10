Feature: Registered REST API v1 inventory
  Every Flask-RESTX method and path registered in restx_api has a documentation contract.

  # Source: restx_api/__init__.py:4, restx_api/__init__.py:60
  Scenario Outline: Registered REST resource is represented in the API contract
    Given the REST API blueprint is mounted at /api/v1
    When the "<method>" resource at "<path>" is registered from "<module>"
    Then docs/api/README.md lists that method and path
    And the linked API page describes its authentication and current behavior

    Examples:
      | method | path | module |
      | POST | /analyzer | analyzer.py |
      | POST | /analyzer/toggle | analyzer.py |
      | POST | /basketorder | basket_order.py |
      | POST | /cancelallorder | cancel_all_order.py |
      | POST | /cancelgttorder | cancel_gtt_order.py |
      | POST | /cancelorder | cancel_order.py |
      | GET | /chart | chart_api.py |
      | POST | /chart | chart_api.py |
      | POST | /closeposition | close_position.py |
      | POST | /depth | depth.py |
      | POST | /expiry | expiry.py |
      | POST | /funds | funds.py |
      | POST | /gttorderbook | gtt_orderbook.py |
      | POST | /history | history.py |
      | POST | /holdings | holdings.py |
      | GET | /instruments | instruments.py |
      | POST | /intervals | intervals.py |
      | POST | /margin | margin.py |
      | POST | /market/holidays | market_holidays.py |
      | POST | /market/timings | market_timings.py |
      | POST | /modifygttorder | modify_gtt_order.py |
      | POST | /modifyorder | modify_order.py |
      | POST | /multioptiongreeks | multi_option_greeks.py |
      | POST | /multiquotes | multiquotes.py |
      | POST | /openposition | openposition.py |
      | POST | /optionchain | option_chain.py |
      | POST | /optiongreeks | option_greeks.py |
      | POST | /optionsymbol | option_symbol.py |
      | POST | /optionsmultiorder | options_multiorder.py |
      | POST | /optionsorder | options_order.py |
      | POST | /orderbook | orderbook.py |
      | POST | /orderstatus | orderstatus.py |
      | POST | /ping | ping.py |
      | POST | /placegttorder | place_gtt_order.py |
      | POST | /placeorder | place_order.py |
      | POST | /placesmartorder | place_smart_order.py |
      | POST | /pnl/symbols | pnl_symbols.py |
      | POST | /positionbook | positionbook.py |
      | POST | /quotes | quotes.py |
      | POST | /search | search.py |
      | POST | /splitorder | split_order.py |
      | POST | /symbol | symbol.py |
      | POST | /syntheticfuture | synthetic_future.py |
      | GET | /telegram/config | telegram_bot.py |
      | POST | /telegram/config | telegram_bot.py |
      | POST | /telegram/start | telegram_bot.py |
      | POST | /telegram/stop | telegram_bot.py |
      | POST | /telegram/webhook | telegram_bot.py |
      | GET | /telegram/users | telegram_bot.py |
      | POST | /telegram/broadcast | telegram_bot.py |
      | POST | /telegram/notify | telegram_bot.py |
      | GET | /telegram/stats | telegram_bot.py |
      | GET | /telegram/preferences | telegram_bot.py |
      | POST | /telegram/preferences | telegram_bot.py |
      | GET | /ticker/<string:symbol> | ticker.py |
      | POST | /tradebook | tradebook.py |
      | POST | /whatsapp/notify | whatsapp_bot.py |
