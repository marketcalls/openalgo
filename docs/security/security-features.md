# OpenAlgo Security Features

## Overview

OpenAlgo includes a comprehensive security module designed to protect your trading platform from malicious traffic, bots, and unauthorized access attempts. This is especially crucial when hosting OpenAlgo on public-facing IPs or custom domains.

## Why Security Matters for Algo Traders

When you host OpenAlgo on a public IP or custom domain, your trading platform becomes accessible to the internet. This exposure can attract:

- **Web Scrapers** attempting to harvest your trading data
- **Bots** probing for vulnerabilities
- **Brute Force Attacks** trying to guess API keys
- **Automated Scanners** looking for exposed endpoints
- **DDoS Attempts** that could disrupt your trading operations

A single security breach could lead to:
- Exposed trading strategies
- Compromised API credentials
- Disrupted trading operations during critical market hours
- Unauthorized access to your portfolio data

## Core Security Features

### 1. IP Ban System

The IP ban system automatically protects your platform by blocking malicious IPs based on suspicious behavior patterns.

#### How It Works
- **Automatic Detection**: Monitors all incoming traffic for suspicious patterns
- **Threshold-Based Banning**: Automatically bans IPs that exceed predefined thresholds
- **Temporary & Permanent Bans**: First-time offenders get temporary bans, repeat offenders get permanently banned
- **Localhost Protection**: Your local IP (127.0.0.1) is protected from accidental banning

#### Ban Types
- **24 Hours**: Default for first offense
- **48 Hours**: For API key abuse
- **1 Week**: Manual option for serious violations
- **Permanent**: After 3 offenses or manual selection

### 2. 404 Error Tracking

Monitors and tracks 404 (Not Found) errors to detect bots and scanners probing for vulnerabilities.

#### Features
- **Real-time Tracking**: Every 404 error is logged with IP and attempted path
- **Auto-Ban Threshold**: 20 404 errors in 24 hours triggers automatic ban
- **Path Analysis**: View which paths attackers are attempting to access
- **24-Hour Window**: Counter resets daily for legitimate users

#### Common Attack Patterns Detected
- WordPress vulnerability scans (wp-admin, wp-login.php)
- PHPMyAdmin probes
- Configuration file searches (.env, .git, config.php)
- Admin panel discovery attempts

### 3. Invalid API Key Monitoring

Protects against brute force attacks on your API endpoints.

#### Features
- **Attempt Tracking**: Logs every invalid API key attempt
- **Auto-Ban Threshold**: 10 invalid attempts in 24 hours triggers 48-hour ban
- **Hashed Storage**: API keys are hashed before tracking for privacy
- **Integration**: Works seamlessly with all OpenAlgo API endpoints

#### Protection Against
- API key brute force attacks
- Credential stuffing attempts
- Automated API abuse
- Unauthorized trading bot access

## Security Dashboard

Access the security dashboard at `/security` (available in the profile dropdown menu).

### Dashboard Components

#### 1. Statistics Overview
- **Total Bans**: Current number of banned IPs
- **Permanent Bans**: IPs permanently blocked
- **Suspicious IPs**: IPs showing suspicious behavior
- **Near Threshold**: IPs close to auto-ban threshold

#### 2. Manual Ban Controls
- **IP Ban**: Manually ban specific IP addresses
- **Host/Domain Ban**: Ban all IPs from a specific host
- **Custom Reasons**: Document why an IP was banned
- **Duration Options**: Choose ban duration or make permanent

#### 3. Banned IPs Table
Displays all currently banned IPs with:
- IP address
- Ban reason
- Ban timestamp
- Expiry time (or permanent status)
- Ban count (repeat offenses)
- Created by (system/manual)
- Unban action button

#### 4. Invalid API Key Attempts
Shows IPs attempting invalid API authentication:
- IP address
- Number of attempts (X/10 threshold)
- First and last attempt timestamps
- Hashed API keys tried
- Quick ban action

#### 5. 404 Error Tracking
Monitors IPs generating 404 errors:
- IP address
- Error count (X/20 threshold)
- First and last error timestamps
- Paths attempted
- Ban and clear actions

## Configuration

The security module works out-of-the-box with these default thresholds:

```python
# 404 Error Threshold
MAX_404_ERRORS_PER_DAY = 20  # Auto-ban after 20 404s

# Invalid API Key Threshold
MAX_INVALID_API_ATTEMPTS = 10  # Auto-ban after 10 attempts

# Repeat Offender Threshold
PERMANENT_BAN_AFTER = 3  # Permanent ban after 3 offenses
```

These thresholds are optimized to:
- Allow legitimate users some margin for error
- Quickly identify and block malicious actors
- Prevent false positives for normal trading operations

## Usage Guide

### Accessing the Security Dashboard

1. Log in to OpenAlgo
2. Click on your profile dropdown
3. Select "Security"

### Manual IP Banning

1. Enter the IP address in the "Manual IP Ban" section
2. Provide a reason for the ban
3. Select duration (24 hours, 48 hours, 1 week, or permanent)
4. Click "Ban IP"

### Banning by Host/Domain

1. Enter the host or domain name
2. Check "Permanent Ban" if needed
3. Click "Ban Host"
4. All IPs from that host will be banned

### Unbanning an IP

1. Find the IP in the "Banned IPs" table
2. Click the "Unban" button
3. Confirm in the modal dialog

### Clearing 404 Tracker

To give an IP a fresh start:
1. Find the IP in the "404 Tracker" table
2. Click "Clear"
3. Confirm the action

## Best Practices

### For Public Hosting

1. **Regular Monitoring**: Check the security dashboard weekly
2. **Review Patterns**: Look for attack patterns in attempted paths
3. **Permanent Bans**: Use for confirmed malicious sources
4. **Documentation**: Use clear ban reasons for future reference

### For Development

1. **Localhost Safety**: Your local IP is protected from banning
2. **Testing**: Use external IPs or tools like ngrok for testing
3. **Clear Trackers**: Reset tracking data after testing

### For Production

1. **Enable HTTPS**: Use SSL certificates for encrypted connections
2. **Strong API Keys**: Use complex, randomly generated API keys
3. **Regular Updates**: Keep OpenAlgo updated for latest security patches
4. **Backup Strategy**: Regular backups before applying bans

## Security Response Workflow

When suspicious activity is detected:

1. **Automatic Response**
   - System tracks the activity
   - Thresholds are monitored
   - Auto-ban triggers if exceeded

2. **Manual Review**
   - Check security dashboard
   - Review attack patterns
   - Apply manual bans if needed

3. **Post-Incident**
   - Document the incident
   - Review if thresholds need adjustment
   - Consider permanent bans for serious attacks

## Database Information

All security data is stored in the `logs.db` database:

- **Table**: `ip_bans` - Stores banned IP information
- **Table**: `error_404_tracker` - Tracks 404 errors
- **Table**: `invalid_api_key_tracker` - Monitors API key attempts
- **Table**: `traffic_logs` - General traffic logging

No additional configuration or migration is required. The tables are created automatically on first run.

## Troubleshooting

### IP Not Getting Banned
- Check if it's localhost (protected from banning)
- Verify thresholds haven't been modified
- Ensure security middleware is active

### Can't Access After Ban
- Access from different IP
- Use database tools to remove ban
- Contact system administrator

### False Positives
- Adjust thresholds if needed
- Use manual unban for legitimate users
- Consider whitelisting (future feature)

## Future Enhancements

Planned security improvements:

1. **IP Whitelist System**: Allow trusted IPs to bypass security checks
2. **Geographic Blocking**: Ban entire countries or regions
3. **Rate Limiting**: Per-endpoint request limits
4. **Two-Factor Authentication**: Additional login security
5. **Webhook Alerts**: Notify on security events via Discord/Telegram

## Support

For security-related issues or questions:

1. Check the security dashboard first
2. Review logs in `/logs` endpoint
3. Join our Discord community
4. Report security vulnerabilities privately

Remember: Security is not a feature, it's a necessity when your money and trading strategies are at stake.