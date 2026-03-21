# Implementation Plan: AWS Lightsail Deployment for OpenAlgo

## Overview

Step-by-step implementation tasks for deploying OpenAlgo on a Lightsail Instance (Ubuntu 22.04, `medium_2_0` bundle: 2 vCPU / 2 GB RAM / 60 GB SSD) with Docker Compose, an NGINX sidecar for WebSocket proxying, a 60 GB attached disk for SQLite persistence, and Let's Encrypt TLS.

## Tasks

- [x] 1. Local prerequisites and AWS CLI setup
  - Install and configure the AWS CLI (`aws configure`) with an IAM user that has Lightsail and ECR permissions
  - Verify Docker is installed locally (`docker info`) and the Docker daemon is running
  - Create a Lightsail SSH key pair in the target region and download the `.pem` file (`chmod 400`)
  - _Requirements: 1.1, 1.2_

- [x] 2. Create ECR repositories for application and NGINX images
  - [x] 2.1 Create the two ECR repositories
    - Run `aws ecr create-repository --repository-name openalgo/app --region us-east-1`
    - Run `aws ecr create-repository --repository-name openalgo/nginx --region us-east-1`
    - Note the repository URIs (`<ACCOUNT_ID>.dkr.ecr.us-east-1.amazonaws.com/openalgo/app` and `.../openalgo/nginx`)
    - _Requirements: 1.2_

- [x] 3. Build and push the OpenAlgo application image to ECR
  - [x] 3.1 Authenticate Docker to ECR and build the image
    - Run `aws ecr get-login-password --region us-east-1 | docker login --username AWS --password-stdin <ACCOUNT_ID>.dkr.ecr.us-east-1.amazonaws.com`
    - Run `docker build -t openalgo:latest .` from the repo root
    - Verify the image contains `/app/.venv`, `/app/frontend/dist`, and `/app/start.sh` by running `docker run --rm openalgo:latest ls /app`
    - _Requirements: 1.1, 1.3, 1.4_
  - [ ]* 3.2 Write image artifact test
    - **Property: Image artifact test (Unit)**
    - Assert `/app/.venv`, `/app/frontend/dist`, and `/app/start.sh` exist inside the built image
    - **Validates: Requirements 1.3**
  - [x] 3.3 Tag and push the application image
    - Run `docker tag openalgo:latest <ACCOUNT_ID>.dkr.ecr.us-east-1.amazonaws.com/openalgo/app:latest`
    - Run `docker push <ACCOUNT_ID>.dkr.ecr.us-east-1.amazonaws.com/openalgo/app:latest`
    - _Requirements: 1.2_

- [x] 4. Create the NGINX sidecar image and push to ECR
  - [x] 4.1 Create `nginx/Dockerfile` and `nginx/nginx.conf`
    - Create `nginx/Dockerfile` using `FROM nginx:1.27-alpine` and `COPY nginx.conf /etc/nginx/nginx.conf`
    - Create `nginx/nginx.conf` with:
      - `location /ws` block: `proxy_pass http://127.0.0.1:8765`, `proxy_http_version 1.1`, `Upgrade` and `Connection "upgrade"` headers, `proxy_read_timeout 3600s`
      - `location /` block: `proxy_pass http://127.0.0.1:5000`, `X-Forwarded-Proto`, `X-Real-IP`, `X-Forwarded-For` headers, `proxy_read_timeout 120s`
      - Proxy buffer settings: `proxy_buffer_size 128k`, `proxy_buffers 4 256k`
    - _Requirements: 5.1, 5.2, 5.4_
  - [x] 4.2 Build and push the NGINX image
    - Run `docker build -t openalgo-nginx:latest ./nginx`
    - Tag and push to `<ACCOUNT_ID>.dkr.ecr.us-east-1.amazonaws.com/openalgo/nginx:latest`
    - _Requirements: 5.1, 5.4_

- [x] 5. Provision the Lightsail instance
  - [x] 5.1 Create the Lightsail instance with user-data bootstrap
    - Run `aws lightsail create-instances` with `--blueprint-id ubuntu_22_04`, `--bundle-id medium_2_0`, and `--user-data` script that installs `docker.io`, `docker-compose-plugin`, `awscli`, enables the Docker service, and adds `ubuntu` to the `docker` group
    - Wait for instance state to become `running` (`aws lightsail get-instance-state --instance-name openalgo-prod`)
    - _Requirements: 2.1, 2.2_
  - [x] 5.2 Allocate and attach a static IP
    - Run `aws lightsail allocate-static-ip --static-ip-name openalgo-ip`
    - Run `aws lightsail attach-static-ip --static-ip-name openalgo-ip --instance-name openalgo-prod`
    - Note the static IP address for DNS configuration
    - _Requirements: 2.1_
  - [x] 5.3 Configure Lightsail firewall to allow only SSH, HTTP, and HTTPS
    - Run `aws lightsail put-instance-public-ports` with port infos for TCP 22, TCP 80, TCP 443 only
    - Verify with `aws lightsail get-instance-port-states --instance-name openalgo-prod`
    - _Requirements: 9.4_

- [x] 6. Attach, format, and mount the 60 GB storage disk
  - [x] 6.1 Create and attach the disk
    - Run `aws lightsail create-disk --disk-name openalgo-data --availability-zone us-east-1a --size-in-gb 60`
    - Run `aws lightsail attach-disk --disk-name openalgo-data --instance-name openalgo-prod --disk-path /dev/xvdf`
    - Wait for disk state to become `in-use`
    - _Requirements: 4.1, 4.2_
  - [x] 6.2 SSH into the instance and format/mount the disk
    - SSH: `ssh -i ~/.ssh/lightsail-key.pem ubuntu@<STATIC_IP>`
    - Format: `sudo mkfs.ext4 /dev/xvdf` (first time only)
    - Mount: `sudo mkdir -p /mnt/openalgo-data && sudo mount /dev/xvdf /mnt/openalgo-data`
    - Persist: append `/dev/xvdf /mnt/openalgo-data ext4 defaults,nofail 0 2` to `/etc/fstab`
    - Create subdirectories: `sudo mkdir -p /mnt/openalgo-data/{db,log,log/strategies,strategies/scripts,strategies/examples,keys}`
    - Set ownership: `sudo chown -R 1000:1000 /mnt/openalgo-data && sudo chmod 700 /mnt/openalgo-data/keys`
    - _Requirements: 4.1, 4.2_

- [x] 7. Configure environment variables on the instance
  - [x] 7.1 Generate secrets locally
    - Run `python -c "import secrets; print(secrets.token_hex(32))"` twice to generate `APP_KEY` and `API_KEY_PEPPER` (different values)
    - Store these values securely (password manager or AWS Secrets Manager)
    - _Requirements: 3.3, 9.1, 9.6_
  - [x] 7.2 Create `/home/ubuntu/openalgo/.env` on the instance
    - SSH into the instance and create `/home/ubuntu/openalgo/.env` with all required variables:
      - `HOST_SERVER=https://yourdomain.com`
      - `APP_KEY=<64-char-hex>`, `API_KEY_PEPPER=<different-64-char-hex>`
      - `BROKER_API_KEY`, `BROKER_API_SECRET`, `REDIRECT_URL=https://yourdomain.com/<broker>/callback`
      - `FLASK_HOST_IP=0.0.0.0`, `FLASK_PORT=5000`, `FLASK_ENV=production`, `FLASK_DEBUG=False`
      - `WEBSOCKET_HOST=0.0.0.0`, `WEBSOCKET_PORT=8765`, `WEBSOCKET_URL=wss://yourdomain.com/ws`
      - `DATABASE_URL=sqlite:///db/openalgo.db`, `LATENCY_DATABASE_URL=sqlite:///db/latency.db`, `LOGS_DATABASE_URL=sqlite:///db/logs.db`, `SANDBOX_DATABASE_URL=sqlite:///db/sandbox.db`
      - `NGROK_ALLOW=FALSE`, `CSRF_ENABLED=TRUE`, `CSP_ENABLED=TRUE`, `CSP_UPGRADE_INSECURE_REQUESTS=TRUE`, `CORS_ENABLED=TRUE`, `CORS_ALLOWED_ORIGINS=https://yourdomain.com`
      - `LOG_TO_FILE=True`, `LOG_LEVEL=INFO`, `LOG_DIR=log`, `LOG_RETENTION=14`
    - Set permissions: `chmod 600 /home/ubuntu/openalgo/.env`
    - _Requirements: 3.1, 3.2, 3.3, 3.4, 3.5, 3.6, 3.7, 3.8, 3.9, 3.10, 3.11_

- [x] 8. Create the production `docker-compose.yaml` on the instance
  - Create `/home/ubuntu/openalgo/docker-compose.yaml` with:
    - `openalgo` service: ECR image, `network_mode: host`, volume mounts for `/app/db`, `/app/log`, `/app/strategies`, `/app/keys`, and `/app/.env` (read-only), `restart: unless-stopped`, healthcheck on `http://localhost:5000/api/v1/ping` (interval 30s, timeout 10s, retries 3, start_period 60s)
    - `nginx` service: ECR image, `network_mode: host`, `depends_on: openalgo (condition: service_healthy)`, `restart: unless-stopped`
  - _Requirements: 2.2, 2.3, 2.4, 4.1, 4.2, 7.1, 7.2, 7.3, 7.4_

- [x] 9. Authenticate ECR on the instance and deploy the stack
  - [x] 9.1 Configure ECR authentication on the instance
    - SSH into the instance
    - Run `aws ecr get-login-password --region us-east-1 | docker login --username AWS --password-stdin <ACCOUNT_ID>.dkr.ecr.us-east-1.amazonaws.com`
    - Configure AWS credentials on the instance (`aws configure` or attach an IAM instance profile with ECR read permissions)
    - _Requirements: 1.2_
  - [x] 9.2 Pull images and start the stack
    - Run `cd /home/ubuntu/openalgo && docker compose pull`
    - Run `docker compose up -d`
    - Verify both containers are running: `docker compose ps`
    - Check logs: `docker compose logs openalgo --tail=50`
    - _Requirements: 2.1, 2.2, 2.3_
  - [x] 9.3 Create a systemd service for auto-start on reboot
    - Create `/etc/systemd/system/openalgo.service` with `WorkingDirectory=/home/ubuntu/openalgo`, `ExecStart=/usr/bin/docker compose up -d`, `ExecStop=/usr/bin/docker compose down`, `After=docker.service network-online.target`
    - Run `sudo systemctl daemon-reload && sudo systemctl enable openalgo`
    - _Requirements: 2.2_

- [x] 10. Checkpoint — verify the stack is running before TLS setup
  - Confirm `docker compose ps` shows both containers as healthy/running
  - Run `curl -f http://<STATIC_IP>/api/v1/ping` and confirm HTTP 200
  - Ensure all tests pass, ask the user if questions arise.

- [ ] 11. TLS/HTTPS setup with Let's Encrypt
  - [x] 11.1 Point DNS A record to the Lightsail static IP
    - In your DNS provider, create an A record: `yourdomain.com → <STATIC_IP>`
    - Wait for DNS propagation (verify with `dig yourdomain.com` or `nslookup yourdomain.com`)
    - _Requirements: 6.1, 6.2_
  - [x] 11.2 Install Certbot and obtain a certificate
    - SSH into the instance
    - Run `sudo apt-get install -y certbot`
    - Stop NGINX temporarily: `docker compose stop nginx`
    - Obtain certificate: `sudo certbot certonly --standalone -d yourdomain.com`
    - Restart NGINX: `docker compose start nginx`
    - _Requirements: 6.1_
  - [ ] 11.3 Update `nginx/nginx.conf` to add HTTPS listener and rebuild the NGINX image
    - Add a `server { listen 443 ssl; ... }` block with `ssl_certificate /etc/letsencrypt/live/yourdomain.com/fullchain.pem`, `ssl_certificate_key`, `ssl_protocols TLSv1.2 TLSv1.3`, and the same `/ws` and `/` location blocks
    - Add a `server { listen 80; return 301 https://$host$request_uri; }` redirect block
    - Rebuild and push the NGINX image to ECR
    - Update `docker-compose.yaml` to mount `/etc/letsencrypt:/etc/letsencrypt:ro` in the `nginx` service
    - Run `docker compose pull nginx && docker compose up -d nginx`
    - _Requirements: 6.1, 6.3, 6.4_
  - [ ] 11.4 Set up automatic certificate renewal via cron
    - Create `/etc/cron.d/certbot-renew` with a daily job that runs `certbot renew --quiet` with pre/post hooks to stop and start the NGINX container
    - _Requirements: 6.1_

- [ ] 12. Security hardening
  - [ ] 12.1 Disable SSH password authentication
    - Edit `/etc/ssh/sshd_config`: set `PasswordAuthentication no`
    - Run `sudo systemctl restart sshd`
    - _Requirements: 9.4_
  - [ ] 12.2 Enable automatic security updates
    - Run `sudo apt-get install -y unattended-upgrades`
    - Run `sudo dpkg-reconfigure -plow unattended-upgrades`
    - _Requirements: 9.4_
  - [ ] 12.3 Verify production environment variables are correct
    - Run `docker exec openalgo-app env | grep -E 'FLASK_DEBUG|FLASK_ENV|NGROK_ALLOW|CSRF_ENABLED|CSP_ENABLED'`
    - Confirm: `FLASK_DEBUG=False`, `FLASK_ENV=production`, `NGROK_ALLOW=FALSE`, `CSRF_ENABLED=TRUE`, `CSP_ENABLED=TRUE`
    - _Requirements: 9.2, 9.3, 9.5_
  - [ ]* 12.4 Write image secrets test
    - **Property: Image secrets test (Unit)**
    - Inspect built Docker image layers via `docker history` and assert `APP_KEY`, `API_KEY_PEPPER`, and broker secret values are not present in any layer
    - **Validates: Requirements 9.6**
  - [ ]* 12.5 Write production mode test
    - **Property: Production mode test (Unit)**
    - When `FLASK_DEBUG=False` and `FLASK_ENV=production`, assert the app returns 404 for `/console` (Werkzeug debugger) and does not expose debug routes
    - **Validates: Requirements 9.2**

- [ ] 13. Deployment verification
  - [ ] 13.1 Verify HTTPS endpoints
    - Run `curl -f https://yourdomain.com/api/v1/ping` — expect HTTP 200
    - Run `curl -I https://yourdomain.com/` — expect HTTP 200 or 302
    - _Requirements: 10.1, 10.2_
  - [ ]* 13.2 Write health endpoint unit test
    - **Property: Health endpoint test (Unit)**
    - `GET /api/v1/ping` returns HTTP 200 with a running app instance
    - **Validates: Requirements 7.2, 10.2**
  - [ ] 13.3 Verify WebSocket connectivity
    - Install `wscat` locally: `npm install -g wscat`
    - Run `wscat -c wss://yourdomain.com/ws` and confirm HTTP 101 upgrade and connection
    - _Requirements: 5.2, 10.4_
  - [ ]* 13.4 Write WebSocket connection unit test
    - **Property: WebSocket connection test (Unit)**
    - A WebSocket client connecting to `ws://localhost/ws` via NGINX receives a successful HTTP 101 upgrade response
    - **Validates: Requirements 5.2, 10.4**
  - [ ] 13.5 Verify SQLite database persistence
    - Check files exist: `ls -la /mnt/openalgo-data/db/` — expect `openalgo.db`, `latency.db`, `logs.db`, `sandbox.db`
    - Restart the container: `docker compose restart openalgo`
    - Re-run `curl -f https://yourdomain.com/api/v1/ping` and confirm API keys/settings are still present
    - _Requirements: 4.3, 10.5_
  - [ ] 13.6 Verify broker OAuth callback routing
    - Register `https://yourdomain.com/<broker>/callback` as the authorized redirect URI in the broker developer portal
    - Navigate to `https://yourdomain.com/<broker>/login`, complete the OAuth flow, and confirm the callback lands correctly
    - _Requirements: 8.1, 8.2, 10.3_
  - [ ]* 13.7 Write OAuth callback routing unit test
    - **Property: OAuth callback routing test (Unit)**
    - A simulated broker OAuth callback POST to `/<broker>/callback` with valid parameters is routed to `brlogin_bp` and returns a redirect or HTTP 200
    - **Validates: Requirements 8.2**

- [ ] 14. Write property-based tests
  - [ ] 14.1 Write property test for `start.sh` `.env` generation (Property 1)
    - Create `tests/test_deployment_properties.py`
    - Use `hypothesis` with `@given(host_server=st.from_regex(r'https?://[a-z0-9\-\.]+\.[a-z]{2,}', fullmatch=True), app_key=st.text(alphabet='0123456789abcdef', min_size=64, max_size=64), api_key_pepper=...)`
    - Run `start.sh` in a temp directory with `HOST_SERVER` set and no `.env` present; assert `/app/.env` is created and contains `HOST_SERVER`, `FLASK_HOST_IP`, `FLASK_ENV`, and `WEBSOCKET_URL`
    - Annotate with `@settings(max_examples=100)`
    - **Property 1: start.sh generates .env when HOST_SERVER is set**
    - **Validates: Requirements 3.2**
  - [ ]* 14.2 Write property test for SQLite persistence round trip (Property 2)
    - Use `hypothesis` with `@given(api_keys=st.lists(st.fixed_dictionaries({...}), min_size=1, max_size=20))`
    - Insert records into `openalgo.db`, stop the container, start the container with the same volume mount, query records, and assert all inserted records are present and unchanged
    - Annotate with `@settings(max_examples=100)`
    - **Property 2: SQLite data survives container restart**
    - **Validates: Requirements 4.3, 10.5**
  - [ ] 14.3 Write property test for secure cookie configuration (Property 3)
    - Use `hypothesis` with `@given(host=st.from_regex(r'https://[a-z0-9\-\.]+\.[a-z]{2,}', fullmatch=True))`
    - For HTTPS hosts: call `create_app({'HOST_SERVER': host})` and assert `SESSION_COOKIE_SECURE is True` and `SESSION_COOKIE_NAME.startswith('__Secure-')`
    - For HTTP hosts: assert `SESSION_COOKIE_SECURE is False`
    - Annotate with `@settings(max_examples=100)`
    - **Property 3: HTTPS HOST_SERVER enables secure cookie configuration**
    - **Validates: Requirements 6.3**
  - [ ]* 14.4 Write property test for CSRF enforcement (Property 4)
    - Use `hypothesis` with `@given(endpoint=st.sampled_from(['/login', '/api/v1/order', '/settings']), payload=st.dictionaries(st.text(), st.text()))`
    - POST to each endpoint without a CSRF token and assert the response status is 400 or 403
    - Annotate with `@settings(max_examples=100)`
    - **Property 4: CSRF protection rejects requests without valid tokens**
    - **Validates: Requirements 9.5**

- [ ] 15. Final checkpoint — ensure all tests pass
  - Run `pytest tests/test_deployment_properties.py -v` and confirm all property tests pass
  - Confirm `docker compose ps` shows both containers healthy
  - Ensure all tests pass, ask the user if questions arise.

## Notes

- Tasks marked with `*` are optional and can be skipped for a faster MVP
- `network_mode: host` is used so NGINX can reach Flask on `127.0.0.1:5000` and the WebSocket proxy on `127.0.0.1:8765` without Docker bridge overhead
- Replace `<ACCOUNT_ID>` with your 12-digit AWS account ID throughout
- Replace `yourdomain.com` with your actual domain or Lightsail static IP
- Replace `<broker>` with your broker name (e.g., `zerodha`, `angel`)
- The `medium_2_0` bundle (2 vCPU / 2 GB RAM / 60 GB SSD) is the exact target spec
- Property tests require `hypothesis` (`pip install hypothesis pytest`)
- Integration tests tagged `@pytest.mark.integration` require a running Docker Compose stack
