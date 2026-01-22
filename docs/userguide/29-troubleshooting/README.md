# 29 - Troubleshooting

## Introduction

This guide helps you diagnose and resolve common issues in OpenAlgo. Problems are organized by category with step-by-step solutions.

## Quick Diagnostic Checklist

Before diving deep, check these basics:

```
┌─────────────────────────────────────────────────────────────────────────────┐
│  Quick Diagnostic Checklist                                                 │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  □ Is OpenAlgo running? (Check terminal/service status)                    │
│  □ Is your broker logged in? (Check broker status indicator)               │
│  □ Is the market open? (Check exchange timings)                            │
│  □ Is your internet working? (Test connectivity)                           │
│  □ Are there any error messages? (Check logs)                              │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

## Installation Issues

### Python Version Error

**Symptom**: `Python 3.12+ required`

**Solution**:
```bash
# Check Python version
python --version

# Install Python 3.12+
# Ubuntu: sudo apt install python3.12
# macOS: brew install python@3.12
# Windows: Download from python.org
```

### Module Not Found

**Symptom**: `ModuleNotFoundError: No module named 'xyz'`

**Solution**:
```bash
# Ensure you're using uv
uv sync

# Or install specific package
uv add package_name
```

### Port Already in Use

**Symptom**: `Address already in use: 5000`

**Solution**:
```bash
# Find process using port
lsof -i :5000

# Kill process (replace PID)
kill -9 PID

# Or use different port
uv run app.py --port 5001
```

### Database Locked

**Symptom**: `database is locked`

**Solution**:
1. Stop OpenAlgo
2. Close all connections
3. Restart OpenAlgo
4. If persistent, delete and recreate database

## Broker Connection Issues

### Cannot Login to Broker

**Symptom**: Broker login fails

**Checklist**:
- [ ] Correct API key and secret
- [ ] API enabled in broker account
- [ ] IP whitelisted (if required)
- [ ] Broker service is up

**Solution**:
```
1. Go to broker website
2. Verify API credentials
3. Check if API access is enabled
4. Verify IP whitelist includes your IP
5. Try logging in to broker website directly
```

### Session Expired

**Symptom**: `Session expired` or `Token invalid`

**Solution**:
1. Go to OpenAlgo dashboard
2. Click on broker status
3. Re-authenticate with broker
4. Complete OAuth flow again

### Broker API Error

**Symptom**: `Broker API returned error`

**Common Causes**:
| Error | Cause | Solution |
|-------|-------|----------|
| Rate limited | Too many requests | Reduce request frequency |
| Invalid token | Session expired | Re-login |
| Service unavailable | Broker down | Wait and retry |
| Permission denied | API scope | Check API permissions |

## Order Placement Issues

### Order Rejected

**Symptom**: Order placed but rejected

**Check Order Book** for rejection reason:

| Rejection Reason | Solution |
|------------------|----------|
| Insufficient margin | Add funds |
| Invalid symbol | Verify symbol format |
| Market closed | Wait for market hours |
| Price out of range | Adjust price |
| Quantity invalid | Check lot size |

### Symbol Not Found

**Symptom**: `Symbol not found in master contract`

**Solution**:
1. Verify symbol format (see Symbol Format Guide)
2. Check if contract is expired
3. Update master contract:
   ```
   Go to Settings → Update Master Contract
   ```
4. Use Search to find correct symbol

### Correct Symbol Format

```
Equity: SBIN (not sbin, not NSE:SBIN)
Futures: NIFTY30JAN25FUT (with date)
Options: NIFTY30JAN2521500CE (with date, strike, type)
```

### Order Not Executing

**Symptom**: Order placed but not executed

**Checklist**:
- [ ] Is it a limit order with price too far?
- [ ] Is the market liquid enough?
- [ ] Is the quantity within limits?
- [ ] Is there sufficient margin?

### Duplicate Orders

**Symptom**: Same order placed multiple times

**Causes**:
1. Webhook sent multiple times
2. Retry logic creating duplicates
3. Strategy triggering repeatedly

**Solution**:
- Implement duplicate detection
- Use smart orders for position management
- Check webhook configuration

## Webhook Issues

### Webhook Not Receiving

**Symptom**: TradingView/ChartInk alerts not reaching OpenAlgo

**Checklist**:
1. Is OpenAlgo accessible from internet?
   ```bash
   # Test with curl from external machine
   curl https://your-openalgo-url/health
   ```

2. Is the URL correct?
   ```
   Correct: https://your-url/api/v1/placeorder
   Wrong: https://your-url/placeorder
   ```

3. Is the payload format correct?
   ```json
   {
     "apikey": "required",
     "symbol": "required",
     "exchange": "required",
     "action": "required",
     "quantity": "required",
     "pricetype": "required",
     "product": "required"
   }
   ```

### Webhook Timeout

**Symptom**: TradingView shows webhook failed

**Solution**:
1. Check OpenAlgo is running
2. Check server response time
3. Increase timeout if needed
4. Check Traffic Logs for details

### Invalid API Key

**Symptom**: `Invalid API key` error

**Solution**:
1. Copy API key from OpenAlgo dashboard
2. Ensure no extra spaces
3. Check key hasn't been regenerated
4. Verify key in webhook payload

## WebSocket Issues

### WebSocket Not Connecting

**Symptom**: Real-time data not updating

**Checklist**:
```
1. Is WebSocket server running?
   - Check port 8765

2. Is firewall blocking?
   - Allow port 8765

3. Is browser blocking?
   - Check browser console
```

### Data Not Streaming

**Symptom**: Prices not updating in real-time

**Solution**:
1. Check broker WebSocket status
2. Verify symbol subscription
3. Restart WebSocket server:
   ```bash
   # Restart OpenAlgo
   uv run app.py
   ```

## Performance Issues

### Slow Response Time

**Symptom**: High latency in order execution

**Diagnostic**:
1. Check Latency Monitor
2. Identify slow component:
   - Network latency
   - Processing time
   - Broker API time

**Solutions**:
| Slow Component | Solution |
|----------------|----------|
| Network | Use closer server |
| Processing | Upgrade hardware |
| Broker API | Contact broker |

### High Memory Usage

**Symptom**: OpenAlgo consuming too much RAM

**Solution**:
```bash
# Check memory usage
ps aux | grep python

# Restart to clear memory
systemctl restart openalgo

# Consider database cleanup
# Delete old logs and data
```

### Database Performance

**Symptom**: Slow database queries

**Solution**:
1. Clean old logs
2. Vacuum database:
   ```bash
   sqlite3 db/openalgo.db "VACUUM;"
   ```
3. Consider archiving old data

## UI Issues

### Page Not Loading

**Symptom**: Dashboard shows blank or error

**Solutions**:
1. Clear browser cache
2. Try incognito mode
3. Check browser console for errors
4. Verify OpenAlgo is running

### Login Issues

**Symptom**: Cannot log in

**Checklist**:
- [ ] Correct username/password
- [ ] Caps lock off
- [ ] Browser cookies enabled
- [ ] 2FA code correct (if enabled)

**Reset Password**:
1. Click "Forgot Password"
2. Follow email instructions
3. Set new password

### Session Expiring Too Fast

**Solution**:
1. Go to Settings → Security
2. Increase session timeout
3. Enable "Remember Me" option

## API Issues

### API Returning Errors

**Common API Errors**:

```json
{"status": "error", "message": "Invalid API key"}
→ Check API key is correct

{"status": "error", "message": "Symbol not found"}
→ Verify symbol format

{"status": "error", "message": "Insufficient margin"}
→ Add funds to account

{"status": "error", "message": "Market closed"}
→ Wait for market hours

{"status": "error", "message": "Rate limit exceeded"}
→ Reduce request frequency
```

### Rate Limiting

**Symptom**: `429 Too Many Requests`

**Solution**:
1. Reduce request frequency
2. Implement request queuing
3. Use batch endpoints where available

## Log Analysis

### Finding Error Logs

```bash
# Application logs
tail -f logs/openalgo.log

# Check for errors
grep -i error logs/openalgo.log

# Check Traffic Logs in UI
```

### Common Log Patterns

```
[ERROR] Failed to place order: Symbol not found
→ Check symbol format

[ERROR] Broker API error: Session expired
→ Re-authenticate broker

[WARNING] Rate limit approaching
→ Reduce request frequency

[ERROR] Database locked
→ Restart application
```

## Recovery Procedures

### Full System Reset

If all else fails:

```bash
# Stop OpenAlgo
pkill -f openalgo

# Backup current data
cp -r db/ db_backup/

# Clear databases (WARNING: loses data)
rm db/*.db

# Restart
uv run app.py
```

### Restore from Backup

```bash
# Stop OpenAlgo
pkill -f openalgo

# Restore backup
cp -r db_backup/* db/

# Restart
uv run app.py
```

## Getting Help

### Before Contacting Support

Gather this information:
1. OpenAlgo version
2. Error messages (exact text)
3. Steps to reproduce
4. Screenshots if applicable
5. Relevant log entries

### Support Channels

OpenAlgo is community-driven:

| Channel | Use For | Link |
|---------|---------|------|
| GitHub Issues | Bug reports, feature requests | [github.com/marketcalls/openalgo/issues](https://github.com/marketcalls/openalgo/issues) |
| Discord | Community support, questions | [openalgo.in/discord](http://openalgo.in/discord) |
| Documentation | How-to guides | [docs.openalgo.in](https://docs.openalgo.in) |

### Useful Commands

```bash
# Check OpenAlgo version
uv run python -c "import openalgo; print(openalgo.__version__)"

# Check system info
uname -a
python --version

# Check running processes
ps aux | grep openalgo

# Check port usage
netstat -tlnp | grep 5000
```

---

**Previous**: [28 - Two-Factor Authentication](../28-two-factor-auth/README.md)

**Next**: [30 - FAQs](../30-faqs/README.md)
