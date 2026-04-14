# File Operations Assessment

## Overview

This assessment reviews file handling in OpenAlgo for security considerations.

**Risk Level**: Low
**Status**: Acceptable

## File Operations in OpenAlgo

### User-Controlled File Operations

| Operation | Location | Description |
|-----------|----------|-------------|
| Quantity freeze CSV upload | `blueprints/admin.py` | Admin uploads CSV file |
| Database paths | `.env` | Configured at setup |
| Log files | Automatic | No user input |

### Key Finding

**Limited file operations**: OpenAlgo has minimal file upload functionality, reducing attack surface.

## CSV Upload Analysis

### Quantity Freeze Upload

**Location**: `blueprints/admin.py`

**Purpose**: Upload CSV with quantity freeze data for symbols

**Current Implementation**:
```python
temp_path = '/tmp/qtyfreeze_upload.csv'
file.save(temp_path)
# Process CSV
# File processed and data stored in database
```

### Security Analysis

| Check | Status | Notes |
|-------|--------|-------|
| Extension validation | Yes | Only `.csv` allowed |
| Path traversal | N/A | Hardcoded path |
| File size limit | Flask default | 16MB default |
| Content validation | Yes | CSV parsing validates format |

### Single-User Perspective

For single-user:
- Only you can upload files (requires login)
- No risk of malicious uploads from other users
- Temporary file in `/tmp` is acceptable

### Potential Improvement

Using secure temporary files (optional enhancement):

```python
import tempfile

fd, temp_path = tempfile.mkstemp(suffix='.csv')
try:
    with os.fdopen(fd, 'wb') as f:
        file.save(f)
    # Process file
finally:
    os.unlink(temp_path)
```

**Priority**: Low - current implementation is acceptable for single-user

## Path Traversal Protection

### Database Paths

**Configuration** (`.env`):
```bash
DATABASE_URL=sqlite:///db/openalgo.db
```

**Protection**:
- Paths set at deployment, not runtime
- No user input in file paths
- Relative to application directory

### Static Files

**Flask default behavior**:
- Only serves files from `static/` directory
- Path traversal attempts blocked automatically

### Log Files

**Configuration**:
```python
LOG_PATH = os.path.join(BASE_DIR, 'logs', 'openalgo.log')
```

**Protection**:
- Hardcoded directory
- No user input in log paths

## Database File Security

### SQLite Files

Located in `db/` directory:

| File | Content | Sensitivity |
|------|---------|-------------|
| `openalgo.db` | User data, orders | High |
| `logs.db` | API logs | Medium |
| `sandbox.db` | Paper trading | Low |
| `latency.db` | Performance | Low |
| `historify.duckdb` | Price history | Low |

### File Permissions

SQLite creates files with default permissions. For additional security:

**Linux/Mac**:
```bash
chmod 600 db/*.db
```

**This prevents**:
- Other users on shared systems from reading your data
- Accidental exposure of trading data

### Recommendation

Enable disk encryption on your machine:
- **Windows**: BitLocker
- **Mac**: FileVault
- **Linux**: LUKS

This protects all files if device is lost/stolen.

## Backup Considerations

### What to Back Up

```
openalgo/
├── .env              # CRITICAL - encryption keys
├── db/               # Trading data
│   ├── openalgo.db
│   ├── logs.db
│   └── ...
└── logs/             # Optional - for troubleshooting
```

### Backup Security

1. **Encrypt backups** before cloud storage
2. **Secure local copies** (encrypted drive)
3. **Test restoration** periodically

### Recovery Without Backup

If you lose data:
- Re-create `.env` with new secrets
- Re-login to brokers (OAuth)
- Generate new API key
- Order history lost (available from broker)

## Temporary Files

### Current Usage

Only the quantity freeze CSV upload uses temp files.

**Risk Assessment**:
- Single operation
- Admin-only access
- File deleted after processing (in normal flow)

### `/tmp` Security

On shared systems, `/tmp` is world-readable. For single-user systems:
- You're the only user
- Risk is negligible

## What's Not a Concern

For single-user OpenAlgo:

| Issue | Why Not Applicable |
|-------|-------------------|
| Arbitrary file upload | No general upload feature |
| Path traversal attacks | No user-controlled paths |
| Symlink attacks | No symlink following |
| File inclusion | No dynamic file includes |

## Recommendations

### Essential

- [x] Limit file uploads to specific types (CSV only)
- [x] Validate file content after upload
- [x] No user input in file paths

### Optional Enhancements

1. **Enable disk encryption** on host machine
2. **Regular backups** of `.env` and `db/` folder
3. **Set file permissions** if on shared system:
   ```bash
   chmod 600 db/*.db
   chmod 600 .env
   ```

### Low Priority

4. Use `tempfile.mkstemp()` for uploads (minor improvement)
5. Add explicit file size limits to upload

## Summary

File handling in OpenAlgo is **secure for single-user deployment**:

- Minimal file operations
- No user-controlled paths
- Content validation on uploads
- Admin-only access to upload feature

The main recommendation is to **enable disk encryption** on your machine for comprehensive data protection.

---

**Back to**: [Security Audit Overview](./README.md)
