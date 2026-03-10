.PHONY: help dev build up down logs test lint k8s-apply

IMAGE   ?= mywebapp
TAG     ?= latest
NS      ?= production

help:
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-20s\033[0m %s\n", $$1, $$2}'

# ── Local dev ─────────────────────────────────────────────
dev: ## Run app locally with hot-reload
	uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

# ── Docker ────────────────────────────────────────────────
build: ## Build Docker image
	docker build -t $(IMAGE):$(TAG) .

up: ## Start full stack with Docker Compose
	docker compose up --build -d

down: ## Stop Docker Compose stack
	docker compose down

logs: ## Tail logs
	docker compose logs -f app

# ── Tests ─────────────────────────────────────────────────
test: ## Run tests
	pytest tests/ -v --cov=app --cov-report=term-missing

lint: ## Lint and type-check
	ruff check app/ && mypy app/

# ── Kubernetes ────────────────────────────────────────────
k8s-apply: ## Apply all K8s manifests
	kubectl apply -f k8s/ -n $(NS)

k8s-status: ## Check deployment rollout
	kubectl rollout status deployment/webapp -n $(NS)

k8s-logs: ## Stream pod logs
	kubectl logs -l app=webapp -n $(NS) -f --max-log-requests=10

k8s-scale: ## Scale deployment (make k8s-scale REPLICAS=5)
	kubectl scale deployment/webapp --replicas=$(REPLICAS) -n $(NS)

push: build ## Build and push image to registry
	docker tag $(IMAGE):$(TAG) registry.example.com/$(IMAGE):$(TAG)
	docker push registry.example.com/$(IMAGE):$(TAG)
