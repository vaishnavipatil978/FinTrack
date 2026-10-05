# FinTrack — Deployment (Stage 15)

> **Status of this document**: this is the deployment design and runbook.
> It has **not** been executed against a real AWS account from this
> environment — there is no cloud access here. Every command below has
> been run successfully in its *local* form (Docker Compose, on the same
> image this document deploys); the AWS-specific wiring (Terraform/CDK,
> IAM, networking) is written to the same design `docs/architecture/
> system-architecture.md` §5 already committed to, but is unverified.
> Do not read this document as evidence of a tested production
> deployment — see `docs/production-readiness.md` for the honest status.

## 1. Target Architecture

```
Internet
   │
   ▼
Route 53 (DNS)
   │
   ▼
Application Load Balancer (HTTPS, ACM certificate)
   │
   ▼
ECS Fargate service: "api"  (N tasks, the Dockerfile in this repo)
   │
   ├──► RDS PostgreSQL 16 (single AZ for v1; Multi-AZ is a one-flag
   │     upgrade once real traffic justifies the cost - see NFR §2)
   ├──► ElastiCache for Redis (single node for v1)
   └──► ECS Fargate service: "worker" + "beat" (same image, different
         command - see docker-compose.yml for the exact commands)
```

Chosen over alternatives for the same reason the system architecture
doc gives for the modular monolith itself: this is the simplest shape
that satisfies the NFRs, not the most impressive one. A single ALB +
Fargate service avoids standing up EKS for three containers; RDS/
ElastiCache avoid self-managing Postgres/Redis HA. If load ever
justifies it, each piece (read replica, Multi-AZ, larger Fargate task
count) is a configuration change, not a redesign.

## 2. Images

One image (this repo's `Dockerfile`) runs three roles via `command:`,
exactly as `docker-compose.yml` already demonstrates locally:

| Role | Command |
|---|---|
| `api` | `uvicorn app.main:create_app --factory --host 0.0.0.0 --port 8000` (the Dockerfile's default `CMD`) |
| `worker` | `celery -A app.workers.celery_app worker --loglevel=INFO` |
| `beat` | `celery -A app.workers.celery_app beat --loglevel=INFO --schedule=/tmp/celerybeat-schedule` |

Build and push:

```bash
docker build -t <ecr-repo-url>:<git-sha> .
docker push <ecr-repo-url>:<git-sha>
```

The `docker-build` job in `.github/workflows/ci.yml` builds this image
on every push to `main`; a follow-up deploy job (not yet added) would
push it to ECR and update the ECS task definitions. That push/deploy
step is the part of this document that is genuinely untested — the
build itself is exercised by CI.

## 3. Environment Variables

Every variable in `.env.example` is required; production values come
from AWS Secrets Manager (not plaintext task-definition environment
variables), injected via ECS's `secrets:` block pointing at Secrets
Manager ARNs. Minimum set for `api`/`worker`/`beat`:

| Variable | Source in production |
|---|---|
| `FINTRACK_ENVIRONMENT` | `production` (plain env var, not a secret) |
| `FINTRACK_DATABASE_URL` | Secrets Manager (includes the RDS-generated password) |
| `FINTRACK_REDIS_URL` | plain env var (ElastiCache has no app-level auth by default; restrict via security group instead) |
| `FINTRACK_JWT_SECRET_KEY` | Secrets Manager, ≥32 random bytes (`secrets.token_urlsafe(48)`) - enforced by `Settings._production_guards` |
| `FINTRACK_CORS_ORIGINS` | plain env var, the real frontend origin(s), never `*` (enforced by the same guard) |

`FINTRACK_LOG_LEVEL=INFO` in production; `DEBUG` is for local use only.

## 4. Networking

- VPC with public subnets (ALB only) and private subnets (ECS tasks,
  RDS, ElastiCache) - no task or database has a public IP.
- Security groups: ALB → ECS tasks on 8000; ECS tasks → RDS on 5432;
  ECS tasks → ElastiCache on 6379. No other ingress.
- The `worker`/`beat` tasks have no inbound rule at all - they only
  make outbound connections to RDS/Redis.

## 5. Migrations

Run once per deploy, **before** the new `api` tasks start serving
traffic, as a one-off ECS task (not baked into the image's `CMD`, and
not run by every replica on boot - see `docs/architecture/background-
jobs.md` for why auto-migrating on boot is deliberately avoided):

```bash
aws ecs run-task --cluster fintrack --task-definition fintrack-migrate \
  --overrides '{"containerOverrides":[{"name":"migrate","command":["alembic","upgrade","head"]}]}'
```

Locally, the equivalent (and the form actually exercised in this
repo's history) is:

```bash
docker compose run --rm api alembic upgrade head
```

## 6. Rollback

- **Application**: ECS supports rolling back to the previous task
  definition revision (`aws ecs update-service --task-definition
  fintrack-api:<previous-revision>`). Because migrations run as a
  separate step, rolling the app back does not touch the schema.
- **Schema**: every migration in `alembic/versions/` has a working
  `downgrade()` (verified repeatedly during Stages 2, 3, and 5-8 by
  running the full `upgrade → downgrade → upgrade` cycle against a
  real Postgres - see each stage's notes). `alembic downgrade -1`
  reverses the most recent migration if a rollback genuinely needs to
  touch schema, which should be rare given the additive migration style
  used throughout this project.

## 7. Logging & Monitoring

- Structured JSON logs (via `structlog`, already configured) go to
  stdout/stderr, which Fargate ships to CloudWatch Logs automatically -
  no extra agent needed.
- `GET /metrics` (Prometheus format, Stage 13) is scraped by a
  Prometheus instance or CloudWatch Container Insights' Prometheus
  integration; not exposed through the ALB's public listener - add a
  second, internal-only listener or scrape over the VPC directly.
- `GET /health` and `GET /ready` back the ECS task health check and the
  ALB target group health check respectively, per their documented
  distinction in `docs/architecture/observability.md` §3.

## 8. What Is Actually Verified vs. Documented

| Claim | Status |
|---|---|
| Image builds from this Dockerfile | **Verified** - built and run repeatedly throughout Stages 1-13 |
| `docker compose up` brings up api+worker+beat+db+redis together | **Verified** |
| Migrations apply cleanly, including full downgrade/upgrade cycles | **Verified** |
| Worker executes recurring/CSV tasks against the real stack | **Verified** (Stages 7-8) |
| CI workflow lints/type-checks/tests/builds the image | **Written, YAML-valid; not run on a real GitHub Actions runner from this environment** |
| ECS/RDS/ElastiCache/ALB topology above | **Designed, not provisioned** - no AWS account reachable here |
| A deploy has been performed and smoke-tested in AWS | **Not done** |

See `docs/production-readiness.md` for how this affects the overall
Definition-of-Done status.
