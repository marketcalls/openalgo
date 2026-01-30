# OpenAlgo Communication Architecture & Kafka Integration

## 📚 Documentation Overview

This directory contains comprehensive documentation for OpenAlgo's communication architecture and the planned Kafka integration for order events.

---

## 🎯 What's Inside

### Current Architecture Documentation
1. **[CURRENT_ZMQ_USAGE.md](./CURRENT_ZMQ_USAGE.md)** - ZeroMQ for market data streaming
2. **[CURRENT_SOCKETIO_USAGE.md](./CURRENT_SOCKETIO_USAGE.md)** - Socket.IO for orders & notifications

### Kafka Integration Plans
3. **[ARCHITECTURE_KAFKA_ORDER_EVENTS.md](./ARCHITECTURE_KAFKA_ORDER_EVENTS.md)** ⭐ **MAIN DOCUMENT**
   - Complete architecture for replacing Socket.IO with Kafka
   - Impact analysis, file modifications, implementation plan
4. **[QUICK_REFERENCE_KAFKA_ORDERS.md](./QUICK_REFERENCE_KAFKA_ORDERS.md)** - Quick summary

### Alternative Designs (For Reference)
5. **[ALTERNATIVE_ESB_ZEROMQ.md](./ALTERNATIVE_ESB_ZEROMQ.md)** - ESB design for market data
6. **[FILES_TO_MODIFY.md](./FILES_TO_MODIFY.md)** - Original Kafka analysis
7. **[MIGRATION_CHECKLIST.md](./MIGRATION_CHECKLIST.md)** - Original migration plan

---

## 🏗️ OpenAlgo Communication Layers

OpenAlgo uses **three independent communication systems**:

```
┌─────────────────────────────────────────────────────────────┐
│                      OPENALGO SYSTEM                         │
├─────────────────────────────────────────────────────────────┤
│                                                              │
│  Layer 1: Socket.IO (Orders & Notifications)                │
│  ┌────────────────────────────────────────────────────────┐ │
│  │  Technology: Flask-SocketIO (HTTP Long-Polling)        │ │
│  │  Purpose: Order events, system notifications           │ │
│  │  Latency: 50-200ms (acceptable for notifications)      │ │
│  │  Status: ✅ Working                                    │ │
│  │  Plan: → Add optional Kafka support                    │ │
│  └────────────────────────────────────────────────────────┘ │
│                                                              │
│  Layer 2: ZeroMQ (Market Data Streaming)                    │
│  ┌────────────────────────────────────────────────────────┐ │
│  │  Technology: ZeroMQ PUB/SUB (TCP)                      │ │
│  │  Purpose: Real-time market data (LTP/Quote/Depth)      │ │
│  │  Latency: < 2ms (critical for trading)                │ │
│  │  Status: ✅ Working perfectly                          │ │
│  │  Plan: → Keep as-is (no changes)                       │ │
│  └────────────────────────────────────────────────────────┘ │
│                                                              │
│  Layer 3: REST APIs (Data & Commands)                       │
│  ┌────────────────────────────────────────────────────────┐ │
│  │  Technology: Flask REST (HTTP/JSON)                    │ │
│  │  Purpose: CRUD operations, order placement             │ │
│  │  Latency: 10-50ms (synchronous)                       │ │
│  │  Status: ✅ Working                                    │ │
│  │  Plan: → Keep as-is (no changes)                       │ │
│  └────────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────┘
```

---

## 🎯 Current Focus: Kafka Integration for Orders

### Goal
Add optional Kafka support for **Layer 1 only** (Orders & Notifications), controlled by environment variable:

```bash
ORDER_EVENT_MODE=SOCKETIO  # Default (current)
ORDER_EVENT_MODE=KAFKA     # New option
```

### Why Kafka?
1. ✅ **Decoupling**: External systems (ESB, analytics) can consume events
2. ✅ **Persistence**: Event history for audit and replay
3. ✅ **Scalability**: Multiple consumers can process events independently
4. ✅ **Integration**: Connect to enterprise systems seamlessly

### What Changes?
- **YES**: Socket.IO event publishing → Kafka publishing (optional)
- **NO**: ZeroMQ market data (stays exactly the same)
- **NO**: REST APIs (stay exactly the same)

---

## 📖 Quick Start Guide

### 1. Understanding Current Architecture

**Start here**:
1. Read [CURRENT_SOCKETIO_USAGE.md](./CURRENT_SOCKETIO_USAGE.md) - Understand current order events
2. Read [CURRENT_ZMQ_USAGE.md](./CURRENT_ZMQ_USAGE.md) - Understand market data (unchanged)

### 2. Kafka Integration Plan

**Main document**:
- Read [ARCHITECTURE_KAFKA_ORDER_EVENTS.md](./ARCHITECTURE_KAFKA_ORDER_EVENTS.md) ⭐

**Quick reference**:
- Skim [QUICK_REFERENCE_KAFKA_ORDERS.md](./QUICK_REFERENCE_KAFKA_ORDERS.md)

### 3. Implementation

Follow the implementation plan in the architecture document:
- **Phase 1**: Foundation (Day 1)
- **Phase 2**: Integration (Day 2)
- **Phase 3**: Testing (Day 3)

---

## 📊 Impact Summary

### Files Changed
- **2 NEW** files (~300 LOC)
- **6 MODIFIED** files (~76 LOC changed)
- **Total**: 8 files, ~376 LOC

### Timeline
- **Development**: 8-10 hours (1-2 days)
- **Testing**: 4-6 hours (0.5-1 day)
- **Total**: 2-3 days

### Risk
- **Low**: Backward compatible, instant rollback

---

## 🔑 Key Features

### 1. Environment-Based Mode Switching
```bash
# Switch between Socket.IO and Kafka without code changes
ORDER_EVENT_MODE=SOCKETIO  # or KAFKA
```

### 2. Event Publisher Abstraction
```python
# Service code doesn't know if using Socket.IO or Kafka
event_publisher.publish_order_event(
    user_id="user123",
    symbol="SBIN-EQ",
    action="BUY",
    orderid="ORD123"
)
```

### 3. Kafka Topics
- **`from_openalgo_order_events`**: OpenAlgo → External systems
- **`from_esb_order_events`**: External systems → OpenAlgo (future)

### 4. Message Catalog
- `order_event` - Order placed/modified/cancelled
- `analyzer_update` - Sandbox mode updates
- `order_notification` - Position match notifications
- `master_contract_download` - Download complete
- `password_change` - Security events

---

## 🚀 Benefits

### For Development
- ✅ **No breaking changes** - Socket.IO remains default
- ✅ **Easy testing** - Switch modes via environment variable
- ✅ **Gradual rollout** - Start with Socket.IO, migrate to Kafka when ready

### For Operations
- ✅ **Instant rollback** - Change env var and restart (< 1 minute)
- ✅ **No data loss** - Kafka stores all events (7 days retention)
- ✅ **Clear monitoring** - Kafka provides built-in metrics

### For Integration
- ✅ **ESB integration** - External systems consume from Kafka
- ✅ **Analytics** - Real-time event streaming to analytics platforms
- ✅ **Audit trail** - Complete event history for compliance
- ✅ **Event replay** - Replay past events for debugging/testing

---

## 📁 Document Guide

### Understanding Current System
| Document | Purpose | Read Time |
|----------|---------|-----------|
| CURRENT_SOCKETIO_USAGE.md | How orders/notifications work now | 15 min |
| CURRENT_ZMQ_USAGE.md | How market data works (unchanged) | 15 min |

### Kafka Integration
| Document | Purpose | Read Time |
|----------|---------|-----------|
| ARCHITECTURE_KAFKA_ORDER_EVENTS.md ⭐ | Complete architecture & implementation plan | 45 min |
| QUICK_REFERENCE_KAFKA_ORDERS.md | Quick summary | 5 min |

### Alternative Designs (Reference)
| Document | Purpose | Status |
|----------|---------|--------|
| ALTERNATIVE_ESB_ZEROMQ.md | ESB for market data | Not selected |
| FILES_TO_MODIFY.md | Original Kafka analysis | Superseded |
| MIGRATION_CHECKLIST.md | Original migration plan | Superseded |

---

## ⚡ Performance Expectations

| Mode | Latency (p95) | Throughput | Notes |
|------|---------------|------------|-------|
| Socket.IO | < 100ms | 100 msg/sec | Current (working) |
| Kafka | < 200ms | 10K msg/sec | New option |

**Verdict**: Kafka latency acceptable for order notifications (not real-time market data)

---

## 🔄 Rollback Plan

If issues occur with Kafka mode:

1. **Edit `.env`**:
   ```bash
   ORDER_EVENT_MODE=SOCKETIO
   ```

2. **Restart service**:
   ```bash
   systemctl restart openalgo
   ```

3. **Time to rollback**: < 1 minute
4. **Data loss**: None (Kafka retains messages)

---

## 📋 Implementation Checklist

### Prerequisites
- [ ] Kafka cluster available
- [ ] Topic created: `from_openalgo_order_events`
- [ ] Environment variables configured
- [ ] kafka-python installed

### Phase 1: Foundation
- [ ] Create `utils/event_publisher.py`
- [ ] Create/update `utils/config.py`
- [ ] Update `.sample.env`
- [ ] Update `requirements.txt`
- [ ] Write unit tests

### Phase 2: Integration
- [ ] Modify `services/place_smart_order_service.py`
- [ ] Modify `blueprints/master_contract_status.py`
- [ ] Modify `blueprints/auth.py`
- [ ] Update `app.py`
- [ ] Integration tests pass

### Phase 3: Testing & Deployment
- [ ] Performance tests pass
- [ ] Documentation complete
- [ ] Deploy with SOCKETIO mode
- [ ] Gradual rollout to KAFKA mode

---

## 🎓 Design Principles

1. **Backward Compatibility**: Socket.IO remains default and fully functional
2. **Zero Downtime**: Switch modes without code deployment
3. **Single Responsibility**: Each layer handles one thing well
4. **Separation of Concerns**: Market data (ZeroMQ) vs Events (Socket.IO/Kafka)
5. **Progressive Enhancement**: Add Kafka without breaking existing functionality

---

## 🤝 Contributing

When modifying communication layers:

1. **Never mix layers**: Keep market data (ZeroMQ), events (Socket.IO/Kafka), and APIs (REST) separate
2. **Maintain abstractions**: Use EventPublisher interface, don't call Socket.IO/Kafka directly
3. **Test both modes**: All changes must work in both SOCKETIO and KAFKA modes
4. **Update docs**: Keep architecture documents in sync with code

---

## 📞 Support

For questions about:
- **Current architecture**: See CURRENT_*.md documents
- **Kafka integration**: See ARCHITECTURE_KAFKA_ORDER_EVENTS.md
- **Implementation**: Follow implementation plan in architecture doc

---

## 📝 Version History

| Version | Date | Changes |
|---------|------|---------|
| 1.0 | 2026-01-29 | Initial architecture documentation |
| 1.1 | 2026-01-29 | Added Kafka integration plan |

---

## 🎯 Next Steps

1. **Review** ARCHITECTURE_KAFKA_ORDER_EVENTS.md with team
2. **Approve** implementation approach
3. **Set up** Kafka development environment
4. **Create** Kafka topics
5. **Begin** Phase 1 implementation

---

**Status**: ✅ Architecture Complete - Ready for Implementation  
**Last Updated**: January 29, 2026
