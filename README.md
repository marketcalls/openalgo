[![Deploy with Vercel](https://vercel.com/button)](https://vercel.com/new/clone?repository-url=https://github.com/marketcalls/algobridge)

# AlgoBridge: Simple Algotrading Interface

AlgoBridge is a Flask-based python application designed to provide a simple  interface for algotrading, connecting traders to major trading platforms such as Amibroker, Tradingview, Excel, and Google Spreadsheets. It is crafted to facilitate easy integration, automation, and execution of trading strategies, offering a user-friendly gateway to enhance trading performance through automation.

## Supported Broker

AngelOne

## How to Deploy in Vercel

- 1)Sign up with a Github Account

- 2)Vercel Signup and Connect Github Account

- 3)Click on the Deploy Button (This will deploy in Vercel) -> Give a name to the app e.g myalgoapp

- 4)myalgoapp -> Settings -> Environmental variables -> upload the .env format

- 5)Storage -> New Database -> Database Name

- 6)Connect the Database to the Application

- 7)Run the Table Query

<code>CREATE TABLE auth (
    id SERIAL PRIMARY KEY,
    name VARCHAR(255) UNIQUE,
    auth VARCHAR(1000)
);</code>

## Features

- **Comprehensive Integration**: Effortlessly connect with Amibroker, Tradingview, Excel, and Google Spreadsheets for a smooth data and strategy transition.
- **User-Friendly Interface**: Navigate through a straightforward Flask-based application interface accessible to traders of all expertise levels.
- **Real-Time Execution**: Implement your trading strategies in real-time, ensuring immediate action to capitalize on market opportunities.
- **Customizable Strategies**: Adapt and tailor your trading strategies to fit your specific needs, with extensive options for customization and automation.
- **Secure and Reliable**: Prioritizing security and reliability, AlgoBridge offers a dependable platform for your algotrading activities, safeguarding your data and trades.

## Getting Started

To get started with AlgoBridge, follow these steps:

1. **Installation**
   - Ensure you have Python installed on your system.
   - Clone the AlgoBridge repository.
   - Install the required dependencies using `pip install -r requirements.txt`.

2. **Configuration**
   - Configure the environmental file as per .sample.env file. Rename .sample.env file to .env if required.
   - If deploying in Vercel then upload the .env file to the enviromental section which is required for login to the app and authentication to placeorders.

3. **Running AlgoBridge**
   - Launch the Flask application by running `python app.py` in your terminal.
   - Access the AlgoBridge interface via your web browser at the provided local address.

4. **Login to the Application**
   - Login with the App Credentials as per the environmental file


5. **Place Order**
   - Place Order with the /placeorder route with the following sample post message
      <br>
      <code>
      {
      "apikey":"5dfs3f4",
      "tradingsymbol":"SBIN-EQ",
      "symboltoken":"3045",
      "transactiontype":"BUY",
      "exchange":"NSE",
      "ordertype":"MARKET",
      "producttype":"INTRADAY",
      "quantity":"1"
      }</code>


## Documentation

For detailed documentation on AlgoBridge, including setup guides, API references, and usage examples, refer to the `docs` folder within the repository.

## Contributing

We welcome contributions to AlgoBridge! If you're interested in improving the application or adding new features, please feel free to fork the repository, make your changes, and submit a pull request.

## License

AlgoBridge is released under the MIT License. See the LICENSE file for more details.

## Contact

For support, feature requests, or to contribute further, please contact us via GitHub issues.

Embrace the future of trading with AlgoBridge, your partner in maximizing algotrading performance.


[![Deploy with Vercel](https://vercel.com/button)](https://vercel.com/new/clone?repository-url=https://github.com/marketcalls/algobridge)
