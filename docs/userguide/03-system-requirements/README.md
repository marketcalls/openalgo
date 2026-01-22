# 03 - System Requirements

## Introduction

OpenAlgo is designed to run on modest hardware. This guide helps you understand what you need and choose the right setup for your needs.

## Minimum Requirements

### For Basic Usage

| Component | Minimum | Recommended |
|-----------|---------|-------------|
| RAM | 2 GB | 4 GB |
| CPU | 1 vCPU | 2 vCPU |
| Storage | 1 GB | 5 GB |
| OS | Windows 10/11, Ubuntu 20.04+, macOS 11+ | Ubuntu 22.04 LTS |
| Python | 3.11 | 3.12 |
| Network | Stable internet | Low-latency connection |

### For Advanced Usage (Python Strategies, Multiple Integrations)

| Component | Recommended |
|-----------|-------------|
| RAM | 4-8 GB |
| CPU | 2-4 vCPU |
| Storage | 10 GB SSD |
| OS | Ubuntu 22.04 LTS |
| Python | 3.12 |

## Operating System Options

### Windows (Easiest for Beginners)

**Pros**:
- Familiar interface
- Easy installation
- Good for learning

**Cons**:
- Higher resource usage
- May need restart for updates

**Best for**: Personal use, learning, testing

### Ubuntu/Linux (Recommended for Production)

**Pros**:
- Lightweight and fast
- More stable for 24/7 operation
- Better for VPS/cloud deployment

**Cons**:
- Command line knowledge helpful
- Less familiar for some users

**Best for**: Production, VPS deployment, serious traders

### macOS

**Pros**:
- Unix-based (similar to Linux)
- Good development experience

**Cons**:
- Hardware cost
- Limited cloud options

**Best for**: Developers, Mac users

## Deployment Options

### Option 1: Your Personal Computer

```
┌─────────────────────────────────────┐
│     Your Windows/Mac Computer       │
│                                     │
│  ┌─────────────────────────────┐   │
│  │       OpenAlgo              │   │
│  │       Running               │   │
│  └─────────────────────────────┘   │
│                                     │
│  Pros: Free, full control          │
│  Cons: Must keep PC on             │
└─────────────────────────────────────┘
```

**Good for**:
- Learning and testing
- Occasional trading
- Manual monitoring

**Limitations**:
- PC must be on during trading hours
- Internet must be stable
- PC restart = OpenAlgo restart

### Option 2: Cloud VPS (Recommended)

```
┌─────────────────────────────────────┐
│         Cloud Provider              │
│    (AWS, DigitalOcean, etc.)        │
│                                     │
│  ┌─────────────────────────────┐   │
│  │       OpenAlgo              │   │
│  │    Running 24/7             │   │
│  └─────────────────────────────┘   │
│                                     │
│  Pros: Always on, reliable         │
│  Cons: Monthly cost                │
└─────────────────────────────────────┘
```

**Good for**:
- Serious automated trading
- TradingView/ChartInk integration
- Reliability required

**Popular VPS Providers**:

| Provider | Cheapest Plan | RAM | Best For |
|----------|--------------|-----|----------|
| DigitalOcean | $6/month | 1 GB | Beginners |
| AWS Lightsail | $5/month | 1 GB | AWS ecosystem |
| Hetzner | €4/month | 2 GB | Europe |
| Contabo | $6/month | 4 GB | Best value |
| Hostinger | $5/month | 1 GB | Budget |

### Option 3: Local Server / Raspberry Pi

**Good for**:
- Tech enthusiasts
- Low power consumption
- Always-on home setup

**Requirements**:
- Raspberry Pi 4 (4GB+ RAM) or mini PC
- Stable internet with static IP or dynamic DNS

## Network Requirements

### Internet Speed

| Activity | Minimum | Recommended |
|----------|---------|-------------|
| Basic trading | 1 Mbps | 10 Mbps |
| WebSocket streaming | 5 Mbps | 25 Mbps |
| Multiple strategies | 10 Mbps | 50 Mbps |

### Latency Considerations

```
Your Location → Internet → Broker Server

Lower latency = Faster order execution
```

**Tips for low latency**:
- Use wired connection (not WiFi)
- Choose VPS in same region as broker
- Avoid VPN unless necessary

### Firewall & Ports

OpenAlgo uses these ports:

| Port | Purpose | Required |
|------|---------|----------|
| 5000 | Web interface | Yes |
| 8765 | WebSocket | For streaming |
| 443 | HTTPS (external) | For webhooks |

**For webhooks from TradingView/ChartInk**:
- Your server must be accessible from internet
- Need port 443 (HTTPS) or use ngrok

## Software Requirements

### Required Software

| Software | Version | Purpose |
|----------|---------|---------|
| Python | 3.11, 3.12, 3.13, or 3.14 | Core runtime |
| pip/uv | Latest | Package management |
| Git | Latest | Download OpenAlgo |
| Web Browser | Chrome/Firefox | Access interface |

### For Development/Frontend

| Software | Version | Purpose |
|----------|---------|---------|
| Node.js | 20+ | Frontend development |
| npm | Latest | Node package manager |

## Choosing Your Setup

### Scenario 1: "I'm just learning"

**Recommendation**: Your personal computer
- Cost: Free
- Setup: Easy
- Time to start: 30 minutes

### Scenario 2: "I want to automate TradingView"

**Recommendation**: Cloud VPS (DigitalOcean/AWS)
- Cost: $5-10/month
- Setup: Medium
- Why: TradingView webhooks need public URL

### Scenario 3: "I'm a serious trader"

**Recommendation**: Cloud VPS + Domain + SSL
- Cost: $10-20/month
- Setup: Advanced
- Why: Reliability, security, monitoring

### Scenario 4: "I manage multiple accounts"

**Recommendation**: Dedicated VPS (4GB+ RAM)
- Cost: $20-40/month
- Setup: Advanced
- Why: Multiple instances, more resources

## Pre-Installation Checklist

Before you install, confirm:

- [ ] Operating system is supported
- [ ] At least 2 GB RAM available
- [ ] At least 1 GB free disk space
- [ ] Stable internet connection
- [ ] Python 3.11+ installed (or will install)
- [ ] Know which broker you'll use
- [ ] Have broker API credentials ready

## Quick Specs Summary

```
Minimum Setup:
┌─────────────────────────────┐
│ • 2 GB RAM                  │
│ • 1 vCPU                    │
│ • 1 GB Storage              │
│ • Python 3.11+              │
│ • Stable Internet           │
└─────────────────────────────┘

Recommended Setup:
┌─────────────────────────────┐
│ • 4 GB RAM                  │
│ • 2 vCPU                    │
│ • 5 GB SSD                  │
│ • Python 3.12               │
│ • Ubuntu 22.04 LTS          │
│ • Low-latency connection    │
└─────────────────────────────┘
```

---

**Previous**: [02 - Key Concepts](../02-key-concepts/README.md)

**Next**: [04 - Installation Guide](../04-installation/README.md)
