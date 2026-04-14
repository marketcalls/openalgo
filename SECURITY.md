# Security Policy

## Our Commitment

OpenAlgo handles sensitive financial operations and broker credentials. We take security seriously and appreciate responsible disclosure of vulnerabilities.

## Supported Versions

| Version | Supported |
|---------|-----------|
| Latest release | Yes |
| Previous release | Security fixes only |
| Older versions | No |

We recommend always running the latest version.

## Reporting a Vulnerability

**Email:** rajandran@openalgo.in

**Please include:**
- Description of the vulnerability
- Steps to reproduce
- Affected component (API, WebSocket, broker integration, etc.)
- Potential impact assessment
- Suggested fix (if any)

**Response Timeline:**
- Acknowledgment: Within 48 hours
- Initial assessment: Within 7 days
- Fix timeline: Based on severity

**Please do NOT:**
- Disclose publicly before we've addressed it
- Access other users' data
- Perform destructive testing

## Security Best Practices for Users

### API Keys
- Never share your API key publicly
- Regenerate keys if compromised
- Use environment variables, not hardcoded values

### Deployment
- Use HTTPS in production (install.sh configures this)
- Keep your server and dependencies updated
- Use strong passwords and enable TOTP
- Restrict firewall to necessary ports only (22, 80, 443)

### Broker Credentials
- Broker tokens are encrypted at rest
- Tokens expire daily (re-authentication required)
- Never commit `.env` files to version control

## Architecture Security

| Component | Protection |
|-----------|------------|
| API Keys | Hashed with pepper before storage |
| Broker Tokens | AES encryption at rest |
| Sessions | Secure cookies, CSRF protection |
| Passwords | Bcrypt hashing |
| WebSocket | API key authentication required |

## Scope

**In Scope:**
- Authentication/authorization bypass
- API key exposure or leakage
- Injection vulnerabilities (SQL, XSS, command)
- Broker credential exposure
- Unauthorized order placement
- Session hijacking

**Out of Scope:**
- Denial of service attacks
- Social engineering
- Physical security
- Third-party broker API vulnerabilities

## Recognition

We acknowledge security researchers who responsibly disclose vulnerabilities. With your permission, we'll credit you in release notes.

## Contact

- **Security issues:** rajandran@openalgo.in
- **General issues:** https://github.com/marketcalls/openalgo/issues
- **Documentation:** https://docs.openalgo.in
