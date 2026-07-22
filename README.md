# Enterprise Support Desk Platform

A cloud-native support ticketing platform running on **Amazon EKS**, provisioned end-to-end with **Terraform** and deployed via **GitOps (Argo CD)**. The platform is split into independently deployable microservices (auth, ticketing, assignment, async worker, frontend) backed by RDS MySQL, SQS, SNS, and S3, with Prometheus/Grafana observability and CloudWatch integration baked in.

---

## Table of Contents

- [Architecture](#architecture)
- [Tech Stack](#tech-stack)
- [Repository Structure](#repository-structure)
- [Microservices](#microservices)
- [Infrastructure (Terraform)](#infrastructure-terraform)
- [CI/CD Pipelines](#cicd-pipelines)
- [GitOps Deployment (Argo CD)](#gitops-deployment-argo-cd)
- [Observability](#observability)
- [Security](#security)
- [Getting Started](#getting-started)
- [Local Development](#local-development)
- [Testing](#testing)
- [Environment Variables & Configuration](#environment-variables--configuration)
- [Teardown](#teardown)

---

## Architecture

```
                                   ┌─────────────────────────────────────────────┐
                                   │                   GitHub                      │
                                   │  ┌───────────────┐   ┌────────────────────┐  │
                                   │  │ infrastructure │   │ application CI/CD  │  │
                                   │  │   .yml (TF)    │   │  build/test/push   │  │
                                   │  └───────┬───────┘   └──────────┬─────────┘  │
                                   └──────────┼──────────────────────┼────────────┘
                                              │                      │
                                              ▼                      ▼
                                     ┌─────────────────┐   ┌────────────────────┐
                                     │ Terraform Apply  │   │   Amazon ECR        │
                                     │ (AWS resources)  │   │ (5 image repos)     │
                                     └────────┬─────────┘   └──────────┬─────────┘
                                              │                        │ image tag bump
                                              ▼                        ▼
┌──────────────────────────────────────────── VPC (10.0.0.0/16) ─────────────────────────────────────────────┐
│                                                                                                                │
│   ┌──────────────── Public Subnets (Multi-AZ) ────────────────┐                                              │
│   │        Internet Gateway  →  NAT Gateway(s)  →  ALB          │                                              │
│   └───────────────────────────────┬───────────────────────────┘                                              │
│                                    │                                                                          │
│   ┌────────────────────────────── Private Subnets (Multi-AZ) ─────────────────────────────────────────────┐  │
│   │                                                                                                          │  │
│   │   ┌───────────────────────────── EKS Cluster ─────────────────────────────┐                             │  │
│   │   │                                                                        │                             │  │
│   │   │   AWS Load Balancer     Argo CD          kube-prometheus-stack         │                             │  │
│   │   │   Controller             (GitOps)        (Prometheus + Grafana)        │                             │  │
│   │   │                                                                        │                             │  │
│   │   │   ┌──────────┐ ┌──────────┐ ┌───────────┐ ┌──────────┐ ┌───────────┐   │                             │  │
│   │   │   │  auth    │ │  ticket  │ │  assign   │ │ frontend │ │  worker   │   │                             │  │
│   │   │   │ :8001    │ │  :8002   │ │  :8003    │ │  :80     │ │ (SQS poll)│   │                             │  │
│   │   │   │ (HPA)    │ │  (HPA)   │ │  (HPA)    │ │          │ │           │   │                             │  │
│   │   │   └────┬─────┘ └────┬─────┘ └─────┬─────┘ └──────────┘ └─────┬─────┘   │                             │  │
│   │   │        └────────────┴─────────────┴─────────────────────────┘         │                             │  │
│   │   │                              IRSA-scoped ServiceAccounts               │                             │  │
│   │   └────────────────────────────────┬───────────────────────────────────────┘                             │  │
│   │                                     │                                                                    │  │
│   │                    ┌────────────────┼─────────────────┬────────────────┐                                │  │
│   │                    ▼                ▼                 ▼                ▼                                │  │
│   │             ┌────────────┐  ┌──────────────┐  ┌──────────────┐ ┌──────────────┐                         │  │
│   │             │ RDS MySQL  │  │ SQS (+ DLQ)  │  │  S3 (assets) │ │ SSM + Secrets │                         │  │
│   │             │  Multi-AZ* │  │  event queue │  │              │ │   Manager     │                         │  │
│   │             └────────────┘  └──────┬───────┘  └──────────────┘ └──────────────┘                         │  │
│   │                                     │                                                                    │  │
│   │                                     ▼                                                                    │  │
│   │                              ┌──────────────┐                                                            │  │
│   │                              │  SNS Topic    │──▶ Email alerts / notifications                           │  │
│   │                              └──────────────┘                                                            │  │
│   └──────────────────────────────────────────────────────────────────────────────────────────────────────┘  │
└────────────────────────────────────────────────────────────────────────────────────────────────────────────┘

CloudWatch: node ASG, RDS, and SQS DLQ metrics/alarms → SNS  (* Multi-AZ toggled via `db_multi_az`)
```

**Request flow:** Client → ALB (via AWS Load Balancer Controller) → path-based routing to `frontend`, `/auth`, `/tickets`, `/assign` services inside EKS → services read/write RDS MySQL and publish events to SQS → `worker` pod consumes SQS, writes to RDS and/or publishes to SNS for email notifications.

**Deployment flow:** Application CI builds/tests each service, pushes images to ECR, bumps image tags in `charts/enterprise-support/values.yaml`, commits back to `main` → Argo CD detects the Git change and syncs the Helm release into the cluster (GitOps pull model — the CI pipeline never talks to the cluster directly for app releases).

---

## Tech Stack

| Layer            | Technology |
|-------------------|------------|
| Compute            | Amazon EKS (managed node group, autoscaling) |
| Networking         | Custom VPC, public/private subnets, NAT Gateway(s), ALB (AWS Load Balancer Controller) |
| Database           | Amazon RDS for MySQL (optional Multi-AZ) |
| Messaging          | Amazon SQS (+ Dead Letter Queue), Amazon SNS |
| Storage            | Amazon S3 (ticket attachments / assets) |
| Secrets/Config     | AWS Secrets Manager, AWS SSM Parameter Store |
| Identity           | IAM Roles for Service Accounts (IRSA) — least-privilege, no static AWS keys in pods |
| Container Registry | Amazon ECR |
| IaC                | Terraform (modular, S3 backend with native locking) |
| App Deployment     | Helm chart + Argo CD (GitOps) |
| CI/CD              | GitHub Actions |
| Observability      | Prometheus, Grafana (kube-prometheus-stack), CloudWatch Agent, CloudWatch Alarms |
| Security Scanning  | Trivy (IaC config scan + container image scan) |
| Backend Services   | Python 3.11, FastAPI, `mysql-connector-python`, `boto3` |
| Frontend           | Vite-based static SPA served via Nginx |

---

## Repository Structure

```
support-desk-platform/
├── main.tf, variables.tf, outputs.tf, provider.tf, backend.tf   # Root Terraform config
├── terraform.tfvars                                             # Non-sensitive default values
├── modules/                                                     # Reusable Terraform modules
│   ├── vpc/            # VPC, subnets, NAT, IGW, security groups
│   ├── iam/             # EKS cluster/node IAM roles
│   ├── iam-irsa/        # Pod-level IRSA roles (app, CloudWatch agent)
│   ├── eks/             # EKS cluster + managed node group
│   ├── alb-controller/  # IRSA role for AWS Load Balancer Controller
│   ├── rds/              # RDS MySQL instance
│   ├── ecr/              # ECR repositories per service
│   ├── s3/                # Assets bucket
│   ├── sqs/               # Event queue + DLQ
│   ├── sns/               # Alert/notification topic
│   ├── secrets/           # Secrets Manager entries
│   ├── ssm/                # SSM Parameter Store (app config)
│   └── cloudwatch/         # Alarms for ASG, RDS, DLQ → SNS
├── app/
│   ├── auth/            # Auth service (FastAPI) — signup/signin, JWT
│   ├── ticket/           # Ticket service (FastAPI) — CRUD, CSV import, S3 uploads
│   ├── assignment/       # Assignment service (FastAPI) — ticket-to-agent assignment
│   ├── worker/            # SQS consumer — emails, notifications, bulk imports
│   ├── frontend/           # Vite SPA + Nginx
│   └── database/           # schema.sql
├── charts/enterprise-support/   # Helm chart deployed by Argo CD
│   ├── Chart.yaml, values.yaml
│   └── templates/          # Deployments, Ingress, ServiceMonitors, DaemonSet, base resources
├── argocd/
│   ├── project.yaml         # Argo CD AppProject
│   └── application.yaml     # Argo CD Application (points at charts/enterprise-support)
├── observability/
│   └── grafana-dashboard-support-desk.yaml   # Custom Grafana dashboard ConfigMap
├── tests/
│   ├── integration/         # Cross-service integration tests (real MySQL)
│   └── smoke/                # Post-deploy smoke test against the live ALB
└── .github/workflows/
    ├── infrastructure.yml    # Terraform plan/apply + Trivy IaC scan + platform bootstrap
    └── application.yml       # Unit/integration tests, build & push, GitOps handoff, smoke test
```

---

## Microservices

| Service      | Port | Path        | Responsibility |
|--------------|------|-------------|-----------------|
| `auth`         | 8001 | `/auth`     | Signup/signin, password hashing (bcrypt), JWT issuance |
| `ticket`        | 8002 | `/tickets`  | Ticket CRUD, CSV bulk import, attachment upload to S3, publishes events to SQS |
| `assignment`     | 8003 | `/assign`   | Assigns tickets to agents, publishes `ticket_assigned` events to SQS |
| `worker`          | —    | —           | Long-running SQS consumer; handles `ticket_assigned`, `new_ticket_created`, and `bulk_ticket_import` events; sends email via SNS; writes to RDS |
| `frontend`         | 80   | `/`         | Static SPA (Vite build) served by Nginx |

All FastAPI services expose Prometheus metrics at `/metrics` (via `prometheus-fastapi-instrumentator`), scraped through a `ServiceMonitor` defined in the Helm chart. Runtime configuration (DB host, queue URLs, topic ARNs, etc.) is loaded from **SSM Parameter Store** at startup, and the DB password is pulled from **Secrets Manager** — no secrets are baked into images or Helm values.

---

## Infrastructure (Terraform)

Terraform state is stored remotely:

```hcl
backend "s3" {
  bucket       = "<your-tfstate-bucket>"
  key          = "enterprise-support/prod/terraform.tfstate"
  region       = "us-east-1"
  use_lockfile = true   # S3-native state locking (Terraform >= 1.10)
}
```

Root module composition (`main.tf`) wires together 13 modules in dependency order: `vpc` → `iam` → `eks` → `rds` → `alb-controller` / `iam-irsa` → `ssm` → `cloudwatch`, alongside standalone `ecr`, `s3`, `sqs`, `sns`, and `secrets` modules.

Key configurable variables (`variables.tf`):

| Variable | Default | Notes |
|---|---|---|
| `project_name` | `enterprise-support` | Prefix for every resource name |
| `environment` | `prod` | |
| `vpc_cidr` | `10.0.0.0/16` | |
| `availability_zones` | `["us-east-1a", "us-east-1b"]` | |
| `nat_gateway_count` | `1` | Set to `2` for one NAT per AZ (higher resilience, higher cost) |
| `db_multi_az` | `false` | Set to `true` for an RDS standby in a second AZ |
| `assets_bucket_suffix` | — | **Required**, no default — must be globally unique |
| `alert_email` | — | **Required**, list of emails for SNS/CloudWatch alerts |

Apply the infrastructure:

```bash
terraform init
terraform plan
terraform apply
```

---

## CI/CD Pipelines

Two independent GitHub Actions workflows, triggered by path filters so infra and app changes never cross-trigger each other.

### `infrastructure.yml` — Terraform + platform bootstrap
- **Trivy IaC scan** on every push/PR (Terraform + Helm configs, non-blocking, surfaces CRITICAL/HIGH findings)
- **PR**: `terraform fmt`, `init`, `validate`, `plan` — plan output posted as a PR comment
- **Push to `main`** (or manual `apply` dispatch): `terraform apply`, then bootstraps the cluster:
  - AWS Load Balancer Controller (Helm)
  - `kube-prometheus-stack` (Prometheus + Grafana)
  - Custom Grafana dashboard
  - Argo CD, plus the `AppProject` and `Application` manifests

### `application.yml` — build, test, release
1. **`unit-test`** — matrix across `auth` / `ticket` / `assignment`, `pytest` per service
2. **`integration-test`** — spins up a real MySQL 8.0 service container, loads `schema.sql`, runs cross-service integration tests
3. **`build-push`** — Docker Buildx build for all 5 services (auth, ticket, assignment, frontend, worker), pushed to ECR tagged `latest` + `<git-sha>`, with layer caching and a per-image **Trivy vulnerability scan**
4. **`update-gitops-manifest`** — bumps image tags in `charts/enterprise-support/values.yaml` via `yq` and commits back to `main` with `[skip ci]` (this is the GitOps handoff — Argo CD picks it up from here)
5. **`smoke-test`** — waits for rollouts, resolves the ALB hostname from the Ingress status, runs `tests/smoke/smoke_test.py` against the live endpoint, and publishes success/failure notifications to SNS

---

## GitOps Deployment (Argo CD)

The CI pipeline **never runs `kubectl apply` or `helm upgrade` against the app**. It only commits an updated `values.yaml`. Argo CD (`argocd/application.yaml`, scoped by `argocd/project.yaml`) watches the `charts/enterprise-support` path on `main` and reconciles the cluster to match Git — Git is the single source of truth for what's running.

---

## Observability

- **Metrics**: every FastAPI service exposes `/metrics`; scraped via `ServiceMonitor` (`kube-prometheus-stack`, 15s interval)
- **Dashboards**: a custom Grafana dashboard (`observability/grafana-dashboard-support-desk.yaml`) is applied automatically during infra bootstrap
- **Infra alarms**: CloudWatch alarms on the EKS node ASG, RDS instance, and SQS DLQ depth — all wired to the SNS alerts topic
- **Node-level metrics**: CloudWatch Agent DaemonSet, IRSA-scoped

---

## Security

- **No long-lived AWS credentials in pods** — every ServiceAccount that needs AWS access uses IRSA (`iam-irsa` / `alb-controller` modules)
- **Secrets never touch Helm values or images** — DB password lives in Secrets Manager, app config in SSM, both fetched at pod startup
- **IaC and image scanning** — Trivy runs on every infra change (config scan) and every image build (vulnerability scan)
- **Private workloads** — EKS nodes and RDS sit in private subnets; only the ALB is internet-facing
- **RBAC-style network boundaries** — dedicated security groups per tier (ALB, EKS nodes, RDS)

> **Note:** `terraform.tfvars` in this repo should only ever contain non-sensitive defaults. Real values for `assets_bucket_suffix` and `alert_email` should be supplied via a local `*.auto.tfvars` (gitignored) or CI secrets — never committed.

---

## Getting Started

### Prerequisites
- Terraform >= 1.10
- AWS CLI v2, configured with credentials that can create VPC/EKS/RDS/IAM resources
- `kubectl`
- Helm 3
- Docker (for local image builds)

### 1. Provision infrastructure
```bash
terraform init
terraform apply
```

### 2. Configure kubectl
```bash
aws eks update-kubeconfig --region us-east-1 --name $(terraform output -raw eks_cluster_name)
```

### 3. Bootstrap the platform (normally done by `infrastructure.yml` on merge)
```bash
# AWS Load Balancer Controller, kube-prometheus-stack, and Argo CD — see
# .github/workflows/infrastructure.yml for the exact helm commands and values.
```

### 4. Ship application code
Push to `main` under `app/**` or `tests/**` — `application.yml` builds, tests, pushes images, and hands off to Argo CD automatically.

---

## Local Development

Each service can be run standalone against a local MySQL instance:

```bash
cd app/auth   # or ticket / assignment / worker
pip install -r requirements.txt -r requirements-dev.txt
uvicorn auth_service:app --reload --port 8001
```

Load the schema first:
```bash
mysql -u root -p < app/database/schema.sql
```

The frontend:
```bash
cd app/frontend
npm install
npm run dev
```

---

## Testing

| Suite | Location | Runs against |
|---|---|---|
| Unit tests | `app/<service>/tests/` | mocked dependencies, per-service |
| Integration tests | `tests/integration/` | real MySQL 8.0 container, all services as subprocesses |
| Smoke tests | `tests/smoke/` | live ALB endpoint, post-deployment |

Run unit tests locally:
```bash
cd app/auth
pytest tests/ -v
```

---

## Environment Variables & Configuration

Services do **not** read individual env vars for secrets/config — they call `load_config()` (`app/*/secrets.py`) at startup, which pulls structured config from **SSM Parameter Store** (`/<project_name>/<environment>/config`) and the DB password from **Secrets Manager**. Relevant SSM keys populated by the `ssm` Terraform module include:

- `eks_cluster_name`, `rds_endpoint`, `rds_db_name`, `rds_db_user`, `rds_secret_arn`
- `assets_bucket`, `orders_queue_url`, `sns_topic_arn`, `aws_region`
- ECR repository URLs per service

---

## Teardown

```bash
kubectl delete -f argocd/application.yaml -f argocd/project.yaml
terraform destroy
```

> Empty the S3 assets bucket first if `force_destroy` is not enabled on the `s3` module, or `terraform destroy` will fail.
