# SMTP Email Setup for OpenAlgo

## Migration (Add Email to Existing Installation)

Run this command in your OpenAlgo directory:

```bash
python upgrade/migrate_smtp_simple.py
```

This adds email functionality to your existing database safely.

## Gmail Configuration Options

Choose the configuration that matches your Gmail setup:

### Personal Gmail (Recommended)

After migration, go to **Profile → SMTP Configuration** and use:

```
SMTP Server: smtp.gmail.com
SMTP Port: 587
Username: your-email@gmail.com
Password: [App Password - see below]
Use TLS/SSL: ✓ (checked)
From Email: your-email@gmail.com
HELO Hostname: smtp.gmail.com
```

### Google Workspace (Business Gmail)

For business domains (e.g., user@yourcompany.com):

#### Option 1: SMTP Relay (Recommended for Businesses)

**Requirements:**
- Google Workspace Admin access
- Server IP registration in Google Admin Console

**Configuration:**
```
SMTP Server: smtp-relay.gmail.com
SMTP Port: 465
Username: your-email@yourcompany.com
Password: [App Password - see below]
Use TLS/SSL: ✓ (checked)
From Email: your-email@yourcompany.com
HELO Hostname: smtp.gmail.com
```

**Setup Steps:**
1. **Admin Console Setup:**
   - Go to [Google Admin Console](https://admin.google.com)
   - Navigate to **Apps → Google Workspace → Gmail → SMTP relay service**
   - Click **Add another** to create new relay
   - Configure these settings:
     ```
     Allowed senders: Only addresses in my domains
     Authentication: Require SMTP Authentication
     Encryption: Require TLS encryption
     ```
   - **Add your server IP address** to allowed IP ranges
   - Save the configuration

2. **Find Your Server IP:**
   ```bash
   # From your OpenAlgo server, run:
   curl -4 ifconfig.me
   # Or visit: https://whatismyipaddress.com/
   ```

3. **Register IP in Admin Console:**
   - In SMTP relay settings, add your server IP to **IP addresses**
   - Format: `YOUR.SERVER.IP.ADDRESS/32` (e.g., `203.0.113.15/32`)

#### Option 2: Personal Gmail Settings (Alternative)

If SMTP relay setup is complex, use personal Gmail settings:

```
SMTP Server: smtp.gmail.com
SMTP Port: 587
Username: your-email@yourcompany.com
Password: [App Password]
Use TLS/SSL: ✓ (checked)
From Email: your-email@yourcompany.com
HELO Hostname: smtp.gmail.com
```

## App Password Setup (Required for Both)

### For Personal Gmail:
1. Go to [Google Account Settings](https://myaccount.google.com/apppasswords)
2. Enable 2-Factor Authentication (if not enabled)
3. Select **App passwords**
4. Choose **Mail** from dropdown
5. Generate password and copy the 16-character code
6. Use this password in OpenAlgo (NOT your regular password)

### For Google Workspace:
1. Go to [Google Account Settings](https://myaccount.google.com/apppasswords)
2. **Admin may need to enable App Passwords:**
   - Admin Console → Security → API controls → App passwords
   - Enable "Allow users to manage their app passwords"
3. Follow same steps as personal Gmail above
4. If App Passwords unavailable, ask your IT administrator

## Advanced Google Workspace Configuration

### Admin Console SMTP Relay Settings

For enterprise deployments, configure these advanced settings:

1. **Security Settings:**
   ```
   Require TLS encryption: Yes
   Require SMTP Authentication: Yes
   Only accept mail from specified IP addresses: Yes
   ```

2. **Rate Limiting:**
   ```
   Per-user rate limit: 10,000 messages/day
   Per-domain rate limit: 1,000,000 messages/day
   ```

3. **Routing Settings:**
   ```
   Also deliver to Gmail mailbox: Optional
   Store and forward: Recommended for reliability
   ```

### Multiple Domain Support

If you have multiple domains in Workspace:

1. **Primary Domain Configuration:**
   ```
   SMTP Server: smtp-relay.gmail.com
   From Email: noreply@primarydomain.com
   ```

2. **Additional Domains:**
   - Add all domains to Admin Console → Domains
   - Enable SMTP relay for each domain
   - Use same SMTP settings with appropriate From Email

### Troubleshooting Google Workspace

#### Common Error: "Mail relay denied"

**Solution 1 - IP Registration:**
```bash
# Check your current IP
curl -4 ifconfig.me

# Add this IP to Google Admin Console:
# Apps → Gmail → SMTP relay service → IP addresses
```

**Solution 2 - Authentication:**
- Verify App Password is correctly generated
- Ensure 2FA is enabled on the account
- Check username format (full email address)

**Solution 3 - Fallback to Personal Settings:**
```
SMTP Server: smtp.gmail.com (instead of smtp-relay.gmail.com)
SMTP Port: 587 (instead of 465)
```

#### Error: "Authentication failed"

1. **Check App Password:**
   - Must be 16 characters without spaces
   - Generated specifically for "Mail"
   - Account must have 2FA enabled

2. **Admin Policy Check:**
   ```
   Admin Console → Security → Less secure app access
   Should be: "Allow users to manage their access to less secure apps"
   ```

3. **Account Verification:**
   - Ensure account is not suspended
   - Check for recent password changes

## Testing Your Configuration

### Step-by-Step Testing

1. **Save SMTP Settings** in Profile → SMTP Configuration
2. **Click "Debug"** to test connection and view detailed diagnostics
3. **Click "Send Test"** to send test email to yourself
4. **Check your inbox** (and spam folder)
5. **Try Password Reset** to test end-to-end functionality

### Expected Test Results

**Debug Output (Success):**
```
✓ SMTP connection successful
✓ Authentication passed
✓ TLS encryption enabled
✓ Server ready to accept messages
```

**Debug Output (Common Issues):**
```
✗ Mail relay denied → Check IP registration in Admin Console
✗ Authentication failed → Verify App Password
✗ Connection timeout → Check firewall/network settings
```

### Testing Different Scenarios

1. **Test from Different IPs:** If using multiple servers
2. **Test Different From Addresses:** Verify domain permissions
3. **Test High Volume:** Check rate limiting behavior
4. **Test Failed Authentication:** Verify error handling

## Production Deployment Best Practices

### Security Recommendations

1. **Use Dedicated Service Account:**
   ```
   Create: noreply@yourcompany.com
   Purpose: SMTP authentication only
   Permissions: Minimal (just send email)
   ```

2. **IP Whitelist Management:**
   - Use static IP addresses for production servers
   - Document all registered IPs
   - Regular audit of IP permissions

3. **Monitor Email Logs:**
   - Track successful/failed send attempts
   - Monitor for suspicious activity
   - Set up alerts for authentication failures

### Performance Optimization

1. **Connection Pooling:** Use persistent SMTP connections when possible
2. **Rate Limiting:** Respect Google's sending limits
3. **Retry Logic:** Implement exponential backoff for failures
4. **Queue Management:** Handle high-volume email sending

## Common Issues & Solutions

### Personal Gmail Issues

- **Authentication Failed**: Use App Password, not regular password
- **Connection Failed**: Try port 587 instead of 465
- **2FA Required**: Enable 2-Factor Authentication first

### Google Workspace Issues

- **Mail relay denied**: 
  - Register server IP in Admin Console
  - Verify SMTP relay service is enabled
  - Check authentication credentials

- **Admin restrictions**: 
  - App passwords may be disabled by admin
  - Less secure app access may be blocked
  - Contact IT administrator for policy changes

- **Domain verification**:
  - Ensure domain is verified in Workspace
  - Check MX records are properly configured
  - Verify user account is active

### Network & Firewall Issues

- **Port blocking**: Ensure ports 587/465 are open outbound
- **Proxy servers**: Configure SMTP through corporate proxy if needed
- **DNS resolution**: Verify smtp.gmail.com resolves correctly

## Alternative Email Providers

### Microsoft 365 / Outlook

**Business (Exchange Online):**
```
SMTP Server: smtp.office365.com
SMTP Port: 587
Username: your-email@yourcompany.com
Password: [Account Password or App Password]
Use TLS/SSL: ✓ (checked)
From Email: your-email@yourcompany.com
HELO Hostname: smtp.office365.com
```

**Personal Outlook/Hotmail:**
```
SMTP Server: smtp-mail.outlook.com
SMTP Port: 587
Username: your-email@outlook.com
Password: [Account Password]
Use TLS/SSL: ✓ (checked)
From Email: your-email@outlook.com
HELO Hostname: smtp-mail.outlook.com
```

### Yahoo Mail

```
SMTP Server: smtp.mail.yahoo.com
SMTP Port: 587
Username: your-email@yahoo.com
Password: [App Password from Yahoo Account Security]
Use TLS/SSL: ✓ (checked)
From Email: your-email@yahoo.com
HELO Hostname: smtp.mail.yahoo.com
```

### Custom SMTP Providers

**SendGrid:**
```
SMTP Server: smtp.sendgrid.net
SMTP Port: 587
Username: apikey
Password: [SendGrid API Key]
```

**Mailgun:**
```
SMTP Server: smtp.mailgun.org
SMTP Port: 587
Username: [Mailgun SMTP Username]
Password: [Mailgun SMTP Password]
```

## Enterprise Integration

### Load Balancing

For high-availability setups:
1. Configure multiple SMTP servers
2. Implement failover logic
3. Monitor server health
4. Balance email load across servers

### Compliance & Logging

1. **Audit Requirements:**
   - Log all email send attempts
   - Track recipient information (hashed)
   - Monitor for compliance violations

2. **Data Retention:**
   - Configure log retention periods
   - Implement secure log storage
   - Regular compliance audits

### Monitoring & Alerting

Set up monitoring for:
- SMTP connection failures
- Authentication errors
- Rate limit violations
- Unusual sending patterns

## Support & Resources

### Google Support Links

- [Google Workspace SMTP Relay](https://support.google.com/a/answer/2956491) - General SMTP relay documentation
- [App Passwords Setup](https://support.google.com/accounts/answer/185833) - How to generate App Passwords
- [Admin Console Guide](https://support.google.com/a/answer/2956491) - SMTP relay service configuration

### OpenAlgo Resources

- **Built-in Debug**: Use SMTP Debug function in profile
- **Log Files**: Check OpenAlgo logs for detailed error messages
- **GitHub Issues**: Report SMTP-specific problems
- **Documentation**: `/docs/PASSWORD_RESET.md` for complete system overview

---

**That's it!** Your OpenAlgo can now send emails for password resets and notifications using your preferred email provider. Choose the configuration that best fits your organization's setup and security requirements.