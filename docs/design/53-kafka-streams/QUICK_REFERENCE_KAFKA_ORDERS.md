# Quick Reference: Kafka Order Events Integration

## 🎯 Overview

Replace Socket.IO with optional Kafka support for order events using environment variable:
```bash
ORDER_EVENT_MODE=SOCKETIO  # Default (current behavior)
ORDER_EVENT_MODE=KAFKA     # New Kafka mode
```

---

## 📊 Impact Summary

| Metric | Value |
|--------|-------|
| **Files to Create** | 2 new files |
| **Files to Modify** | 6 existing files |
| **Total LOC** | ~376 lines |
| **Development Time** | 8-10 hours |
| **Testing Time** | 4-6 hours |
| **Total Timeline** | 2-3 days |

---

## 📁 Files Changed

### NEW Files
1. **`utils/event_publisher.py`** (250 lines) - Event publisher abstraction
2. **`utils/config.py`** (50 lines) - Configuration validation

### MODIFIED Files
1. **`services/place_smart_order_service.py`** (~30 lines) - Replace socketio.emit
2. **`blueprints/master_contract_status.py`** (~10 lines) - Replace socketio.emit
3. **`blueprints/auth.py`** (~10 lines) - Replace socketio.emit
4. **`app.py`** (+15 lines) - Add config validation
5. **`requirements.txt`** (+1 line) - Add kafka-python
6. **`.sample.env`** (+10 lines) - Add Kafka config

---

## 📨 Messages Published to Kafka

### Topic: `from_openalgo_order_events`

| Event Type | Source File | Frequency | Priority |
|-----------|-------------|-----------|----------|
| `order_event` | place_smart_order_service.py | 100s/day | Critical |
| `analyzer_update` | place_smart_order_service.py | 1000s/day | High |
| `order_notification` | place_smart_order_service.py | 20/day | Medium |
| `master_contract_download` | master_contract_status.py | 5/day | Low |
| `password_change` | auth.py | 2/month | Low |

**Total Volume**: 100-1000 messages/day per user

---

## 🔧 Configuration

### .env File
```bash
# Order Event Mode
ORDER_EVENT_MODE=SOCKETIO  # or KAFKA

# Kafka Settings (only if KAFKA mode)
KAFKA_BOOTSTRAP_SERVERS=localhost:9092
KAFKA_ORDER_EVENTS_TOPIC=from_openalgo_order_events
KAFKA_PRODUCER_COMPRESSION=snappy
KAFKA_PRODUCER_BATCH_SIZE=16384
KAFKA_PRODUCER_LINGER_MS=10
```

---

## 🚀 Implementation Steps

### Phase 1: Foundation (Day 1 - 4 hours)
- [ ] Create `utils/event_publisher.py`
- [ ] Create/update `utils/config.py`
- [ ] Update `.sample.env`
- [ ] Update `requirements.txt`
- [ ] Write unit tests

### Phase 2: Integration (Day 2 - 4 hours)
- [ ] Modify `place_smart_order_service.py`
- [ ] Modify `master_contract_status.py`
- [ ] Modify `auth.py`
- [ ] Update `app.py`

### Phase 3: Testing (Day 3 - 4 hours)
- [ ] Integration tests
- [ ] Performance tests
- [ ] Documentation

---

## 🔄 Before & After Code

### Before (Current Socket.IO)
```python
from extensions import socketio

# Order placed
socketio.emit('order_event', {
    "symbol": "SBIN-EQ",
    "action": "BUY",
    "orderid": "ORD123"
})
```

### After (Kafka Support)
```python
from utils.event_publisher import EventPublisherFactory

event_publisher = EventPublisherFactory.create_publisher()

# Order placed
event_publisher.publish_order_event(
    user_id="user123",
    symbol="SBIN-EQ",
    action="BUY",
    orderid="ORD123",
    mode="live"
)
```

**Behavior**: 
- If `ORDER_EVENT_MODE=SOCKETIO` → Same as before
- If `ORDER_EVENT_MODE=KAFKA` → Publishes to Kafka

---

## 📝 Message Format (Kafka)

```json
{
  "event_type": "order_event",
  "timestamp": "2026-01-29T10:30:45.123456Z",
  "user_id": "user123",
  "source": "openalgo",
  "data": {
    "symbol": "SBIN-EQ",
    "action": "BUY",
    "orderid": "ORD123456",
    "mode": "live",
    "broker": "angel",
    "quantity": "1",
    "price": "850.50"
  }
}
```

---

## ⚡ Performance

| Mode | Latency (p95) | Notes |
|------|---------------|-------|
| Socket.IO | < 100ms | Current behavior |
| Kafka | < 200ms | Acceptable for notifications |

---

## 🔙 Rollback Plan

**If issues occur:**
1. Edit `.env`: `ORDER_EVENT_MODE=SOCKETIO`
2. Restart: `systemctl restart openalgo`
3. **Time**: < 1 minute

**No code changes needed!**

---

## ✅ Success Criteria

- [x] Socket.IO mode works exactly as before
- [x] Kafka mode publishes all events correctly
- [x] Configuration validation works
- [x] Performance acceptable (< 200ms latency)
- [x] < 1 minute rollback time

---

## 📚 Related Documents

1. **ARCHITECTURE_KAFKA_ORDER_EVENTS.md** - Full architecture (this doc)
2. **CURRENT_SOCKETIO_USAGE.md** - Current Socket.IO implementation
3. **CURRENT_ZMQ_USAGE.md** - ZeroMQ (unchanged)
4. **ALTERNATIVE_ESB_ZEROMQ.md** - ESB design for market data

---

## 🎓 Key Decisions

1. ✅ **Environment-based switching** - No code changes to switch modes
2. ✅ **Backward compatible** - Socket.IO remains default
3. ✅ **Single Kafka topic** - All events to `from_openalgo_order_events`
4. ✅ **No consumer in Phase 1** - Publishing only (as requested)
5. ✅ **Keep ZeroMQ unchanged** - Only Socket.IO replaced

---

**Version**: 1.0  
**Date**: January 29, 2026  
**Status**: Ready for Implementation
