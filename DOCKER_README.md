# OpenAlgo - Algorithmic Trading Platform

OpenAlgo is a production-ready algorithmic trading platform providing a unified API layer across 24+ Indian brokers. Seamlessly integrate with TradingView, Amibroker, Excel, Python, and AI agents.

## Quick Start

### Windows
```powershell
curl.exe -O https://raw.githubusercontent.com/marketcalls/openalgo/main/install/docker-run.bat
docker-run.bat
```

### macOS / Linux
```bash
curl -O https://raw.githubusercontent.com/marketcalls/openalgo/main/install/docker-run.sh
chmod +x docker-run.sh
./docker-run.sh
```

## What's Included

- **Web UI**: http://127.0.0.1:5000
- **WebSocket**: ws://127.0.0.1:8765
- **REST API**: Full Swagger documentation at `/api/docs`
- **Automatic Setup**: Secure key generation, broker configuration
- **Auto Migrations**: Database updates on container start

## Supported Brokers

Zerodha, Fyers, Angel One, Dhan, Upstox, Shoonya, Flattrade, Kotak, IIFL, 5paisa, AliceBlue, Firstock, Groww, IndMoney, Motilal Oswal, MStock, Paytm Money, Pocketful, Samco, Tradejini, Zebu, and more.

## Management Commands

```bash
# Windows
docker-run.bat start      # Start OpenAlgo
docker-run.bat stop       # Stop OpenAlgo
docker-run.bat restart    # Update & restart
docker-run.bat logs       # View logs
docker-run.bat status     # Check status

# macOS / Linux
./docker-run.sh start
./docker-run.sh stop
./docker-run.sh restart
./docker-run.sh logs
./docker-run.sh status
```

## Data Persistence

All data is stored locally in the script directory:
- `db/` - SQLite databases
- `strategies/` - Python strategy scripts
- `log/` - Application and strategy logs
- `.env` - Configuration file

## Documentation

- **Full Docs**: https://docs.openalgo.in
- **Installation Guide**: https://github.com/marketcalls/openalgo/blob/main/install/Docker-install-readme.md
- **GitHub**: https://github.com/marketcalls/openalgo

## Community

- **Discord**: https://discord.com/invite/UPh7QPsNhP
- **YouTube**: https://youtube.com/@openalgoHQ
- **Website**: https://openalgo.in

## License

AGPL V3.0 License
