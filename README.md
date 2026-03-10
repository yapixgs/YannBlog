# 🚀 YannBlog — FastAPI + Docker

Stack : **FastAPI** · **Gunicorn/Uvicorn** · **PostgreSQL** · **Redis** · **Docker** · **Nginx**

---

## Architecture

```
YannBlog/
├── app/
│   ├── main.py                        # Point d'entrée FastAPI
│   ├── core/
│   │   ├── config.py                  # Config via pydantic-settings + .env
│   │   ├── logging.py                 # Logs structurés JSON
│   │   └── sessions.py                # Gestion des sessions
│   ├── api/
│   │   ├── router.py                  # Agrégation des routers
│   │   └── endpoints/
│   │       ├── auth.py                # Auth WebAuthn (YubiKey)
│   │       ├── posts.py               # CRUD articles
│   │       ├── comments.py            # Commentaires
│   │       ├── users.py               # Utilisateurs
│   │       └── metrics.py             # Prometheus /metrics
│   ├── models/
│   │   └── db.py                      # Modèles SQLAlchemy + PostgreSQL async
│   ├── services/
│   │   └── webauthn_service.py        # Service WebAuthn / FIDO2
│   └── static/
│       └── index.html                 # Frontend
├── k8s/
│   ├── deployment.yaml
│   └── service-hpa-pdb.yaml
├── nginx/
│   └── nginx.conf                     # Reverse proxy, rate limiting
├── Dockerfile                         # Multi-stage build
├── docker-compose.yml                 # Stack complète locale
├── requirements.txt
├── Makefile
└── blog.db                            # SQLite (dev local uniquement)
```

---

## Démarrage avec Docker (recommandé)

```bash
# Lancer toute la stack (app + postgres + redis + nginx)
docker compose build && docker compose up -d

# Voir les logs de l'app
docker compose logs -f app

# Arrêter proprement (données conservées)
docker compose down
```

> ⚠️ Ne pas utiliser `make up` — le Makefile utilise `--keepalive` qui est invalide.
> Utiliser `docker compose build && docker compose up -d` à la place.

L'app est accessible sur **http://localhost**

---

## Corrections appliquées

| Problème | Correction |
|----------|------------|
| `--keepalive 5` invalide dans Dockerfile | Remplacé par `--keep-alive 5` |
| `asyncpg` manquant dans requirements.txt | Ajouté `asyncpg==0.29.0` |
| `docker compose` plugin manquant | Installer via `sudo pacman -S docker-compose` |

---

## Développement local (sans Docker)

```bash
source .venv/bin/activate
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
# → http://localhost:8000/docs
```

---

## Variables d'environnement clés

| Variable | Défaut | Description |
|----------|--------|-------------|
| `ENVIRONMENT` | `production` | `development` \| `staging` \| `production` |
| `WORKERS` | `4` | Nombre de workers Gunicorn |
| `DATABASE_URL` | — | URL PostgreSQL async (`postgresql+asyncpg://...`) |
| `REDIS_URL` | — | URL Redis |
| `LOG_LEVEL` | `INFO` | `DEBUG` \| `INFO` \| `WARNING` |
| `SECRET_KEY` | — | Clé secrète JWT / sessions |

---

## SSH avec YubiKey (GPG Agent)

La clé SSH est gérée par `gpg-agent`. Configuration dans `~/.bashrc` / `~/.zshrc` :

```bash
export GPG_TTY=$(tty)
export SSH_AUTH_SOCK=$(gpgconf --list-dirs agent-ssh-socket)
```

Vérifier que la YubiKey est détectée :

```bash
ssh-add -L
```

---

## Kubernetes (production)

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
