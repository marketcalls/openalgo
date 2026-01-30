# Architecture Document: Kafka Integration for Order Events & Notifications

## Executive Summary

This document outlines the architecture for adding **optional Kafka support** to replace Socket.IO for order events and system notifications in OpenAlgo. The implementation uses an environment variable `ORDER_EVENT_MODE` to switch between Socket.IO (default) and Kafka without code changes.

**Scope**: Communication Layer 1 only (Orders & Events)  
**Out of Scope**: Communication Layer 2 (ZeroMQ market data) - remains unchanged

---

## Table of Contents

1. [Current vs Proposed Architecture](#current-vs-proposed-architecture)
2. [Configuration](#configuration)
3. [Kafka Topics Design](#kafka-topics-design)
4. [Message Catalog](#message-catalog)
5. [Impact Analysis](#impact-analysis)
6. [Implementation Plan](#implementation-plan)
7. [File Modifications](#file-modifications)
8. [Testing Strategy](#testing-strategy)

---

## Current vs Proposed Architecture

### Current Architecture (Socket.IO)

```
┌─────────────────────────────────────────────────────────────┐
│                      FLASK BACKEND                           │
│                                                              │
│  ┌────────────────────────────────────────────────────────┐ │
│  │  Service Layer (place_smart_order_service.py, etc.)   │ │
│  │                                                         │ │
│  │  socketio.emit('order_event', data)                   │ │
│  │  socketio.emit('analyzer_update', data)               │ │
│  │  socketio.emit('password_change', data)               │ │
│  └───────────────────────┬────────────────────────────────┘ │
│                          │                                   │
│  ┌───────────────────────▼────────────────────────────────┐ │
│  │  Flask-SocketIO (extensions.py)                        │ │
│  │  - HTTP Long-Polling                                   │ │
│  │  - Threading mode                                      │ │
│  └───────────────────────┬────────────────────────────────┘ │
└────────────────────────────┼─────────────────────────────────┘
                             │ HTTP Long-Polling
                             │
┌────────────────────────────▼─────────────────────────────────┐
│                      FRONTEND                                │
│  ┌────────────────────────────────────────────────────────┐ │
│  │  Socket.IO Client                                       │ │
│  │                                                         │ │
│  │  socket.on('order_event', callback)                    │ │
│  │  socket.on('analyzer_update', callback)                │ │
│  │  socket.on('password_change', callback)                │ │
│  └────────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────┘
```

**Characteristics**:
- ✅ Simple, direct communication
- ✅ Works out of the box
- ❌ Tight coupling (backend → frontend only)
- ❌ No message persistence
- ❌ No external system integration
- ❌ Limited to HTTP clients only

---

### Proposed Architecture (Kafka Option)

```
┌─────────────────────────────────────────────────────────────┐
│                      FLASK BACKEND                           │
│                                                              │
│  ┌────────────────────────────────────────────────────────┐ │
│  │  Service Layer (place_smart_order_service.py, etc.)   │ │
│  │                                                         │ │
│  │  event_publisher.publish_order_event(data)            │ │
│  │  event_publisher.publish_analyzer_update(data)        │ │
│  │  event_publisher.publish_password_change(data)        │ │
│  └───────────────────────┬────────────────────────────────┘ │
│                          │                                   │
│  ┌───────────────────────▼────────────────────────────────┐ │
│  │  Event Publisher Abstraction (NEW)                     │ │
│  │  utils/event_publisher.py                              │ │
│  │                                                         │ │
│  │  if ORDER_EVENT_MODE == "SOCKETIO":                   │ │
│  │      socketio.emit(...)                                │ │
│  │  elif ORDER_EVENT_MODE == "KAFKA":                    │ │
│  │      kafka_producer.send(...)                          │ │
│  └───────────────────────┬────────────────────────────────┘ │
└────────────────────────────┼─────────────────────────────────┘
                             │
                ┌────────────┴────────────┐
                │                         │
                │ SOCKETIO                │ KAFKA
                │                         │
┌───────────────▼──────────┐   ┌─────────▼──────────────────────┐
│  Flask-SocketIO          │   │  Kafka Cluster                  │
│  (Current behavior)      │   │                                 │
│  - HTTP Long-Polling     │   │  Topics:                        │
│                          │   │  - from_openalgo_order_events   │
│                          │   │  - from_esb_order_events        │
└───────────┬──────────────┘   └─────────┬──────────────────────┘
            │                             │
            │ HTTP                        │ Kafka Protocol
            │                             │
┌───────────▼──────────────┐   ┌─────────▼──────────────────────┐
│  Frontend                │   │  External Systems               │
│  Socket.IO Client        │   │  - ESB                          │
│                          │   │  - Order Management System      │
│                          │   │  - Analytics Platform           │
│                          │   │  - Risk Management System       │
└──────────────────────────┘   └─────────────────────────────────┘
```

**Benefits**:
- ✅ **Decoupled**: External systems can consume events
- ✅ **Persistent**: Messages stored in Kafka (replay capability)
- ✅ **Scalable**: Multiple consumers can process events
- ✅ **Integration**: ESB and other systems can subscribe
- ✅ **Auditable**: Complete event history for compliance
- ✅ **Backward Compatible**: Socket.IO still available as default

---

## Configuration

### Environment Variable

Add to `.env` file:

```bash
# Order Event Communication Mode
# Options: SOCKETIO (default), KAFKA
ORDER_EVENT_MODE=SOCKETIO

# Kafka Configuration (only needed if ORDER_EVENT_MODE=KAFKA)
KAFKA_BOOTSTRAP_SERVERS=localhost:9092
KAFKA_ORDER_EVENTS_TOPIC=from_openalgo_order_events
KAFKA_ESB_EVENTS_TOPIC=from_esb_order_events
KAFKA_PRODUCER_COMPRESSION=snappy
KAFKA_PRODUCER_BATCH_SIZE=16384
KAFKA_PRODUCER_LINGER_MS=10
KAFKA_CONSUMER_GROUP=openalgo-order-consumer
KAFKA_CONSUMER_AUTO_OFFSET_RESET=latest
```

### Configuration Validation

**File**: `utils/config.py` (NEW or UPDATE)

```python
import os
from utils.logging import get_logger

logger = get_logger(__name__)

def validate_order_event_config():
    """
    Validate order event configuration
    
    Raises:
        ValueError: If configuration is invalid
    """
    order_event_mode = os.getenv('ORDER_EVENT_MODE', 'SOCKETIO').upper()
    
    # Validate mode
    if order_event_mode not in ['SOCKETIO', 'KAFKA']:
        raise ValueError(
            f"Invalid ORDER_EVENT_MODE: {order_event_mode}. "
            f"Must be 'SOCKETIO' or 'KAFKA'"
        )
    
    # If Kafka mode, validate Kafka settings
    if order_event_mode == 'KAFKA':
        required_kafka_vars = [
            'KAFKA_BOOTSTRAP_SERVERS',
            'KAFKA_ORDER_EVENTS_TOPIC',
        ]
        
        missing_vars = [
            var for var in required_kafka_vars 
            if not os.getenv(var)
        ]
        
        if missing_vars:
            raise ValueError(
                f"ORDER_EVENT_MODE=KAFKA requires: {', '.join(missing_vars)}"
            )
        
        logger.info(f"Kafka order events enabled on topic: "
                   f"{os.getenv('KAFKA_ORDER_EVENTS_TOPIC')}")
    else:
        logger.info("Socket.IO order events enabled (default)")
    
    return order_event_mode
```

---

## Kafka Topics Design

### Topic 1: from_openalgo_order_events

**Purpose**: OpenAlgo publishes all order and system events to this topic

**Partitioning Strategy**: Hash by `user_id`  
**Replication Factor**: 3  
**Retention**: 7 days  
**Compression**: Snappy  

**Message Format**:
```json
{
  "event_type": "order_event",
  "timestamp": "2026-01-29T10:30:45.123Z",
  "user_id": "user123",
  "data": {
    "symbol": "SBIN-EQ",
    "action": "BUY",
    "orderid": "ORD123456",
    "mode": "live"
  }
}
```

**Kafka Configuration**:
```bash
# Create topic
kafka-topics.sh --create \
  --topic from_openalgo_order_events \
  --partitions 5 \
  --replication-factor 3 \
  --config retention.ms=604800000 \
  --config compression.type=snappy
```

---

### Topic 2: from_esb_order_events (Optional)

**Purpose**: ESB or external systems send commands/events to OpenAlgo

**Note**: Based on your requirement "If there is no receiving logic, you can ignore the consumer part", this topic is **OPTIONAL** and will only be implemented if needed.

**Use Cases** (Future):
- ESB sends order confirmation acknowledgments
- External risk system sends order rejection
- Analytics system requests order replay

**Partitioning Strategy**: Hash by `user_id`  
**Replication Factor**: 3  
**Retention**: 24 hours  

**Message Format**:
```json
{
  "event_type": "order_acknowledgment",
  "timestamp": "2026-01-29T10:30:46.456Z",
  "user_id": "user123",
  "data": {
    "orderid": "ORD123456",
    "status": "acknowledged",
    "source": "ESB"
  }
}
```

---

## Message Catalog

### Messages Published TO Kafka

All messages that are currently sent via `socketio.emit()` will be published to Kafka topic `from_openalgo_order_events`.

#### 1. order_event

**Current Code**:
```python
socketio.emit('order_event', {
    "symbol": order_data.get("symbol"),
    "action": order_data.get("action"),
    "orderid": order_id,
    "mode": "live"
})
```

**New Kafka Message**:
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

**When Emitted**: After successful order placement  
**Source File**: `services/place_smart_order_service.py`  
**Frequency**: Every order placement (1-100/day per user)

---

#### 2. analyzer_update

**Current Code**:
```python
socketio.emit('analyzer_update', {
    "request": analyzer_request,
    "response": response_data
})
```

**New Kafka Message**:
```json
{
  "event_type": "analyzer_update",
  "timestamp": "2026-01-29T10:30:45.123456Z",
  "user_id": "user123",
  "source": "openalgo",
  "data": {
    "request": {
      "symbol": "RELIANCE-EQ",
      "action": "BUY",
      "quantity": "1",
      "api_type": "placesmartorder"
    },
    "response": {
      "mode": "analyze",
      "status": "success",
      "orderid": "SANDBOX_ORD_123"
    }
  }
}
```

**When Emitted**: During sandbox/analyzer mode operations  
**Source File**: `services/place_smart_order_service.py`  
**Frequency**: Every sandbox order (1-1000/day in testing)

---

#### 3. order_notification

**Current Code**:
```python
socketio.emit('order_notification', {
    "symbol": order_data.get("symbol"),
    "status": "info",
    "message": "Positions Already Matched. No Action needed."
})
```

**New Kafka Message**:
```json
{
  "event_type": "order_notification",
  "timestamp": "2026-01-29T10:30:45.123456Z",
  "user_id": "user123",
  "source": "openalgo",
  "data": {
    "symbol": "INFY-EQ",
    "status": "info",
    "message": "Positions Already Matched. No Action needed.",
    "notification_type": "position_match"
  }
}
```

**When Emitted**: When smart order finds position already matched  
**Source File**: `services/place_smart_order_service.py`  
**Frequency**: Occasional (5-20/day per user)

---

#### 4. master_contract_download

**Current Code**:
```python
socketio.emit('master_contract_download', {
    'broker': broker_name,
    'status': 'success',
    'message': 'Master contract downloaded successfully'
})
```

**New Kafka Message**:
```json
{
  "event_type": "master_contract_download",
  "timestamp": "2026-01-29T10:30:45.123456Z",
  "user_id": "admin",
  "source": "openalgo",
  "data": {
    "broker": "angel",
    "status": "success",
    "message": "Master contract downloaded successfully",
    "symbols_count": 5000,
    "download_time_seconds": 45.2
  }
}
```

**When Emitted**: After master contract download completes  
**Source File**: `blueprints/master_contract_status.py`  
**Frequency**: Rare (1-5/day system-wide)

---

#### 5. password_change

**Current Code**:
```python
socketio.emit('password_change', {
    'user': username,
    'status': 'success',
    'message': 'Password changed successfully'
})
```

**New Kafka Message**:
```json
{
  "event_type": "password_change",
  "timestamp": "2026-01-29T10:30:45.123456Z",
  "user_id": "user123",
  "source": "openalgo",
  "data": {
    "user": "user123",
    "status": "success",
    "message": "Password changed successfully",
    "ip_address": "192.168.1.100",
    "user_agent": "Mozilla/5.0..."
  }
}
```

**When Emitted**: After password change  
**Source File**: `blueprints/auth.py`  
**Frequency**: Very rare (0-2/month per user)

---

### Summary: Messages Published to Kafka

| Event Type | Source File | Frequency | Priority |
|-----------|-------------|-----------|----------|
| `order_event` | place_smart_order_service.py | High (100s/day) | Critical |
| `analyzer_update` | place_smart_order_service.py | High (1000s/day in test) | High |
| `order_notification` | place_smart_order_service.py | Medium (20/day) | Medium |
| `master_contract_download` | master_contract_status.py | Low (5/day) | Low |
| `password_change` | auth.py | Very Low (2/month) | Low |

**Total Estimated Volume**: 100-1000 messages/day per user in production  
**Peak Volume**: 5000+ messages/day during heavy testing

---

### Messages Received FROM Kafka (Optional)

**Status**: **NOT IMPLEMENTED in Phase 1**

**Reason**: No current receiving logic identified. This is a future enhancement.

**Potential Future Use Cases**:
1. **Order Acknowledgments from ESB**: External system confirms order receipt
2. **Risk Management Alerts**: Risk system sends order rejection
3. **Order Modifications from External System**: External trading system modifies orders
4. **Position Reconciliation**: External system sends position updates

**If implemented later**, create:
- Consumer: `services/kafka_order_consumer.py`
- Topic: `from_esb_order_events`
- Handler: Process incoming commands and route to appropriate service

---

## Impact Analysis

### Files to Create (NEW)

#### 1. utils/event_publisher.py (NEW - CRITICAL)

**Purpose**: Abstract event publishing to support both Socket.IO and Kafka

**Estimated LOC**: 250 lines

**Key Classes**:
```python
class EventPublisher(ABC):
    """Abstract base class for event publishing"""
    @abstractmethod
    def publish_order_event(self, user_id, **data): pass
    
    @abstractmethod
    def publish_analyzer_update(self, user_id, request, response): pass
    
    @abstractmethod
    def publish_order_notification(self, user_id, **data): pass
    
    @abstractmethod
    def publish_master_contract_download(self, **data): pass
    
    @abstractmethod
    def publish_password_change(self, user_id, **data): pass

class SocketIOEventPublisher(EventPublisher):
    """Socket.IO implementation (current behavior)"""
    def __init__(self, socketio_instance):
        self.socketio = socketio_instance
    
    def publish_order_event(self, user_id, **data):
        self.socketio.emit('order_event', data)

class KafkaEventPublisher(EventPublisher):
    """Kafka implementation (new)"""
    def __init__(self, bootstrap_servers, topic):
        from kafka import KafkaProducer
        self.producer = KafkaProducer(
            bootstrap_servers=bootstrap_servers,
            value_serializer=lambda v: json.dumps(v).encode('utf-8'),
            compression_type='snappy'
        )
        self.topic = topic
    
    def publish_order_event(self, user_id, **data):
        message = {
            "event_type": "order_event",
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "user_id": user_id,
            "source": "openalgo",
            "data": data
        }
        self.producer.send(
            self.topic,
            key=user_id.encode('utf-8'),
            value=message
        )

class EventPublisherFactory:
    """Factory to create appropriate publisher"""
    @staticmethod
    def create_publisher():
        mode = os.getenv('ORDER_EVENT_MODE', 'SOCKETIO').upper()
        
        if mode == 'KAFKA':
            bootstrap_servers = os.getenv('KAFKA_BOOTSTRAP_SERVERS')
            topic = os.getenv('KAFKA_ORDER_EVENTS_TOPIC')
            return KafkaEventPublisher(bootstrap_servers, topic)
        else:
            from extensions import socketio
            return SocketIOEventPublisher(socketio)
```

---

#### 2. utils/config.py (NEW or UPDATE)

**Purpose**: Validate configuration at startup

**Estimated LOC**: 50 lines (if new) or +30 lines (if updating existing)

**Key Function**:
```python
def validate_order_event_config():
    """Validate ORDER_EVENT_MODE configuration"""
    # Implementation shown in Configuration section above
```

---

#### 3. services/kafka_order_consumer.py (OPTIONAL - Future)

**Purpose**: Consume messages from ESB/external systems

**Status**: **Not implemented in Phase 1**

**Estimated LOC**: 200 lines (when implemented)

---

### Files to Modify (EXISTING)

#### 1. services/place_smart_order_service.py (CRITICAL)

**Current Lines**: ~500 lines  
**Lines to Modify**: ~30 lines  
**Effort**: 2 hours

**Changes**:

**Before**:
```python
from extensions import socketio

# Order placed
socketio.start_background_task(
    socketio.emit,
    "order_event",
    {
        "symbol": order_data.get("symbol"),
        "action": order_data.get("action"),
        "orderid": order_id,
        "mode": "live"
    }
)

# Analyzer update
socketio.start_background_task(
    socketio.emit,
    "analyzer_update",
    {"request": analyzer_request, "response": response_data}
)

# Order notification
socketio.start_background_task(
    socketio.emit,
    "order_notification",
    {
        "symbol": order_data.get("symbol"),
        "status": "info",
        "message": "Positions Already Matched. No Action needed."
    }
)
```

**After**:
```python
from utils.event_publisher import EventPublisherFactory

# Initialize event publisher (at module level)
event_publisher = EventPublisherFactory.create_publisher()

# Order placed
event_publisher.publish_order_event(
    user_id=user_id,
    symbol=order_data.get("symbol"),
    action=order_data.get("action"),
    orderid=order_id,
    mode="live",
    broker=broker,
    quantity=order_data.get("quantity"),
    price=order_data.get("price")
)

# Analyzer update
event_publisher.publish_analyzer_update(
    user_id=user_id,
    request=analyzer_request,
    response=response_data
)

# Order notification
event_publisher.publish_order_notification(
    user_id=user_id,
    symbol=order_data.get("symbol"),
    status="info",
    message="Positions Already Matched. No Action needed.",
    notification_type="position_match"
)
```

**Locations to Change**:
- Line ~50: Add import
- Line ~180: Replace order_event emission (3 locations)
- Line ~210: Replace analyzer_update emission (2 locations)
- Line ~250: Replace order_notification emission (1 location)

---

#### 2. blueprints/master_contract_status.py

**Current Lines**: ~300 lines  
**Lines to Modify**: ~10 lines  
**Effort**: 30 minutes

**Changes**:

**Before**:
```python
from extensions import socketio

socketio.emit('master_contract_download', {
    'broker': broker_name,
    'status': 'success',
    'message': 'Master contract downloaded successfully'
})
```

**After**:
```python
from utils.event_publisher import EventPublisherFactory

event_publisher = EventPublisherFactory.create_publisher()

event_publisher.publish_master_contract_download(
    broker=broker_name,
    status='success',
    message='Master contract downloaded successfully',
    symbols_count=len(symbols),
    download_time_seconds=download_time
)
```

**Locations to Change**:
- Line ~15: Add import
- Line ~150: Replace master_contract_download emission

---

#### 3. blueprints/auth.py

**Current Lines**: ~400 lines  
**Lines to Modify**: ~10 lines  
**Effort**: 30 minutes

**Changes**:

**Before**:
```python
from extensions import socketio

socketio.emit('password_change', {
    'user': username,
    'status': 'success',
    'message': 'Password changed successfully'
})
```

**After**:
```python
from utils.event_publisher import EventPublisherFactory

event_publisher = EventPublisherFactory.create_publisher()

event_publisher.publish_password_change(
    user_id=username,
    status='success',
    message='Password changed successfully',
    ip_address=request.remote_addr,
    user_agent=request.headers.get('User-Agent')
)
```

**Locations to Change**:
- Line ~15: Add import
- Line ~280: Replace password_change emission

---

#### 4. app.py (Main application)

**Current Lines**: ~200 lines  
**Lines to Add**: ~15 lines  
**Effort**: 30 minutes

**Changes**:

**Add configuration validation at startup**:

```python
from utils.config import validate_order_event_config

def create_app():
    app = Flask(__name__)
    
    # Validate order event configuration
    order_event_mode = validate_order_event_config()
    logger.info(f"Order event mode: {order_event_mode}")
    
    # ... rest of initialization
    
    return app
```

**Location**: After environment loading, before blueprint registration

---

#### 5. requirements.txt

**Lines to Add**: 1 line  
**Effort**: 1 minute

**Add Kafka dependency**:
```txt
kafka-python==2.0.2  # For Kafka producer
```

**Note**: Only needed if ORDER_EVENT_MODE=KAFKA

---

#### 6. .sample.env

**Lines to Add**: ~10 lines  
**Effort**: 5 minutes

**Add Kafka configuration**:
```bash
# Order Event Communication Mode
ORDER_EVENT_MODE=SOCKETIO

# Kafka Configuration (only if ORDER_EVENT_MODE=KAFKA)
KAFKA_BOOTSTRAP_SERVERS=localhost:9092
KAFKA_ORDER_EVENTS_TOPIC=from_openalgo_order_events
KAFKA_PRODUCER_COMPRESSION=snappy
```

---

### Impact Summary

| File | Type | LOC Impact | Effort | Priority |
|------|------|------------|--------|----------|
| utils/event_publisher.py | NEW | +250 | 4h | Critical |
| utils/config.py | NEW/UPDATE | +50 | 1h | High |
| place_smart_order_service.py | MODIFY | ~30 | 2h | Critical |
| master_contract_status.py | MODIFY | ~10 | 0.5h | Medium |
| auth.py | MODIFY | ~10 | 0.5h | Medium |
| app.py | MODIFY | +15 | 0.5h | High |
| requirements.txt | MODIFY | +1 | 0.1h | High |
| .sample.env | MODIFY | +10 | 0.1h | Low |
| **TOTAL** | | **~376 LOC** | **8.7h** | |

**Total Files**: 8 files (2 new, 6 modified)  
**Estimated Development Time**: 8-10 hours  
**Estimated Testing Time**: 4-6 hours  
**Total Timeline**: 2-3 days

---

## Implementation Plan

### Phase 1: Foundation (Day 1 - 4 hours)

**Goal**: Create abstraction layer and configuration

**Tasks**:
1. Create `utils/event_publisher.py` with all publisher classes (3 hours)
2. Create/update `utils/config.py` with validation (30 minutes)
3. Add Kafka configuration to `.sample.env` (15 minutes)
4. Add `kafka-python` to `requirements.txt` (5 minutes)
5. Write unit tests for event publishers (30 minutes)

**Deliverables**:
- ✅ EventPublisher abstraction working
- ✅ SocketIOEventPublisher maintains current behavior
- ✅ KafkaEventPublisher can publish to Kafka
- ✅ Configuration validation works
- ✅ Unit tests pass (90% coverage)

---

### Phase 2: Integration (Day 2 - 4 hours)

**Goal**: Replace Socket.IO calls with abstraction

**Tasks**:
1. Modify `services/place_smart_order_service.py` (2 hours)
   - Import EventPublisherFactory
   - Replace 6 socketio.emit calls
   - Test with Socket.IO mode
   - Test with Kafka mode
2. Modify `blueprints/master_contract_status.py` (30 minutes)
   - Replace socketio.emit call
   - Test both modes
3. Modify `blueprints/auth.py` (30 minutes)
   - Replace socketio.emit call
   - Test both modes
4. Update `app.py` to validate config at startup (30 minutes)

**Deliverables**:
- ✅ All Socket.IO calls replaced
- ✅ Socket.IO mode still works (backward compatibility)
- ✅ Kafka mode publishes to topic
- ✅ Integration tests pass

---

### Phase 3: Testing & Documentation (Day 3 - 4 hours)

**Goal**: Comprehensive testing and documentation

**Tasks**:
1. Integration testing (2 hours)
   - Test order flow with Socket.IO mode
   - Test order flow with Kafka mode
   - Test mode switching without restart
   - Test error scenarios
2. Performance testing (1 hour)
   - Measure Socket.IO latency
   - Measure Kafka latency
   - Load test with 100 concurrent orders
3. Documentation (1 hour)
   - Update README
   - Create migration guide
   - Document Kafka topic schemas

**Deliverables**:
- ✅ All tests passing
- ✅ Performance benchmarks documented
- ✅ Migration guide complete

---

### Phase 4: Deployment (Optional)

**Goal**: Deploy to production

**Prerequisites**:
- Kafka cluster running
- Topics created
- Configuration updated

**Rollout Strategy**:
1. Deploy with `ORDER_EVENT_MODE=SOCKETIO` (no change)
2. Monitor for 1 day
3. Switch to `ORDER_EVENT_MODE=KAFKA` for 10% of users
4. Monitor for 1 day
5. Gradually increase to 100%

---

## File Modifications Detail

### 1. utils/event_publisher.py (NEW - 250 lines)

```python
"""
Event Publisher Abstraction Layer

Supports both Socket.IO (default) and Kafka for order event publishing.
Configure via ORDER_EVENT_MODE environment variable.
"""

import json
import os
from abc import ABC, abstractmethod
from datetime import datetime
from typing import Any, Dict, Optional

from utils.logging import get_logger

logger = get_logger(__name__)


class EventPublisher(ABC):
    """Abstract base class for event publishing"""

    @abstractmethod
    def publish_order_event(
        self,
        user_id: str,
        symbol: str,
        action: str,
        orderid: str,
        mode: str,
        **kwargs
    ):
        """Publish order placement event"""
        pass

    @abstractmethod
    def publish_analyzer_update(
        self,
        user_id: str,
        request: Dict[str, Any],
        response: Dict[str, Any]
    ):
        """Publish analyzer mode update"""
        pass

    @abstractmethod
    def publish_order_notification(
        self,
        user_id: str,
        symbol: str,
        status: str,
        message: str,
        **kwargs
    ):
        """Publish order notification"""
        pass

    @abstractmethod
    def publish_master_contract_download(
        self,
        broker: str,
        status: str,
        message: str,
        **kwargs
    ):
        """Publish master contract download event"""
        pass

    @abstractmethod
    def publish_password_change(
        self,
        user_id: str,
        status: str,
        message: str,
        **kwargs
    ):
        """Publish password change event"""
        pass


class SocketIOEventPublisher(EventPublisher):
    """Socket.IO implementation - maintains current behavior"""

    def __init__(self, socketio_instance):
        self.socketio = socketio_instance
        logger.info("SocketIOEventPublisher initialized")

    def publish_order_event(
        self,
        user_id: str,
        symbol: str,
        action: str,
        orderid: str,
        mode: str,
        **kwargs
    ):
        """Publish order event via Socket.IO"""
        data = {
            "symbol": symbol,
            "action": action,
            "orderid": orderid,
            "mode": mode,
            **kwargs
        }
        
        # Emit asynchronously (non-blocking)
        self.socketio.start_background_task(
            self.socketio.emit,
            "order_event",
            data
        )
        
        logger.debug(f"Published order_event via Socket.IO: {orderid}")

    def publish_analyzer_update(
        self,
        user_id: str,
        request: Dict[str, Any],
        response: Dict[str, Any]
    ):
        """Publish analyzer update via Socket.IO"""
        data = {
            "request": request,
            "response": response
        }
        
        self.socketio.start_background_task(
            self.socketio.emit,
            "analyzer_update",
            data
        )
        
        logger.debug(f"Published analyzer_update via Socket.IO")

    def publish_order_notification(
        self,
        user_id: str,
        symbol: str,
        status: str,
        message: str,
        **kwargs
    ):
        """Publish order notification via Socket.IO"""
        data = {
            "symbol": symbol,
            "status": status,
            "message": message,
            **kwargs
        }
        
        self.socketio.start_background_task(
            self.socketio.emit,
            "order_notification",
            data
        )
        
        logger.debug(f"Published order_notification via Socket.IO: {symbol}")

    def publish_master_contract_download(
        self,
        broker: str,
        status: str,
        message: str,
        **kwargs
    ):
        """Publish master contract download event via Socket.IO"""
        data = {
            "broker": broker,
            "status": status,
            "message": message,
            **kwargs
        }
        
        self.socketio.emit("master_contract_download", data)
        
        logger.info(f"Published master_contract_download via Socket.IO: {broker}")

    def publish_password_change(
        self,
        user_id: str,
        status: str,
        message: str,
        **kwargs
    ):
        """Publish password change event via Socket.IO"""
        data = {
            "user": user_id,
            "status": status,
            "message": message,
            **kwargs
        }
        
        self.socketio.emit("password_change", data)
        
        logger.info(f"Published password_change via Socket.IO: {user_id}")


class KafkaEventPublisher(EventPublisher):
    """Kafka implementation - publishes to Kafka topic"""

    def __init__(self, bootstrap_servers: str, topic: str):
        from kafka import KafkaProducer
        
        self.topic = topic
        self.producer = KafkaProducer(
            bootstrap_servers=bootstrap_servers.split(','),
            value_serializer=lambda v: json.dumps(v).encode('utf-8'),
            compression_type=os.getenv('KAFKA_PRODUCER_COMPRESSION', 'snappy'),
            batch_size=int(os.getenv('KAFKA_PRODUCER_BATCH_SIZE', '16384')),
            linger_ms=int(os.getenv('KAFKA_PRODUCER_LINGER_MS', '10')),
            acks='all'  # Wait for all replicas
        )
        
        logger.info(f"KafkaEventPublisher initialized - topic: {topic}")

    def _publish_to_kafka(
        self,
        event_type: str,
        user_id: str,
        data: Dict[str, Any]
    ):
        """Helper method to publish message to Kafka"""
        message = {
            "event_type": event_type,
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "user_id": user_id,
            "source": "openalgo",
            "data": data
        }
        
        try:
            future = self.producer.send(
                self.topic,
                key=user_id.encode('utf-8'),
                value=message
            )
            
            # Optional: Wait for confirmation (blocking)
            # future.get(timeout=1)
            
            logger.debug(f"Published {event_type} to Kafka: {user_id}")
            
        except Exception as e:
            logger.error(f"Failed to publish {event_type} to Kafka: {e}")

    def publish_order_event(
        self,
        user_id: str,
        symbol: str,
        action: str,
        orderid: str,
        mode: str,
        **kwargs
    ):
        """Publish order event to Kafka"""
        data = {
            "symbol": symbol,
            "action": action,
            "orderid": orderid,
            "mode": mode,
            **kwargs
        }
        
        self._publish_to_kafka("order_event", user_id, data)

    def publish_analyzer_update(
        self,
        user_id: str,
        request: Dict[str, Any],
        response: Dict[str, Any]
    ):
        """Publish analyzer update to Kafka"""
        data = {
            "request": request,
            "response": response
        }
        
        self._publish_to_kafka("analyzer_update", user_id, data)

    def publish_order_notification(
        self,
        user_id: str,
        symbol: str,
        status: str,
        message: str,
        **kwargs
    ):
        """Publish order notification to Kafka"""
        data = {
            "symbol": symbol,
            "status": status,
            "message": message,
            **kwargs
        }
        
        self._publish_to_kafka("order_notification", user_id, data)

    def publish_master_contract_download(
        self,
        broker: str,
        status: str,
        message: str,
        **kwargs
    ):
        """Publish master contract download event to Kafka"""
        data = {
            "broker": broker,
            "status": status,
            "message": message,
            **kwargs
        }
        
        # Use 'admin' as user_id for system events
        self._publish_to_kafka("master_contract_download", "admin", data)

    def publish_password_change(
        self,
        user_id: str,
        status: str,
        message: str,
        **kwargs
    ):
        """Publish password change event to Kafka"""
        data = {
            "user": user_id,
            "status": status,
            "message": message,
            **kwargs
        }
        
        self._publish_to_kafka("password_change", user_id, data)

    def close(self):
        """Close Kafka producer"""
        try:
            self.producer.close(timeout=5)
            logger.info("Kafka producer closed")
        except Exception as e:
            logger.error(f"Error closing Kafka producer: {e}")


class EventPublisherFactory:
    """Factory to create appropriate event publisher"""

    _instance = None

    @classmethod
    def create_publisher(cls) -> EventPublisher:
        """
        Create and return event publisher based on ORDER_EVENT_MODE
        
        Returns:
            EventPublisher: SocketIO or Kafka publisher
        """
        # Singleton pattern - reuse instance
        if cls._instance is not None:
            return cls._instance
        
        mode = os.getenv('ORDER_EVENT_MODE', 'SOCKETIO').upper()
        
        if mode == 'KAFKA':
            bootstrap_servers = os.getenv('KAFKA_BOOTSTRAP_SERVERS')
            topic = os.getenv('KAFKA_ORDER_EVENTS_TOPIC')
            
            if not bootstrap_servers or not topic:
                logger.error(
                    "KAFKA mode requires KAFKA_BOOTSTRAP_SERVERS and "
                    "KAFKA_ORDER_EVENTS_TOPIC"
                )
                raise ValueError("Missing Kafka configuration")
            
            cls._instance = KafkaEventPublisher(bootstrap_servers, topic)
            logger.info("Using Kafka for order events")
            
        else:
            # Default to Socket.IO
            from extensions import socketio
            cls._instance = SocketIOEventPublisher(socketio)
            logger.info("Using Socket.IO for order events (default)")
        
        return cls._instance
```

---

### 2. utils/config.py (NEW or UPDATE - +50 lines)

```python
"""
Configuration validation for OpenAlgo
"""

import os
from utils.logging import get_logger

logger = get_logger(__name__)


def validate_order_event_config():
    """
    Validate ORDER_EVENT_MODE configuration
    
    Returns:
        str: The validated order event mode
        
    Raises:
        ValueError: If configuration is invalid
    """
    order_event_mode = os.getenv('ORDER_EVENT_MODE', 'SOCKETIO').upper()
    
    # Validate mode
    valid_modes = ['SOCKETIO', 'KAFKA']
    if order_event_mode not in valid_modes:
        raise ValueError(
            f"Invalid ORDER_EVENT_MODE: '{order_event_mode}'. "
            f"Must be one of: {', '.join(valid_modes)}"
        )
    
    # If Kafka mode, validate Kafka settings
    if order_event_mode == 'KAFKA':
        required_kafka_vars = {
            'KAFKA_BOOTSTRAP_SERVERS': 'Kafka broker addresses',
            'KAFKA_ORDER_EVENTS_TOPIC': 'Topic for publishing order events',
        }
        
        missing_vars = []
        for var, description in required_kafka_vars.items():
            if not os.getenv(var):
                missing_vars.append(f"{var} ({description})")
        
        if missing_vars:
            raise ValueError(
                f"ORDER_EVENT_MODE=KAFKA requires the following environment variables:\n" +
                "\n".join(f"  - {var}" for var in missing_vars)
            )
        
        # Log Kafka configuration
        logger.info(
            f"✓ Kafka order events enabled\n"
            f"  Bootstrap servers: {os.getenv('KAFKA_BOOTSTRAP_SERVERS')}\n"
            f"  Topic: {os.getenv('KAFKA_ORDER_EVENTS_TOPIC')}\n"
            f"  Compression: {os.getenv('KAFKA_PRODUCER_COMPRESSION', 'snappy')}"
        )
        
        # Test Kafka connectivity
        try:
            from kafka import KafkaProducer
            producer = KafkaProducer(
                bootstrap_servers=os.getenv('KAFKA_BOOTSTRAP_SERVERS').split(','),
                request_timeout_ms=5000
            )
            producer.close()
            logger.info("✓ Kafka connectivity test passed")
        except Exception as e:
            logger.warning(f"⚠ Kafka connectivity test failed: {e}")
            logger.warning("  Kafka may not be available yet")
    
    else:
        logger.info("✓ Socket.IO order events enabled (default)")
    
    return order_event_mode


def validate_all_configs():
    """
    Validate all application configurations
    
    Raises:
        ValueError: If any configuration is invalid
    """
    logger.info("Validating application configuration...")
    
    # Validate order event mode
    order_event_mode = validate_order_event_config()
    
    # Add other validations here as needed
    # validate_zeromq_config()
    # validate_broker_config()
    
    logger.info("✓ All configurations validated successfully")
    
    return {
        'order_event_mode': order_event_mode
    }
```

---

## Testing Strategy

### Unit Tests

**File**: `tests/test_event_publisher.py` (NEW)

```python
import unittest
from unittest.mock import MagicMock, patch
import os

from utils.event_publisher import (
    EventPublisherFactory,
    SocketIOEventPublisher,
    KafkaEventPublisher
)


class TestEventPublisher(unittest.TestCase):
    
    def setUp(self):
        # Reset singleton
        EventPublisherFactory._instance = None
    
    @patch.dict(os.environ, {'ORDER_EVENT_MODE': 'SOCKETIO'})
    def test_factory_creates_socketio_publisher(self):
        """Test factory creates Socket.IO publisher in SOCKETIO mode"""
        publisher = EventPublisherFactory.create_publisher()
        self.assertIsInstance(publisher, SocketIOEventPublisher)
    
    @patch.dict(os.environ, {
        'ORDER_EVENT_MODE': 'KAFKA',
        'KAFKA_BOOTSTRAP_SERVERS': 'localhost:9092',
        'KAFKA_ORDER_EVENTS_TOPIC': 'test-topic'
    })
    @patch('utils.event_publisher.KafkaProducer')
    def test_factory_creates_kafka_publisher(self, mock_kafka):
        """Test factory creates Kafka publisher in KAFKA mode"""
        publisher = EventPublisherFactory.create_publisher()
        self.assertIsInstance(publisher, KafkaEventPublisher)
    
    def test_socketio_publisher_emits_order_event(self):
        """Test Socket.IO publisher emits order event correctly"""
        mock_socketio = MagicMock()
        publisher = SocketIOEventPublisher(mock_socketio)
        
        publisher.publish_order_event(
            user_id="user123",
            symbol="SBIN-EQ",
            action="BUY",
            orderid="ORD123",
            mode="live"
        )
        
        # Verify socketio.start_background_task was called
        mock_socketio.start_background_task.assert_called_once()
    
    @patch('utils.event_publisher.KafkaProducer')
    def test_kafka_publisher_sends_to_topic(self, mock_kafka_producer):
        """Test Kafka publisher sends message to topic"""
        mock_producer = MagicMock()
        mock_kafka_producer.return_value = mock_producer
        
        publisher = KafkaEventPublisher("localhost:9092", "test-topic")
        
        publisher.publish_order_event(
            user_id="user123",
            symbol="SBIN-EQ",
            action="BUY",
            orderid="ORD123",
            mode="live"
        )
        
        # Verify producer.send was called
        mock_producer.send.assert_called_once()
        
        # Verify message structure
        call_args = mock_producer.send.call_args
        self.assertEqual(call_args[0][0], "test-topic")  # Topic name
        self.assertEqual(call_args[1]['key'], b"user123")  # User ID as key


if __name__ == '__main__':
    unittest.main()
```

### Integration Tests

**Test Scenarios**:
1. Order placement with Socket.IO mode
2. Order placement with Kafka mode
3. Analyzer update with both modes
4. Password change with both modes
5. Mode switching without restart
6. Error handling when Kafka unavailable

### Performance Tests

**Metrics to Measure**:
- Socket.IO latency: Expected < 100ms
- Kafka latency: Expected < 200ms
- Throughput: 100 orders/second
- Memory usage: < 100MB additional

---

## Rollback Plan

### If Issues Occur

**Step 1**: Change environment variable
```bash
# In .env file
ORDER_EVENT_MODE=SOCKETIO
```

**Step 2**: Restart application
```bash
systemctl restart openalgo
```

**Time to Rollback**: < 1 minute

### No Code Changes Needed

All modifications are backward compatible. Socket.IO mode maintains exact current behavior.

---

## Success Criteria

### Functional Requirements

- ✅ Socket.IO mode works exactly as before (no regressions)
- ✅ Kafka mode publishes all 5 event types correctly
- ✅ Messages contain all required fields
- ✅ Configuration validation prevents startup with invalid settings
- ✅ Mode switching works without code changes

### Performance Requirements

- ✅ Socket.IO latency: < 100ms (p95)
- ✅ Kafka latency: < 200ms (p95)
- ✅ No performance degradation in order placement API
- ✅ Memory overhead: < 100MB

### Operational Requirements

- ✅ Clear error messages for configuration issues
- ✅ Logging for all published events
- ✅ Graceful handling of Kafka unavailability
- ✅ < 1 minute rollback time

---

## Document Version

**Version**: 1.0  
**Date**: January 29, 2026  
**Author**: Architecture Team  
**Status**: Ready for Implementation

---

## Next Steps

1. **Review** this architecture document with team
2. **Approve** implementation approach
3. **Set up** Kafka development environment
4. **Create** Kafka topics
5. **Begin** Phase 1 implementation (Foundation)

---

## Appendices

### A. Kafka Topic Creation Commands

```bash
# Create topic: from_openalgo_order_events
kafka-topics.sh --create \
  --bootstrap-server localhost:9092 \
  --topic from_openalgo_order_events \
  --partitions 5 \
  --replication-factor 3 \
  --config retention.ms=604800000 \
  --config compression.type=snappy \
  --config max.message.bytes=1048576

# Verify topic created
kafka-topics.sh --describe \
  --bootstrap-server localhost:9092 \
  --topic from_openalgo_order_events
```

### B. Kafka Consumer Example (External System)

```python
from kafka import KafkaConsumer
import json

consumer = KafkaConsumer(
    'from_openalgo_order_events',
    bootstrap_servers='localhost:9092',
    group_id='esb-consumer-group',
    value_deserializer=lambda m: json.loads(m.decode('utf-8'))
)

for message in consumer:
    event = message.value
    print(f"Received: {event['event_type']} - {event['data']}")
    
    # Process event
    if event['event_type'] == 'order_event':
        handle_order(event['data'])
```

### C. Docker Compose for Kafka (Development)

```yaml
version: '3.8'

services:
  zookeeper:
    image: confluentinc/cp-zookeeper:7.5.0
    environment:
      ZOOKEEPER_CLIENT_PORT: 2181
      ZOOKEEPER_TICK_TIME: 2000
    ports:
      - "2181:2181"

  kafka:
    image: confluentinc/cp-kafka:7.5.0
    depends_on:
      - zookeeper
    ports:
      - "9092:9092"
    environment:
      KAFKA_BROKER_ID: 1
      KAFKA_ZOOKEEPER_CONNECT: zookeeper:2181
      KAFKA_ADVERTISED_LISTENERS: PLAINTEXT://localhost:9092
      KAFKA_OFFSETS_TOPIC_REPLICATION_FACTOR: 1
```

### D. Monitoring Queries

```bash
# Check producer metrics
kafka-consumer-groups.sh \
  --bootstrap-server localhost:9092 \
  --describe \
  --group openalgo-order-consumer

# Monitor topic lag
kafka-consumer-groups.sh \
  --bootstrap-server localhost:9092 \
  --describe \
  --all-groups

# View messages
kafka-console-consumer.sh \
  --bootstrap-server localhost:9092 \
  --topic from_openalgo_order_events \
  --from-beginning \
  --max-messages 10
```
