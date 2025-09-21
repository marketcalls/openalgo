# Deployment Architecture

## Overview

OpenAlgo supports multiple deployment architectures to accommodate different scale, security, and infrastructure requirements. This document details the various deployment options, their configurations, and best practices for production deployments.

## Deployment Options

### 1. Ubuntu VPS with Nginx (Production Recommended)

**Architecture:**
```
Internet → Nginx (443/80) → Gunicorn (Unix Socket) → Flask App
                ↓
         SSL Certificate
         (Let's Encrypt)
```

**Components:**
- **Nginx**: Reverse proxy, SSL termination, static file serving
- **Gunicorn**: WSGI server with eventlet worker
- **Systemd**: Process management and auto-restart
- **Let's Encrypt**: Free SSL certificates

**Installation Script Features:**
```bash
# install.sh provides:
- System requirement checks (RAM/Swap)
- Automatic swap configuration (3GB if RAM < 2GB)
- IST timezone configuration
- Python virtual environment with uv
- Nginx configuration with SSL
- Systemd service setup
- Directory permissions
- Firewall configuration (UFW)
```

**Directory Structure:**
```
/var/python/openalgo-flask/{domain}-{broker}/
├── openalgo/           # Application code
├── venv/               # Python virtual environment
├── openalgo.sock       # Unix socket file
└── logs/               # Installation logs
```

### 2. Simple HTTP Deployment (Development/Testing)

**Architecture:**
```
Internet → Gunicorn (Port 80) → Flask App
```

**Use Cases:**
- Development environments
- Internal networks
- Testing deployments
- IP-based access

**Installation Script Features:**
```bash
# ubuntu-ip.sh provides:
- Direct HTTP access (no SSL)
- IP-based configuration
- Fail2ban for security
- Basic firewall setup
- Simplified deployment
```

### 3. Docker Deployment

**Architecture:**
```
Docker Host → Docker Container → Flask App
            → Volume Mounts (db, logs, strategies)
```

**Docker Compose Configuration:**
```yaml
version: '3.8'
services:
  openalgo:
    build: .
    ports:
      - "5000:5000"
    volumes:
      - ./db:/app/db
      - ./logs:/app/logs
      - ./strategies:/app/strategies
    environment:
      - DATABASE_URL=sqlite:///db/openalgo.db
    restart: unless-stopped
```

**Advantages:**
- Consistent environment
- Easy scaling
- Simple rollback
- Platform independent

### 4. AWS Elastic Beanstalk

**Architecture:**
```
Route 53 → ALB → EC2 Instances → Flask App
                → Auto Scaling Group
                → RDS (Optional)
```

**Configuration (.ebextensions/01_flask.config):**
```yaml
option_settings:
  aws:elasticbeanstalk:container:python:
    WSGIPath: "app:app"
  aws:elasticbeanstalk:application:environment:
    PYTHONPATH: "/var/app/current:$PYTHONPATH"

container_commands:
  01_create_directories:
    command: |
      mkdir -p /var/app/current/strategies/scripts
      mkdir -p /var/app/current/log/strategies
      mkdir -p /var/app/current/keys
      mkdir -p /var/app/current/db
```

**Benefits:**
- Auto-scaling
- Managed infrastructure
- Built-in monitoring
- Easy deployment

## System Requirements

### Minimum Requirements

| Component | Minimum | Recommended | Notes |
|-----------|---------|-------------|-------|
| CPU | 1 vCPU | 2+ vCPU | More for multiple strategies |
| RAM | 2 GB | 4+ GB | With swap if < 2GB |
| Storage | 20 GB | 50+ GB | For logs and database |
| Network | 1 Mbps | 10+ Mbps | For market data |
| OS | Ubuntu 20.04 | Ubuntu 22.04 | LTS versions preferred |

### Swap Configuration

For systems with < 2GB RAM:
```bash
# Automatic in installation scripts
sudo fallocate -l 3G /swapfile
sudo chmod 600 /swapfile
sudo mkswap /swapfile
sudo swapon /swapfile
echo "/swapfile none swap sw 0 0" | sudo tee -a /etc/fstab
sudo sysctl vm.swappiness=10
```

## Security Architecture

### 1. Network Security

**Firewall Configuration:**
```bash
# UFW rules (automatically configured)
sudo ufw default deny incoming
sudo ufw default allow outgoing
sudo ufw allow ssh
sudo ufw allow 'Nginx Full'  # or allow 80/tcp for HTTP only
sudo ufw enable
```

**SSL/TLS Configuration:**
```nginx
# Nginx SSL configuration
ssl_protocols TLSv1.2 TLSv1.3;
ssl_prefer_server_ciphers on;
ssl_ciphers EECDH+AESGCM:EDH+AESGCM;
ssl_ecdh_curve secp384r1;
ssl_session_timeout 10m;
ssl_session_cache shared:SSL:10m;
ssl_stapling on;
ssl_stapling_verify on;
```

### 2. Application Security

**Security Headers:**
```nginx
# Nginx security headers
add_header X-Frame-Options DENY;
add_header X-Content-Type-Options nosniff;
add_header X-XSS-Protection "1; mode=block";
add_header Strict-Transport-Security "max-age=63072000" always;
```

**Rate Limiting:**
```python
# Flask-Limiter configuration
from flask_limiter import Limiter
limiter = Limiter(
    app,
    key_func=get_remote_address,
    default_limits=["100 per minute"]
)
```

### 3. Process Isolation

**User Permissions:**
```bash
# Run as non-root user
User=www-data
Group=www-data
WorkingDirectory=/var/python/openalgo
```

**Directory Permissions:**
```bash
# Secure directory permissions
chmod 755 /var/python/openalgo
chmod 700 /var/python/openalgo/keys
chmod 755 /var/python/openalgo/strategies
chown -R www-data:www-data /var/python/openalgo
```

## High Availability Setup

### 1. Load Balancing

**Multiple Instance Setup:**
```
                 Load Balancer (Nginx/HAProxy)
                      /        |        \
            Instance 1    Instance 2    Instance 3
                      \        |        /
                       Shared Database
                       (PostgreSQL/MySQL)
```

**Nginx Load Balancer Configuration:**
```nginx
upstream openalgo_backend {
    least_conn;
    server 10.0.1.10:5000;
    server 10.0.1.11:5000;
    server 10.0.1.12:5000;
}

server {
    location / {
        proxy_pass http://openalgo_backend;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }
}
```

### 2. Database Configuration

**PostgreSQL for Production:**
```python
# .env configuration
DATABASE_URL=postgresql://user:password@localhost/openalgo
SQLALCHEMY_POOL_SIZE=10
SQLALCHEMY_POOL_RECYCLE=3600
SQLALCHEMY_POOL_PRE_PING=True
```

**Database Replication:**
```
Primary Database → Streaming Replication → Standby Database
                → Async Replication → Read Replicas
```

### 3. Session Management

**Redis for Session Storage:**
```python
# Flask session configuration
SESSION_TYPE = 'redis'
SESSION_REDIS = redis.from_url('redis://localhost:6379')
SESSION_PERMANENT = False
PERMANENT_SESSION_LIFETIME = timedelta(hours=24)
```

## Monitoring and Logging

### 1. Application Monitoring

**Health Check Endpoint:**
```python
@app.route('/health')
def health_check():
    return {
        'status': 'healthy',
        'timestamp': datetime.now().isoformat(),
        'version': APP_VERSION,
        'database': check_database_connection(),
        'broker_connections': check_broker_connections()
    }
```

**Prometheus Metrics:**
```python
from prometheus_flask_exporter import PrometheusMetrics
metrics = PrometheusMetrics(app)

# Custom metrics
order_counter = metrics.counter(
    'orders_placed_total',
    'Total number of orders placed',
    labels={'broker': lambda: request.view_args.get('broker')}
)
```

### 2. Log Management

**Centralized Logging:**
```python
# Logging configuration
LOGGING_CONFIG = {
    'version': 1,
    'handlers': {
        'file': {
            'class': 'logging.handlers.RotatingFileHandler',
            'filename': 'logs/openalgo.log',
            'maxBytes': 10485760,  # 10MB
            'backupCount': 10
        },
        'syslog': {
            'class': 'logging.handlers.SysLogHandler',
            'address': ('localhost', 514)
        }
    }
}
```

**Log Aggregation Stack:**
```
Application Logs → Filebeat → Logstash → Elasticsearch → Kibana
                → Fluentd → CloudWatch (AWS)
```

### 3. Performance Monitoring

**APM Integration:**
```python
# New Relic example
import newrelic.agent
newrelic.agent.initialize('newrelic.ini')
app = newrelic.agent.WSGIApplicationWrapper(app)
```

## Backup and Recovery

### 1. Database Backup

**Automated Backup Script:**
```bash
#!/bin/bash
# Daily database backup
BACKUP_DIR="/backups/openalgo"
DATE=$(date +%Y%m%d_%H%M%S)

# SQLite backup
sqlite3 /var/python/openalgo/db/openalgo.db ".backup ${BACKUP_DIR}/openalgo_${DATE}.db"

# PostgreSQL backup
pg_dump openalgo > ${BACKUP_DIR}/openalgo_${DATE}.sql

# Compress and encrypt
tar czf - ${BACKUP_DIR}/openalgo_${DATE}.* | \
  openssl enc -aes-256-cbc -salt -out ${BACKUP_DIR}/openalgo_${DATE}.tar.gz.enc

# Upload to S3
aws s3 cp ${BACKUP_DIR}/openalgo_${DATE}.tar.gz.enc s3://backup-bucket/openalgo/
```

### 2. Strategy Backup

```bash
# Backup strategies and configurations
tar czf strategies_backup_$(date +%Y%m%d).tar.gz \
  strategies/ \
  keys/ \
  *.json
```

### 3. Disaster Recovery Plan

**Recovery Time Objective (RTO): 1 hour**
**Recovery Point Objective (RPO): 24 hours**

**Recovery Steps:**
1. Provision new infrastructure
2. Deploy application code
3. Restore database from backup
4. Restore strategy configurations
5. Verify broker connections
6. Resume operations

## Deployment Checklist

### Pre-Deployment

- [ ] System requirements verified
- [ ] Domain/IP configured
- [ ] Broker API credentials obtained
- [ ] SSL certificate configured (production)
- [ ] Firewall rules configured
- [ ] Backup strategy defined

### Deployment

- [ ] Installation script executed
- [ ] Environment variables configured
- [ ] Database initialized
- [ ] Service started and enabled
- [ ] Nginx configured (if applicable)
- [ ] SSL certificate obtained

### Post-Deployment

- [ ] Health check passing
- [ ] Broker connection verified
- [ ] Test order placed
- [ ] Monitoring configured
- [ ] Backup job scheduled
- [ ] Documentation updated

## Troubleshooting

### Common Issues

1. **Service Won't Start**
```bash
# Check logs
sudo journalctl -u openalgo -n 50
# Check permissions
ls -la /var/python/openalgo
# Check socket file
ls -la /var/python/openalgo/*.sock
```

2. **502 Bad Gateway**
```bash
# Check if service is running
sudo systemctl status openalgo
# Check Nginx error log
sudo tail -f /var/log/nginx/error.log
# Restart services
sudo systemctl restart openalgo nginx
```

3. **Database Connection Error**
```bash
# Check database service
sudo systemctl status postgresql
# Check connection string
grep DATABASE_URL /var/python/openalgo/.env
# Test connection
python -c "from app import db; db.create_all()"
```

4. **Permission Denied**
```bash
# Fix ownership
sudo chown -R www-data:www-data /var/python/openalgo
# Fix permissions
sudo chmod -R 755 /var/python/openalgo
sudo chmod 700 /var/python/openalgo/keys
```

## Performance Tuning

### 1. Gunicorn Configuration

```python
# Optimal worker configuration
workers = multiprocessing.cpu_count() * 2 + 1
worker_class = 'eventlet'
worker_connections = 1000
keepalive = 5
timeout = 120
```

### 2. Database Optimization

```sql
-- Create indexes for frequently queried columns
CREATE INDEX idx_orders_user_id ON orders(user_id);
CREATE INDEX idx_orders_created_at ON orders(created_at);
CREATE INDEX idx_positions_user_broker ON positions(user_id, broker);
```

### 3. Caching Strategy

```python
# Redis caching for frequently accessed data
from flask_caching import Cache
cache = Cache(app, config={
    'CACHE_TYPE': 'redis',
    'CACHE_REDIS_URL': 'redis://localhost:6379/0',
    'CACHE_DEFAULT_TIMEOUT': 300
})

@cache.cached(timeout=60)
def get_market_data(symbol):
    return fetch_market_data(symbol)
```

## Scaling Strategies

### Vertical Scaling
- Increase CPU cores for compute-intensive strategies
- Add RAM for concurrent strategy execution
- Use SSD for better I/O performance

### Horizontal Scaling
- Deploy multiple instances behind load balancer
- Use shared database (PostgreSQL/MySQL)
- Implement session stickiness for WebSocket connections
- Use Redis for shared cache and session storage

### Auto-Scaling (AWS)
```yaml
# Auto-scaling configuration
ScalingPolicy:
  TargetValue: 70.0
  PredefinedMetricType: ASGAverageCPUUtilization
  ScaleInCooldown: 300
  ScaleOutCooldown: 60
```