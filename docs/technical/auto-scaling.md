# Auto-Scaling Foundation

Status: foundation policy for Dentora's current Docker Compose / Coolify deployment. This is intentionally not final capacity tuning.

## Architecture

Dentora keeps one Uvicorn process per API container and scales the `backend` service horizontally. The autoscaler runs on the Docker host, not inside the application container, so the API never receives Docker socket access and domain/AI code stays isolated from infrastructure control.

The control flow is:

1. `DockerComposeAdapter` discovers `backend` replicas and reads Docker CPU, memory, and health state.
2. The pure policy evaluator returns a desired replica count.
3. The controller calls `docker compose scale --no-deps backend=N` only when a decision crosses the configured safety gates.
4. Caddy resolves the `backend` service dynamically so newly created replica addresses enter request routing without a Caddy restart.
5. A Prometheus text exposition file is written as a monitoring hook. It can be scraped by any future node/textfile collector without coupling the controller to a monitoring vendor.

No Kubernetes, Redis, Celery, RQ, or new runtime service is introduced.

## Current policy

Source of truth: `infra/autoscaling/policy.json`.

- replicas: minimum `1`, maximum `4`
- scale out: average CPU >= `70%` **or** average memory >= `75%`
- scale out quorum: `2` consecutive evaluations
- scale out step: `+1`
- scale out cooldown: `60s`
- scale in: average CPU <= `35%` **and** average memory <= `50%`
- scale in quorum: `5` consecutive evaluations
- scale in step: `-1`
- scale in cooldown: `300s`
- scale in stabilization after the last scale-out: `300s`
- evaluation interval: `30s`
- queue scaling contract: present but disabled because the current deployment has no durable application queue or queue-depth metric

Production Compose defaults, independently configurable through environment variables:

- API CPU limit: `1.0` CPU
- API memory limit: `768m`
- API memory reservation: `256m`
- graceful stop period: `30s`

These values are conservative foundation defaults, not measured production capacity targets.

## Health and traffic safety

The existing `/health` endpoint is the process liveness probe and `/health/ready` is the database-backed readiness probe. Production/Coolify backend container health checks use readiness. Scale-in is blocked unless every observed replica is healthy. Caddy uses dynamic A/AAAA discovery for `backend`, round-robin balancing, retry, and passive failure memory.

## Running the controller

Validate first:

```bash
python -m unittest discover -s scripts/autoscaling/tests -v
python -c "from scripts.autoscaling.config import load_policy; print(load_policy('infra/autoscaling/policy.json'))"
docker compose -f docker-compose.prod.yml config >/dev/null
```

Dry run one evaluation:

```bash
python -m scripts.autoscaling.controller \
  --policy infra/autoscaling/policy.json \
  --compose-file docker-compose.prod.yml \
  --env-file .env \
  --dry-run --once
```

Run continuously on the Docker host:

```bash
python -m scripts.autoscaling.controller \
  --policy infra/autoscaling/policy.json \
  --compose-file docker-compose.prod.yml \
  --env-file .env
```

`infra/autoscaling/dentora-autoscaler.service.example` is a host-level systemd example. Install it only after adjusting `WorkingDirectory` to the deployment path.

## Queue/worker scaling

The current baseline has scheduled/in-process application work but no Celery/RQ/Redis-style durable queue with a measurable backlog. Adding a queue solely to claim queue autoscaling would change architecture unnecessarily.

The domain policy already accepts `queue_depth` and validates queue thresholds. When a future heavy-task worker/queue is introduced, add a `MetricsSource` adapter that populates queue depth and a replica manager for that worker service. Existing policy and API scaling do not need to be redesigned.

## Validation and load smoke

CI validates:

- autoscaling unit tests and policy semantics
- production and Coolify Compose rendering
- Caddy configuration syntax using the official Caddy image
- existing full backend/frontend/docs/catalog/E2E gates
- a bounded HTTP concurrency probe against the real CI backend

The load probe is a regression/stress smoke only. It does not establish production RPS or final thresholds.

## Operational limitations

This foundation scales replicas on one Docker host. It improves concurrency and provides replica-level fault handling, but it does not provide host-level high availability. A host failure still affects all local replicas. Multi-host HA can later use Coolify horizontal scaling / Docker Swarm or another orchestrator when justified.

The production `storage_data` volume is shared by replicas on the same host. Future multi-host scaling requires shared/object storage for any files that must be visible to every API instance.

The controller deliberately has no queue adapter until Dentora has a real queue source of truth. Keep `queue.enabled=false` until such an adapter is wired.

## Production tuning later

After representative production telemetry exists, tune only configuration: CPU/memory limits, min/max replicas, high/low thresholds, breach counts, cooldowns, stabilization, and queue thresholds if a queue is added. The architecture and policy engine should not require a feature rewrite.
