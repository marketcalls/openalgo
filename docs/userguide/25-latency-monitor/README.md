# 25 - Latency Monitor

## Introduction

The Latency Monitor tracks the time taken for various operations in OpenAlgo, from receiving signals to order execution. Understanding and optimizing latency is critical for algorithmic trading, especially for time-sensitive strategies.

## What is Latency?

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                        Order Execution Latency                              │
│                                                                              │
│  Signal Source → OpenAlgo Processing → Broker API → Exchange → Execution   │
│       │               │                    │            │           │       │
│       │←── Network ──▶│←── Processing ────▶│←─ Broker ─▶│←─ Exch ──▶│       │
│       │    Latency    │     Latency        │   Latency  │  Latency  │       │
│       │               │                    │            │           │       │
│       └───────────────┴────────────────────┴────────────┴───────────┘       │
│                                                                              │
│                        Total End-to-End Latency                             │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

## Latency Components

| Component | Description | Typical Range |
|-----------|-------------|---------------|
| Network Latency | Signal source to OpenAlgo | 50-500ms |
| Processing Latency | OpenAlgo internal processing | 1-10ms |
| API Latency | OpenAlgo to Broker API | 50-200ms |
| Broker Latency | Broker to Exchange | 10-50ms |
| Exchange Latency | Order matching | 1-5ms |

## Accessing Latency Monitor

Navigate to **Latency** in the sidebar.

## Dashboard Overview

```
┌─────────────────────────────────────────────────────────────────────────────┐
│  Latency Monitor                                   [Today] [Week] [Month]   │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  ┌───────────────┐  ┌───────────────┐  ┌───────────────┐  ┌─────────────┐  │
│  │ Avg Latency   │  │ Min Latency   │  │ Max Latency   │  │ 99th %ile   │  │
│  │   156ms       │  │    45ms       │  │   890ms       │  │   420ms     │  │
│  │   ↓ 12%       │  │               │  │               │  │             │  │
│  └───────────────┘  └───────────────┘  └───────────────┘  └─────────────┘  │
│                                                                              │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │                     LATENCY OVER TIME                                │   │
│  │  500ms │                                                             │   │
│  │        │     ∧           ∧                                           │   │
│  │  300ms │    / \    ∧    / \                                          │   │
│  │        │   /   \  / \  /   \    ∧                                    │   │
│  │  100ms │──/─────\/───\/─────\──/─\──────────────────                 │   │
│  │        │                                                             │   │
│  │    0ms └─────────────────────────────────────────────                │   │
│  │          09:30   10:00   10:30   11:00   11:30                       │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│                                                                              │
│  ┌──────────────────────────────┐  ┌────────────────────────────────┐      │
│  │  LATENCY DISTRIBUTION        │  │  COMPONENT BREAKDOWN           │      │
│  │  ─────────────────────        │  │  ───────────────────            │      │
│  │  <100ms:  ████████████ 65%   │  │  Network:    ████░░ 40%        │      │
│  │  100-200: ██████ 25%         │  │  Processing: █░░░░░ 5%         │      │
│  │  200-500: ███ 8%             │  │  Broker API: ██████ 45%        │      │
│  │  >500ms:  █ 2%               │  │  Other:      ██░░░░ 10%        │      │
│  └──────────────────────────────┘  └────────────────────────────────┘      │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

## Metrics Explained

### Average Latency

Mean time from signal receipt to order placement.

```
Avg Latency = Σ(Individual Latencies) / Number of Orders

Good: <200ms
Acceptable: 200-500ms
Needs Improvement: >500ms
```

### Minimum Latency

Best-case latency achieved.

```
Min Latency = Lowest recorded latency

Indicates optimal conditions
Benchmark for improvements
```

### Maximum Latency

Worst-case latency recorded.

```
Max Latency = Highest recorded latency

Investigate causes:
- Network spikes
- Server overload
- Broker API issues
```

### Percentiles

```
50th Percentile (Median): Half of orders faster than this
90th Percentile: 90% of orders faster than this
99th Percentile: 99% of orders faster than this

Example:
99th %ile = 420ms
→ 99% of orders complete within 420ms
→ Only 1% take longer
```

## Latency Breakdown

### Component-Level Analysis

```
┌─────────────────────────────────────────────────────────────────────────────┐
│  Component Latency Breakdown                                                │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  Component          Avg      Min      Max      % of Total                   │
│  ────────────────   ───────  ───────  ───────  ──────────                   │
│  Network Ingress    62ms     20ms     350ms    40%                          │
│  Authentication     5ms      2ms      15ms     3%                           │
│  Validation         3ms      1ms      10ms     2%                           │
│  Order Processing   8ms      3ms      25ms     5%                           │
│  Broker API Call    70ms     30ms     400ms    45%                          │
│  Response Handling  8ms      3ms      20ms     5%                           │
│  ────────────────   ───────  ───────  ───────  ──────────                   │
│  Total              156ms    45ms     890ms    100%                         │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

### Identifying Bottlenecks

| High Latency In | Possible Cause | Solution |
|-----------------|----------------|----------|
| Network Ingress | Slow connection | Upgrade internet, use local server |
| Authentication | Token refresh | Implement token caching |
| Broker API Call | Broker server load | Contact broker, optimize requests |
| Order Processing | Heavy computation | Optimize code, upgrade hardware |

## Historical Analysis

### Time-Based Patterns

```
┌─────────────────────────────────────────────────────────────────────────────┐
│  Latency by Time of Day                                                     │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  Time         Avg Latency    Orders    Notes                               │
│  ──────────   ───────────    ──────    ─────                               │
│  09:15-09:30  285ms          45        Market opening - high load          │
│  09:30-10:00  180ms          120       Moderate activity                   │
│  10:00-12:00  145ms          250       Normal trading                      │
│  12:00-14:00  130ms          80        Low activity                        │
│  14:00-15:00  160ms          180       Increased activity                  │
│  15:00-15:30  320ms          60        Market closing - high load          │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

### Day-by-Day Comparison

```
┌─────────────────────────────────────────────────────────────────────────────┐
│  Weekly Latency Comparison                                                  │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  Day        Avg      Min      Max      Orders    Spikes                    │
│  ─────────  ───────  ───────  ───────  ──────    ──────                    │
│  Monday     165ms    50ms     520ms    180       2                         │
│  Tuesday    152ms    48ms     480ms    195       1                         │
│  Wednesday  148ms    45ms     390ms    210       0                         │
│  Thursday   158ms    52ms     890ms    175       3                         │
│  Friday     172ms    55ms     650ms    155       2                         │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

## Alerts and Thresholds

### Configuring Alerts

1. Go to **Latency** → **Alerts**
2. Set thresholds:

| Alert Type | Threshold | Action |
|------------|-----------|--------|
| High Latency | >500ms | Warning notification |
| Critical Latency | >1000ms | Critical alert |
| Sustained High | Avg >300ms for 5min | Investigation alert |
| Spike Detection | >2x average | Spike notification |

### Alert Example

```
⚠️ LATENCY ALERT

High latency detected!

Current: 750ms
Threshold: 500ms
Component: Broker API

Time: 2025-01-21 10:30:15
Orders affected: 3

Recommendation:
- Check broker API status
- Verify network connectivity
```

## Optimization Tips

### 1. Network Optimization

```
Current Setup:
Signal Source → Internet → OpenAlgo

Optimized Setup:
Signal Source → Same Network → OpenAlgo (Co-located)

Improvement: 50-100ms reduction
```

### 2. Broker API Optimization

| Technique | Benefit |
|-----------|---------|
| Connection pooling | Faster subsequent requests |
| Token caching | Avoid re-authentication |
| Batch orders | Reduce API calls |
| Pre-validation | Fail fast on invalid orders |

### 3. Server Optimization

| Upgrade | Impact |
|---------|--------|
| SSD storage | Faster database operations |
| More RAM | Better caching |
| Better CPU | Faster processing |
| Local deployment | Reduced network latency |

### 4. Code Optimization

```python
# Before: Multiple API calls
for order in orders:
    place_order(order)  # 150ms each

# After: Batch API call
place_basket_order(orders)  # 200ms total
```

## Comparing Brokers

### Broker Latency Comparison

```
┌─────────────────────────────────────────────────────────────────────────────┐
│  Broker API Latency Comparison                                              │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  Broker        Avg      P99      Orders    Status                          │
│  ──────────    ───────  ───────  ──────    ──────                          │
│  Zerodha       65ms     180ms    500       ✅ Excellent                    │
│  Angel One     75ms     200ms    450       ✅ Good                         │
│  Dhan          70ms     190ms    480       ✅ Good                         │
│  Upstox        80ms     220ms    420       ✅ Good                         │
│  Fyers         85ms     250ms    380       ⚠️ Fair                        │
│                                                                              │
│  Note: Latency varies by time of day and market conditions                 │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

## Export and Reporting

### Export Latency Data

1. Click **Export**
2. Select format (CSV, JSON)
3. Choose date range
4. Download file

### Generate Report

1. Click **Generate Report**
2. Select time period
3. PDF report generated with:
   - Summary statistics
   - Charts and graphs
   - Recommendations

## Best Practices

### 1. Monitor Regularly

- Check daily latency trends
- Investigate spikes immediately
- Compare across time periods

### 2. Set Appropriate Thresholds

- Based on strategy requirements
- Account for market conditions
- Adjust as system improves

### 3. Optimize Proactively

- Don't wait for problems
- Test improvements in sandbox
- Document changes and results

### 4. Consider Strategy Requirements

| Strategy Type | Acceptable Latency |
|---------------|-------------------|
| Scalping | <100ms |
| Intraday | <300ms |
| Positional | <1000ms |
| Long-term | Less critical |

---

**Previous**: [24 - PnL Tracker](../24-pnl-tracker/README.md)

**Next**: [26 - Traffic Logs](../26-traffic-logs/README.md)
