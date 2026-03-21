#!/bin/bash
set -e

INSTANCE_IP="13.233.95.10"
SSH_KEY="$HOME/Downloads/ubuntu-keypair.pem"
ECR_REGISTRY="973370772689.dkr.ecr.ap-south-1.amazonaws.com"
AWS_REGION="ap-south-1"

echo "=== OpenAlgo Lightsail Deployment Script ==="
echo "Instance: dev-ubuntu @ $INSTANCE_IP (Ubuntu 24.04, NVMe disk)"
echo ""

AWS_ACCESS_KEY=$(aws configure get aws_access_key_id)
AWS_SECRET_KEY=$(aws configure get aws_secret_access_key)

# ─────────────────────────────────────────────────────────────────────────────
# STEP 1 — Copy .env to instance
# ─────────────────────────────────────────────────────────────────────────────
echo "Step 1 - Copying .env to instance..."
scp -i "$SSH_KEY" -o StrictHostKeyChecking=no .env ubuntu@$INSTANCE_IP:/home/ubuntu/.env-openalgo

# ─────────────────────────────────────────────────────────────────────────────
# STEP 2 — Install Docker (official repo) + AWS CLI v2
# ─────────────────────────────────────────────────────────────────────────────
echo ""
echo "Step 2 - Installing Docker (official repo) and AWS CLI v2..."

ssh -i "$SSH_KEY" -o StrictHostKeyChecking=no ubuntu@$INSTANCE_IP "sudo apt-get update -y -qq"
ssh -i "$SSH_KEY" -o StrictHostKeyChecking=no ubuntu@$INSTANCE_IP "sudo apt-get install -y -qq ca-certificates curl unzip"
ssh -i "$SSH_KEY" -o StrictHostKeyChecking=no ubuntu@$INSTANCE_IP "sudo install -m 0755 -d /etc/apt/keyrings"
ssh -i "$SSH_KEY" -o StrictHostKeyChecking=no ubuntu@$INSTANCE_IP "sudo curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc && sudo chmod a+r /etc/apt/keyrings/docker.asc"
ssh -i "$SSH_KEY" -o StrictHostKeyChecking=no ubuntu@$INSTANCE_IP 'echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu $(. /etc/os-release && echo "$VERSION_CODENAME") stable" | sudo tee /etc/apt/sources.list.d/docker.list > /dev/null'
ssh -i "$SSH_KEY" -o StrictHostKeyChecking=no ubuntu@$INSTANCE_IP "sudo apt-get update -y -qq && sudo apt-get install -y -qq docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin"
ssh -i "$SSH_KEY" -o StrictHostKeyChecking=no ubuntu@$INSTANCE_IP "sudo systemctl enable docker && sudo systemctl start docker && sudo usermod -aG docker ubuntu"
ssh -i "$SSH_KEY" -o StrictHostKeyChecking=no ubuntu@$INSTANCE_IP "curl -fsSL 'https://awscli.amazonaws.com/awscli-exe-linux-x86_64.zip' -o /tmp/awscliv2.zip && unzip -q /tmp/awscliv2.zip -d /tmp && sudo /tmp/aws/install --update && rm -rf /tmp/aws /tmp/awscliv2.zip"
ssh -i "$SSH_KEY" -o StrictHostKeyChecking=no ubuntu@$INSTANCE_IP "docker --version && aws --version"

# ─────────────────────────────────────────────────────────────────────────────
# STEP 3 — Storage directories (root disk — no separate disk attached)
# ─────────────────────────────────────────────────────────────────────────────
echo ""
echo "Step 3 - Setting up storage directories..."
ssh -i "$SSH_KEY" -o StrictHostKeyChecking=no ubuntu@$INSTANCE_IP "sudo mkdir -p /mnt/openalgo-data/{db,log,log/strategies,strategies/scripts,strategies/examples,keys} && sudo chown -R 1000:1000 /mnt/openalgo-data && sudo chmod -R 755 /mnt/openalgo-data && sudo chmod 700 /mnt/openalgo-data/keys"

# ─────────────────────────────────────────────────────────────────────────────
# STEP 4 — App directory and .env
# ─────────────────────────────────────────────────────────────────────────────
echo ""
echo "Step 4 - Setting up app directory..."
ssh -i "$SSH_KEY" -o StrictHostKeyChecking=no ubuntu@$INSTANCE_IP "mkdir -p /home/ubuntu/openalgo && cp /home/ubuntu/.env-openalgo /home/ubuntu/openalgo/.env && chmod 600 /home/ubuntu/openalgo/.env"

# ─────────────────────────────────────────────────────────────────────────────
# STEP 5 — Write docker-compose.yaml
# ─────────────────────────────────────────────────────────────────────────────
echo ""
echo "Step 5 - Writing docker-compose.yaml..."
cat > /tmp/docker-compose.yaml << COMPOSE
services:
  openalgo:
    image: ${ECR_REGISTRY}/openalgo/app:latest
    container_name: openalgo-app
    network_mode: host
    volumes:
      - /mnt/openalgo-data/db:/app/db
      - /mnt/openalgo-data/log:/app/log
      - /mnt/openalgo-data/strategies:/app/strategies
      - /mnt/openalgo-data/keys:/app/keys
      - /home/ubuntu/openalgo/.env:/app/.env:ro
    restart: unless-stopped
    healthcheck:
      test: ["CMD", "python3", "-c", "import urllib.request; urllib.request.urlopen('http://localhost:5000/api/v1/ping')"]
      interval: 30s
      timeout: 10s
      retries: 3
      start_period: 60s

  nginx:
    image: ${ECR_REGISTRY}/openalgo/nginx:latest
    container_name: openalgo-nginx
    network_mode: host
    depends_on:
      openalgo:
        condition: service_healthy
    restart: unless-stopped
COMPOSE
scp -i "$SSH_KEY" -o StrictHostKeyChecking=no /tmp/docker-compose.yaml ubuntu@$INSTANCE_IP:/home/ubuntu/openalgo/docker-compose.yaml

# ─────────────────────────────────────────────────────────────────────────────
# STEP 6 — AWS credentials + ECR auth + pull + start
# ─────────────────────────────────────────────────────────────────────────────
echo ""
echo "Step 6 - Configuring AWS credentials and deploying..."
ssh -i "$SSH_KEY" -o StrictHostKeyChecking=no ubuntu@$INSTANCE_IP "aws configure set aws_access_key_id ${AWS_ACCESS_KEY} && aws configure set aws_secret_access_key ${AWS_SECRET_KEY} && aws configure set region ${AWS_REGION}"
ssh -i "$SSH_KEY" -o StrictHostKeyChecking=no ubuntu@$INSTANCE_IP "aws ecr get-login-password --region ${AWS_REGION} | docker login --username AWS --password-stdin ${ECR_REGISTRY}"
ssh -i "$SSH_KEY" -o StrictHostKeyChecking=no ubuntu@$INSTANCE_IP "cd /home/ubuntu/openalgo && docker compose pull"
ssh -i "$SSH_KEY" -o StrictHostKeyChecking=no ubuntu@$INSTANCE_IP "cd /home/ubuntu/openalgo && docker compose up -d"

# ─────────────────────────────────────────────────────────────────────────────
# STEP 7 — Systemd service
# ─────────────────────────────────────────────────────────────────────────────
echo ""
echo "Step 7 - Creating systemd service..."
cat > /tmp/openalgo.service << 'SVC'
[Unit]
Description=OpenAlgo Docker Compose Stack
Requires=docker.service
After=docker.service network-online.target
Wants=network-online.target

[Service]
Type=oneshot
RemainAfterExit=yes
WorkingDirectory=/home/ubuntu/openalgo
ExecStart=/usr/bin/docker compose up -d
ExecStop=/usr/bin/docker compose down
TimeoutStartSec=300

[Install]
WantedBy=multi-user.target
SVC
scp -i "$SSH_KEY" -o StrictHostKeyChecking=no /tmp/openalgo.service ubuntu@$INSTANCE_IP:/home/ubuntu/openalgo.service
ssh -i "$SSH_KEY" -o StrictHostKeyChecking=no ubuntu@$INSTANCE_IP "sudo mv /home/ubuntu/openalgo.service /etc/systemd/system/openalgo.service && sudo systemctl daemon-reload && sudo systemctl enable openalgo"

# ─────────────────────────────────────────────────────────────────────────────
# STEP 8 — Status check
# ─────────────────────────────────────────────────────────────────────────────
echo ""
echo "Waiting 75 seconds for containers to become healthy..."
sleep 75

echo ""
echo "Step 8 - Container status..."
ssh -i "$SSH_KEY" ubuntu@$INSTANCE_IP "cd /home/ubuntu/openalgo && docker compose ps"

echo ""
echo "Step 8 - Application logs (last 30 lines)..."
ssh -i "$SSH_KEY" ubuntu@$INSTANCE_IP "cd /home/ubuntu/openalgo && docker compose logs openalgo --tail=30"

# ─────────────────────────────────────────────────────────────────────────────
# CHECKPOINT
# ─────────────────────────────────────────────────────────────────────────────
echo ""
echo "=== Deployment Complete ==="
echo ""
echo "Checkpoint — Testing health endpoint..."
curl -f "http://$INSTANCE_IP/api/v1/ping" && echo " ✓ Health check passed" || echo " ✗ Health check failed"

echo ""
echo "Next steps:"
echo "  1. Visit http://$INSTANCE_IP in your browser"
echo "  2. For HTTPS: point a domain to $INSTANCE_IP then run Task 11 (TLS setup)"
echo ""
