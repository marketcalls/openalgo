# CSRF Testing Guide - Cross-Platform

This guide ensures CSRF protection works correctly across Ubuntu Server, Windows, and macOS.

## Automated Testing

### Quick Test
Run the automated test script from the project root:

```bash
# Make sure the OpenAlgo server is running first
python test/test_csrf.py

# Or test against a different URL
python test/test_csrf.py http://your-server:5000
```

The script will:
- ✅ Verify environment variables are loaded
- ✅ Check server connectivity
- ✅ Test CSRF token generation
- ✅ Verify forms are protected without CSRF
- ✅ Confirm API endpoints are exempt
- ✅ Test platform-specific compatibility

Results are saved to `csrf_test_results_{platform}.json`

## Manual Testing Checklist

### 1. Environment Setup Verification

**All Platforms:**
```bash
# Check if CSRF variables are in .env
grep "CSRF_" .env

# Expected output:
# CSRF_ENABLED = 'TRUE'
# CSRF_TIME_LIMIT = ''
```

### 2. Server Startup Test

**Ubuntu Server:**
```bash
# Start with systemd
sudo systemctl start openalgo
sudo systemctl status openalgo

# Or manually
python app.py
```

**Windows:**
```cmd
# Run from Command Prompt or PowerShell
python app.py
```

**macOS:**
```bash
# Run from Terminal
python app.py
```

**What to check:**
- Server starts without errors
- No CSRF-related warnings in console

### 3. Form Protection Tests

1. **Login Form Test**
   - Open browser: http://localhost:5000/login
   - Open Developer Tools (F12)
   - Go to Network tab
   - Try to login
   - Check request contains `csrf_token` in form data

2. **Using cURL (All Platforms)**
   ```bash
   # This should fail with 400 Bad Request
   curl -X POST http://localhost:5000/login \
     -H "Content-Type: application/x-www-form-urlencoded" \
     -d "username=test&password=test"
   ```

3. **Browser Console Test**
   ```javascript
   // This should fail without CSRF token
   fetch('/login', {
     method: 'POST',
     headers: {'Content-Type': 'application/json'},
     body: JSON.stringify({username: 'test', password: 'test'})
   }).then(r => console.log(r.status))
   ```

### 4. API Endpoint Test

```bash
# API should work without CSRF (will fail auth, but not CSRF)
curl -X GET http://localhost:5000/api/v1/orders \
  -H "X-API-KEY: your-api-key"
```

### 5. Configuration Toggle Test

1. **Disable CSRF:**
   ```bash
   # Edit .env
   CSRF_ENABLED = 'FALSE'
   ```
   
2. Restart server
3. Forms should now work without CSRF token
4. **Re-enable CSRF after testing!**

### 6. Token Expiry Test (if configured)

1. **Set time limit:**
   ```bash
   # Edit .env
   CSRF_TIME_LIMIT = '300'  # 5 minutes
   ```

2. Restart server
3. Load a form page
4. Wait 6 minutes
5. Try to submit - should fail
6. Refresh page and try again - should work

## Platform-Specific Checks

### Ubuntu Server
```bash
# Check Python version
python3 --version  # Should be 3.8+

# Check permissions
ls -la .env  # Should be readable by app user

# Check service logs
journalctl -u openalgo -n 50
```

### Windows
```powershell
# Check Python version
python --version

# Check file encoding (should be UTF-8)
Get-Content .env -Encoding UTF8 | Select-String "CSRF"

# Check Windows Defender isn't blocking
Get-MpPreference | Select-Object ExclusionPath
```

### macOS
```bash
# Check Python version
python3 --version

# Check file permissions
ls -la@ .env  # Check for extended attributes

# Check if running with correct Python
which python3
```

## Troubleshooting

### Issue: CSRF token missing
- Check `base.html` is properly extended
- Verify `{{ csrf_token() }}` in forms
- Check browser console for JavaScript errors

### Issue: 400 Bad Request on all forms
- Verify CSRF_ENABLED is 'TRUE' (not True or true)
- Check APP_KEY is set in .env
- Restart the application

### Issue: Different behavior across platforms
- Check line endings in .env (LF vs CRLF)
- Verify Python version consistency
- Check file permissions

### Issue: Tests fail on server but work locally
- Check timezone differences
- Verify session configuration
- Check proxy/reverse proxy headers

## Performance Testing

Test CSRF overhead:
```bash
# Without CSRF
CSRF_ENABLED='FALSE' python app.py

# Measure form submission time
time curl -X POST http://localhost:5000/login -d "username=test&password=test"

# With CSRF (need valid token)
CSRF_ENABLED='TRUE' python app.py
```

## Security Validation

1. **Cross-Origin Test:**
   Create a simple HTML file and open from `file://`:
   ```html
   <form action="http://localhost:5000/login" method="POST">
     <input name="username" value="test">
     <input name="password" value="test">
     <button>Submit</button>
   </form>
   ```
   This should fail with CSRF enabled.

2. **Token Uniqueness:**
   - Open two different browsers
   - Check each gets different CSRF tokens
   - Tokens shouldn't be interchangeable

## Reporting Issues

If tests fail, collect:
1. Platform info: `python -c "import platform; print(platform.platform())"`
2. Python version: `python --version`
3. Test results: `csrf_test_results_{platform}.json`
4. Server logs during test
5. `.env` contents (remove sensitive data)

## Best Practices

1. Always test after deployment
2. Test with actual broker forms
3. Monitor logs for CSRF violations
4. Keep CSRF_ENABLED='TRUE' in production
5. Document any platform-specific configurations