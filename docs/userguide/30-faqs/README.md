# 30 - Frequently Asked Questions (FAQs)

## General Questions

### What is OpenAlgo?

OpenAlgo is an open-source algorithmic trading platform that connects various trading platforms (TradingView, Amibroker, Python) to Indian stock brokers through a unified API.

### Is OpenAlgo free?

Yes, OpenAlgo is completely free and open-source. You can download, use, and modify it without any cost.

### Which brokers are supported?

OpenAlgo supports 24+ Indian brokers including:
- Zerodha
- Angel One
- Dhan
- Upstox
- Fyers
- And many more (see full list in documentation)

### Can I use OpenAlgo for live trading?

Yes, OpenAlgo supports live trading with real money. However, we strongly recommend:
1. Testing in Analyzer Mode first
2. Starting with small quantities
3. Monitoring your first few trades closely

### Do I need programming knowledge?

- **Basic usage**: No, you can use TradingView alerts without coding
- **Advanced features**: Basic understanding helps
- **Custom strategies**: Programming knowledge required

## Setup Questions

### What are the system requirements?

| Requirement | Minimum |
|-------------|---------|
| Python | 3.12+ |
| RAM | 4 GB |
| Storage | 1 GB |
| OS | Windows 10+, Ubuntu 20+, macOS 11+ |
| Internet | Stable broadband |

### How do I install OpenAlgo?

```bash
# Clone repository
git clone https://github.com/marketcalls/openalgo.git
cd openalgo

# Setup environment
cp .sample.env .env

# Run
uv run app.py
```

See [Installation Guide](../04-installation/README.md) for details.

### Can I run OpenAlgo on a VPS/Cloud?

Yes, OpenAlgo can run on:
- AWS EC2/Lightsail
- Google Cloud
- DigitalOcean
- Azure
- Any Linux VPS

### How do I update OpenAlgo?

```bash
cd openalgo
git pull origin main
uv sync
```

## Broker Questions

### Why do I need to login daily?

Most Indian brokers require daily authentication for security. This is a broker requirement, not an OpenAlgo limitation.

### Can I use multiple brokers?

Currently, OpenAlgo supports one broker at a time. You can switch between brokers by changing the configuration.

### Why is my broker not connecting?

Common reasons:
1. Incorrect API credentials
2. API not enabled in broker account
3. IP not whitelisted
4. Broker service is down

See [Troubleshooting](../29-troubleshooting/README.md) for solutions.

### Do I need to pay for broker API access?

Most brokers provide API access free or at minimal cost. Check with your specific broker.

## Trading Questions

### What is the latency for order execution?

Typical latency:
- OpenAlgo processing: 5-20ms
- Broker API: 50-200ms
- Total: 100-500ms

See [Latency Monitor](../25-latency-monitor/README.md) for details.

### Can I trade F&O (Futures & Options)?

Yes, OpenAlgo fully supports F&O trading. Use correct symbol format:
- Futures: `NIFTY30JAN25FUT`
- Options: `NIFTY30JAN2521500CE`

### What is Analyzer Mode?

Analyzer Mode is OpenAlgo's sandbox testing environment. It simulates trading with ₹1 Crore sandbox capital using real market prices but no real money.

### Can I backtest strategies?

OpenAlgo is primarily for live trading and walkforward testing strategies. For backtesting:
- Use TradingView's strategy tester
- Use Amibroker's backtesting
- Use Python backtesting libraries

### What happens if OpenAlgo crashes during a trade?

- Open positions remain with your broker
- You can manage them through broker terminal
- Always have access to broker's trading platform

## API Questions

### How do I get an API key?

1. Login to OpenAlgo
2. Go to API Key page
3. Click Generate New Key
4. Copy and store securely

### Can I use multiple API keys?

Yes, you can generate multiple API keys for different integrations.

### What is the rate limit?

Default rate limits:
- 10 requests per second
- 1000 requests per day

These can be configured in settings.

### Is the API secure?

Yes:
- API keys are hashed
- HTTPS encryption supported
- IP whitelisting available
- Rate limiting prevents abuse

## TradingView Questions

### How do I connect TradingView to OpenAlgo?

1. Enable OpenAlgo accessible via internet (ngrok/cloud)
2. Create webhook alert in TradingView
3. Use OpenAlgo endpoint URL
4. Configure JSON payload

See [TradingView Integration](../16-tradingview-integration/README.md).

### What TradingView plan do I need?

- Essential or higher for webhooks
- Free plan doesn't support webhooks

### Why aren't my TradingView alerts working?

Check:
1. Webhook URL is correct and accessible
2. JSON payload format is valid
3. API key is correct
4. Broker is logged in
5. Market is open

### Can I use TradingView variables?

Yes:
- `{{ticker}}` - Symbol
- `{{strategy.order.action}}` - BUY/SELL
- `{{strategy.position_size}}` - Position
- See TradingView documentation for more

## Python Questions

### How do I install the Python library?

```bash
pip install openalgo
```

### Can I run multiple strategies?

Yes, you can run multiple Python scripts simultaneously with different strategy names.

### Where can I find example strategies?

- Check the `examples/` folder in repository
- See [Python Strategies](../20-python-strategies/README.md)
- GitHub discussions and community

## Security Questions

### Is my data safe?

- Credentials encrypted at rest
- API keys hashed
- Local database (your control)
- Open-source (auditable code)

### Should I enable 2FA?

Yes, we strongly recommend enabling Two-Factor Authentication for additional security.

### What if I lose my 2FA device?

Use recovery codes to regain access. Store them safely when setting up 2FA.

### How do I report a security issue?

Report security vulnerabilities to: security@openalgo.in (or via GitHub private advisory)

## Static IP Questions

### Do I need a static IP for algo trading?

Some brokers require static IP registration for API access, especially when placing orders. Check your broker's API developer portal for requirements.

### Can I deploy on cloud services without static IP registration?

No. Even on cloud platforms (AWS, GCP, Azure), you need to register your static IP with your broker. However, VPS providers like DigitalOcean, Vultr, and OVH provide static IPs by default.

### What if I travel or work from different locations?

You can update your registered IP, but most brokers only allow changes once a week through their API developer portal. Daily switching isn't feasible.

### Can I register more than one static IP?

Yes, most brokers allow a primary and backup IP per app. However, changing IPs frequently goes against broker guidelines.

### Do I need a static IP for streaming market data only?

No. If your app only receives data and doesn't place or modify orders, static IP registration may not be required. Check your specific broker's requirements.

### Can I use an IP from any country?

Yes, as long as the country is not on the broker's restricted list. You can host from India, US, Europe, or other approved regions.

### Can I use one static IP for multiple trading accounts?

You can use the same IP across different brokers. But for multiple accounts with the same broker, each may require its own registered IP.

### What if my strategy places many orders?

If your strategy consistently places over 10 orders per second, you may need formal registration with your broker. Occasional spikes are typically okay.

## Support Questions

### Where can I get help?

OpenAlgo is community-driven. Get help through:

1. Documentation: [https://docs.openalgo.in](https://docs.openalgo.in)
2. Discord Community: [http://openalgo.in/discord](http://openalgo.in/discord)
3. GitHub Issues: [https://github.com/marketcalls/openalgo/issues](https://github.com/marketcalls/openalgo/issues)
4. YouTube tutorials: For video guides

### How do I report a bug?

1. Go to GitHub Issues
2. Use the bug report template
3. Include:
   - OpenAlgo version
   - Steps to reproduce
   - Error messages
   - Screenshots

### Can I request features?

Yes! Submit feature requests on GitHub Issues with the "enhancement" label.

### How can I contribute?

- Report bugs
- Submit feature requests
- Contribute code (PRs welcome)
- Improve documentation
- Help other users

## Pricing Questions

### Is OpenAlgo really free?

Yes, OpenAlgo is 100% free and open-source under the AGPL license.

### Are there any hidden costs?

No hidden costs from OpenAlgo. You may have:
- Broker API charges (varies by broker)
- Cloud hosting costs (if using cloud)
- TradingView subscription (for webhooks)

### Do you offer paid support?

Currently, support is community-based. For enterprise needs, contact the maintainers.

## Common Misconceptions

### "OpenAlgo is a trading bot"

OpenAlgo is a **bridge/platform**, not a trading bot. It connects your strategy signals to your broker. You still need to create or use existing strategies.

### "I can make guaranteed profits"

No trading system guarantees profits. OpenAlgo is a tool - your results depend on your strategy.

### "It works without internet"

OpenAlgo requires internet connection to communicate with brokers and receive signals.

### "I can trade after market hours"

OpenAlgo follows exchange timings. F&O can be traded during extended hours as per exchange rules.

## Symbol Format Quick Reference

```
Equity:   SBIN
Futures:  NIFTY30JAN25FUT  (Symbol + DD + MMM + YY + FUT)
Options:  NIFTY30JAN2521500CE  (Symbol + DD + MMM + YY + Strike + CE/PE)

Exchanges: NSE, BSE, NFO, BFO, CDS, MCX
Products:  MIS (intraday), CNC (delivery), NRML (F&O overnight)
```

## Still Have Questions?

If your question isn't answered here:

1. Search the [documentation](../README.md)
2. Check [GitHub Discussions](https://github.com/marketcalls/openalgo/discussions)
3. Ask in community forums
4. Create a GitHub issue

---

**Previous**: [29 - Troubleshooting](../29-troubleshooting/README.md)

**Return to**: [User Guide Home](../README.md)
