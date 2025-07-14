# Migration Guide: From .env to Zero-Config Broker Setup

## Overview

This guide provides detailed instructions for migrating OpenAlgo from the manual `.env` broker configuration system to the new zero-config, database-driven broker setup system. The migration process is designed to be seamless and backwards compatible.

## Migration Timeline

### Phase 1: Preparation (Pre-Migration)
- **Duration**: 1-2 days
- **Goal**: Prepare for migration without disrupting current operations
- **Backwards Compatibility**: Full

### Phase 2: Database Setup (Migration Day)
- **Duration**: 1 day
- **Goal**: Set up new database schema and migrate existing configurations
- **Backwards Compatibility**: Full (both systems active)

### Phase 3: Transition Period
- **Duration**: 2-4 weeks
- **Goal**: Users adopt new system while maintaining .env fallback
- **Backwards Compatibility**: Full with deprecation warnings

### Phase 4: Completion
- **Duration**: Ongoing
- **Goal**: Full adoption of new system, .env configs deprecated
- **Backwards Compatibility**: Limited (warnings only)

## Pre-Migration Checklist

### System Requirements
- [ ] OpenAlgo version 2.0+ installed
- [ ] Database backup completed
- [ ] Administrative access to OpenAlgo instance
- [ ] Current .env file documented
- [ ] Network connectivity verified

### Backup Procedures
```bash
# 1. Backup current database
cp /path/to/openalgo/db/openalgo.db /path/to/backup/openalgo_pre_migration_$(date +%Y%m%d).db

# 2. Backup .env file
cp /path/to/openalgo/.env /path/to/backup/env_backup_$(date +%Y%m%d).txt

# 3. Backup application files (if modified)
tar -czf /path/to/backup/openalgo_app_backup_$(date +%Y%m%d).tar.gz /path/to/openalgo/
```

### Environment Assessment
```bash
# Check current broker configuration
cat .env | grep BROKER_

# Expected output:
# BROKER_API_KEY=your_api_key
# BROKER_API_SECRET=your_api_secret
# BROKER_API_KEY_MARKET=your_market_api_key  (optional)
# BROKER_API_SECRET_MARKET=your_market_api_secret  (optional)
# REDIRECT_URL=http://127.0.0.1:5000/broker/callback
```

## Migration Process

### Step 1: Update OpenAlgo

#### Option A: Automatic Update (Recommended)
```bash
cd /path/to/openalgo
git pull origin main
pip install -r requirements.txt
```

#### Option B: Manual Update
1. Download latest OpenAlgo release
2. Extract to new directory
3. Copy existing database and .env files
4. Install dependencies

### Step 2: Run Database Migration

```bash
# Navigate to OpenAlgo directory
cd /path/to/openalgo

# Run migration script
python migrations/001_create_broker_configs.py

# Expected output:
# Migration 001: Creating broker configuration tables...
# - Created broker_templates table
# - Created broker_configs table  
# - Created broker_config_audit table
# - Created indexes
# - Inserted default broker templates
# Migration completed successfully!
```

### Step 3: Migrate Existing Configuration

#### Automatic Migration
```bash
# Run automatic migration script
python migrations/migrate_env_to_db.py

# Interactive prompts:
# Detected broker configuration in .env file
# Broker: dhan
# API Key: 1000002130 (masked)
# API Secret: eyJ0eXAi... (masked)
# Redirect URL: http://127.0.0.1:5000/dhan/callback
# 
# Migrate this configuration to database? (y/n): y
# Enter admin username: admin
# Configuration migrated successfully!
# Test connection? (y/n): y
# Connection test: SUCCESS
```

#### Manual Migration (Alternative)
If automatic migration fails, use the web interface:

1. **Access OpenAlgo**: Navigate to your OpenAlgo URL
2. **Login**: Use admin credentials
3. **Broker Setup**: Go to Settings → Broker Configuration
4. **Add Configuration**: Click "Add New Broker"
5. **Select Broker**: Choose your broker (e.g., Dhan, Angel)
6. **Enter Credentials**: 
   - API Key: Copy from .env `BROKER_API_KEY`
   - API Secret: Copy from .env `BROKER_API_SECRET`
   - Market API Key: Copy from .env `BROKER_API_KEY_MARKET` (if applicable)
   - Market API Secret: Copy from .env `BROKER_API_SECRET_MARKET` (if applicable)
7. **Test Connection**: Click "Test Connection"
8. **Save Configuration**: If test passes, click "Save"

### Step 4: Verification

#### Verify Database Migration
```bash
# Check if tables were created
sqlite3 db/openalgo.db ".tables" | grep broker

# Expected output:
# broker_configs
# broker_templates
# broker_config_audit
```

#### Verify Configuration Migration
```bash
# Check migrated configurations
sqlite3 db/openalgo.db "SELECT user_id, broker_name, is_active, is_default FROM broker_configs;"

# Expected output:
# admin|dhan|1|1
```

#### Test Application Functionality
1. **Login Test**: Verify user login still works
2. **Broker Authentication**: Test broker login flow
3. **Trading Functions**: Verify basic trading operations
4. **Dashboard Access**: Check dashboard loads correctly

### Step 5: User Communication

#### Notify Users
Send communication to all users about the new feature:

```
Subject: OpenAlgo Enhancement - New Broker Configuration System

Dear OpenAlgo Users,

We've enhanced OpenAlgo with a new zero-configuration broker setup system. 

New Features:
- Web-based broker configuration (no more .env editing!)
- Support for multiple brokers per user
- Improved security with encrypted credential storage
- Easy broker switching and management

For existing users:
- Your current broker configuration has been automatically migrated
- No action required - everything continues to work as before
- New broker management interface available in Settings

For new features, visit: Settings → Broker Configuration

Best regards,
OpenAlgo Team
```

## Post-Migration Tasks

### Immediate Tasks (Day 1)

#### Monitor System Health
```bash
# Check application logs
tail -f log/openalgo_$(date +%Y-%m-%d).log

# Monitor for any migration-related errors
grep -i "broker\|migration\|error" log/openalgo_$(date +%Y-%m-%d).log
```

#### Verify User Access
- [ ] Test admin login and broker configuration access
- [ ] Verify new users can set up broker configurations
- [ ] Confirm existing users can access their accounts

### Week 1 Tasks

#### User Support
- [ ] Monitor support channels for migration-related issues
- [ ] Provide assistance with broker configuration setup
- [ ] Document common issues and solutions

#### System Optimization
- [ ] Monitor database performance
- [ ] Optimize caching settings if needed
- [ ] Review and adjust rate limiting settings

### Week 2-4 Tasks

#### Feature Adoption
- [ ] Track usage of new broker configuration features
- [ ] Gather user feedback on the new interface
- [ ] Identify areas for improvement

#### Gradual Deprecation
- [ ] Add deprecation warnings for .env broker configurations
- [ ] Encourage users to migrate to database configuration
- [ ] Plan timeline for .env support removal

## Troubleshooting

### Common Migration Issues

#### Issue: Migration Script Fails
```bash
# Error: Unable to connect to database
# Solution: Check database file permissions
chmod 664 db/openalgo.db
chown openalgo:openalgo db/openalgo.db
```

#### Issue: Broker Configuration Not Found
```bash
# Error: No broker configuration found for user
# Solution: Check if migration completed
sqlite3 db/openalgo.db "SELECT * FROM broker_configs WHERE user_id='admin';"

# If empty, run manual migration
python migrations/migrate_env_to_db.py --force
```

#### Issue: Connection Test Fails
```
# Error: Broker authentication failed
# Solution: Verify credentials in database
# 1. Check if credentials are encrypted correctly
# 2. Verify broker API endpoints are accessible
# 3. Confirm API keys are valid and active
```

#### Issue: Multiple Default Brokers
```sql
-- Error: Constraint violation on is_default
-- Solution: Fix constraint violation
UPDATE broker_configs SET is_default = FALSE WHERE user_id = 'admin';
UPDATE broker_configs SET is_default = TRUE WHERE user_id = 'admin' AND broker_name = 'dhan';
```

### Advanced Troubleshooting

#### Database Integrity Check
```bash
# Check database integrity
sqlite3 db/openalgo.db "PRAGMA integrity_check;"

# Check foreign key constraints
sqlite3 db/openalgo.db "PRAGMA foreign_key_check;"
```

#### Manual Credential Decryption (Debug Only)
```python
# Only for debugging - never in production
from database.broker_config_db import decrypt_credential

# Get encrypted credential from database
encrypted_key = "gAAAAABh..."  # From database
decrypted_key = decrypt_credential(encrypted_key)
print(f"Decrypted API Key: {decrypted_key[:4]}...")  # Show only first 4 chars
```

#### Recovery Procedures
```bash
# If migration fails completely, restore from backup
cp /path/to/backup/openalgo_pre_migration_*.db db/openalgo.db

# If database corruption occurs
sqlite3 db/openalgo.db ".backup db/openalgo_recovered.db"
mv db/openalgo_recovered.db db/openalgo.db
```

## Rollback Procedures

### Emergency Rollback (If Required)

#### Step 1: Stop Application
```bash
# Stop OpenAlgo service
sudo systemctl stop openalgo
# or
pkill -f "python app.py"
```

#### Step 2: Restore Database
```bash
# Restore pre-migration database
cp /path/to/backup/openalgo_pre_migration_*.db db/openalgo.db
```

#### Step 3: Restore Application Files
```bash
# If application files were modified
tar -xzf /path/to/backup/openalgo_app_backup_*.tar.gz -C /
```

#### Step 4: Restart Application
```bash
# Restart OpenAlgo
sudo systemctl start openalgo
# or
python app.py
```

### Partial Rollback (Keep New Features)

If you want to keep the new system but revert specific configurations:

```sql
-- Remove specific broker configuration
DELETE FROM broker_configs WHERE user_id = 'admin' AND broker_name = 'dhan';

-- Disable new system for specific user (forces .env fallback)
UPDATE broker_configs SET is_active = FALSE WHERE user_id = 'admin';
```

## Validation and Testing

### Migration Success Criteria

#### Database Validation
- [ ] All new tables created successfully
- [ ] Existing data preserved
- [ ] Foreign key constraints working
- [ ] Indexes created and optimized

#### Functional Validation
- [ ] User authentication works
- [ ] Broker authentication succeeds
- [ ] Trading functions operational
- [ ] New broker configuration interface accessible

#### Security Validation
- [ ] Credentials properly encrypted
- [ ] No plaintext secrets in database
- [ ] Access controls functioning
- [ ] Audit logging active

### Testing Scenarios

#### Scenario 1: Existing User Login
1. Login with existing credentials
2. Verify broker connection
3. Execute test trade
4. Access broker configuration interface

#### Scenario 2: New User Registration
1. Create new user account
2. Set up broker configuration
3. Test broker connection
4. Verify trading functionality

#### Scenario 3: Multi-Broker Setup
1. Configure primary broker (e.g., Dhan)
2. Add secondary broker (e.g., Angel)
3. Switch between brokers
4. Test functionality with both

#### Scenario 4: Configuration Management
1. Edit existing broker configuration
2. Test connection with new credentials
3. Deactivate and reactivate configuration
4. Delete and recreate configuration

## Monitoring and Maintenance

### Post-Migration Monitoring

#### Application Metrics
- Response time for broker authentication
- Database query performance
- Error rates and patterns
- User adoption of new features

#### Database Metrics
- Table sizes and growth
- Index usage and efficiency
- Lock contention and deadlocks
- Backup and recovery procedures

### Ongoing Maintenance

#### Weekly Tasks
- [ ] Review broker configuration audit logs
- [ ] Monitor credential validation success rates
- [ ] Check for failed connection attempts
- [ ] Update broker templates if needed

#### Monthly Tasks
- [ ] Analyze user adoption metrics
- [ ] Review and optimize database performance
- [ ] Plan feature enhancements
- [ ] Update documentation

## Support and Resources

### Getting Help

#### Internal Support
- Check application logs: `/path/to/openalgo/log/`
- Review audit trails in database
- Consult troubleshooting section above

#### Community Support
- OpenAlgo GitHub Issues: Report bugs or request help
- OpenAlgo Discord/Forums: Community discussion
- Documentation: Comprehensive guides and references

#### Professional Support
- Contact OpenAlgo support team
- Schedule consultation for complex migrations
- Custom migration services available

### Additional Resources

#### Documentation
- [Zero-Config Broker Setup Guide](zero_config_broker_setup.md)
- [Database Schema Design](database_schema_design.md)
- [Implementation Phases](implementation_phases.md)

#### Tools and Scripts
- Migration validation scripts
- Performance monitoring tools
- Backup and recovery utilities

## Conclusion

The migration from .env to zero-config broker setup represents a significant improvement in OpenAlgo's usability and security. By following this guide carefully and using the provided tools and scripts, the migration should be smooth and transparent to end users.

Key benefits of the new system:
- **Ease of Use**: No more manual file editing
- **Security**: Encrypted credential storage
- **Flexibility**: Multiple broker support
- **Scalability**: Per-user configurations

Remember to:
- Always backup before migration
- Test thoroughly after migration
- Monitor system health post-migration
- Provide user support during transition

If you encounter any issues during migration, refer to the troubleshooting section or contact support for assistance.