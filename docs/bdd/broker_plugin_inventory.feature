Feature: Broker plugin inventory
  Broker availability and supported exchanges are discovered from plugin metadata.

  # Source: utils/plugin_loader.py:17, broker/*/plugin.json
  Scenario Outline: Configured broker is discoverable as a plugin
    Given a plugin exists at "broker/<broker>/plugin.json"
    When broker capabilities are loaded at startup
    Then "<broker>" is available as a configured "<type>" broker
    And its supported exchanges come from plugin metadata

    Examples:
      | broker | type |
      | aliceblue | IN_stock |
      | angel | IN_stock |
      | arrow | IN_stock |
      | compositedge | IN_stock |
      | definedge | IN_stock |
      | deltaexchange | crypto |
      | dhan | IN_stock |
      | dhan_sandbox | IN_stock |
      | firstock | IN_stock |
      | fivepaisa | IN_stock |
      | fivepaisaxts | IN_stock |
      | flattrade | IN_stock |
      | fyers | IN_stock |
      | groww | IN_stock |
      | ibulls | IN_stock |
      | iifl | IN_stock |
      | iiflcapital | IN_stock |
      | indmoney | IN_stock |
      | jainamxts | IN_stock |
      | kotak | IN_stock |
      | motilal | IN_stock |
      | mstock | IN_stock |
      | nubra | IN_stock |
      | paytm | IN_stock |
      | pocketful | IN_stock |
      | rmoney | IN_stock |
      | samco | IN_stock |
      | shoonya | IN_stock |
      | tradejini | IN_stock |
      | tradesmart | IN_stock |
      | upstox | IN_stock |
      | wisdom | IN_stock |
      | zebu | IN_stock |
      | zerodha | IN_stock |
