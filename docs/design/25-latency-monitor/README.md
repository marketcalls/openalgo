# 25 - Latency Monitor

## Overview

OpenAlgo tracks order execution latency at multiple stages to help identify performance bottlenecks and ensure SLA compliance.

## Architecture Diagram

```
┌──────────────────────────────────────────────────────────────────────────────┐
│                       Latency Monitoring Architecture                        │
└──────────────────────────────────────────────────────────────────────────────┘

                              Order Request
                                   │
                                   ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                          Latency Tracking Points                             │
│                                                                              │
│  T0: Request Received ───────────────────────────────────────────────────►  │
│           │                                                                  │
│           ▼                                                                  │
│  ┌─────────────────┐                                                         │
│  │  Validation     │  ← T1: validation_latency_ms                           │
│  │  (API key,      │                                                         │
│  │   schema)       │                                                         │
│  └────────┬────────┘                                                         │
│           │                                                                  │
│           ▼                                                                  │
│  ┌─────────────────┐                                                         │
│  │  Broker API     │  ← T2: rtt_ms (Round-Trip Time)                        │
│  │  Request/       │                                                         │
│  │  Response       │                                                         │
│  └────────┬────────┘                                                         │
│           │                                                                  │
│           ▼                                                                  │
│  ┌─────────────────┐                                                         │
│  │  Response       │  ← T3: response_latency_ms                             │
│  │  Processing     │                                                         │
│  └────────┬────────┘                                                         │
│           │                                                                  │
│           ▼                                                                  │
│  T4: Response Sent ─────────────────────────────────────────────────────►   │
│                                                                              │
│  total_latency_ms = T4 - T0                                                 │
│  overhead_ms = validation_ms + response_ms                                  │
└─────────────────────────────────────────────────────────────────────────────┘
```

## Metrics Tracked

### Latency Components

| Metric | Description |
|--------|-------------|
| rtt_ms | Broker API round-trip time |
| validation_latency_ms | Pre-request validation |
| response_latency_ms | Post-response processing |
| overhead_ms | Total OpenAlgo overhead |
| total_latency_ms | End-to-end time |

### Database Schema

```
┌────────────────────────────────────────────────────┐
│              order_latency table                    │
├──────────────────┬──────────────┬──────────────────┤
│ Column           │ Type         │ Description      │
├──────────────────┼──────────────┼──────────────────┤
│ id               │ INTEGER PK   │ Auto-increment   │
│ timestamp        │ DATETIME     │ Log time         │
│ order_id         │ VARCHAR(100) │ Order ID         │
│ user_id          │ INTEGER      │ User ID          │
│ broker           │ VARCHAR(50)  │ Broker name      │
│ symbol           │ VARCHAR(50)  │ Trading symbol   │
│ order_type       │ VARCHAR(20)  │ MARKET/LIMIT/SL  │
│ rtt_ms           │ FLOAT        │ Round-trip time  │
│ validation_ms    │ FLOAT        │ Validation time  │
│ response_ms      │ FLOAT        │ Response time    │
│ overhead_ms      │ FLOAT        │ OpenAlgo overhead│
│ total_latency_ms │ FLOAT        │ Total time       │
│ request_body     │ JSON         │ Original request │
│ response_body    │ JSON         │ Broker response  │
│ status           │ VARCHAR(20)  │ SUCCESS/FAILED   │
│ error            │ VARCHAR(500) │ Error message    │
└──────────────────┴──────────────┴──────────────────┘
```

## Implementation

### Latency Tracker Class

```python
class LatencyTracker:
    def __init__(self):
        self.start_time = time.perf_counter()
        self.validation_start = None
        self.validation_end = None
        self.broker_start = None
        self.broker_end = None
        self.response_start = None

    def mark_validation_start(self):
        self.validation_start = time.perf_counter()

    def mark_validation_end(self):
        self.validation_end = time.perf_counter()

    def mark_broker_start(self):
        self.broker_start = time.perf_counter()

    def mark_broker_end(self):
        self.broker_end = time.perf_counter()

    def get_metrics(self):
        end_time = time.perf_counter()
        return {
            'validation_ms': (self.validation_end - self.validation_start) * 1000,
            'rtt_ms': (self.broker_end - self.broker_start) * 1000,
            'response_ms': (end_time - self.broker_end) * 1000,
            'total_ms': (end_time - self.start_time) * 1000
        }
```

### Decorator Usage

```python
from utils.latency_monitor import track_latency

@bp.route('/api/v1/placeorder', methods=['POST'])
@track_latency('placeorder')
def place_order():
    # Latency automatically tracked
    pass
```

## Dashboard

### Access
```
/logs/latency
```

### Dashboard View

```
┌────────────────────────────────────────────────────────────────────────────┐
│                         Latency Dashboard                                   │
│                                                                             │
│  Average Latency: 85ms     P95: 145ms     P99: 195ms     SLA: 98.5%       │
│                                                                             │
│ ┌─────────────────────────────────────────────────────────────────────────┐│
│ │ Latency Distribution (Last 24h)                                          ││
│ │                                                                          ││
│ │  < 50ms  ████████████████████████████  45%                              ││
│ │  50-100ms  ██████████████████  35%                                      ││
│ │  100-150ms  ████████  15%                                               ││
│ │  150-200ms  ██  4%                                                      ││
│ │  > 200ms  █  1%                                                         ││
│ └─────────────────────────────────────────────────────────────────────────┘│
│                                                                             │
│ ┌─────────────────────────────────────────────────────────────────────────┐│
│ │ Recent Orders                                                            ││
│ │                                                                          ││
│ │ Time      │ Symbol   │ Broker   │ RTT    │ Total  │ Status              ││
│ ├───────────┼──────────┼──────────┼────────┼────────┼─────────────────────┤│
│ │ 09:30:15  │ SBIN     │ zerodha  │ 65ms   │ 78ms   │ SUCCESS             ││
│ │ 09:30:20  │ INFY     │ dhan     │ 45ms   │ 55ms   │ SUCCESS             ││
│ │ 09:31:05  │ RELIANCE │ angel    │ 180ms  │ 195ms  │ SUCCESS             ││
│ │ 09:32:10  │ TCS      │ zerodha  │ 350ms  │ 380ms  │ TIMEOUT             ││
│ └─────────────────────────────────────────────────────────────────────────┘│
└────────────────────────────────────────────────────────────────────────────┘
```

## SLA Targets

### Performance Thresholds

| Metric | Target | Description |
|--------|--------|-------------|
| P50 | < 100ms | 50% of requests |
| P90 | < 150ms | 90% of requests |
| P95 | < 175ms | 95% of requests |
| P99 | < 200ms | 99% of requests |

### SLA Calculation

```python
def calculate_sla_compliance():
    total = LatencyLog.query.count()
    within_sla = LatencyLog.query.filter(
        LatencyLog.total_latency_ms < 200
    ).count()

    return (within_sla / total) * 100 if total > 0 else 100
```

## Broker Comparison

### Per-Broker Stats

```
┌────────────────────────────────────────────────────────────────┐
│                    Broker Latency Comparison                    │
│                                                                 │
│  Broker      │ Avg RTT  │ P95 RTT  │ Success Rate             │
│  ────────────┼──────────┼──────────┼───────────────────────── │
│  zerodha     │ 65ms     │ 120ms    │ 99.8%                    │
│  dhan        │ 45ms     │ 95ms     │ 99.9%                    │
│  angel       │ 85ms     │ 160ms    │ 99.5%                    │
│  shoonya     │ 75ms     │ 140ms    │ 99.7%                    │
│  firstock    │ 55ms     │ 110ms    │ 99.6%                    │
└────────────────────────────────────────────────────────────────┘
```

## Alerting

### Threshold Alerts

```python
def check_latency_alerts(metrics):
    if metrics['total_ms'] > 500:
        logger.warning(f"High latency: {metrics['total_ms']}ms")
        send_alert('High latency detected')

    if metrics['status'] == 'TIMEOUT':
        logger.error('Broker request timeout')
        send_alert('Broker timeout detected')
```

## HTTP Client Integration

### Connection Timing

```python
def _on_request(request):
    request.extensions['start_time'] = time.perf_counter()

def _on_response(response):
    start = response.request.extensions.get('start_time')
    if start:
        latency = (time.perf_counter() - start) * 1000
        logger.debug(f"HTTP Request: {latency:.2f}ms")
```

## Analytics Queries

### Common Queries

```python
# Average latency by broker
SELECT broker, AVG(rtt_ms) as avg_rtt
FROM order_latency
WHERE timestamp > NOW() - INTERVAL '24 hours'
GROUP BY broker

# SLA compliance by hour
SELECT
    DATE_TRUNC('hour', timestamp) as hour,
    COUNT(*) as total,
    SUM(CASE WHEN total_latency_ms < 200 THEN 1 ELSE 0 END) as within_sla
FROM order_latency
GROUP BY hour

# Slowest requests
SELECT *
FROM order_latency
ORDER BY total_latency_ms DESC
LIMIT 10
```

## Key Files Reference

| File | Purpose |
|------|---------|
| `utils/latency_monitor.py` | Tracking utilities |
| `database/latency_db.py` | Latency model |
| `blueprints/logs.py` | Dashboard routes |
| `utils/httpx_client.py` | HTTP timing hooks |
| `frontend/src/pages/Latency.tsx` | React dashboard |
