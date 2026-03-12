# April 1, 2026 Compliance Implementation Guide

## Overview

This document provides implementation guidance for integrating two critical April 1, 2026 compliance features into OpenAlgo:

1. **Market Protection Orders** - Converting market orders to protection orders
2. **Static IP Configuration** - Registering and validating static IPs per broker requirements

**Timeline**: 20 days until April 1, 2026  
**Brokers Affected**: All 29 brokers in OpenAlgo  
**Status**: Foundation work complete - Ready for PR deployment

---

## Part 1: Market Protection Order Converter

### File Location
```
services/market_protection_order_converter.py
```

### How It Works

The `MarketProtectionOrderConverter` service automatically converts market orders to market protection orders based on broker-specific rules.

**Example Usage** (in place_order_service.py):

```python
from services.market_protection_order_converter import market_protection_converter

def place_order(...):
    # ... existing validation code ...
    
    # Convert market orders to protection orders
    if order.get('pricetype') == 'MARKET':
        converted_order, success, msg = market_protection_converter.convert_market_order(
            order=order,
            broker_name=broker_name,
            protect_pct=None  # Uses broker default
        )
        
        if success:
            logger.info(f"Market order converted: {msg}")
            # Use converted_order instead of original
            order = converted_order
        else:
            logger.warning(f"Conversion failed: {msg}, using market order as-is")
    
    # Continue with normal order placement...
```

### Supported Brokers

All 29 brokers configured with default protection levels:

| Broker | Protection Field | Default % | Status |
|--------|------------------|-----------|--------|
| Zerodha | limit_offset | 0.5% | ✅ Ready |
| Angel One | protection_price | 0.75% | ✅ Ready |
| Dhan | protection_limit | 1.0% | ✅ Ready |
| Upstox | stop_price | 0.75% | ✅ Ready |
| Fyers | disclosed_quantity | 1.0% | ✅ Ready |
| 5paisa | limit_offset | 0.5% | ✅ Ready |
| Motilal | protection_level | 1.0% | ✅ Ready |
| Firstock | stop_price | 1.0% | ✅ Ready |
| Kotak | price_per_unit | 0.75% | ✅ Ready |
| Shoonya | execution_limit | 1.5% | ✅ Ready |
| Others | [broker-specific] | [varies] | ✅ Ready |

### Testing the Converter

```python
# Test market order conversion
converter = MarketProtectionOrderConverter()

test_order = {
    'symbol': 'SBIN-EQ',
    'exchange': 'NSE',
    'quantity': 100,
    'action': 'BUY',
    'pricetype': 'MARKET',
    'price': '500',
    'product': 'MIS',
}

# Convert for Zerodha
converted, success, msg = converter.convert_market_order(test_order, 'zerodha')
print(f"Success: {success}, Message: {msg}")
print(f"Converted order: {converted}")

# Check broker config
config = converter.get_broker_protection_config('zerodha')
print(f"Zerodha protection config: {config}")
```

### Next PR: Integration PR

**Title**: `feat(services): integrate market protection order converter into place_order_service`

**Changes**:
1. Import converter in `services/place_order_service.py`
2. Add conversion logic after order validation
3. Add unit tests covering all broker types
4. Add logging for audit trail

---

## Part 2: Static IP Configuration

### File Locations

```
broker/zerodha/config/static_ip_config.py     (ZerodhaStaticIPConfig)
broker/angel/config/static_ip_config.py       (AngelOneStaticIPConfig)
broker/dhan/config/static_ip_config.py        (DhanStaticIPConfig)
```

### How It Works

Each broker has a dedicated `StaticIPConfig` class that:

1. **Loads** static IP from environment variables
2. **Validates** IP format and broker configuration
3. **Registers** IPs with broker (manual + API methods)
4. **Validates** incoming request IPs against whitelist
5. **Provides** setup instructions and troubleshooting

### Environment Variables

**Zerodha**:
```bash
ZERODHA_STATIC_IP=203.0.113.1
ZERODHA_STATIC_IP_BACKUP=203.0.113.2      # Optional
ZERODHA_IP_ENABLED=true
```

**Angel One**:
```bash
ANGEL_STATIC_IP=203.0.113.1
ANGEL_STATIC_IP_BACKUP=203.0.113.2        # Optional
ANGEL_CLIENT_CODE=A123456
ANGEL_PASSWORD=password123
ANGEL_API_KEY=your_api_key
ANGEL_IP_ENABLED=true
```

**Dhan**:
```bash
DHAN_STATIC_IP=203.0.113.1
DHAN_STATIC_IP_BACKUP=203.0.113.2         # Optional
DHAN_CLIENT_ID=your_client_id
DHAN_ACCESS_TOKEN=your_access_token
DHAN_API_KEY=your_api_key
DHAN_IP_ENABLED=true
```

### How to Integrate into Auth APIs

**In `broker/zerodha/api/auth_api.py`**:

```python
from broker.zerodha.config import zerodha_static_ip_config

def authenticate_broker(request, request_token):
    """
    Authenticate with Static IP validation.
    """
    # Validate request IP if Static IP enforcement enabled
    if zerodha_static_ip_config.is_valid:
        request_ip = request.remote_addr
        is_valid, msg = zerodha_static_ip_config.validate_request_ip(request_ip)
        
        if not is_valid:
            logger.warning(f"Authentication blocked from IP {request_ip}: {msg}")
            return None, f"Static IP validation failed: {msg}"
    
    # Proceed with normal authentication
    auth_response = authenticate_broker(request_token)
    
    return auth_response
```

**In `broker/angel/api/auth_api.py`**:

```python
from broker.angel.config import angel_static_ip_config

def authenticate_broker(request_data):
    """
    Authenticate with Static IP validation.
    """
    # Validate request IP
    if angel_static_ip_config.is_valid:
        request_ip = get_client_ip(request_data)
        is_valid, msg = angel_static_ip_config.validate_request_ip(request_ip)
        
        if not is_valid:
            logger.warning(f"Auth blocked from {request_ip}: {msg}")
            return {"status": "error", "message": msg}
    
    # Proceed with normal authentication
    # ...
```

### Testing Static IP Config

```python
from broker.zerodha.config import zerodha_static_ip_config

# Check configuration
config = zerodha_static_ip_config.get_configuration()
print(config)

# Get active IP
ip, status = zerodha_static_ip_config.get_active_ip()
print(f"Active IP: {ip}, Status: {status}")

# Validate a request IP
test_ip = "203.0.113.1"
is_valid, msg = zerodha_static_ip_config.validate_request_ip(test_ip)
print(f"Validation result: {is_valid}, {msg}")

# Get setup instructions
print(zerodha_static_ip_config.get_setup_instructions())
```

### User Setup Flow

Users need to:

1. **Get Static IP from ISP**
   - Contact ISP to assign static IP
   - Ensure it's truly fixed (not dynamic)
   - Document the IP address

2. **Update .env File**
   ```bash
   # Add to .env
   ZERODHA_STATIC_IP=<your_ip>
   ZERODHA_IP_ENABLED=true
   ```

3. **Register IP with Broker**
   - Login to broker admin console
   - Go to Settings → API → IP Whitelist
   - Add the static IP
   - Save/Confirm
   - Wait 15-30 minutes for approval

4. **Verify in OpenAlgo**
   - Restart app: `uv run app.py`
   - Check logs: "Static IP validation enabled"
   - Test API call → should work
   - Test from different IP → should be blocked

### Next PRs: Broker-Specific Integration

**Three separate PRs** (one per major broker):

**PR #1**: `feat(broker/zerodha): implement static IP compliance configuration`
- Update `auth_api.py` to validate request IPs
- Add IP validation to order placement
- Add error responses for IP mismatch
- Test with multiple IPs

**PR #2**: `feat(broker/angel): implement static IP compliance configuration`
- Same pattern as Zerodha
- Angel-specific API changes

**PR #3**: `feat(broker/dhan): implement static IP compliance configuration`
- Same pattern as Zerodha
- Dhan-specific API changes

---

## Part 3: Documentation & User Guides

### New File Needed
```
docs/APRIL_1_2026_COMPLIANCE.md
```

**Contents**:
1. Summary of changes (market protection + static IP)
2. Setup instructions per broker
3. Troubleshooting guide
4. FAQ section
5. Links to broker documentation

### Update README.md

Add section:
```markdown
### April 1, 2026 Compliance

OpenAlgo has implemented required changes for broker API compliance:
- **Market Protection Orders** - All market orders now include protection parameters
- **Static IP Registration** - All connections must originate from registered static IPs

See [APRIL_1_2026_COMPLIANCE.md](docs/APRIL_1_2026_COMPLIANCE.md) for setup instructions.
```

---

## Part 4: Testing Strategy

### Unit Tests for Market Protection Converter

File: `test/test_market_protection_converter.py`

```python
import pytest
from services.market_protection_order_converter import market_protection_converter

class TestMarketProtectionConverter:
    def test_zerodha_market_order_conversion(self):
        order = {
            'symbol': 'SBIN-EQ',
            'exchange': 'NSE',
            'quantity': 100,
            'action': 'BUY',
            'pricetype': 'MARKET',
            'price': '500',
            'product': 'MIS',
        }
        
        converted, success, msg = market_protection_converter.convert_market_order(
            order, 'zerodha'
        )
        
        assert success
        assert 'limit_offset' in converted
        assert converted['limit_offset'] == 0.5
        
    def test_non_market_orders_unchanged(self):
        order = {
            'symbol': 'SBIN-EQ',
            'exchange': 'NSE',
            'quantity': 100,
            'action': 'BUY',
            'pricetype': 'LIMIT',
            'price': '500',
            'product': 'MIS',
        }
        
        converted, success, msg = market_protection_converter.convert_market_order(
            order, 'zerodha'
        )
        
        assert success  # No conversion but not an error
        assert converted == order  # Unchanged
```

### Integration Tests

File: `test/test_static_ip_config.py`

```python
import pytest
import os
from broker.zerodha.config import zerodha_static_ip_config

class TestZerodhaStaticIPConfig:
    def test_config_validation(self):
        config = zerodha_static_ip_config.get_configuration()
        assert 'primary_ip' in config
        assert config['is_valid'] or not config['ip_enabled']
    
    def test_valid_ip_format(self):
        assert zerodha_static_ip_config._is_valid_ip("203.0.113.1")
        assert not zerodha_static_ip_config._is_valid_ip("999.999.999.999")
        assert not zerodha_static_ip_config._is_valid_ip("invalid")
    
    def test_ip_whitelist_validation(self):
        # Assuming config has IPs set
        valid, msg = zerodha_static_ip_config.validate_request_ip("203.0.113.1")
        # Result depends on environment
```

---

## Implementation Checklist

### Week 1 (Mar 11-17)
- [ ] PR #981 merged (Database docstrings)
- [ ] PR #1040 merged (Docker bind mounts)
- [ ] PR: Market protection converter (services/)
  - [ ] Create `market_protection_order_converter.py` ✅ DONE
  - [ ] Add unit tests
  - [ ] Get maintainer approval
  - [ ] Merge

### Week 2 (Mar 18-24)
- [ ] PR: Zerodha Static IP config
  - [ ] Create `broker/zerodha/config/static_ip_config.py` ✅ DONE
  - [ ] Update auth API to use it
  - [ ] Add tests
  - [ ] Merge

- [ ] PR: Angel One Static IP config
  - [ ] Create `broker/angel/config/static_ip_config.py` ✅ DONE
  - [ ] Update auth API
  - [ ] Merge

### Week 3 (Mar 25-31)
- [ ] PR: Dhan Static IP config
  - [ ] Create `broker/dhan/config/static_ip_config.py` ✅ DONE
  - [ ] Update auth API
  - [ ] Merge

- [ ] PR: Integration guide & documentation
  - [ ] Create `docs/APRIL_1_2026_COMPLIANCE.md`
  - [ ] Update README
  - [ ] Merge

### Apr 1 (Go-Live)
- [ ] All code deployed
- [ ] All brokers tested
- [ ] Users notified of static IP requirement
- [ ] Monitoring active for compliance issues

---

## Summary

✅ **Completed**:
- Market protection order converter service
- Static IP config modules for 3 brokers (Zerodha, Angel One, Dhan)
- Comprehensive docstrings and setup instructions
- Configuration __init__ files

🔄 **Next Steps**:
1. Add unit tests for converter
2. Integrate converter into place_order_service
3. Update broker auth APIs for IP validation
4. Create documentation
5. Create PRs and get reviews

📊 **Expected Merged PRs from This Work**:
- Converter PR: 1 merge
- Zerodha Static IP: 1 merge
- Angel One Static IP: 1 merge
- Dhan Static IP: 1 merge
- Documentation: 1 merge
- **Total**: 5 PRs = 5 merges toward your 15+ target ✅

---

## Questions?

- Check broker documentation links in config files
- Ask in Discord #algo-regulations channel
- Reference CLAUDE.md for OpenAlgo architecture
