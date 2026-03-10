# 🚀 Python Web App — Production Template

Stack production-grade : **FastAPI** · **Gunicorn/Uvicorn** · **PostgreSQL** · **Redis** · **Docker** · **Kubernetes**

---

## Architecture

```
webapp/
├── app/
│   ├── main.py               # Point d'entrée FastAPI (lifespan, middlewares, routes)
│   ├── core/
│   │   ├── config.py         # Config centralisée via pydantic-settings + .env
│   │   └── logging.py        # Logs structurés JSON (Datadog / Loki / ELK)
│   └── api/
│       ├── router.py         # Agrégation des routers
│       └── endpoints/
│           ├── users.py      # Exemple d'endpoint CRUD
│           ├── items.py
│           └── metrics.py    # Endpoint Prometheus /metrics
├── k8s/
│   ├── deployment.yaml       # Deployment + probes + security context
│   └── service-hpa-pdb.yaml  # Service, HPA, PDB, ConfigMap, Ingress
├── nginx/
│   └── nginx.conf            # Reverse proxy, rate limiting, logs JSON
├── Dockerfile                # Multi-stage build (builder + runtime minimal)
├── docker-compose.yml        # Stack locale : app + postgres + redis + nginx
├── requirements.txt
├── Makefile                  # Commandes dev/deploy
└── .env.example
```

---

## Démarrage rapide

### Local (dev)
```bash
cp .env.example .env
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
make dev
# → http://localhost:8000/docs
```

### Docker Compose (staging / démo)
```bash
make up
# → http://localhost/api/v1/users
make logs
make down
```

### Kubernetes (production)
```bash
# 1. Construire et pousser l'image
make push TAG=1.0.0

# 2. Créer le namespace et les secrets
kubectl create namespace production
kubectl create secret generic webapp-secrets \
  --from-literal=SECRET_KEY=your-secret \
  --from-literal=DATABASE_URL=postgresql+asyncpg://... \
  -n production

# 3. Déployer
make k8s-apply
make k8s-status
```

---

## Points clés de stabilité

| Couche | Mécanisme |
|--------|-----------|
| **Zero-downtime deploys** | `RollingUpdate` + `maxUnavailable: 0` |
| **Auto-scaling** | HPA CPU 70% / Mémoire 80% → 3–20 pods |
| **Résilience** | PodDisruptionBudget `minAvailable: 2` |
| **Health checks** | `/healthz` (liveness) + `/readyz` (readiness) |
| **Sécurité** | Non-root, `readOnlyRootFilesystem`, `drop ALL` capabilities |
| **Observabilité** | Logs JSON + Prometheus `/metrics` |
| **Rate limiting** | Nginx (30 req/s) + Kubernetes Ingress |
| **Workers** | Gunicorn multi-process + Uvicorn async workers |

---

## Ajouter un endpoint

```python
# app/api/endpoints/products.py
from fastapi import APIRouter
router = APIRouter()

@router.get("/")
async def list_products():
    return [{"id": 1, "name": "Widget"}]
```

```python
# app/api/router.py  — ajouter :
from app.api.endpoints import products
api_router.include_router(products.router, prefix="/products", tags=["products"])
```

---

## Variables d'environnement clés

| Variable | Défaut | Description |
|----------|--------|-------------|
| `ENVIRONMENT` | `production` | `development` \| `staging` \| `production` |
| `WORKERS` | `4` | Nombre de workers Gunicorn |
| `DATABASE_URL` | — | URL PostgreSQL async |
| `REDIS_URL` | — | URL Redis |
| `LOG_LEVEL` | `INFO` | `DEBUG` \| `INFO` \| `WARNING` |
| `SECRET_KEY` | — | Clé secrète JWT / sessions |
