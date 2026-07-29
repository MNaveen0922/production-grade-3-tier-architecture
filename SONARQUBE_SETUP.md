# SonarQube Integration — Setup Steps

Files added/changed (already applied in this repo copy):
- `sonarqube/docker-compose.yml` — spins up a SonarQube Server + Postgres
- `sonar-project.properties` — scan config (sources, tests, coverage paths)
- `app/{auth,ticket,assignment}/requirements-dev.txt` — added `pytest-cov`
- `.github/workflows/application.yml`:
  - `unit-test` job now generates `coverage-<service>.xml` and uploads it
  - new `sonarqube` job: runs the scan, then blocks on the Quality Gate
  - `build-push` now depends on `sonarqube`, so a failed gate stops the
    build/push/deploy — nothing gets released past a broken gate.

## 1. Stand up a SonarQube server (you don't have one yet)

```bash
cd sonarqube
docker compose up -d
```

Open `http://localhost:9000`, log in with `admin` / `admin`, set a new
password. This is fine for trying things out; for anything long-lived, put
it behind HTTPS and point `SONAR_JDBC_URL` at a real Postgres instance (e.g.
the RDS module already in this repo) instead of the bundled `db` container.

## 2. Create the project + token in SonarQube

- In SonarQube: **Projects > Create Project > Manually**, project key
  `support-desk-platform` (matches `sonar-project.properties`).
- **My Account > Security > Generate Token** — copy it, you won't see it again.

## 3. Add GitHub Actions secrets

Repo **Settings > Secrets and variables > Actions**:

| Secret | Value |
|---|---|
| `SONAR_HOST_URL` | e.g. `http://<your-server>:9000` (must be reachable from the runner) |
| `SONAR_TOKEN` | the token generated above |

If your SonarQube instance is only reachable on a private network (e.g.
inside the VPC this repo's Terraform builds), GitHub-hosted runners won't be
able to reach it — either expose it via the existing ALB/ingress, or switch
the `sonarqube` job to a self-hosted runner inside that network.

## 4. Run it

Push to `main` or open a PR touching `app/**` — the `sonarqube` job runs
after `unit-test`/`integration-test` and before any image is built. A
failing Quality Gate fails that job, which stops `build-push`,
`update-gitops-manifest`, and `smoke-test` from running at all.

## Notes

- Only `auth`, `ticket`, and `assignment` have coverage wired in (they're the
  only services with a `tests/` dir today). `worker` and `frontend` are
  still scanned for code quality/issues, just without coverage numbers.
- The frontend has no test suite yet, so JS coverage isn't reported. Add one
  (e.g. `vitest --coverage`) and uncomment `sonar.javascript.lcov.reportPaths`
  in `sonar-project.properties` to wire it in later.
- Default Quality Gate ("Sonar way") requires 80% coverage on new code and no
  new bugs/vulnerabilities/code smells above a threshold — tune this in
  SonarQube under **Quality Gates** if it's too strict to start.
