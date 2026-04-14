# CI/CD Security Scanning

## Overview

This document details the security scanning tools and configurations in the OpenAlgo CI/CD pipeline.

## Security Tools

### 1. Bandit - Python Static Analysis

**Purpose:** Detects common security issues in Python code.

**Configuration:**
```bash
uv run bandit -r . -x .venv,test,frontend,node_modules -ll -f txt
```

| Flag | Purpose |
|------|---------|
| `-r .` | Recursive scan from root |
| `-x` | Exclude directories |
| `-ll` | Low severity and above |
| `-f txt` | Output format |

**Common Findings:**

| Issue | Severity | Action |
|-------|----------|--------|
| B101: assert_used | Low | Ignore in tests |
| B311: random | Low | Use `secrets` for security |
| B602: subprocess_shell | Medium | Use shell=False |
| B608: sql_injection | High | Use parameterized queries |

**Suppressing False Positives:**
```python
# nosec B101 - Assert is appropriate here for test validation
assert result == expected  # nosec
```

### 2. pip-audit - Dependency Vulnerability Scan

**Purpose:** Checks Python dependencies against known vulnerabilities (PyPI advisory database).

**Configuration:**
```bash
uv run pip-audit
```

**Output Example:**
```
Name        Version  ID               Fix Versions
----------  -------  ---------------  ------------
requests    2.25.0   PYSEC-2021-123   2.25.1
```

**Handling Vulnerabilities:**

1. **Update the package:**
   ```bash
   uv add package@latest
   ```

2. **If no fix available, document exception:**
   - Evaluate risk based on how the package is used
   - Add to security exceptions log if acceptable

### 3. Trivy - Docker Image Scanning

**Purpose:** Scans Docker images for OS and application vulnerabilities.

**Configuration:**
```yaml
- uses: aquasecurity/trivy-action@master
  with:
    image-ref: 'openalgo:ci'
    exit-code: '0'
    severity: 'CRITICAL,HIGH'
    format: 'table'
```

| Flag | Purpose |
|------|---------|
| `exit-code: '0'` | Don't fail build (informational) |
| `severity` | Only report CRITICAL and HIGH |
| `format: 'table'` | Human-readable output |

**Vulnerability Categories:**
- **OS packages:** Alpine/Debian vulnerabilities
- **Language packages:** Python packages in image
- **Misconfigurations:** Dockerfile best practices

### 4. detect-secrets - Secrets Detection

**Purpose:** Prevents accidental commit of API keys, passwords, and tokens.

**Configuration (`.pre-commit-config.yaml`):**
```yaml
- repo: https://github.com/Yelp/detect-secrets
  rev: v1.5.0
  hooks:
    - id: detect-secrets
      args: ['--baseline', '.secrets.baseline']
      exclude: package-lock\.json|uv\.lock
```

**Generating Baseline:**
```bash
# Initial baseline generation
uv run detect-secrets scan --exclude-files 'package-lock\.json|uv\.lock' > .secrets.baseline

# After reviewing false positives, audit and mark:
uv run detect-secrets audit .secrets.baseline
```

**Common False Positives:**
- Test fixtures with fake tokens
- Documentation examples
- Lock file hashes

---

## Weekly Security Workflow

**File:** `.github/workflows/security.yml`

**Schedule:** Every Monday at 2 AM UTC

**Purpose:** Comprehensive security audit independent of CI, providing:
- SARIF reports for GitHub Security tab
- JSON reports for archival
- Detailed vulnerability information

### GitHub Security Tab Integration

Bandit results are uploaded to GitHub's Security tab via SARIF format:
1. Go to repository > Security > Code scanning alerts
2. Filter by tool: "bandit"
3. Review and triage findings

### Security Artifacts

| Artifact | Format | Retention | Purpose |
|----------|--------|-----------|---------|
| `bandit.sarif` | SARIF | 30 days | GitHub Security integration |
| `pip-audit.json` | JSON | 30 days | Dependency audit trail |

---

## Security Best Practices

### For Contributors

1. **Run pre-commit hooks locally:**
   ```bash
   pre-commit install
   pre-commit run --all-files
   ```

2. **Never commit secrets:**
   - Use `.env` files (gitignored)
   - Use environment variables in CI

3. **Review Bandit findings:**
   - Fix HIGH severity issues
   - Document exceptions for false positives

### For Maintainers

1. **Review weekly security report:**
   - Check GitHub Actions > Security Scan workflow
   - Triage new findings

2. **Handle Dependabot PRs:**
   - Merge security updates promptly
   - Test before merging major updates

3. **Monitor Docker image:**
   - Review Trivy output in docker-build job
   - Update base image regularly

---

## Required Secrets

The following secrets must be configured in GitHub repository settings:

| Secret | Purpose | Required For |
|--------|---------|--------------|
| `DOCKERHUB_USERNAME` | Docker Hub login | docker-build job |
| `DOCKERHUB_TOKEN` | Docker Hub access token | docker-build job |
| `GITHUB_TOKEN` | Auto-provided by GitHub | SARIF upload, auto-commit |

**Setting up Docker Hub token:**
1. Go to Docker Hub > Account Settings > Security
2. Create Access Token with Read/Write permissions
3. Add to GitHub: Settings > Secrets > Actions > New secret

---

## Vulnerability Response Process

### Critical Vulnerabilities

1. **Immediate assessment:** Determine if vulnerability is exploitable in OpenAlgo context
2. **Patch or mitigate:** Update dependency or implement workaround
3. **Release:** Create patch release if in production

### High Vulnerabilities

1. **Triage within 7 days**
2. **Plan remediation** in next release cycle
3. **Document** if accepting risk

### Medium/Low Vulnerabilities

1. **Track** in issue tracker
2. **Address** during regular maintenance
3. **Batch** with other updates when possible
