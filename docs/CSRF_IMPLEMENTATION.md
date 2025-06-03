# CSRF Implementation Documentation

## Overview
OpenAlgo now implements comprehensive CSRF (Cross-Site Request Forgery) protection using Flask-WTF to secure all form submissions and state-changing operations.

## Implementation Details

### 1. Core Configuration
CSRF protection is initialized in `app.py`:
```python
from flask_wtf.csrf import CSRFProtect
csrf = CSRFProtect(app)
app.config['WTF_CSRF_TIME_LIMIT'] = None  # No time limit for tokens
app.config['WTF_CSRF_ENABLED'] = True
```

### 2. Protected Forms
All 26+ forms across the application now include CSRF tokens:

#### Authentication Forms
- Login (`/templates/login.html`)
- Password Reset (`/templates/reset_password.html`)
- Initial Setup (`/templates/setup.html`)
- Profile/Password Change (`/templates/profile.html`)

#### Broker Authentication Forms
- Angel One, 5paisa, AliceBlue, Firstock, Kotak, Shoonya, Tradejini, Zebu
- All broker forms include: `<input type="hidden" name="csrf_token" value="{{ csrf_token() }}"/>`

#### Management Forms
- API Key Generation (`/templates/apikey.html`)
- Strategy Creation (`/templates/strategy/new_strategy.html`)
- ChartInk Strategy (`/templates/chartink/new_strategy.html`)
- Symbol Configuration (with AJAX protection)

### 3. AJAX Request Protection

A global helper function is provided in `base.html`:
```javascript
function getCSRFToken() {
    const token = document.querySelector('meta[name="csrf-token"]');
    return token ? token.getAttribute('content') : '';
}

// Usage in fetch requests
fetch(url, {
    method: 'POST',
    headers: {
        'Content-Type': 'application/json',
        'X-CSRFToken': getCSRFToken()
    },
    body: JSON.stringify(data)
})
```

### 4. API Endpoint Exemption
REST API endpoints (`/api/v1/*`) are exempt from CSRF protection as they use API key authentication:
```python
csrf.exempt(api_v1_bp)
```

### 5. Security Benefits
- **Prevents CSRF attacks**: Malicious websites cannot forge requests
- **Session-based validation**: Tokens are tied to user sessions
- **No time expiration**: Tokens remain valid for the session duration
- **Transparent to users**: Protection works seamlessly in the background

## Testing CSRF Protection

### Manual Testing
1. Try submitting any form without the CSRF token - it should fail with a 400 error
2. Submit forms normally - they should work as expected
3. Check browser developer tools to see CSRF tokens in requests

### Automated Test
Run the provided test script:
```bash
python test_csrf.py
```

## Developer Guidelines

### Adding New Forms
1. For HTML forms, add the CSRF token field:
   ```html
   <form method="POST">
       <input type="hidden" name="csrf_token" value="{{ csrf_token() }}"/>
       <!-- other fields -->
   </form>
   ```

2. For AJAX requests, include the token in headers:
   ```javascript
   headers: {
       'X-CSRFToken': getCSRFToken()
   }
   ```

### Troubleshooting
- **400 Bad Request**: Missing or invalid CSRF token
- **Token not found**: Ensure `base.html` is extended (contains meta tag)
- **API calls failing**: Check if endpoint should be exempt

## Migration Notes
- All existing forms have been updated with CSRF protection
- No changes required to existing user workflows
- API integrations continue to work with API key authentication