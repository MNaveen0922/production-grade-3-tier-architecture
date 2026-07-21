# Support Desk — Production-Grade 3-Tier Platform on AWS

An IT helpdesk ticketing application, fully containerized and deployed to
production on AWS EKS via Terraform, Helm, Argo CD, and GitHub Actions.
Built as a 3-tier reference architecture: React frontend, FastAPI
microservice backend, MySQL database, async messaging and notifications,
GitOps delivery, and a full observability stack.

This is a different sample application from the reference project it was
modeled on, but follows the same repository layout, Terraform module
structure, and CI/CD pattern.

## Architecture

```
Internet
   │
   ▼
 ALB (public, created by AWS Load Balancer Controller from an Ingress
      rendered by charts/enterprise-support/templates/ingress.yaml)
   │
   ├── /auth      → auth-service      (FastAPI, :8001)
   ├── /tickets   → ticket-service    (FastAPI, :8002)
   ├── /assign    → assign-service    (FastAPI, :8003)
   └── /          → frontend-service  (React + Nginx, :80)

 EKS (private subnets)
   ├── auth/ticket/assign/frontend  (Deployments + HPA + Prometheus ServiceMonitors)
   ├── worker  (long-running SQS consumer, no HTTP port)
   ├── aws-load-balancer-controller (kube-system)
   ├── kube-prometheus-stack — Prometheus + Grafana + Alertmanager (monitoring ns)
   ├── Argo CD (argocd ns) — watches charts/enterprise-support/ in git, auto-syncs
   └── CloudWatch agent + Fluent Bit (amazon-cloudwatch ns)

 RDS MySQL (private subnets, SG allows only EKS nodes on :3306)
 SQS  (main queue + DLQ) — ticket-service/assign-service publish events
 SNS  (alerts topic, email subscription) — worker publishes ticket notifications, CI/CD publishes deploy status
 S3   (assets bucket) — private, encrypted, versioned
 SSM Parameter Store — non-secret runtime config (DB endpoint, queue URL, topic ARN, bucket name, ECR URLs)
 Secrets Manager — RDS master password (AWS-managed) + generated JWT signing key
 CloudWatch — log groups per service, dashboard, alarms (EKS node CPU, RDS CPU/storage, SQS DLQ depth) → SNS
```

## How a deploy actually happens (GitOps)

```
push to main (app/**)
   │
   ▼
unit-test (mocked DB, matrix: auth/ticket/assignment)
   │
   ▼
integration-test (real MySQL service container + real FastAPI processes)
   │
   ▼
build-push (5 images → ECR) + Trivy image scan
   │
   ▼
update-gitops-manifest — bumps image tag in charts/enterprise-support/values.yaml, commits
   │
   ▼
Argo CD notices the git diff and syncs the cluster automatically
   │
   ▼
smoke-test — waits for rollouts, then hits the live ALB's /health endpoints
```

CI/CD **never runs `kubectl apply` or `helm upgrade` against the app itself**.
Its only deploy-side action is committing an image-tag bump to git — Argo CD
(installed once by `infrastructure.yml`) does the actual reconciliation. This
means the cluster's state is always fully described by what's in git, drift
gets self-healed automatically, and `git revert` is a valid rollback.

## Why this domain

The reference project this was built from managed a digital library
(auth / book / borrow / worker / frontend). This project keeps the same
3-tier shape and the same AWS services, but implements a **support ticket
desk** instead:

| Reference concept | This project        |
|--------------------|---------------------|
| auth (signup/signin) | auth (signup/signin) |
| book (catalogue + CSV import) | ticket (catalogue + CSV import) |
| borrow (borrow a book) | assign (assign a ticket to an agent) |
| worker (SQS → email via SNS) | worker (SQS → email via SNS) |
| React frontend | React frontend |

## Repository layout

```
.
├── .github/workflows/
│   ├── ci-cd.yml            # unit test → integration test → build/push+Trivy → GitOps commit → smoke test
│   └── infrastructure.yml   # Trivy IaC scan → terraform plan (PR) / apply (push) →
│                            # install ALB Controller, kube-prometheus-stack, Argo CD
├── app/
│   ├── auth/                 # FastAPI — signup, signin (+ tests/, requirements-dev.txt)
│   ├── ticket/                # FastAPI — CRUD + CSV bulk import (+ tests/, requirements-dev.txt)
│   ├── assignment/             # FastAPI — assign ticket to agent (+ tests/, requirements-dev.txt)
│   ├── worker/                # long-running SQS consumer → SNS publisher
│   ├── frontend/              # React (Vite) + Nginx, proxies /auth /tickets /assign
│   └── database/schema.sql   # MySQL schema + seed data (apply manually against RDS)
├── charts/enterprise-support/       # Helm chart — replaces raw k8s/*.yaml manifests entirely
│   ├── Chart.yaml, values.yaml
│   └── templates/             # namespace, SA, configmap, api/frontend/worker deployments,
│                               # ingress, HPA, ServiceMonitors, CloudWatch daemonset
├── argocd/
│   ├── project.yaml           # AppProject — scopes repo/namespace access
│   └── application.yaml       # Application — auto-sync, self-heal, prune
├── observability/
│   └── grafana-dashboard-enterprise-support.yaml  # auto-discovered Grafana dashboard
├── tests/
│   ├── integration/           # real MySQL + real FastAPI processes, full ticket lifecycle
│   └── smoke/smoke_test.py    # post-deploy health checks against the live ALB
├── modules/                    # 13 reusable Terraform modules
│   ├── vpc/ iam/ ecr/ s3/ sqs/ sns/ secrets/ eks/ rds/
│   └── alb-controller/ iam-irsa/ ssm/ cloudwatch/
├── main.tf / variables.tf / outputs.tf / provider.tf / backend.tf
└── terraform.tfvars.example
```

No docker-compose, no shell scripts, and no GitHub OIDC — CI/CD authenticates
to AWS with long-lived access keys stored as GitHub Secrets, and all Docker
builds/pushes happen inside the `ci-cd.yml` pipeline itself.

## The test pyramid

| Layer | Where | What it checks | Real DB? | Real AWS? |
|---|---|---|---|---|
| Unit | `app/<service>/tests/` | Request/response logic, validation, business rules | No — mocked | No — mocked |
| Integration | `tests/integration/` | All 3 services + real MySQL agree end-to-end (signup → signin → create ticket → assign → list) | Yes — MySQL service container | No — SQS/SNS calls no-op when unset, exercising the exact "local dev" code path |
| Smoke | `tests/smoke/smoke_test.py` | The real deployed app is actually reachable and healthy post-deploy | Yes — production RDS | Yes — real ALB |

Run any layer locally:
```bash
# Unit (per service)
cd app/auth && pip install -r requirements.txt -r requirements-dev.txt && pytest tests/ -v

# Integration (needs a local MySQL 8 on 127.0.0.1:3306 with schema.sql applied)
pip install -r app/auth/requirements.txt -r app/ticket/requirements.txt \
              -r app/assignment/requirements.txt -r tests/integration/requirements.txt
pytest tests/integration/ -v

# Smoke (against any live URL)
python tests/smoke/smoke_test.py http://<alb-dns-name>
```

## AWS services used

VPC · EKS · RDS (MySQL) · SQS · SNS · S3 · IAM (+ IRSA) · ALB (via AWS Load
Balancer Controller) · SSM Parameter Store · Secrets Manager · CloudWatch
(logs, alarms, dashboard) · ECR

## Cluster add-ons (installed by `infrastructure.yml`, once)

| Add-on | Namespace | Purpose |
|---|---|---|
| AWS Load Balancer Controller | `kube-system` | Turns the `Ingress` into a real ALB |
| kube-prometheus-stack (Prometheus + Grafana + Alertmanager) | `monitoring` | Scrapes `/metrics` from all 3 FastAPI services via `ServiceMonitor`; Grafana auto-loads `observability/grafana-dashboard-enterprise-support.yaml` |
| Argo CD | `argocd` | Watches `charts/enterprise-support/` in git, auto-syncs the cluster — the entire GitOps delivery mechanism |
| CloudWatch agent + Fluent Bit | `amazon-cloudwatch` | Ships pod logs and container metrics to CloudWatch (complements Prometheus/Grafana, doesn't duplicate it — CloudWatch owns AWS-side metrics like RDS/SQS, Grafana owns in-cluster metrics) |

## Security scanning

Two independent Trivy passes, catching different things:
- **`ci-cd.yml` → Trivy image scan** — scans each pushed container image for
  known CVEs in OS packages and language dependencies.
- **`infrastructure.yml` → Trivy IaC scan** — scans the Terraform and the
  Helm chart for misconfigurations (open security groups, missing
  encryption, etc.), independent of whether AWS credentials are even
  available, so it runs on every PR too.

Both currently run with `exit-code: "0"` (report, don't block) — tighten to
`"1"` once the codebase is at a CVE/misconfiguration baseline you're
comfortable gating merges on.

## Deploying

### 1. One-time bootstrap
Create an S3 bucket for Terraform state and update `backend.tf` with its name.

### 2. terraform.tfvars
```bash
cp terraform.tfvars.example terraform.tfvars
```
Fill in:
- `assets_bucket_suffix` — any globally-unique string
- `alert_email` — e.g. `["mnaveen8639@gmail.com"]` (you'll get an SNS
  subscription-confirmation email after `apply` — click the link or you
  won't receive notifications)

### 3. GitHub Secrets
Set these in the repo's Settings → Secrets → Actions:

| Secret | Used by |
|---|---|
| `AWS_ACCESS_KEY_ID` / `AWS_SECRET_ACCESS_KEY` | ci-cd.yml (ECR push, smoke-test kubeconfig) |
| `AWS_ACCESS_KEY_ID_INFRA` / `AWS_SECRET_ACCESS_KEY_INFRA` | infrastructure.yml (Terraform apply + add-on installs) |
| `AWS_REGION` | both — `us-east-1` |
| `ECR_REGISTRY` | ci-cd.yml — `<account-id>.dkr.ecr.us-east-1.amazonaws.com` |
| `EKS_CLUSTER` | both — `enterprise-support-prod-eks` |
| `K8S_NAMESPACE` | ci-cd.yml — `enterprise-support` |
| `SNS_TOPIC_ARN` | ci-cd.yml — from `terraform output sns_topic_arn` |
| `TF_VERSION` | infrastructure.yml — e.g. `1.10.0` |
| `TF_VAR_ASSETS_BUCKET_SUFFIX` / `TF_VAR_ALERT_EMAIL` | infrastructure.yml |
| `ARGOCD_SERVER` / `ARGOCD_AUTH_TOKEN` (optional) | ci-cd.yml — triggers an immediate Argo sync instead of waiting on its ~3 min auto-poll |

### 4. First run
Push to `main` (or trigger `infrastructure.yml` manually with `apply`) to
provision the VPC/EKS/RDS/etc. `infrastructure.yml` also installs the AWS
Load Balancer Controller, kube-prometheus-stack, and Argo CD via Helm, then
applies `argocd/project.yaml` + `argocd/application.yaml` to bootstrap
GitOps. From that point on, pushing to `main` under `app/**` runs the test
→ build → GitOps-commit → smoke-test pipeline in `ci-cd.yml`, and Argo CD
handles the actual deployment.

### 5. Load the schema
Connect to the RDS endpoint (from `terraform output rds_endpoint`, password
from the Secrets Manager ARN in `terraform output rds_master_user_secret_arn`)
and run `app/database/schema.sql` once.

### 6. Find the app
```bash
kubectl get ingress -n enterprise-support
```
The ALB's DNS name serves the frontend at `/` and the three APIs at
`/auth`, `/tickets`, `/assign`.

### 7. Find Grafana / Argo CD UIs
Both are `ClusterIP` by default (not internet-facing) — reach them via
port-forward:
```bash
kubectl -n monitoring port-forward svc/kube-prometheus-stack-grafana 3000:80
kubectl -n argocd port-forward svc/argocd-server 8080:443
```
Grafana's default admin password is auto-generated — retrieve it with:
```bash
kubectl -n monitoring get secret kube-prometheus-stack-grafana \
  -o jsonpath="{.data.admin-password}" | base64 -d
```

## Notes on Helm chart placeholders

`charts/enterprise-support/values.yaml` contains `<ACCOUNT_ID>` / `<ALB_SECURITY_GROUP_ID>`
placeholders for `serviceAccount.roleArn`, `image.registry`,
`ingress.albSecurityGroupId`, and `cloudwatchAgent.roleArn`. Fill these in
from `terraform output` once — Argo CD then keeps the cluster in sync with
whatever is committed here going forward. `argocd/project.yaml` and
`argocd/application.yaml` also need their `<GIT_REPO_URL>` placeholder
filled in with this repo's actual clone URL.
