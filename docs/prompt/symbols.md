# Symbol Format

#### OpenAlgo Symbol Format Standardization

OpenAlgo standardizes financial instrument identification via a common symbol format across all exchanges and brokers, enhancing compatibility and simplifying automated trading. This uniform symbology eliminates the need for traders to adapt to varied broker-specific formats, streamlining algorithm development and execution. The format integrates key identifiers such as the base symbol, expiration date, and option type, ensuring consistent and error-free communication within trading systems. With OpenAlgo, developers can efficiently extend platform capabilities while traders focus on strategy, not syntax.

### Equity Symbol Format

In the context of OpenAlgo, equity symbols are constructed based on the base symbol of the stock.

**Examples:**

1. **NSE Equity for Infosys:** Given the base symbol `INFY`, the OpenAlgo symbol for Infosys on the National Stock Exchange (NSE) would be `INFY`.
2. **BSE Equity for Tata Motors:** With the base symbol `TATAMOTORS`, the symbol on the Bombay Stock Exchange (BSE) would be `TATAMOTORS`.
3. **NSE Equity for State Bank of India:** If the base symbol is `SBIN`, the OpenAlgo symbol on NSE would be `SBIN`.

### Future Symbol Format

For futures, the OpenAlgo symbology specifies that the symbol should consist of the base symbol followed by the expiration date and "FUT" to denote that it is a futures contract.

**Format:** `[Base Symbol][Expiration Date]FUT`

Below are the extended examples for various futures contracts:

**NSE Futures:**

* **Example:** For Bank Nifty futures expiring in April 2024, the symbol would be `BANKNIFTY24APR24FUT`.

**BSE Futures:**

* **Example:** For SENSEX futures expiring in April 2024, the symbol would be `SENSEX24APR25FUT`.

**Currency Futures:**

* **Example:** For USDINR currency futures expiring in May 2024, the symbol would be `USDINR10MAY24FUT`.

**MCX Futures:**

* **Example:** For crude oil futures on MCX expiring in May 2024, the symbol would be `CRUDEOILM20MAY24FUT`.

**IRC Futures:**

* **Example:** For government bond futures, specifically the 7.26% 2033 bond expiring in April 2024, the symbol in OpenAlgo would be `726GS203325APR24FUT`.

### Options Symbol Format

Options symbols in OpenAlgo are structured to include the base symbol, the expiration date, the strike price, and whether it's a Call or Put option.

**Format:** `[Base Symbol][Expiration Date][Strike Price][Option Type]`

**Examples:**

**NSE Index Options:**

* **Example:** For a Nifty call option with a strike price of 20,800, expiring on 28th March 2024, the symbol would be `NIFTY28MAR2420800CE`.

**NSE Stock Options:**

* **Example:** For a Vedanta Limited (VEDL) call option with a strike price of 292.50, expiring on 25th April 2024, the symbol would be `VEDL25APR24292.5CE`.

**Currency Options:**

* **Example:** For a US Dollar to Indian Rupee (USDINR) call option with a strike price of 82, expiring on 19th April 2024, the symbol would be `USDINR19APR2482CE`.

**MCX Options:**

* **Example:** For a Crude Oil call option with a strike price of 6,750, expiring on 17th April 2024, the symbol would be `CRUDEOIL17APR246750CE`.

**IRC Options:**

* **Example:** For an Goverent bond (726GS2032) put option with a strike price of 97, expiring on 25th April 2024, the symbol would be `726GS203225APR2497PE`.

### Common NSE Index Symbols (Exchange Code : NSE\_INDEX)

NIFTY
\
NIFTYNXT50
\
FINNIFTY
\
BANKNIFTY
\
MIDCPNIFTY
\
INDIAVIX

### Common BSE Index Symbols (Exchange Code : BSE\_INDEX)

SENSEX
\
BANKEX
\
SENSEX50

### Exchange  Codes

The supported exchange symbol formats in OpenAlgo allow for an identification system that denotes where the instrument is traded, along with specific details that vary by instrument type:

* **NSE:** `NSE` for National Stock Exchange equities.
* **BSE:** `BSE` for Bombay Stock Exchange equities.
* **NFO:** `NFO` for NSE Futures and Options.
* **BFO:** `BFO` for BSE Futures and Options.
* **BCD:** `BCD` for BSE Currency Derivatives.
* **CDS:** `CDS` for NSE Currency Derivatives.
* **MCX:** `MCX` for commodities traded on the Multi Commodity Exchange.
* **NSE\_INDEX:** `NSE_INDEX` for indices on the National Stock Exchange.
* **BSE\_INDEX:** `BSE_INDEX` for indices on the Bombay Stock Exchange.

### Database Schema (Common Symbols)

For developers, understanding the database schema is essential for managing data effectively within OpenAlgo:

1. **id:** A unique identifier for each record in the database.
2. **symbol:** The standard trading symbol of the instrument as per OpenAlgo's symbology.
3. **brsymbol:** The broker-specific symbol for the instrument, if applicable.
4. **name:** The common name of the instrument (e.g., the company name for equities).
5. **exchange:** The standard exchange identifier code (e.g NSE, BSE, MCX CDS etc) where the instrument is traded as per OpenAlgo's symbology.
6. **brexchange:** The specific broker exchange identifier, if different from the standard exchange code.
7. **token:** A unique token or code assigned to the instrument, possibly for internal tracking or broker-specific identification.
8. **expiry:** The expiration date for derivatives contracts, formatted as per broker/exchange standards.
9. **strike:** The strike price for options contracts.
10. **lotsize:** The standardized lot size for the instrument, particularly relevant for derivatives trading.
11. **instrumenttype:** The type of instrument (e.g., equity, future, option).
12. **tick\_size:** The minimum price movement of the instrument on the exchange.

<figure><img src="https://17901342-files.gitbook.io/~/files/v0/b/gitbook-x-prod.appspot.com/o/spaces%2FmBwEhITzgv0O0fEGIIRN%2Fuploads%2FvUWO49dLv5Pklo6qPtIV%2Fimage.png?alt=media&#x26;token=7cea9426-f5b9-4c29-b29f-a2e4b9ea7030" alt=""><figcaption></figcaption></figure>

This schema captures both the standardized OpenAlgo symbology and the potentially divergent broker-specific information, enabling algorithms and traders to operate across multiple platforms without confusion. It allows for the storage of instrument metadata necessary for trading activities and ensures that all financial instruments are identifiable and their market details readily accessible.