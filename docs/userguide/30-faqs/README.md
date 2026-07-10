# 30 - Frequently Asked Questions

## General

### What is OpenAlgo?

OpenAlgo is a self-hosted, open-source trading automation platform. It connects external strategies and applications to broker adapters through a common REST API and normalized market-data interfaces.

### Is OpenAlgo free?

Yes. OpenAlgo is released under the AGPL v3.0 license. Broker API access, market-data subscriptions, hosting, domains, and third-party services can have separate costs.

### Which brokers are supported?

The current repository contains 34 plugin directories: 33 securities integrations and Delta Exchange for crypto derivatives. See [Broker Connection](../06-broker-connection/README.md) for the authoritative plugin identifiers. Supported exchanges and features vary by plugin.

### Can I use live trading?

Yes, after a broker is configured and authenticated. Test the same workflow in Analyzer Mode first, start with small quantities, and keep direct access to the broker terminal.

### Do I need programming knowledge?

The dashboard, TradingView webhooks, Analyzer Mode, and Flow builder cover workflows that need little or no code. Custom Python strategies and direct API integrations require development experience.

## Installation and Updates

### What does the current build require?

OpenAlgo requires Python 3.12 or newer. Resource needs depend on market-data subscriptions, strategy count, Historify data volume, and deployment topology. See [System Requirements](../03-system-requirements/README.md) and the platform-specific installation guide.

### How do I update an installed instance?

From the repository root run:

```bash
bash install/update.sh
```

The updater backs up its configured data set, synchronizes code and dependencies, runs `upgrade/migrate_all.py`, rebuilds the frontend, and restarts services where applicable. Back up `db/health.db` separately because the current automatic backup list does not include it.

### Can I run OpenAlgo on a VPS?

Yes. Use a supported production installer, TLS, a controlled reverse proxy, host firewall rules, and persistent backups. Broker static-IP and callback requirements are broker policies; verify the current rules in that broker's developer portal.

## Broker Sessions

### Why am I asked to reconnect?

Broker authentication lifetimes are controlled by the adapter and broker. If a broker token expires while the OpenAlgo session remains active, OpenAlgo redirects to `/broker` so the connection can be re-established.

### Can one instance use multiple brokers at once?

No. One instance has one configured broker. Run isolated instances with separate configuration, ports, databases, and service definitions for concurrent brokers.

### Why does broker login fail?

Check the broker-specific key format, callback URL, app status, credential expiry, and whether the broker requires a current token, consent, TOTP, or registered IP. Application and broker logs usually contain the adapter's error response.

## Trading and Data

### What latency should I expect?

There is no universal value. Network distance, broker response time, connection reuse, exchange load, order type, and the host all contribute. Use OpenAlgo's [Latency Monitor](../25-latency-monitor/README.md) on the actual deployment instead of relying on a fixed benchmark.

### What is Analyzer Mode?

Analyzer Mode routes supported order workflows to the sandbox database instead of the live broker. It starts with configured sandbox capital and is intended for API and strategy validation, not exchange-accurate backtesting.

### Does OpenAlgo provide backtesting?

Historify stores historical data and OpenAlgo supports live or walk-forward strategy execution. Use a dedicated backtesting engine or the testing tools in your charting platform for portfolio backtests.

### What happens if OpenAlgo stops while a position is open?

The position remains at the broker. Use the broker terminal to monitor or close it. Process supervision and health monitoring reduce downtime but do not replace broker-side risk controls.

## REST API

### Where is the API reference?

Use the maintained [REST API documentation](../../api/README.md). Interactive Swagger is intentionally disabled (`doc=False`), so `/api/docs` is not a supported route.

### How do I get an API key?

Sign in, open the API Key page, and generate or regenerate the instance key. Store it as a secret. The database keeps a hash rather than the raw value.

### What are the rate limits?

Limits are endpoint-specific and configurable through environment variables such as `API_RATE_LIMIT`, `ORDER_RATE_LIMIT`, `SMART_ORDER_RATE_LIMIT`, and the webhook and strategy limits. A deployment's `.env` is authoritative.

### Does an API key have per-operation permissions?

Not currently. A valid key can call the public REST operations exposed by the instance, subject to request validation, mode, Action Center behavior, and rate limits.

## Security

### What should be protected?

Protect `.env`, database files, MCP signing keys, backups, and the raw OpenAlgo API key. Use TLS for remote access, enable TOTP, and do not expose Flask directly to the internet.

### Does OpenAlgo support IP whitelisting?

The application supports individual IP bans and automatic abuse thresholds, but it does not currently implement a CIDR allowlist. Use a firewall, cloud security group, VPN, or reverse-proxy policy for allowlisting.

### Does Traffic Logs store order payloads?

No. It stores metadata such as timestamp, method, path, status, duration, IP, host, and an unhandled error field. Request and response bodies are not captured.

## Integrations

### How do I connect TradingView?

Expose OpenAlgo through HTTPS, create an alert with a valid OpenAlgo JSON payload, and use the webhook URL documented in [TradingView Integration](../16-tradingview-integration/README.md). Webhook availability depends on the TradingView plan and current TradingView policy.

### How do I install the Python SDK?

```bash
pip install openalgo
```

The SDK can connect to any reachable OpenAlgo instance when given its host URL and API key.

### Can multiple strategies run concurrently?

Yes. Strategy isolation and host capacity still matter; use unique strategy names, review schedules, and monitor logs and resource usage.

## Support

- Documentation: [docs.openalgo.in](https://docs.openalgo.in)
- GitHub issues: [github.com/marketcalls/openalgo/issues](https://github.com/marketcalls/openalgo/issues)
- GitHub discussions: [github.com/marketcalls/openalgo/discussions](https://github.com/marketcalls/openalgo/discussions)
- Community: [openalgo.in/discord](https://openalgo.in/discord)

When reporting a bug, include the OpenAlgo version, deployment method, reproduction steps, relevant redacted logs, and the expected versus actual behavior. Never attach `.env`, API keys, broker credentials, or session tokens.

---

**Previous**: [29 - Troubleshooting](../29-troubleshooting/README.md)

**Return to**: [User Guide Home](../README.md)
