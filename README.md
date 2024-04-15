# OpenAlgo - Take Control of Your Algo Platform

OpenAlgo is an open-source, Flask-based Python application designed to bridge the gap between traders and major trading platforms such as Amibroker, Tradingview, Excel, and Google Spreadsheets. With a focus on simplifying algotrading, OpenAlgo facilitates easy integration, automation, and execution of trading strategies, providing a user-friendly interface to enhance trading performance.

[![What is OpenAlgo?](https://img.youtube.com/vi/Afthm49vtAA/maxresdefault.jpg)](https://www.youtube.com/watch?v=Afthm49vtAA)


## Supported Broker

- **AngelOne**
- **Fyers**
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

[![Windows Installation Procedure](https://img.youtube.com/vi/PCPAeDKTh50/maxresdefault.jpg)](https://www.youtube.com/watch?v=PCPAeDKTh50)


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


## Windows and Linux Complete Configuration Instructions 

For Configuration Instructions Visit the Tutorial
[https://docs.openalgo.in](https://docs.openalgo.in)


Congratulations! You have successfully set up OpenAlgo. Explore the platform and start maximizing your trading performance through automation.

