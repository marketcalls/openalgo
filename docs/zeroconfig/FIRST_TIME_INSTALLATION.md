# First-Time Installation Guide - Zero-Config OpenAlgo

## 🚀 Complete Installation Flow for New Users

This guide walks you through the complete process of setting up OpenAlgo from scratch using the zero-config broker setup system. No manual `.env` file editing required!

## 📋 Prerequisites

- Python 3.8+ installed
- OpenAlgo application downloaded
- Network access to broker APIs
- Valid broker account and API credentials

## 🎯 Step-by-Step Installation Flow

### **Step 1: Initial Application Startup**

```bash
# Start OpenAlgo
uv run app.py
```

**What Happens Internally:**
- Database tables are automatically created
- Broker templates are loaded (Dhan, Angel, Zerodha, etc.)
- No user accounts exist yet
- System is ready for first-time setup

### **Step 2: First Access - Automatic Setup Detection**

**Navigate to:** `http://127.0.0.1:5000`

**System Behavior:**
- OpenAlgo detects no users exist
- Automatically redirects to `/setup`
- No manual configuration needed

### **Step 3: Admin Account Creation**

**Page:** `/setup`

**User Actions:**
1. Fill in admin account details:
   - Username
   - Password  
   - Email (optional)
   - TOTP setup (optional but recommended)
2. Click "Create Account"

**System Response:**
- Creates admin user in database
- Initializes user session
- Redirects to login page

### **Step 4: First Login**

**Page:** `/auth/login`

**User Actions:**
1. Enter username and password
2. Click "Login"

**System Behavior:**
- Validates credentials
- Sets `session['user'] = username`
- Redirects to broker selection

### **Step 5: Broker Selection (First Time)**

**Page:** `/auth/broker`

**What You'll See:**
```
⚠️ Warning: No Brokers Configured
Please configure your broker credentials first in Broker Setup
```

**Broker List Status:**
- All brokers show as "Disabled"
- Clear link to broker setup provided
- User guidance displayed

### **Step 6: Zero-Config Broker Setup**

**Page:** `/broker/setup`

**Interface:**
- **Grid Layout**: Visual cards for each supported broker
- **Status Indicators**: 
  - "Not Set" (red) - Needs configuration
  - "Configured" (green) - Ready to use
- **Supported Brokers**: Dhan, Angel One, Zerodha, AliceBlue, etc.

**User Actions:**
1. Click "Configure" on desired broker
2. Multiple brokers can be configured

### **Step 7: Broker Credential Configuration**

**Page:** `/broker/configure/<broker_name>` (e.g., `/broker/configure/angel`)

**Form Fields:**

#### **Standard Brokers (2 credentials):**
- API Key
- API Secret
- Redirect URL (auto-generated)
- Set as default broker (checkbox)

#### **XTS Brokers (4 credentials):**
- Trading API Key
- Trading API Secret  
- Market Data API Key
- Market Data API Secret
- Redirect URL (auto-generated)
- Set as default broker (checkbox)

**Security Features:**
- All credentials encrypted before storage
- CSRF protection on forms
- Input validation and sanitization

**User Actions:**
1. Enter broker API credentials
2. Optionally set as default broker
3. Click "Save Configuration"

**System Response:**
```json
{
  "success": true,
  "message": "Configuration saved successfully",
  "logout_required": false
}
```

### **Step 8: Configuration Confirmation**

**Page:** Returns to `/broker/setup`

**Updated Status:**
- Configured broker shows "Configured ✅"
- Option to configure additional brokers
- Clear overview of setup progress

**User Options:**
- Configure more brokers
- Proceed to login
- Manage existing configurations

### **Step 9: Updated Broker Selection**

**Page:** `/auth/broker`

**What You'll See:**
```
ℹ️ Info: Configured Brokers
You have 1 broker(s) configured: angel
```

**Broker List Status:**
- Configured brokers: **ENABLED** ✅
- Unconfigured brokers: **DISABLED**
- Clear indication of available options

### **Step 10: Broker Authentication**

**User Actions:**
1. Select configured broker from dropdown
2. Click "Connect Account"

**System Behavior:**
- Loads database credentials automatically
- Redirects to broker-specific authentication

### **Step 11: Broker-Specific Login**

**Examples:**

#### **Angel One** (`/angel/callback`):
- Enter Client ID
- Enter PIN
- Enter TOTP code
- Submit form

#### **Dhan** (`/dhan/callback`):
- Automatic OAuth redirect
- User authorizes on Dhan website
- Returns to OpenAlgo with token

**System Processing:**
1. Uses database credentials for API calls
2. Validates with broker API
3. Stores authentication tokens
4. Sets up user session

### **Step 12: Dashboard Access**

**Final Result:**
- User successfully logged in
- Full dashboard access
- All trading functions operational
- Master contract download begins automatically

## 🔄 **Complete Call Flow Diagram**

```
┌─────────────────┐    ┌─────────────────┐    ┌─────────────────┐
│   First Visit   │───▶│  No Users Found │───▶│   Setup Page    │
│ 127.0.0.1:5000  │    │   Auto Detect   │    │   /setup        │
└─────────────────┘    └─────────────────┘    └─────────────────┘
                                                        │
                                                        ▼
┌─────────────────┐    ┌─────────────────┐    ┌─────────────────┐
│  Login Success  │◀───│   Login Page    │◀───│ Account Created │
│ session['user'] │    │  /auth/login    │    │  Redirect       │
└─────────────────┘    └─────────────────┘    └─────────────────┘
          │
          ▼
┌─────────────────┐    ┌─────────────────┐    ┌─────────────────┐
│ Broker Warning  │───▶│ Broker Setup    │───▶│ Configure Form  │
│ No Configs Found│    │  /broker/setup  │    │/broker/configure│
└─────────────────┘    └─────────────────┘    └─────────────────┘
                                                        │
                                                        ▼
┌─────────────────┐    ┌─────────────────┐    ┌─────────────────┐
│   Dashboard     │◀───│ Broker Auth     │◀───│ Credentials     │
│   Success!      │    │ /broker/callback│    │    Saved        │
└─────────────────┘    └─────────────────┘    └─────────────────┘
```

## 🛠️ **Technical Implementation Details**

### **Database Schema**
```sql
-- Broker configurations (encrypted)
broker_configs: [user_id, broker_name, encrypted_credentials, ...]

-- Broker templates (pre-loaded)
broker_templates: [broker_name, display_name, required_fields, ...]

-- User accounts
users: [username, password_hash, email, ...]

-- Authentication tokens
auth: [user_id, auth_token, broker, feed_token, ...]
```

### **Credential Priority System**
1. **Database credentials** (primary)
2. **Environment variables** (fallback for compatibility)

### **Security Features**
- **Fernet Encryption**: All credentials encrypted at rest
- **CSRF Protection**: All forms protected with tokens
- **Session Management**: Secure session handling
- **Audit Logging**: Complete trail of credential changes
- **Auto-logout**: On credential changes for security

## 🔧 **Management and Configuration**

### **Post-Setup Management**

#### **Broker Management** (`/broker/manage`):
- View all configured brokers
- Edit existing configurations
- Set default broker
- Delete configurations
- View connection status

#### **Multiple Broker Support**:
- Configure multiple brokers per user
- Switch between brokers easily
- Each broker maintains separate credentials
- Independent authentication tokens

### **Configuration Updates**

**When credentials change:**
1. User gets warning modal about security implications
2. System triggers automatic logout on save
3. Auth tokens are cleared from database
4. Fresh authentication required
5. Master contract re-download triggered

## 🚨 **Troubleshooting**

### **Common Issues**

#### **1. Broker Not Available**
**Symptoms**: Broker shows as disabled
**Solution**: Configure broker via `/broker/setup`

#### **2. Authentication Fails**
**Symptoms**: Login fails after credential entry
**Causes**: 
- Invalid API credentials
- Broker API key not active
- Network connectivity issues
**Solution**: Verify credentials in broker portal

#### **3. Master Contract Download Fails**
**Symptoms**: Dashboard loads but no symbol data
**Solution**: Check broker authentication and API limits

#### **4. Session Expires Quickly**
**Symptoms**: Frequent logouts
**Causes**: 
- Credential changes triggering security logout
- Session configuration issues
**Solution**: Check session settings and avoid credential changes

### **Getting Help**

#### **Debug Information**
- Check application logs in terminal
- Review browser developer console
- Check network connectivity to broker APIs

#### **Support Channels**
- OpenAlgo GitHub Issues
- Documentation: `/docs/zeroconfig/`
- Community forums

## 🎉 **Success Indicators**

### **Complete Setup Checklist**
- [ ] Admin account created successfully
- [ ] At least one broker configured
- [ ] Broker authentication succeeds
- [ ] Dashboard loads with margin data
- [ ] Master contract download completes
- [ ] Trading functions accessible

### **What You Should See**
1. **Broker Setup**: All desired brokers show "Configured ✅"
2. **Login Page**: Only configured brokers are enabled
3. **Dashboard**: Margin data loads without errors
4. **Logs**: "Using database credentials" messages
5. **Navigation**: Access to all trading features

## 📚 **Next Steps**

After successful installation:

1. **Configure Trading Strategy**: Set up your algorithmic trading strategies
2. **Test Trading**: Place test orders to verify functionality
3. **Set Up Monitoring**: Configure alerts and monitoring
4. **Backup Configuration**: Export broker configurations if needed
5. **Additional Brokers**: Configure additional brokers as needed

## 🔗 **Related Documentation**

- **[Migration Guide](./migration_guide.md)** - For upgrading existing installations
- **[Database Schema](./database_schema_design.md)** - Technical implementation details
- **[Implementation Complete](./IMPLEMENTATION_COMPLETE.md)** - Current system status
- **[Troubleshooting](./troubleshooting.md)** - Common issues and solutions

---

**🎯 The zero-config system eliminates all manual configuration barriers, making OpenAlgo accessible to users of all technical levels while maintaining enterprise-grade security and functionality.**