.PHONY: help setup run run-with-ngrok run-with-cloudflare run-backend run-frontend build-frontend lint lint-security test test-e2e format clean docker-build docker-build-nocache docker-start docker-stop docker-restart docker-logs docker-status docker-clean docker-upgrade docker-shell docker-migrate docker-test-deps docker-inspect-shm docker-prune docker-enable-remote-mcp upgrade backup reset-password rotate-pepper generate-keys server-start server-stop server-logs server-restart server-status server-reload nginx-test nginx-reload nginx-logs fix-env setup-swap fix-selinux fix-firewalld fix-ufw enable-remote-mcp install-native install-native-multi change-domain install-docker install-docker-multi test-broker

# Default target
.DEFAULT_GOAL := help

help: ## Show this help menu
	@awk 'BEGIN {FS = ":.*?## "} /^[a-zA-Z_-]+:.*?## / {printf "  \033[36m%-25s\033[0m %s\n", $$1, $$2} /^##@/ { printf "\n\033[1m%s\033[0m\n", substr($$0, 5) } ' $(MAKEFILE_LIST)

# ==============================================================================
##@ LOCAL DEVELOPMENT & SETUP
# ==============================================================================

setup: ## Initial project setup (copies .env, installs all dependencies)
	@if [ ! -f .env ]; then cp .sample.env .env; echo "Created .env from .sample.env. Please configure it."; else echo ".env already exists."; fi
	@echo "\nInstalling backend dependencies..."
	uv sync
	@echo "\nInstalling frontend dependencies..."
	cd frontend && npm install
	@echo "\nSetup complete! You can now run 'make run-backend' and 'make run-frontend' in separate terminals."

run: ## Run both the Python backend and React frontend concurrently
	$(MAKE) -j2 run-backend run-frontend

run-with-ngrok: ## Run both the backend and frontend concurrently with Ngrok tunnel enabled
	NGROK_ALLOW=TRUE $(MAKE) run

run-with-cloudflare: ## Start a free temporary Cloudflare tunnel to expose the backend
	cloudflared tunnel --url http://127.0.0.1:5000

run-backend: ## Run the Python backend locally (uv)
	uv run app.py

run-frontend: ## Run the React frontend locally in watch mode (Vite)
	cd frontend && npm run dev

build-frontend: ## Compile and build the React frontend for production
	cd frontend && npm run build

# ==============================================================================
##@ PLATFORM ADMINISTRATION (Customer Operations)
# ==============================================================================

upgrade: ## Upgrade OpenAlgo to the latest version (pulls code, migrates DB, updates deps)
	chmod +x install/update.sh
	./install/update.sh

backup: ## Backup all local databases (SQLite & DuckDB)
	@mkdir -p db/backup_$$(date +%Y%m%d_%H%M%S)
	@cp db/*.db db/backup_$$(date +%Y%m%d_%H%M%S)/ 2>/dev/null || true
	@cp db/historify.duckdb db/backup_$$(date +%Y%m%d_%H%M%S)/ 2>/dev/null || true
	@echo "Databases backed up successfully."

reset-password: ## Reset the admin password
	uv run python upgrade/reset_admin_password.py

rotate-pepper: ## Securely rotate the API_KEY_PEPPER and re-encrypt tokens
	uv run python upgrade/rotate_pepper.py

generate-keys: ## Generate secure 32-byte hex keys for APP_KEY or API_KEY_PEPPER
	@echo "Generated Key: "
	@uv run python -c "import secrets; print(secrets.token_hex(32))"

# ==============================================================================
##@ CODE QUALITY & TESTING
# ==============================================================================

lint: ## Lint both backend (Ruff) and frontend (Biome)
	@echo "Linting backend..."
	uv run ruff check .
	@echo "\nLinting frontend..."
	cd frontend && npm run lint

lint-security: ## Run backend security linters (Bandit, pip-audit, detect-secrets)
	uv run bandit -r . -x .venv,test,frontend,node_modules -ll
	uv run pip-audit

format: ## Format both backend (Ruff) and frontend (Biome)
	@echo "Formatting backend..."
	uv run ruff format .
	@echo "\nFormatting frontend..."
	cd frontend && npm run format

test: ## Run unit tests for backend (Pytest) and frontend (Vitest)
	@echo "Running backend tests..."
	uv run pytest
	@echo "\nRunning frontend unit tests..."
	cd frontend && npm run test:run

test-broker: ## Run broker-specific integration tests
	uv run pytest test/test_broker.py -v

test-e2e: ## Run end-to-end tests for the frontend (Playwright)
	cd frontend && npm run e2e

# ==============================================================================
##@ CLEANUP
# ==============================================================================

clean: ## Clean local dependency caches, node_modules, and build artifacts
	rm -rf frontend/node_modules frontend/dist
	rm -rf .venv __pycache__ .pytest_cache .ruff_cache
	find . -type d -name "__pycache__" -exec rm -rf {} +
	@echo "Cleaned up local dependencies and caches."

# ==============================================================================
##@ DOCKER MANAGEMENT
# ==============================================================================

docker-build: ## Build the OpenAlgo Docker image with numba/llvmlite optimizations
	chmod +x docker-build.sh
	./docker-build.sh

docker-start: ## Start the OpenAlgo container in the background
	docker-compose up -d

docker-stop: ## Stop the OpenAlgo container gracefully
	docker-compose down

docker-restart: ## Restart the OpenAlgo container
	docker-compose restart

docker-logs: ## View real-time logs from the OpenAlgo container
	docker-compose logs -f

docker-status: ## View the status of the OpenAlgo container
	docker-compose ps

docker-clean: ## Stop container & remove named volumes (WARNING: Deletes DBs & Strategies)
	@read -p "Are you sure you want to delete all Docker data (DBs, strategies)? [y/N] " ans && if [ $${ans:-N} = y ]; then \
		docker-compose down -v; \
		echo "Volumes removed."; \
	else \
		echo "Aborted."; \
	fi

docker-upgrade: ## Upgrade the Docker container to the latest image
	docker-compose pull
	docker-compose up -d

docker-shell: ## Open a bash shell inside the running OpenAlgo container
	docker-compose exec openalgo bash

docker-migrate: ## Run database migrations inside the Docker container
	docker-compose exec openalgo python upgrade/migrate_all.py

docker-test-deps: ## Verify numba, scipy, and llvmlite work correctly inside Docker
	docker-compose exec openalgo python -c "import numba; import llvmlite; import scipy; print('Docker dependencies loaded successfully!')"

docker-inspect-shm: ## Check the shared memory size configured for the container
	docker inspect openalgo --format='Shared Memory: {{.HostConfig.ShmSize}}'

docker-prune: ## Complete Docker cleanup (WARNING: Removes all unused Docker images/volumes system-wide)
	docker system prune -a --volumes

docker-build-nocache: ## Build the Docker image from scratch without using cache
	docker-compose build --no-cache

docker-enable-remote-mcp: ## Enable the Remote MCP feature for Docker deployments
	chmod +x install/enable-remote-mcp-docker.sh
	sudo ./install/enable-remote-mcp-docker.sh

# ==============================================================================
##@ SERVER DEPLOYMENT MANAGEMENT (Systemd / Nginx)
# ==============================================================================

server-start: ## Start all native OpenAlgo systemd services
	sudo systemctl start "openalgo-*"

server-stop: ## Stop all native OpenAlgo systemd services
	sudo systemctl stop "openalgo-*"

server-logs: ## View real-time systemd logs for all native OpenAlgo deployments
	sudo journalctl -f -u "openalgo-*"

server-restart: ## Restart all native OpenAlgo systemd services
	sudo systemctl restart "openalgo-*"

server-status: ## Check the status of all native OpenAlgo systemd services
	sudo systemctl status "openalgo-*"

server-reload: ## Reload systemd daemon
	sudo systemctl daemon-reload

nginx-test: ## Test Nginx configuration for syntax errors
	sudo nginx -t

nginx-reload: ## Reload Nginx gracefully
	sudo systemctl reload nginx

nginx-logs: ## View Nginx error and access logs
	sudo tail -f /var/log/nginx/error.log /var/log/nginx/access.log

fix-env: ## Fix permissions for the .env file (required for Docker/native)
	sudo chown 1000:1000 .env
	sudo chmod 600 .env

setup-swap: ## Create a 4GB swapfile for low-memory VPS deployments
	sudo fallocate -l 4G /swapfile
	sudo chmod 600 /swapfile
	sudo mkswap /swapfile
	sudo swapon /swapfile

fix-selinux: ## (RHEL/CentOS) Fix SELinux permissions for Nginx and OpenAlgo
	sudo setsebool -P httpd_can_network_connect on
	sudo semanage fcontext -a -t httpd_sys_rw_content_t "/var/python/openalgo-flask(/.*)?"
	sudo restorecon -Rv /var/python/openalgo-flask

fix-firewalld: ## (RHEL/CentOS) Open HTTP/HTTPS ports in Firewalld
	sudo firewall-cmd --permanent --add-service=http
	sudo firewall-cmd --permanent --add-service=https
	sudo firewall-cmd --reload

fix-ufw: ## (Ubuntu/Debian) Open HTTP/HTTPS ports in UFW firewall
	sudo ufw allow http
	sudo ufw allow https
	sudo ufw reload

enable-remote-mcp: ## Enable the Remote MCP feature for native (systemd) deployments
	chmod +x install/enable-remote-mcp.sh
	sudo ./install/enable-remote-mcp.sh

install-native: ## Run the single-domain native (Nginx/systemd) installer
	chmod +x install/install.sh
	sudo ./install/install.sh

install-native-multi: ## Run the multi-domain native (Nginx/systemd) installer
	chmod +x install/install-multi.sh
	sudo ./install/install-multi.sh

change-domain: ## Change the domain of an existing native deployment
	chmod +x install/change-domain.sh
	sudo ./install/change-domain.sh

install-docker: ## Run the standard Docker installer
	chmod +x install/install-docker.sh
	sudo ./install/install-docker.sh

install-docker-multi: ## Run the multi-domain custom SSL Docker installer
	chmod +x install/install-docker-multi-custom-ssl.sh
	sudo ./install/install-docker-multi-custom-ssl.sh
