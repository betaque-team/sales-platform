# =============================================================================
#  Sales Data Platform — Operations Makefile
#
#  Quick start (local dev):    make dev
#  First production deploy:    make provision  →  make deploy
#  Redeploy:                   make deploy
#  Rollback:                   make rollback
# =============================================================================

SHELL       := /bin/bash
.DEFAULT_GOAL := help

# ── Config ────────────────────────────────────────────────────────────────────
COMPOSE_DEV    := docker compose -f docker-compose.yml
COMPOSE_PROD   := docker compose -f docker-compose.prod.yml
COMPOSE_TUNNEL := docker compose -f docker-compose.prod.yml -f docker-compose.tunnel.yml
TF_DIR         := infra/terraform
RELEASE_TAG    ?= $(shell date +%Y%m%d_%H%M%S)
DOMAIN         ?= salesplatform.reventlabs.com
TUNNEL_NAME    ?= sales-platform
SERVER         ?= root@YOUR_SERVER_IP
BRANCH         ?= main

# ── Colors ────────────────────────────────────────────────────────────────────
_B := \033[1m
_G := \033[0;32m
_Y := \033[1;33m
_R := \033[0;31m
_N := \033[0m

# ==============================================================================
#  DEVELOPMENT
# ==============================================================================

.PHONY: dev
dev: ## Start local development stack
	@echo -e "$(_G)Starting dev stack...$(_N)"
	$(COMPOSE_DEV) up -d --build
	@echo -e "$(_G)Dev stack running: http://localhost:3000$(_N)"

.PHONY: dev-down
dev-down: ## Stop local development stack
	$(COMPOSE_DEV) down

.PHONY: dev-logs
dev-logs: ## Tail all dev container logs
	$(COMPOSE_DEV) logs -f --tail=50

.PHONY: migrate
migrate: ## Run database migrations
	$(COMPOSE_DEV) exec backend alembic upgrade head

.PHONY: seed
seed: ## Seed admin user + remote companies
	$(COMPOSE_DEV) exec backend python -m app.seed_admin
	$(COMPOSE_DEV) exec backend python -m app.seed_remote_companies

.PHONY: test
test: ## Run backend tests
	$(COMPOSE_DEV) exec backend python -m pytest tests/ -v

.PHONY: shell
shell: ## Open Python shell in backend container
	$(COMPOSE_DEV) exec backend python

# ==============================================================================
#  PRODUCTION — BUILD & DEPLOY
# ==============================================================================

.PHONY: build
build: ## Build production images locally
	@echo -e "$(_B)Building backend image...$(_N)"
	docker build -t platform-backend:$(RELEASE_TAG) ./backend
	docker tag platform-backend:$(RELEASE_TAG) platform-backend:latest
	@echo -e "$(_B)Building frontend image...$(_N)"
	docker build -t platform-frontend:$(RELEASE_TAG) ./frontend
	docker tag platform-frontend:$(RELEASE_TAG) platform-frontend:latest
	@echo -e "$(_G)Images built: platform-backend:$(RELEASE_TAG) platform-frontend:$(RELEASE_TAG)$(_N)"

.PHONY: deploy
deploy: confirm-deploy backup-pre build ## Full deploy: backup → build → migrate → restart → health check
	@echo -e "$(_B)━━━ Deploying $(RELEASE_TAG) ━━━$(_N)"
	@# Migrate
	@echo -e "$(_Y)Running migrations...$(_N)"
	RELEASE_TAG=$(RELEASE_TAG) $(COMPOSE_PROD) run --rm backend alembic upgrade head
	@# Rolling restart
	@echo -e "$(_Y)Restarting services...$(_N)"
	RELEASE_TAG=$(RELEASE_TAG) $(COMPOSE_PROD) up -d --no-deps backend
	@sleep 5
	RELEASE_TAG=$(RELEASE_TAG) $(COMPOSE_PROD) up -d --no-deps celery-worker celery-beat
	RELEASE_TAG=$(RELEASE_TAG) $(COMPOSE_PROD) up -d --no-deps frontend nginx
	@# Health check
	@echo -e "$(_Y)Waiting for health...$(_N)"
	@bash infra/scripts/health-check.sh
	@# Record release
	@echo '{"release":"$(RELEASE_TAG)","deployed_at":"$(shell date -u +%Y-%m-%dT%H:%M:%SZ)","branch":"$(BRANCH)"}' > .last-deploy.json
	@echo -e "$(_G)✅ Deploy $(RELEASE_TAG) complete$(_N)"

.PHONY: deploy-quick
deploy-quick: build ## Quick deploy without backup (use for hotfixes)
	@echo -e "$(_Y)Quick deploying (no backup)...$(_N)"
	RELEASE_TAG=$(RELEASE_TAG) $(COMPOSE_PROD) up -d
	@bash infra/scripts/health-check.sh
	@echo -e "$(_G)✅ Quick deploy complete$(_N)"

# ==============================================================================
#  ROLLBACK
# ==============================================================================

.PHONY: rollback
rollback: ## Rollback to previous release (code only)
	@bash infra/scripts/rollback.sh

.PHONY: rollback-full
rollback-full: ## Rollback to previous release + restore database
	@bash infra/scripts/rollback.sh --with-db

# ==============================================================================
#  BACKUP & RESTORE
# ==============================================================================

.PHONY: backup
backup: ## Take a database backup now
	@bash infra/scripts/backup.sh

.PHONY: backup-pre
backup-pre: ## Pre-deploy backup (called automatically by deploy)
	@echo -e "$(_Y)Pre-deploy backup...$(_N)"
	@bash infra/scripts/backup.sh --label pre-deploy-$(RELEASE_TAG)

.PHONY: restore
restore: ## Restore from backup (interactive — lists available backups)
	@bash infra/scripts/restore.sh

.PHONY: backup-validate
backup-validate: ## Validate latest backup integrity
	@bash infra/scripts/validate-backup.sh

.PHONY: backup-list
backup-list: ## List all available backups
	@bash infra/scripts/backup.sh --list

# ==============================================================================
#  ORACLE CLOUD INFRASTRUCTURE (Terraform)
# ==============================================================================

.PHONY: infra-setup
infra-setup: ## Interactive guide: create OCI + Cloudflare accounts, generate tfvars
	@bash infra/scripts/oci-setup-guide.sh

.PHONY: infra-init
infra-init: ## Initialize Terraform (download providers)
	@echo -e "$(_G)Initializing Terraform...$(_N)"
	@cd $(TF_DIR) && terraform init

.PHONY: infra-plan
infra-plan: ## Preview infrastructure changes
	@cd $(TF_DIR) && terraform plan

.PHONY: infra-up
infra-up: ## Create OCI VM + Cloudflare Tunnel + DNS + monitoring (one command)
	@echo -e "$(_B)Creating Oracle Cloud + Cloudflare infrastructure...$(_N)"
	@echo -e "$(_Y)This creates: ARM VM (4CPU/24GB), Cloudflare Tunnel, DNS, monitoring alerts$(_N)"
	@read -p "Continue? [y/N] " confirm; \
	if [ "$$confirm" != "y" ] && [ "$$confirm" != "Y" ]; then exit 1; fi
	@cd $(TF_DIR) && terraform apply
	@echo -e "\n$(_G)Infrastructure created! Cloud-init is bootstrapping the VM (~5-8 min)$(_N)"
	@echo -e "  Check progress: $(_B)make infra-ssh$(_N) then $(_B)sudo tail -f /var/log/cloud-init-output.log$(_N)"

.PHONY: infra-ssh
infra-ssh: ## SSH into the Oracle Cloud VM
	@cd $(TF_DIR) && ssh -i $$(terraform output -raw ssh_private_key_path 2>/dev/null || echo ~/.ssh/id_rsa) \
		ubuntu@$$(terraform output -raw instance_public_ip)

.PHONY: infra-status
infra-status: ## Show infrastructure: VM IP, tunnel, app URL
	@echo -e "$(_B)Infrastructure Status:$(_N)"
	@cd $(TF_DIR) && terraform output 2>/dev/null || echo "  (not provisioned — run: make infra-setup)"

.PHONY: infra-destroy
infra-destroy: ## DESTROY Oracle Cloud VM and all resources
	@echo -e "$(_R)This will DESTROY the VM, tunnel, DNS, and all data!$(_N)"
	@read -p "Type 'yes, destroy' to continue: " confirm; \
	if [ "$$confirm" = "yes, destroy" ]; then \
		cd $(TF_DIR) && terraform destroy; \
	else echo "Aborted."; fi

# ==============================================================================
#  DATA MIGRATION  (local dev → cloud VM, run once after first deploy)
# ==============================================================================

.PHONY: migrate-data
migrate-data: ## Push local database to cloud VM (one-time, after first infra-up)
	@echo -e "$(_B)Migrating local data → cloud VM...$(_N)"
	@bash infra/scripts/migrate-data.sh $(if $(VM_IP),--vm-ip $(VM_IP),) $(if $(SSH_KEY),--ssh-key $(SSH_KEY),)

# ==============================================================================
#  SERVER PROVISIONING (manual — use infra-* targets instead)
# ==============================================================================

.PHONY: provision
provision: ## Provision a fresh server (run once)
	@echo -e "$(_B)Provisioning server $(SERVER)...$(_N)"
	@bash infra/scripts/provision.sh $(SERVER)

.PHONY: ssl-init
ssl-init: ## Obtain initial SSL certificate
	@echo -e "$(_Y)Obtaining SSL cert for $(DOMAIN)...$(_N)"
	@sed -i.bak 's/YOUR_DOMAIN/$(DOMAIN)/g' infra/nginx/conf.d/app.conf
	$(COMPOSE_PROD) run --rm certbot certonly \
		--webroot --webroot-path=/usr/share/nginx/html \
		--email admin@$(DOMAIN) --agree-tos --no-eff-email \
		-d $(DOMAIN)
	$(COMPOSE_PROD) restart nginx
	@echo -e "$(_G)SSL certificate obtained for $(DOMAIN)$(_N)"

.PHONY: ssl-renew
ssl-renew: ## Renew SSL certificate
	$(COMPOSE_PROD) run --rm certbot renew
	$(COMPOSE_PROD) restart nginx

# ==============================================================================
#  CLOUDFLARE TUNNEL
# ==============================================================================

.PHONY: tunnel-login
tunnel-login: ## Authenticate with Cloudflare (first time)
	@bash infra/scripts/tunnel.sh login

.PHONY: tunnel-create
tunnel-create: ## Create tunnel + DNS route (first time)
	@bash infra/scripts/tunnel.sh create $(TUNNEL_NAME) $(DOMAIN)

.PHONY: tunnel-up
tunnel-up: ## Start platform with Cloudflare Tunnel (no public ports)
	@echo -e "$(_G)Starting with Cloudflare Tunnel...$(_N)"
	$(COMPOSE_TUNNEL) up -d
	@echo -e "$(_G)Tunnel running — accessible via https://$(DOMAIN)$(_N)"

.PHONY: tunnel-down
tunnel-down: ## Stop tunnel stack
	$(COMPOSE_TUNNEL) down

.PHONY: tunnel-deploy
tunnel-deploy: confirm-deploy backup-pre build ## Full deploy through Cloudflare Tunnel
	@echo -e "$(_B)━━━ Deploying $(RELEASE_TAG) via tunnel ━━━$(_N)"
	RELEASE_TAG=$(RELEASE_TAG) $(COMPOSE_TUNNEL) run --rm backend alembic upgrade head
	RELEASE_TAG=$(RELEASE_TAG) $(COMPOSE_TUNNEL) up -d --no-deps backend
	@sleep 5
	RELEASE_TAG=$(RELEASE_TAG) $(COMPOSE_TUNNEL) up -d --no-deps celery-worker celery-beat frontend nginx cloudflared
	@bash infra/scripts/health-check.sh
	@echo '{"release":"$(RELEASE_TAG)","deployed_at":"$(shell date -u +%Y-%m-%dT%H:%M:%SZ)","branch":"$(BRANCH)","mode":"tunnel"}' > .last-deploy.json
	@echo -e "$(_G)✅ Tunnel deploy $(RELEASE_TAG) complete$(_N)"

.PHONY: tunnel-status
tunnel-status: ## Show tunnel health and connection info
	@bash infra/scripts/tunnel.sh status

.PHONY: tunnel-logs
tunnel-logs: ## Tail cloudflared logs
	$(COMPOSE_TUNNEL) logs -f --tail=50 cloudflared

.PHONY: tunnel-list
tunnel-list: ## List all Cloudflare tunnels
	@bash infra/scripts/tunnel.sh list

.PHONY: tunnel-delete
tunnel-delete: ## Delete the tunnel
	@bash infra/scripts/tunnel.sh delete $(TUNNEL_NAME)

# ==============================================================================
#  MONITORING & LOGS
# ==============================================================================

.PHONY: status
status: ## Show platform health status
	@bash infra/scripts/status.sh

.PHONY: logs
logs: ## Tail production logs (all services)
	$(COMPOSE_PROD) logs -f --tail=50

.PHONY: logs-backend
logs-backend: ## Tail backend logs
	$(COMPOSE_PROD) logs -f --tail=100 backend

.PHONY: logs-worker
logs-worker: ## Tail celery worker logs
	$(COMPOSE_PROD) logs -f --tail=100 celery-worker

.PHONY: logs-nginx
logs-nginx: ## Tail nginx access/error logs
	$(COMPOSE_PROD) logs -f --tail=100 nginx

.PHONY: db-shell
db-shell: ## Open psql shell
	$(COMPOSE_PROD) exec postgres psql -U $${POSTGRES_USER:-postgres} -d $${POSTGRES_DB:-jobplatform}

.PHONY: db-stats
db-stats: ## Show database row counts
	@$(COMPOSE_PROD) exec postgres psql -U $${POSTGRES_USER:-postgres} -d $${POSTGRES_DB:-jobplatform} -c \
		"SELECT relname AS table, n_live_tup AS rows FROM pg_stat_user_tables WHERE n_live_tup > 0 ORDER BY n_live_tup DESC;"

# ==============================================================================
#  CLEANUP
# ==============================================================================

.PHONY: clean
clean: ## Remove stopped containers, dangling images, build cache
	docker system prune -f
	docker image prune -f

.PHONY: clean-all
clean-all: ## ⚠ Remove everything (containers, volumes, images)
	@echo -e "$(_R)This will delete ALL data including database volumes!$(_N)"
	@read -p "Type 'yes, destroy' to continue: " confirm; \
	if [ "$$confirm" = "yes, destroy" ]; then \
		$(COMPOSE_PROD) down -v --rmi all; \
		echo -e "$(_R)Everything removed.$(_N)"; \
	else echo "Aborted."; fi

# ==============================================================================
#  HELPERS
# ==============================================================================

.PHONY: confirm-deploy
confirm-deploy:
	@echo -e "$(_Y)Deploying release $(RELEASE_TAG) from branch $(BRANCH)$(_N)"
	@read -p "Continue? [y/N] " confirm; \
	if [ "$$confirm" != "y" ] && [ "$$confirm" != "Y" ]; then exit 1; fi

.PHONY: help
help: ## Show this help
	@echo -e "\n$(_B)Sales Data Platform — Operations$(_N)\n"
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "  $(_G)%-20s$(_N) %s\n", $$1, $$2}'
	@echo
