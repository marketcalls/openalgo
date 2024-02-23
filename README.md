# OpenAlgo - Take Control of Your Algo Platform

OpenAlgo is an open-source, Flask-based Python application designed to bridge the gap between traders and major trading platforms such as Amibroker, Tradingview, Excel, and Google Spreadsheets. With a focus on simplifying algotrading, OpenAlgo facilitates easy integration, automation, and execution of trading strategies, providing a user-friendly interface to enhance trading performance.

## Supported Broker

- **AngelOne**

## Features

- **Comprehensive Integration**: Seamlessly connect with Amibroker, Tradingview, Excel, and Google Spreadsheets for smooth data and strategy transition.
- **User-Friendly Interface**: A straightforward Flask-based application interface accessible to traders of all levels of expertise.
- **Real-Time Execution**: Implement your trading strategies in real time, ensuring immediate action to capitalize on market opportunities.
- **Customizable Strategies**: Easily adapt and tailor your trading strategies to meet your specific needs, with extensive options for customization and automation.
- **Secure and Reliable**: With a focus on security and reliability, OpenAlgo provides a dependable platform for your algotrading activities, safeguarding your data and trades.

## Documentation

For detailed documentation on OpenAlgo, including setup guides, API references, and usage examples, refer to the `docs` folder within the repository.

## Contributing

We welcome contributions to OpenAlgo! If you're interested in improving the application or adding new features, please feel free to fork the repository, make your changes, and submit a pull request.

## License

OpenAlgo is released under the MIT License. See the `LICENSE` file for more details.

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
- **PostgreSQL** for Windows (current version 16).

### Setup

1. **Install VS Code Extensions**: Open VS Code, navigate to the Extensions section on the left tab, and install the Python, Pylance, and Jupyter extensions.
2. **Clone the Repository**: Open the VS Code Terminal and clone the OpenAlgo repository with the command:

<code>git clone https://github.com/marketcalls/openalgo</code>

3. **Install Dependencies**: Navigate to the directory where OpenAlgo is cloned and execute:

<code>pip install -r requirements.txt</code>

to install the necessary Python libraries.

4. **Set Up PostgreSQL**:
- Download and install PostgreSQL for Windows.
- Remember the password you set during installation; the default username is `postgres`.
- Use pgAdmin 4 to create a localhost server and a new database named `openalgo_db`.

5. **Configure Environment Variables**: Update the `.env` file located in `/openalgo/api/` with your specific configurations as shown in the provided template.

6. **Run the Application**: From the `/openalgo/api` directory, start the Flask application with the command:

<code>python index.py</code>


### Accessing OpenAlgo

After completing the setup, access the OpenAlgo platform by navigating to [http://127.0.0.1:5000](http://127.0.0.1:5000) in your web browser. Log in using the credentials you defined in the `.env` file.

### Connecting Trading Platforms

You can now connect your Amibroker and Tradingview modules to transmit orders, and use the Flask application to monitor trades.

### Place Order


Place Order with the /placeorder route with the following sample post message
<code>
{
"apikey":"5dfs3f4",
"tradingsymbol":"SBIN-EQ",
"transactiontype":"BUY",
"exchange":"NSE",
"ordertype":"MARKET",
"producttype":"INTRADAY",
"quantity":"1"
}</code>
<br>
Congratulations! You have successfully set up OpenAlgo. Explore the platform and start maximizing your trading performance through automation.

