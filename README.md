# OpenAlgo - Take Control of Your Algo Platform

OpenAlgo is an open-source, Flask-based Python application designed to bridge the gap between traders and major trading platforms such as Amibroker, Tradingview, Excel, and Google Spreadsheets. With a focus on simplifying algotrading, OpenAlgo facilitates easy integration, automation, and execution of trading strategies, providing a user-friendly interface to enhance trading performance.

## Supported Broker

- **AngelOne**
- **Upstox**
- **Zerodha**

## Features

- **Comprehensive Integration**: Seamlessly connect with Amibroker, Tradingview, Excel, and Google Spreadsheets for smooth data and strategy transition.
- **User-Friendly Interface**: A straightforward Flask-based application interface accessible to traders of all levels of expertise.
- **Real-Time Execution**: Implement your trading strategies in real time, ensuring immediate action to capitalize on market opportunities.
- **Customizable Strategies**: Easily adapt and tailor your trading strategies to meet your specific needs, with extensive options for customization and automation.
- **Secure and Reliable**: With a focus on security and reliability, OpenAlgo provides a dependable platform for your algotrading activities, safeguarding your data and trades.

## Documentation

For detailed documentation on OpenAlgo, including setup guides, API references, and usage examples, refer to [https://docs.openalgo.in](https://docs.openalgo.in)

## Contributing

We welcome contributions to OpenAlgo! If you're interested in improving the application or adding new features, please feel free to fork the repository, make your changes, and submit a pull request.

## License

OpenAlgo is released under the GPL V3.0 License. See the `LICENSE` file for more details.

## Contact

For support, feature requests, or to contribute further, please contact us via GitHub issues.

---

# Getting Started with OpenAlgo

## Installation Procedure

### Prerequisites

Before we begin, ensure you have the following:

- **Visual Studio Code (VS Code)** installed on Windows.
- **Python** version 3.10 or 3.11 installed.
- **Git** for cloning the repository (Download from [https://git-scm.com/downloads](https://git-scm.com/downloads)).


### Setup

1. **Install VS Code Extensions**: Open VS Code, navigate to the Extensions section on the left tab, and install the Python, Pylance, and Jupyter extensions.
2. **Clone the Repository**: Open the VS Code Terminal and clone the OpenAlgo repository with the command:

<code>git clone https://github.com/marketcalls/openalgo</code>

3. **Install Dependencies**: 

Windows users Navigate to the directory where OpenAlgo is cloned and execute:

<code>pip install -r requirements.txt</code>

Linux/Nginx users Navigate to the directory where OpenAlgo is cloned and execute:
<code>pip install -r requirements-nginx.txt</code>

to install the necessary Python libraries.


4. **Configure Environment Variables**: 

Rename the `.sample.env` file located in `openalgo` folder to `.env` 

Update the `.env`  with your specific configurations as shown in the provided template.

5. **Run the Application**: 

From the `openalgo` directory, start the Flask application with the command:

<code>python app.py</code>

If you are using nginx it is recommded to execute using gunicorn with 
eventlet or gevent (in this app we are using eventlet).
<br>
<code>gunicorn --worker-class eventlet -w 1 app:app</code>

In case of running using Gunicorn, -w 1 specifies that you should only use one worker process. This is important because WebSocket connections are persistent and stateful; having more than one worker would mean that a user could be switched between different workers, which would break the connection.


### Accessing OpenAlgo

After completing the setup, access the OpenAlgo platform by navigating to [http://127.0.0.1:5000](http://127.0.0.1:5000) in your web browser. Setup the account using  [http://127.0.0.1:5000/setup](http://127.0.0.1:5000/setup)
Login into openalgo with the credentials and start using OpenAlgo for Automation.

### Connecting Trading Platforms

You can now connect your Amibroker and Tradingview modules to transmit orders, and use the Flask application to monitor trades.

## Generate the APP API Key

Goto the API Key Section and Generate the APP API Key. And use it to placeorder from your trading applicaton

### Place Order

Sample Place Order with the /api/v1/placeorder which can be used with any trading platforms to place orders
<code>
{
"apikey":"<your_app_apikey>",
"strategy:"Test Strategy",
"symbol":"SAIL-EQ",
"action":"BUY",
"exchange":"NSE",
"pricetype":"MARKET",
"product":"MIS",
"quantity":"1"
}</code>
<br>

## Full Sample API Request
<code>
{
    "apikey": "your_app_apikey",
    "strategy": "Test Strategy",
    "exchange": "NSE",
    "symbol": "BHEL-EQ",
    "action": "BUY",
    "product": "MIS",
    "pricetype": "MARKET",
    "quantity": "1",
    "price": "0",
    "trigger_price": "0",
    "disclosed_quantity": "0",
}</code>



## Parameters Description

| Parameters          | Description          | Mandatory/Optional  | Default Value |
|---------------------|----------------------|---------------------|---------------|
| apikey              | App API key          | Mandatory           | -             |
| strategy            | Strategy name        | Mandatory           | -             |
| exchange            | Exchange code        | Mandatory           | -             |
| symbol              | Trading symbol       | Mandatory           | -             |
| action              | Action (BUY/SELL)    | Mandatory           | -             |
| product             | Product type         | Optional            | MIS           |
| pricetype           | Price type           | Optional            | MARKET        |
| quantity            | Quantity             | Mandatory           | -             |
| price               | Price                | Optional            | 0             |
| trigger_price       | Trigger price        | Optional            | 0             |
| disclosed_quantity  | Disclosed quantity   | Optional            | 0             |


### Place Smart Order

Sample Place Order with the /api/v1/placesmartorder which can be used with any trading platforms to place orders based on the open position
<code>
{
"apikey":"<your_app_apikey>",
"strategy:"Test Strategy",
"symbol":"IDEA-EQ",
"action":"BUY",
"exchange":"NSE",
"pricetype":"MARKET",
"product":"MIS",
"quantity":"0",
"position_size": "5"
}</code>
<br>

## Full Sample API Request
<code>
{
    "apikey": "your_app_apikey",
    "strategy": "Test Strategy",
    "exchange": "NSE",
    "symbol": "IDEA-EQ",
    "action": "BUY",
    "product": "MIS",
    "pricetype": "MARKET",
    "quantity": "1",
    "position_size": "5"
    "price": "0",
    "trigger_price": "0",
    "disclosed_quantity": "0",
}</code>



## Parameters Description

| Parameters          | Description          | Mandatory/Optional  | Default Value |
|---------------------|----------------------|---------------------|---------------|
| apikey              | App API key          | Mandatory           | -             |
| strategy            | Strategy name        | Mandatory           | -             |
| exchange            | Exchange code        | Mandatory           | -             |
| symbol              | Trading symbol       | Mandatory           | -             |
| action              | Action (BUY/SELL)    | Mandatory           | -             |
| product             | Product type         | Optional            | MIS           |
| pricetype           | Price type           | Optional            | MARKET        |
| quantity            | Quantity             | Mandatory           | -             |
| position_size       | Position Size        | Mandatory           | -             |
| price               | Price                | Optional            | 0             |
| trigger_price       | Trigger price        | Optional            | 0             |
| disclosed_quantity  | Disclosed quantity   | Optional            | 0             |


## How Place Smart Order Works?
PlaceSmartOrder API function, which allows traders to build intelligent trading systems that can automatically place orders based on existing trade positions in the position book.

| Action | Qty (API) | Pos Size (API) | Current Open Pos | Action by OpenAlgo                     |
|--------|-----------|----------------|------------------|----------------------------------------|
| BUY    | 100       | 0              | 0                | No Open Pos Found. Buy +100 qty        |
| BUY    | 100       | 100            | -100             | BUY 200 to match Open Pos in API Param |
| BUY    | 100       | 100            | 100              | No Action. Position matched            |
| BUY    | 100       | 200            | 100              | BUY 100 to match Open Pos in API Param |
| SELL   | 100       | 0              | 0                | No Open Pos Found. SELL 100 qty        |
| SELL   | 100       | -100           | +100             | SELL 200 to match Open Pos in API Param|
| SELL   | 100       | -100           | -100             | No Action. Position matched            |
| SELL   | 100       | -200           | -100             | SELL 100 to match Open Pos in API Param|



# Order Constants

## Exchange
- NSE: NSE Equity
- NFO: NSE Futures & Options
- CDS: NSE Currency
- BSE: BSE Equity
- BFO: BSE Futures & Options
- BCD: BSE Currency
- MCX: MCX Commodity
- NCDEX: NCDEX Commodity

## Product Type
- CNC: Cash & Carry for equity
- NRML: Normal for futures and options
- MIS: Intraday Squareoff


## Price Type
- MARKET: Market Order
- LIMIT: Limit Order
- SL: Stop Loss Limit Order
- SL-M: Stop Loss Market Order

## Action
- BUY: Buy
- SELL: Sell

## AMO
- YES: Yes
- NO: No
<br>


## Windows and Linux Complete Configuration Instructions 

For Configuration Instructions Visit the Tutorial
[https://docs.openalgo.in](https://docs.openalgo.in)


Congratulations! You have successfully set up OpenAlgo. Explore the platform and start maximizing your trading performance through automation.

