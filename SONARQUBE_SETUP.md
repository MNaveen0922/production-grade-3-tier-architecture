# SonarQube Integration — Automated EC2 Setup

You don't have Docker locally, so SonarQube runs on a small EC2 instance
instead. `terraform apply` provisions the box **and** fully configures it —
no SSH, no manual `docker compose up`, no clicking through the SonarQube UI
to create a project or token.

## What's automated

`modules/sonarqube/` provisions:
- An EC2 instance (Amazon Linux 2023, `t3.medium` by default)
- A security group open **only** to `sonarqube_allowed_cidr_blocks` on port
  9000 — no port 22 open unless you explicitly set `sonarqube_key_name`
- An IAM role using **SSM Session Manager** for shell access (no SSH key to
  manage or lose)
- A static Elastic IP, so the URL never changes across restarts

On first boot, a `user_data` script (see
`modules/sonarqube/templates/user_data.sh.tpl`) automatically:
1. Installs Docker + Compose
2. Starts SonarQube + Postgres (the same containers as the old
   `sonarqube/docker-compose.yml`, now running on the EC2 box instead of
   your laptop)
3. Waits for SonarQube to report healthy
4. Resets the default `admin/admin` password to a random one
5. Creates the `support-desk-platform` project
6. Generates a CI token
7. Pushes both the admin password and the token into **SSM Parameter
   Store** as `SecureString`s — never written to disk in plaintext, never
   printed to your terminal

## 1. Set your IP and apply

```bash
cp terraform.tfvars.example terraform.tfvars
# Edit terraform.tfvars: set sonarqube_allowed_cidr_blocks to your IP.
# Find it with: curl -s ifconfig.me   ->  use "x.x.x.x/32"

terraform init
terraform apply
```

Boot + bootstrap takes about 3-5 minutes after the instance comes up
(SonarQube's bundled Elasticsearch is the slow part). Check progress with:

```bash
aws ssm start-session --target "$(terraform output -raw sonarqube_instance_id)"
# then, inside the session:
sudo tail -f /var/log/sonarqube-bootstrap.log
```

## 2. Grab the token for GitHub Actions

```bash
terraform output sonarqube_url
# -> http://<elastic-ip>:9000  (open it in a browser to confirm it's up)

aws ssm get-parameter \
  --name "$(terraform output -raw sonarqube_token_ssm_path)" \
  --with-decryption --query Parameter.Value --output text --region us-east-1
```

## 3. Add GitHub Actions secrets

Repo **Settings > Secrets and variables > Actions**:

| Secret | Value |
|---|---|
| `SONAR_HOST_URL` | `terraform output sonarqube_url` |
| `SONAR_TOKEN` | the value fetched from SSM above |

If GitHub-hosted runners can't reach the Elastic IP because you locked
`sonarqube_allowed_cidr_blocks` down to just your own IP, either widen it to
include GitHub's runner IP ranges, or switch the `sonarqube` CI job to a
self-hosted runner that can reach it.

## 4. Run it

Push to `main` or open a PR touching `app/**` — the `sonarqube` job in
`.github/workflows/application.yml` runs the scan and blocks on the Quality
Gate before anything gets built or deployed.

## Re-running / rebuilding

The instance is stateful (Docker volumes persist SonarQube's data across
reboots). If you ever need a clean rebuild:
`terraform taint module.sonarqube.aws_instance.sonarqube && terraform apply`
— the boot script re-runs from scratch and generates a fresh admin
password/token.

## Cost note

A `t3.medium` running 24/7 is roughly $30/month. If you only need
SonarQube during active development, stop it manually when idle:
`aws ec2 stop-instances --instance-ids "$(terraform output -raw sonarqube_instance_id)"`
— the Elastic IP and all data persist, and `start-instances` brings it back
without re-running the bootstrap (it's already configured). Just don't
`terraform destroy` between sessions, or you'll lose the project history.

## Notes (unchanged from before)

- Only `auth`, `ticket`, and `assignment` have coverage wired in (they're
  the only services with a `tests/` dir today). `worker` and `frontend` are
  still scanned for code quality/issues, just without coverage numbers.
- The frontend has no test suite yet, so JS coverage isn't reported. Add
  one (e.g. `vitest --coverage`) and uncomment
  `sonar.javascript.lcov.reportPaths` in `sonar-project.properties` later.
- Default Quality Gate ("Sonar way") requires 80% coverage on new code and
  no new bugs/vulnerabilities/code smells above a threshold — tune this in
  SonarQube under **Quality Gates** if it's too strict to start.
