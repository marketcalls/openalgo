# Zero-Config Troubleshooting Guide

## 🚨 Common Issues and Solutions

This guide covers common issues encountered with the zero-config broker setup system and their solutions.

## 🔧 Installation Issues

### **Issue: "Method Not Allowed" Error During Broker Configuration**

**Symptoms:**
- Error appears when saving broker configuration
- URL shows `/broker/configure/<broker>` after form submission
- User sees raw error page instead of success message

**Cause:**
- Form submitting via HTML instead of JavaScript
- Missing `action` attribute or JavaScript event handler failure

**Solution:**
- Clear browser cache and cookies
- Ensure JavaScript is enabled
- Check browser developer console for JavaScript errors
- Try different browser

**Technical Fix (if needed):**
```html
<!-- Form should have proper JavaScript handling -->
<form id="brokerConfigForm" onsubmit="return false;">
```

### **Issue: Broker Login Causes Immediate Logout**

**Symptoms:**
- User authenticates with broker successfully
- Gets redirected to login page immediately
- Logs show "Auth Revoked in the Database"

**Cause:**
- Broker API calls using wrong credentials
- "Invalid API Key" errors triggering security logout

**Diagnosis:**
Check logs for:
```
INFO in funds: Margin Data: {'success': False, 'message': 'Invalid API Key', 'errorCode': 'AG8004'}
ERROR in dashboard: Failed to get margin data - authentication may have expired
INFO in auth: Auth Revoked in the Database for user: username
```

**Solution:**
1. Verify broker credentials are correct
2. Check API key is active in broker portal
3. Ensure API key has proper permissions
4. Reconfigure broker with correct credentials

### **Issue: No Brokers Available for Selection**

**Symptoms:**
- All brokers show as "Disabled" in login page
- Warning: "No Brokers Configured"

**Cause:**
- No brokers configured in database
- User hasn't completed broker setup

**Solution:**
1. Visit `/broker/setup`
2. Configure at least one broker
3. Complete the credential setup process
4. Return to broker selection page

## 🔐 Authentication Issues

### **Issue: Broker Authentication Fails**

**Symptoms:**
- Error during broker login process
- "Authentication failed" messages
- Unable to connect to broker

**Common Causes & Solutions:**

#### **1. Invalid Credentials**
- **Check**: API Key and Secret are correct
- **Verify**: Credentials are active in broker portal
- **Test**: Try logging into broker portal directly

#### **2. API Key Permissions**
- **Angel One**: Ensure API key has trading permissions
- **Dhan**: Verify OAuth app is properly configured
- **General**: Check broker-specific API documentation

#### **3. Network Issues**
- **Check**: Internet connectivity
- **Verify**: No firewall blocking broker APIs
- **Test**: Try from different network

#### **4. Broker API Downtime**
- **Check**: Broker's API status page
- **Wait**: Retry after some time
- **Contact**: Broker support if persistent

### **Issue: XTS Broker Configuration Problems**

**Symptoms:**
- Four credential fields not showing
- Configuration fails for XTS-based brokers

**XTS Brokers:**
- 5Paisa XTS
- CompositEdge
- Indiabulls
- IIFL
- Jainam
- Wisdom Capital

**Solution:**
1. Ensure all four credentials are provided:
   - Trading API Key
   - Trading API Secret
   - Market Data API Key
   - Market Data API Secret
2. Verify each credential separately in broker portal
3. Check broker documentation for XTS API setup

## 💾 Database Issues

### **Issue: Migration from .env Fails**

**Symptoms:**
- Existing .env configuration not detected
- Manual migration script errors
- Database migration failures

**Diagnosis:**
```bash
# Check if tables exist
sqlite3 db/openalgo.db ".tables" | grep broker

# Should show:
# broker_configs
# broker_templates
# broker_config_audit
```

**Solution:**
```bash
# Run migration manually
python migrations/001_create_broker_configs.py
python migrations/migrate_env_to_db.py
```

### **Issue: Credential Encryption Errors**

**Symptoms:**
- "Failed to encrypt credentials" errors
- Database storage failures

**Cause:**
- Missing or invalid `API_KEY_PEPPER` environment variable

**Solution:**
1. Set proper encryption key:
```bash
export API_KEY_PEPPER="your-secure-pepper-key"
```
2. Restart application
3. Reconfigure broker credentials

### **Issue: Database Corruption**

**Symptoms:**
- Application startup errors
- "Database locked" messages
- Credential retrieval failures

**Recovery:**
```bash
# Backup current database
cp db/openalgo.db db/openalgo_backup.db

# Check integrity
sqlite3 db/openalgo.db "PRAGMA integrity_check;"

# If corrupted, restore from backup or reinitialize
```

## 🌐 Web Interface Issues

### **Issue: Broker Setup Page Not Loading**

**Symptoms:**
- 404 error on `/broker/setup`
- Navigation links not working

**Cause:**
- Blueprint not registered
- Routing configuration issues

**Solution:**
1. Restart application
2. Check application logs for blueprint registration
3. Verify all required imports in app.py

### **Issue: CSRF Token Errors**

**Symptoms:**
- "CSRF token missing" errors
- Form submission failures

**Cause:**
- CSRF protection enabled but tokens not properly included

**Solution:**
1. Clear browser cache
2. Disable browser extensions
3. Check meta tag in page source:
```html
<meta name="csrf-token" content="...">
```

### **Issue: JavaScript Not Working**

**Symptoms:**
- Form submits to wrong URL
- No dynamic behavior on pages
- Console errors in browser

**Diagnosis:**
- Open browser Developer Tools (F12)
- Check Console tab for errors
- Verify JavaScript files are loading

**Common Solutions:**
1. Clear browser cache
2. Disable ad blockers
3. Try incognito/private browsing mode
4. Check browser compatibility

## 📊 Performance Issues

### **Issue: Slow Database Operations**

**Symptoms:**
- Long loading times for broker setup
- Timeouts during configuration
- Slow credential retrieval

**Solutions:**
1. **Database Optimization:**
```sql
-- Rebuild database indexes
REINDEX;

-- Analyze query performance
EXPLAIN QUERY PLAN SELECT * FROM broker_configs;
```

2. **Application Restart:**
```bash
# Clear cache and restart
rm -rf __pycache__
uv run app.py
```

### **Issue: Memory Usage Growth**

**Symptoms:**
- Application uses increasing memory
- Performance degrades over time

**Monitoring:**
```bash
# Check process memory usage
ps aux | grep python

# Monitor application logs for memory warnings
tail -f log/openalgo_$(date +%Y-%m-%d).log | grep -i memory
```

## 🔍 Debugging Steps

### **General Debugging Process**

1. **Check Application Logs:**
```bash
tail -f log/openalgo_$(date +%Y-%m-%d).log
```

2. **Verify Database State:**
```bash
sqlite3 db/openalgo.db "SELECT user_id, broker_name, is_active FROM broker_configs;"
```

3. **Test Broker APIs:**
```bash
# Test broker API connectivity
curl -X GET "https://apiconnect.angelbroking.com/rest/auth/angelbroking/user/v1/loginByPassword"
```

4. **Check Environment Variables:**
```bash
echo $DATABASE_URL
echo $API_KEY_PEPPER
echo $HOST_SERVER
```

### **Log Analysis**

**Look for these patterns:**

#### **Successful Flow:**
```
INFO in broker_credentials: Using database credentials for user X, broker Y
INFO in brlogin: Successfully connected broker: Y
INFO in auth_utils: User X logged in successfully with broker Y
```

#### **Error Patterns:**
```
ERROR in broker_credentials: Failed to get credentials from database
ERROR in brlogin: Authentication failed for broker: error_message
ERROR in dashboard: Failed to get margin data - authentication may have expired
```

### **Network Debugging**

1. **Check Broker API Status:**
   - Angel One: Check official status page
   - Dhan: Verify OAuth endpoints
   - Others: Check respective broker documentation

2. **Network Connectivity:**
```bash
# Test DNS resolution
nslookup apiconnect.angelbroking.com

# Test connectivity
telnet apiconnect.angelbroking.com 443
```

3. **Firewall Issues:**
   - Check corporate firewall settings
   - Verify no proxy issues
   - Test from different network

## 🆘 Getting Help

### **Before Seeking Help**

1. **Gather Information:**
   - Error messages (exact text)
   - Application logs (relevant sections)
   - Steps to reproduce the issue
   - Browser and OS information

2. **Try Basic Solutions:**
   - Restart application
   - Clear browser cache
   - Check network connectivity
   - Verify credentials

### **Support Channels**

1. **Documentation:**
   - [Implementation Complete](./IMPLEMENTATION_COMPLETE.md)
   - [Migration Guide](./migration_guide.md)
   - [Database Schema](./database_schema_design.md)

2. **Community Support:**
   - OpenAlgo GitHub Issues
   - Discord/Forum communities
   - Stack Overflow (use #openalgo tag)

3. **Professional Support:**
   - Contact OpenAlgo support team
   - Schedule technical consultation
   - Custom implementation services

### **Issue Reporting Template**

When reporting issues, include:

```
**Environment:**
- OpenAlgo Version: 
- Operating System: 
- Python Version: 
- Browser: 

**Issue Description:**
- What you were trying to do
- What happened instead
- Exact error messages

**Steps to Reproduce:**
1. 
2. 
3. 

**Logs:**
```
[Include relevant log entries]
```

**Additional Information:**
- Configuration details
- Recent changes
- Workarounds attempted
```

## 🎯 Prevention Tips

### **Best Practices**

1. **Regular Backups:**
```bash
# Backup database daily
cp db/openalgo.db backups/openalgo_$(date +%Y%m%d).db
```

2. **Monitor Logs:**
```bash
# Set up log rotation
logrotate /path/to/openalgo/log/
```

3. **Keep Credentials Updated:**
   - Regularly verify API key status
   - Update credentials before expiry
   - Test authentication periodically

4. **System Maintenance:**
   - Regular application updates
   - Database integrity checks
   - Performance monitoring

### **Monitoring Setup**

1. **Database Health:**
```sql
-- Check credential count per user
SELECT user_id, COUNT(*) as broker_count 
FROM broker_configs 
WHERE is_active = 1 
GROUP BY user_id;

-- Check for failed authentications
SELECT * FROM broker_config_audit 
WHERE action = 'auth_failed' 
ORDER BY created_at DESC 
LIMIT 10;
```

2. **Application Health:**
   - Monitor response times
   - Check error rates
   - Track memory usage
   - Verify broker API connectivity

---

**💡 Remember: Most issues are configuration-related and can be resolved by verifying credentials and following the proper setup process outlined in the [First-Time Installation Guide](./FIRST_TIME_INSTALLATION.md).**