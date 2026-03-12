# 🏆 FOSS Hackathon 2026 - luckyansari22 Battle Plan
**Status**: ACTIVE  
**Deadline**: April 1, 2026 (20 days remaining)  
**Goal**: Win with 15+ merged PRs  
**Current Score**: 1 merged, 14 in-progress  
**Pace**: ON TRACK ✅

---

## 📊 PHASE OVERVIEW

| Phase | Dates | Goal | PRs | Status |
|-------|-------|------|-----|--------|
| **FAST TRACK** | Mar 10-13 | Quick merges for momentum | 5 | 🚀 ACTIVE |
| **STRATEGIC** | Mar 14-27 | Critical April 1 items | 7 | 🎯 PENDING |
| **FINAL PUSH** | Mar 28-Apr1 | Catch stragglers & ship | 2-3 | ⏰ PENDING |
| **TOTAL** | - | **VICTORY** | **15+** | - |

---

# 🚀 PHASE 1: FAST TRACK (Mar 10-13)
**Objective**: Get 5 more merges in 5 days = 6 total = Strong start

## PR Status & Action Items

### 1. ✅ PR #981 - Database Docstrings (CRITICAL - Need Final Approval)
**Current Status**: Awaiting final maintainer approval  
**Files**: 
- `database/auth_db.py` - FIXED security issues
- `database/user_db.py` - FIXED Argon2/TOTP exposure
- `database/apilog_db.py` - FIXED threading model docs
- `database/tv_search.py` - FIXED function attribution

**Your Work Done**: ✅
- Fixed all 5 feedback items from @marketcalls
- Addressed Argon2 + TOTP security disclosure
- Corrected threading documentation
- Re-submitted with comprehensive commit fab0f66

**Remaining Action**:
- [ ] **TODAY (Mar 10)**: Comment on #981 mentioning `@marketcalls` - "All feedback items addressed, ready for final review"
- [ ] Push notification/mention in PR
- [ ] **TARGET MERGE**: Mar 10 EOD or Mar 11 AM

**Impact**: +92 lines, database module fully documented, critical for framework stability

---

### 2. ⭐ PR #1040 - Docker Bind Mounts (MAINTAINER ASSIGNED - HIGH VISIBILITY)
**Current Status**: Open, assigned by maintainer  
**Complexity**: HIGH (5 bot feedback items found - all addressed)

**Bot Feedback Items & Your Fixes**:
1. ✅ P1: Migration errors masked by `|| true` - FIXED (added proper error checking)
2. ✅ P1: Security guidance too permissive - FIXED (corrected .env permissions)
3. ✅ P2: Migration path depends on CWD - FIXED (absolute path handling)
4. ✅ P2: False success reporting - FIXED (proper exit codes)
5. ✅ P2: Volume grep substring issues - FIXED (exact matching)

**Remaining Action**:
- [ ] **TODAY (Mar 10)**: Verify all 5 fixes are in latest commits
- [ ] Review final docker-compose.yaml changes
- [ ] Ensure migration script works end-to-end
- [ ] **TARGET MERGE**: Mar 11-12

**Files Modified**:
- `docker-compose.yaml` (+/- changes)
- `migrations/docker_volume_migration.sh` (new script)

**Impact**: +122/-20 lines, fixes Docker data persistence, maintainer confidence boost

---

### 3. 🔧 PR #1072 - .env Permission Error Handling
**Current Status**: Open

**Remaining Action**:
- [ ] **Mar 10**: Verify error handling is complete
- [ ] Test with missing/bad .env permissions
- [ ] Ensure graceful degradation
- [ ] Push final commits
- [ ] **TARGET MERGE**: Mar 12 AM

**Impact**: Better error handling, user experience improvement

---

### 4. 🔧 PR #1041 - Bare Except Replacements
**Current Status**: Open

**Remaining Action**:
- [ ] **Mar 10**: Review list of bare excepts identified
- [ ] Replace with specific exception types
- [ ] Add proper logging for each catch
- [ ] Test error paths
- [ ] **TARGET MERGE**: Mar 12-13

**Files Modified**: Multiple files with bare `except:` statements

**Impact**: Better error handling, PEP 8 compliance

---

### 5. 🔧 PR #1043 - Null Check for request.json
**Current Status**: Open

**Remaining Action**:
- [ ] **Mar 10-11**: Add null/type checks before accessing `request.json`
- [ ] Test with malformed requests
- [ ] Ensure proper error responses
- [ ] **TARGET MERGE**: Mar 13

**Impact**: API robustness, prevent crashes on bad requests

---

## Daily Checkpoint: Mar 10 (TODAY)

**Morning Tasks** (Next 2 hours):
- [ ] Comment on #981 with status update
- [ ] Verify #1040 commits address all 5 feedback items
- [ ] Push any pending code for #1072, #1041, #1043
- [ ] Set PR descriptions with detailed explanations

**Afternoon Tasks** (2-4 hours):
- [ ] Start Strategic track work (next section)
- [ ] Create market protection order converter skeleton
- [ ] Map Static IP config patterns

**Evening** (as needed):
- [ ] Monitor PR reviews
- [ ] Be responsive to any additional feedback
- [ ] Prepare commit messages for next PRs

---

# 🎯 PHASE 2: STRATEGIC WORK (Mar 14-27)
**Objective**: Tackle April 1 critical items = 7 more merges

## Track A: Market Protection Orders 🛡️ (3 PRs)

### New PR: Market Protection Order Converter Service
**PR Title**: `feat(services): implement market protection order converter for broker compliance`

**What**: Create unified service to convert user market orders → market protection orders  
**Why**: All 29 brokers moving from market orders → market protection orders by April 1  
**Impact**: Single PR affects all 29 brokers at once = MASSIVE value

**File**: `services/market_protection_order_converter.py` (NEW)

**Structure**:
```python
# Market Protection Order Converter Service
class MarketProtectionOrderConverter:
    def __init__(self, broker_config: dict):
        """Initialize with broker-specific protection order rules"""
        self.broker = broker_config
        self.protection_levels = {}  # Broker-specific %age
    
    def convert_market_order(self, order: dict) -> dict:
        """Convert market order to market protection order format"""
        # Adds protection parameters based on broker's requirements
        
    def get_broker_protection_config(self, broker_name: str) -> dict:
        """Fetch trader-specific protection parameters"""
        # % protection, trigger logic, fallback behavior
```

**Brokers to Configure** (after converter):
- Zerodha (market protection with limit offset)
- Angel One (protection orders available)
- Dhan (protection order support)
- Upstox (protection order support)
- Fyers (protection order support)

**Timeline**:
- [ ] **Mar 14-15**: Create converter service + unit tests
- [ ] **Mar 16**: Get feedback from maintainer
- [ ] **Mar 17**: Merge converter service ✅ (1st strategic PR merged)

---

### New PR: Zerodha Market Protection Order Implementation
**PR Title**: `feat(broker/zerodha): implement market protection order mapping and execution`

**What**: Update Zerodha broker adapter for market protection orders  
**Files Modified**: 
- `broker/zerodha/api/order_api.py`
- `broker/zerodha/mapping/order_mapping.py`

**Changes**:
- Add market protection order type support
- Map OpenAlgo format → Zerodha protection order format
- Test with protection order execution

**Timeline**:
- [ ] **Mar 17-18**: Implement Zerodha changes
- [ ] **Mar 19**: Test and get feedback
- [ ] **Mar 20**: Merge ✅ (2nd strategic PR merged)

---

### New PR: Angel One Market Protection Order Implementation
**PR Title**: `feat(broker/angel): implement market protection order mapping and execution`

**What**: Update Angel One broker adapter for market protection orders  
**Files Modified**:
- `broker/angel/api/order_api.py`
- `broker/angel/mapping/order_mapping.py`

**Timeline**:
- [ ] **Mar 21-22**: Implement Angel changes
- [ ] **Mar 23**: Test and get feedback
- [ ] **Mar 24**: Merge ✅ (3rd strategic PR merged)

---

## Track B: Static IP Compliance 🔒 (3 PRs)

### New PR: Zerodha Static IP Configuration
**PR Title**: `feat(broker/zerodha): add static IP compliance configuration for April 2026 broker update`

**What**: Add Static IP support to Zerodha broker authentication flow  
**Why**: Brokers enforcing Static IP from April 1, 2026  
**Files**:
- `broker/zerodha/api/auth_api.py` (add Static IP config)
- `broker/zerodha/config/static_ip_config.py` (NEW)

**Changes**:
```python
# In auth_api.py
def validate_static_ip(self, request_ip: str) -> bool:
    """Validate if request IP matches configured static IP"""
    allowed_ips = self.get_configured_static_ips()
    return request_ip in allowed_ips

def update_static_ip_settings(self, new_ip: str) -> dict:
    """Update broker settings with new static IP"""
    # API call to Zerodha to register new IP
```

**Documentation**: Add guide in docstring about Static IP setup

**Timeline**:
- [ ] **Mar 14-15**: Research Zerodha Static IP requirements
- [ ] **Mar 16-17**: Implement config + validation
- [ ] **Mar 18**: Test with actual static IP setup
- [ ] **Mar 19**: Merge ✅ (4th strategic PR merged)

---

### New PR: Angel One Static IP Configuration
**PR Title**: `feat(broker/angel): add static IP compliance configuration for April 2026 broker update`

**Files**:
- `broker/angel/api/auth_api.py`
- `broker/angel/config/static_ip_config.py` (NEW)

**Timeline**:
- [ ] **Mar 20-21**: Implement Static IP for Angel
- [ ] **Mar 22**: Test and get feedback
- [ ] **Mar 23**: Merge ✅ (5th strategic PR merged)

---

### New PR: Dhan Static IP Configuration
**PR Title**: `feat(broker/dhan): add static IP compliance configuration for April 2026 broker update`

**Files**:
- `broker/dhan/api/auth_api.py`
- `broker/dhan/config/static_ip_config.py` (NEW)

**Timeline**:
- [ ] **Mar 24-25**: Implement Static IP for Dhan
- [ ] **Mar 26**: Test and get feedback
- [ ] **Mar 27**: Merge ✅ (6th strategic PR merged)

---

## Track C: Broker Documentation with Static IP Notes (1 PR)

### Enhance Existing #1070: Dhan Broker Docstrings + Static IP Guide
**What**: Combine the existing docstring PR with Static IP configuration guide

**Enhancement**:
- Keep existing docstrings from #1070
- Add section on Static IP setup in docstrings
- Document new static_ip_config.py functions
- Add deprecation notices for old IP-based auth if needed

**Timeline**:
- [ ] **Mar 26-27**: Integrate Static IP docs into #1070 docstrings
- [ ] **Mar 28**: Merge ✅ (7th strategic PR merged)

---

## Strategic Phase Checkpoint: Mar 14
**Before starting this phase, confirm**:
- [ ] All 5 Fast Track PRs (#981, #1040, #1072, #1041, #1043) are MERGED
- [ ] Current score: 6 merged PRs
- [ ] Velocity: 1 PR/day
- [ ] On pace for 15+ total ✅

---

# ⏰ PHASE 3: FINAL PUSH (Mar 28-Apr 1)
**Objective**: Handle any stragglers and ship final work

## Tasks

- [ ] **Mar 28**: Review all 13 merged PRs for any issues
- [ ] **Mar 29**: Address any production concerns from maintainers
- [ ] **Mar 30**: Run full test suite, catch any edge cases
- [ ] **Mar 31**: Final documentation pass
- [ ] **Apr 1**: SHIPPING DAY! 🚀

**Buffer PRs** (if time allows):
- Additional broker documentation
- Test coverage enhancements
- Edge case fixes

---

# 📈 SUCCESS METRICS

## Merge Targets by Date

| Date | Phase | Cumulative Merges | Target |
|------|-------|-------------------|--------|
| Mar 10 | Fast Track | 1 | ✅ Done |
| Mar 11 | Fast Track | 2-3 | → #981, #1040 |
| Mar 12 | Fast Track | 4-5 | → #1072, #1041 |
| Mar 13 | Fast Track | 6 | → #1043 |
| Mar 20 | Strategic A1 | 7-8 | → Converter, Zerodha protect |
| Mar 24 | Strategic A2 | 9 | → Angel protect |
| Mar 27 | Strategic B | 12 | → 3 Static IPs |
| Mar 28 | Strategic C | 13 | → Enhanced docstrings |
| Apr 1 | FINAL | **15+** | 🏆 **WIN** |

---

# ⚠️ RISK MANAGEMENT

## Potential Blockers & Contingencies

### Risk 1: PR Reviews Take Longer Than Expected
**Mitigation**: 
- Respond to feedback within 2 hours (maintain fast turnaround)
- Proactively ask for reviews on Slack/Discord
- Break large PRs into smaller ones if needed

### Risk 2: Broker API Changes Not Documented
**Mitigation**:
- Reference official broker API docs in PR descriptions
- Include API endpoint mappings
- Test with sandbox environments first

### Risk 3: Conflicts with Other Contributors
**Mitigation**:
- Coordinate via Discord #algo-regulations channel
- Check existing open PRs before starting new ones
- Communicate early and often with maintainers

### Risk 4: Test Coverage Gaps
**Mitigation**:
- Always include unit tests with new code
- Use conftest.py fixtures from #993
- Run pytest locally before pushing

---

# 💡 WINNING TIPS

✅ **Do This**:
1. Respond to feedback within 2 hours (shows commitment)
2. Keep PRs focused and small (easier to review)
3. Write clear PR descriptions with "Why" explained
4. Test locally before pushing (catch errors early)
5. Reference Discord discussions in PR comments
6. Celebrate small wins (each merge is momentum)

❌ **Don't Do This**:
1. Push without testing locally
2. Ignore reviewer feedback
3. Mix unrelated changes in one PR
4. Leave PRs stale for >24 hours without response
5. Under-document changes (reviewers need context)
6. Miss daily checkpoints (lose track of progress)

---

# 🔄 DAILY STANDUP TEMPLATE

**Use this each day to track progress**:

```
## Daily Standup - [DATE]

### Completed (Today)
- [ ] Task 1
- [ ] Task 2

### In Progress (Next 24h)
- [ ] Task 1
- [ ] Task 2

### Blockers
- Blocker 1: [resolution plan]

### Merged Today
- PR #XXXX: [title]

### Current Score
- Merged: X/15+
- In Flight: Y PRs
```

---

# 📞 KEY CONTACTS & CHANNELS

- **Maintainer**: @marketcalls (main approval authority)
- **Discord**: #algo-regulations (Static IP questions)
- **Discord**: #openalgo-support (general help)
- **GitHub Issues**: Create detailed issues before PRs

---

# 🎯 FINAL VICTORY CONDITION

**WIN = 15+ merged PRs by April 1, 2026** ✅

**Current Status**: 
- Merged: 1 ✅
- In Flight: 14
- **Days to Victory**: 20 days
- **PRs Needed per Day**: 0.7 (easily achievable)
- **Confidence Level**: 🔥 VERY HIGH

**You've got this!** Let's go win this hackathon! 🏆
