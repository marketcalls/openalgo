$ErrorActionPreference = "Stop"

$INSTANCE_IP = "13.233.95.10"
$SSH_KEY = "$HOME\Downloads\ubuntu-keypair.pem"
$ECR_REGISTRY = "973370772689.dkr.ecr.ap-south-1.amazonaws.com"
$AWS_REGION = "ap-south-1"

Write-Host "=== OpenAlgo Lightsail Deployment Script ===" -ForegroundColor Cyan
Write-Host "Instance: dev-ubuntu @ $INSTANCE_IP (Ubuntu 24.04, NVMe disk)"
Write-Host ""

$AWS_ACCESS_KEY = (aws configure get aws_access_key_id).Trim()
$AWS_SECRET_KEY = (aws configure get aws_secret_access_key).Trim()

function Invoke-SSH {
    param([string]$Cmd)
    & ssh -i $SSH_KEY -o StrictHostKeyChecking=no ubuntu@$INSTANCE_IP $Cmd
    if ($LASTEXITCODE -ne 0) { throw "SSH command failed: $Cmd" }
}

function Invoke-SSHNoFail {
    param([string]$Cmd)
    & ssh -i $SSH_KEY -o StrictHostKeyChecking=no ubuntu@$INSTANCE_IP $Cmd
}

# ─────────────────────────────────────────────────────────────────────────────
# STEP 1 — Copy .env
# ─────────────────────────────────────────────────────────────────────────────
Write-Host "Step 1 - Copying .env to instance..." -ForegroundColor Yellow
& scp -i $SSH_KEY -o StrictHostKeyChecking=no .env ubuntu@${INSTANCE_IP}:/home/ubuntu/.env-openalgo
if ($LASTEXITCODE -ne 0) { throw "scp failed" }
Write-Host "  Done" -ForegroundColor Green

# ─────────────────────────────────────────────────────────────────────────────
# STEP 2 — Install Docker (Ubuntu 24.04 official repo) + AWS CLI v2
# ─────────────────────────────────────────────────────────────────────────────
Write-Host ""
Write-Host "Step 2 - Installing Docker (official repo) and AWS CLI v2..." -ForegroundColor Yellow

Invoke-SSH "sudo apt-get update -y -qq"
# Install prerequisites
Invoke-SSH "sudo apt-get install -y -qq ca-certificates curl unzip"
# Add Docker's official GPG key and repo
Invoke-SSH "sudo install -m 0755 -d /etc/apt/keyrings"
Invoke-SSH "sudo curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc"
Invoke-SSH "sudo chmod a+r /etc/apt/keyrings/docker.asc"
Invoke-SSH @'
echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu $(. /etc/os-release && echo "$VERSION_CODENAME") stable" | sudo tee /etc/apt/sources.list.d/docker.list > /dev/null
'@
Invoke-SSH "sudo apt-get update -y -qq"
Invoke-SSH "sudo apt-get install -y -qq docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin"
Invoke-SSH "sudo systemctl enable docker && sudo systemctl start docker"
Invoke-SSH "sudo usermod -aG docker ubuntu"

# Install AWS CLI v2
Invoke-SSH "curl -fsSL 'https://awscli.amazonaws.com/awscli-exe-linux-x86_64.zip' -o /tmp/awscliv2.zip && unzip -q /tmp/awscliv2.zip -d /tmp && sudo /tmp/aws/install --update && rm -rf /tmp/aws /tmp/awscliv2.zip"

Write-Host "  Verifying..." -ForegroundColor Gray
Invoke-SSH "docker --version && aws --version"
Write-Host "  Installed" -ForegroundColor Green

# ─────────────────────────────────────────────────────────────────────────────
# STEP 3 — Storage directories (using root disk — no separate disk attached)
# ─────────────────────────────────────────────────────────────────────────────
Write-Host ""
Write-Host "Step 3 - Setting up storage directories on root disk..." -ForegroundColor Yellow
Invoke-SSH "sudo mkdir -p /mnt/openalgo-data/db /mnt/openalgo-data/log /mnt/openalgo-data/log/strategies /mnt/openalgo-data/strategies/scripts /mnt/openalgo-data/strategies/examples /mnt/openalgo-data/keys"
Invoke-SSH "sudo chown -R 1000:1000 /mnt/openalgo-data && sudo chmod -R 755 /mnt/openalgo-data && sudo chmod 700 /mnt/openalgo-data/keys"
Write-Host "  Done" -ForegroundColor Green

# ─────────────────────────────────────────────────────────────────────────────
# STEP 4 — App directory and .env
# ─────────────────────────────────────────────────────────────────────────────
Write-Host ""
Write-Host "Step 4 - Setting up app directory..." -ForegroundColor Yellow
Invoke-SSH "mkdir -p /home/ubuntu/openalgo && cp /home/ubuntu/.env-openalgo /home/ubuntu/openalgo/.env && chmod 600 /home/ubuntu/openalgo/.env"
Write-Host "  Done" -ForegroundColor Green

# ─────────────────────────────────────────────────────────────────────────────
# STEP 5 — Write docker-compose.yaml via base64 (avoids CRLF issues)
# ─────────────────────────────────────────────────────────────────────────────
Write-Host ""
Write-Host "Step 5 - Writing docker-compose.yaml..." -ForegroundColor Yellow

$lines = @(
    "services:",
    "  openalgo:",
    "    image: $ECR_REGISTRY/openalgo/app:latest",
    "    container_name: openalgo-app",
    "    network_mode: host",
    "    volumes:",
    "      - /mnt/openalgo-data/db:/app/db",
    "      - /mnt/openalgo-data/log:/app/log",
    "      - /mnt/openalgo-data/strategies:/app/strategies",
    "      - /mnt/openalgo-data/keys:/app/keys",
    "      - /home/ubuntu/openalgo/.env:/app/.env:ro",
    "    restart: unless-stopped",
    "    healthcheck:",
    "      test: [`"CMD`", `"python3`", `"-c`", `"import urllib.request; urllib.request.urlopen('http://localhost:5000/api/v1/ping')`"]",
    "      interval: 30s",
    "      timeout: 10s",
    "      retries: 3",
    "      start_period: 60s",
    "  nginx:",
    "    image: $ECR_REGISTRY/openalgo/nginx:latest",
    "    container_name: openalgo-nginx",
    "    network_mode: host",
    "    depends_on:",
    "      openalgo:",
    "        condition: service_healthy",
    "    restart: unless-stopped"
)
$composeContent = $lines -join "`n"
$composeBytes = [System.Text.Encoding]::UTF8.GetBytes($composeContent)
$composeB64 = [Convert]::ToBase64String($composeBytes)
Invoke-SSH "echo $composeB64 | base64 -d > /home/ubuntu/openalgo/docker-compose.yaml"
Write-Host "  Done" -ForegroundColor Green

# ─────────────────────────────────────────────────────────────────────────────
# STEP 6 — AWS credentials + ECR auth + pull + start
# ─────────────────────────────────────────────────────────────────────────────
Write-Host ""
Write-Host "Step 6 - Configuring AWS credentials on instance..." -ForegroundColor Yellow
Invoke-SSH "aws configure set aws_access_key_id $AWS_ACCESS_KEY"
Invoke-SSH "aws configure set aws_secret_access_key $AWS_SECRET_KEY"
Invoke-SSH "aws configure set region $AWS_REGION"

Write-Host "Step 6 - Authenticating Docker to ECR..." -ForegroundColor Yellow
Invoke-SSH "aws ecr get-login-password --region $AWS_REGION | docker login --username AWS --password-stdin $ECR_REGISTRY"

Write-Host "Step 6 - Pulling images (this may take a few minutes)..." -ForegroundColor Yellow
Invoke-SSH "cd /home/ubuntu/openalgo && docker compose pull"

Write-Host "Step 6 - Starting stack..." -ForegroundColor Yellow
Invoke-SSH "cd /home/ubuntu/openalgo && docker compose up -d"

# ─────────────────────────────────────────────────────────────────────────────
# STEP 7 — Systemd service
# ─────────────────────────────────────────────────────────────────────────────
Write-Host ""
Write-Host "Step 7 - Creating systemd service..." -ForegroundColor Yellow
$svcLines = @(
    "[Unit]",
    "Description=OpenAlgo Docker Compose Stack",
    "Requires=docker.service",
    "After=docker.service network-online.target",
    "Wants=network-online.target",
    "",
    "[Service]",
    "Type=oneshot",
    "RemainAfterExit=yes",
    "WorkingDirectory=/home/ubuntu/openalgo",
    "ExecStart=/usr/bin/docker compose up -d",
    "ExecStop=/usr/bin/docker compose down",
    "TimeoutStartSec=300",
    "",
    "[Install]",
    "WantedBy=multi-user.target"
)
$svcContent = $svcLines -join "`n"
$svcBytes = [System.Text.Encoding]::UTF8.GetBytes($svcContent)
$svcB64 = [Convert]::ToBase64String($svcBytes)
Invoke-SSH "echo $svcB64 | base64 -d | sudo tee /etc/systemd/system/openalgo.service > /dev/null"
Invoke-SSH "sudo systemctl daemon-reload && sudo systemctl enable openalgo"
Write-Host "  Done" -ForegroundColor Green

# ─────────────────────────────────────────────────────────────────────────────
# STEP 8 — Status check
# ─────────────────────────────────────────────────────────────────────────────
Write-Host ""
Write-Host "Waiting 75 seconds for containers to become healthy..." -ForegroundColor Yellow
Start-Sleep -Seconds 75

Write-Host ""
Write-Host "Step 8 - Container status..." -ForegroundColor Yellow
Invoke-SSH "cd /home/ubuntu/openalgo && docker compose ps"

Write-Host ""
Write-Host "Step 8 - Application logs (last 30 lines)..." -ForegroundColor Yellow
Invoke-SSH "cd /home/ubuntu/openalgo && docker compose logs openalgo --tail=30"

# ─────────────────────────────────────────────────────────────────────────────
# CHECKPOINT
# ─────────────────────────────────────────────────────────────────────────────
Write-Host ""
Write-Host "=== Deployment Complete ===" -ForegroundColor Green
Write-Host ""
Write-Host "Checkpoint - Testing health endpoint at http://$INSTANCE_IP/api/v1/ping ..." -ForegroundColor Yellow
try {
    $response = Invoke-WebRequest -Uri "http://$INSTANCE_IP/api/v1/ping" -UseBasicParsing -TimeoutSec 15
    if ($response.StatusCode -eq 200) {
        Write-Host "Health check PASSED (HTTP 200)" -ForegroundColor Green
    }
} catch {
    Write-Host "Health check FAILED: $($_.Exception.Message)" -ForegroundColor Red
    Write-Host "Debug: ssh -i $SSH_KEY ubuntu@$INSTANCE_IP 'docker compose -f /home/ubuntu/openalgo/docker-compose.yaml logs openalgo --tail=50'"
}

Write-Host ""
Write-Host "Next steps:" -ForegroundColor Cyan
Write-Host "  1. Visit http://$INSTANCE_IP in your browser"
Write-Host "  2. For HTTPS: point a domain to $INSTANCE_IP then run Task 11 (TLS setup)"
Write-Host ""
