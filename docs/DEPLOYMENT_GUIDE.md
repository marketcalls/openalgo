# OpenAlgo Deployment Guide
## Production Deployment on Linux, Docker, and Cloud Platforms

---

## 📋 Prerequisites

- Ubuntu 20.04+ (or equivalent Linux distribution)
- Python 3.12+
- Node.js 20+ (for React frontend build)
- 2GB RAM minimum, 4GB+ recommended
- Fast internet connection for broker API connectivity

---

## 🚀 Quick Deployment (5 minutes)

### Option 1: Direct Linux Deployment

```bash
# 1. Clone repository
git clone https://github.com/marketcalls/openalgo
cd openalgo

# 2. Install dependencies
sudo apt-get update
sudo apt-get install python3.12 python3.12-venv nodejs npm

# 3. Setup environment
pip install uv
cp .sample.env .env

# 4. Generate security keys
python3 -c "import secrets; print(secrets.token_hex(32))"  # Set as APP_KEY
python3 -c "import secrets; print(secrets.token_hex(32))"  # Set as API_KEY_PEPPER

# 5. Build frontend
cd frontend && npm install && npm run build && cd ..

# 6. Run application
uv run app.py
```

### Option 2: Docker Deployment (Recommended)

```bash
# Build Docker image
docker build -t openalgo:latest .

# Run container
docker run -p 5000:5000 -p 8765:8765 \
  -e APP_KEY=your-app-key \
  -e API_KEY_PEPPER=your-api-pepper \
  -v openalgo-db:/app/db \
  openalgo:latest
```

---

## 🐳 Docker Deployment (Recommended for Production)

### Using Docker Compose

```yaml
# docker-compose.yaml
version: '3.8'

services:
  openalgo:
    build:
      context: .
      dockerfile: Dockerfile
    ports:
      - "5000:5000"    # Flask API
      - "8765:8765"    # WebSocket Server
    environment:
      - APP_KEY=${APP_KEY}
      - API_KEY_PEPPER=${API_KEY_PEPPER}
      - FLASK_ENV=production
      - WEBSOCKET_HOST=0.0.0.0
    volumes:
      - openalgo-db:/app/db        # Database storage
      - openalgo-logs:/app/log     # Log storage
    restart: unless-stopped
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:5000/health"]
      interval: 30s
      timeout: 10s
      retries: 3

volumes:
  openalgo-db:
  openalgo-logs:
```

**Deploy**:
```bash
docker-compose up -d
```

---

## ☁️ Cloud Deployment

### AWS EC2 Deployment

1. **Launch EC2 Instance**:
   - AMI: Ubuntu 22.04 LTS
   - Instance Type: t3.medium (2GB RAM)
   - Security Group: Allow ports 5000, 8765
   - EBS: 20GB gp3

2. **Connect to Instance**:
   ```bash
   ssh -i your-key.pem ubuntu@your-instance-ip
   ```

3. **Deploy OpenAlgo**:
   ```bash
   # Run the Quick Deployment script from above
   ```

4. **Setup Gunicorn + Nginx**:
   ```bash
   # Install Gunicorn
   pip install gunicorn eventlet
   
   # Start Gunicorn
   gunicorn --worker-class eventlet -w 1 \
     -b 0.0.0.0:5000 app:app
   ```

### Google Cloud Platform (GCP)

1. **Create Cloud Run Service**:
   ```bash
   gcloud run deploy openalgo \
     --source . \
     --platform managed \
     --region us-central1 \
     --allow-unauthenticated
   ```

2. **Set Environment Variables**:
   ```bash
   gcloud run services update openalgo \
     --set-env-vars APP_KEY=your-key,API_KEY_PEPPER=your-pepper
   ```

### Heroku Deployment

```bash
# Install Heroku CLI
# Create app
heroku create openalgo

# Set environment variables
heroku config:set APP_KEY=your-key
heroku config:set API_KEY_PEPPER=your-pepper

# Deploy
git push heroku main
```

---

## 🛡️ Production Security Setup

### 1. Use HTTPS/TLS

```nginx
# /etc/nginx/sites-available/openalgo
server {
    listen 443 ssl http2;
    server_name yourdomain.com;
    
    ssl_certificate /etc/ssl/certs/your-cert.crt;
    ssl_certificate_key /etc/ssl/private/your-key.key;
    
    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_ciphers HIGH:!aNULL:!MD5;
    
    location / {
        proxy_pass http://localhost:5000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }
}
```

### 2. Setup Firewall

```bash
sudo ufw enable
sudo ufw allow 22/tcp    # SSH
sudo ufw allow 80/tcp    # HTTP
sudo ufw allow 443/tcp   # HTTPS
sudo ufw allow 8765/tcp  # WebSocket
```

### 3. Secure Environment Variables

```bash
# Use secrets management
sudo apt-get install docker.io
docker run -v /var/run/secrets:/run/secrets myapp

# Or use env files with restricted permissions
chmod 600 .env
chown root:root .env
```

### 4. Enable API Rate Limiting

In `.env`:
```
RATE_LIMIT_ENABLED=true
RATE_LIMIT_CALLS=100
RATE_LIMIT_PERIOD=3600
```

---

## 📊 Monitoring & Logging

### 1. Setup Centralized Logging

```bash
# Install Elasticsearch + Kibana
docker run -d \
  -e ES_JAVA_OPTS="-Xms512m -Xmx512m" \
  --name elasticsearch \
  docker.elastic.co/elasticsearch/elasticsearch:8.0.0
```

### 2. Monitor Health

```bash
# Check API health
curl http://localhost:5000/health

# Check WebSocket
curl http://localhost:8765

# View logs
tail -f log/app.log
```

### 3. Setup Alerting

```bash
# Check critical conditions
if ! curl -f http://localhost:5000/health; then
  echo "ALERT: OpenAlgo health check failed"
  # Send email/Slack notification
fi
```

---

## 📈 Performance Tuning

### 1. Database Optimization

```bash
# Use faster disk (SSD)
# Monitor disk usage
df -h

# Optimize SQLite (if used)
sqlite3 db/openalgo.db "VACUUM;"
```

### 2. WebSocket Performance

```env
# In .env
MAX_SYMBOLS_PER_WEBSOCKET=1000
MAX_WEBSOCKET_CONNECTIONS=3
MESSAGE_BATCH_SIZE=100
```

### 3. Flask Configuration

```python
# Optimize for production
app.config['JSON_COMPACT'] = True
app.config['JSONIFY_PRETTYPRINT_REGULAR'] = False
app.config['SEND_FILE_MAX_AGE_DEFAULT'] = 31536000  # 1 year
```

---

## 🔄 Update & Maintenance

### Rolling Update (Zero Downtime)

```bash
# Using Docker:
docker build -t openalgo:v2 .
docker run -p 5001:5000 openalgo:v2  # New version on port 5001

# Update load balancer to route to new version
# Shutdown old container
docker stop openalgo:latest
```

### Database Backup

```bash
# Daily backup
0 2 * * * cp db/openalgo.db db/backups/openalgo-$(date +\%Y\%m\%d).db

# Cloud backup
gsutil cp db/openalgo.db gs://your-bucket/backups/
```

### Automated Deployment (CI/CD)

```yaml
# .github/workflows/deploy.yml
name: Deploy to Production
on:
  push:
    branches: [main]

jobs:
  deploy:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3
      - name: Build and push Docker
        run: docker push your-registry/openalgo:latest
      - name: Deploy to K8s
        run: kubectl apply -f k8s/deployment.yaml
```

---

## ✅ Deployment Checklist

- [ ] Environment variables configured
- [ ] HTTPS/TLS certificates in place
- [ ] Firewall rules configured
- [ ] Database backups enabled
- [ ] Monitoring and alerting setup
- [ ] WebSocket connectivity verified
- [ ] API health checks passing
- [ ] Load testing completed
- [ ] Incident response plan ready
- [ ] Documentation updated

---

## 🆘 Troubleshooting

### Port Already in Use

```
Error: Address already in use
Solution: lsof -i :5000 && kill <PID>
```

### WebSocket Connection Failed

```
Error: WebSocket connection refused
Solution: Check port 8765 is open, check firewall rules
```

### High Memory Usage

```
Error: Out of memory
Solution: Reduce MAX_SYMBOLS_PER_WEBSOCKET
```

### API Slow

```
Error: Request timeout
Solution: Scale horizontally (add more servers), optimize queries
```

---

## 📞 Support

- **Documentation**: https://docs.openalgo.in
- **GitHub Issues**: https://github.com/marketcalls/openalgo/issues
- **Community Slack**: https://openalgo.slack.com

---

**Last Updated**: March 10, 2026  
**Status**: Production Ready ✅  
**Version**: 1.0  
