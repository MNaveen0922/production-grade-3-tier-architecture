#!/bin/bash
# Fully-automated SonarQube bootstrap - runs once on first boot via cloud-init.
# No manual docker compose, no manual "create project", no manual "generate token".
set -euxo pipefail

exec > >(tee /var/log/sonarqube-bootstrap.log) 2>&1

echo "=== [1/7] Kernel settings SonarQube's bundled Elasticsearch requires ==="
sysctl -w vm.max_map_count=262144
sysctl -w fs.file-max=131072
cat >> /etc/sysctl.conf <<EOF
vm.max_map_count=262144
fs.file-max=131072
EOF

echo "=== [2/7] Install Docker + Compose plugin + openssl + SSM agent ==="
# NOTE: no `dnf update -y` here on purpose - a full system update on first
# boot can hang cloud-init for a long time and occasionally upgrades
# packages to versions that break this script. Install only what we need.
dnf install -y docker jq unzip openssl amazon-ssm-agent

# amazon-ssm-agent ships preinstalled on most AL2023 AMIs but not all -
# installing + enabling it explicitly is what makes
# `aws ssm start-session --target <instance-id>` reliable.
systemctl enable --now amazon-ssm-agent

systemctl enable --now docker
usermod -aG docker ec2-user

mkdir -p /usr/local/lib/docker/cli-plugins
curl -sSL "https://github.com/docker/compose/releases/latest/download/docker-compose-linux-$(uname -m)" \
  -o /usr/local/lib/docker/cli-plugins/docker-compose
chmod +x /usr/local/lib/docker/cli-plugins/docker-compose

echo "=== [3/7] Install AWS CLI v2 (needed to push the token to SSM later) ==="
curl -sSL "https://awscli.amazonaws.com/awscli-exe-linux-$(uname -m).zip" -o /tmp/awscliv2.zip
unzip -q /tmp/awscliv2.zip -d /tmp
/tmp/aws/install

echo "=== [4/7] Write docker-compose.yml and start SonarQube + Postgres ==="
mkdir -p /opt/sonarqube
cat > /opt/sonarqube/docker-compose.yml <<'COMPOSE_EOF'
services:
  sonarqube:
    image: sonarqube:10-community
    container_name: sonarqube
    restart: unless-stopped
    depends_on:
      - db
    ports:
      - "9000:9000"
    environment:
      SONAR_JDBC_URL: jdbc:postgresql://db:5432/sonar
      SONAR_JDBC_USERNAME: sonar
      SONAR_JDBC_PASSWORD: sonar
    volumes:
      - sonarqube_data:/opt/sonarqube/data
      - sonarqube_extensions:/opt/sonarqube/extensions
      - sonarqube_logs:/opt/sonarqube/logs
    ulimits:
      nofile:
        soft: 65536
        hard: 65536
      nproc: 4096

  db:
    image: postgres:15
    container_name: sonarqube_db
    restart: unless-stopped
    environment:
      POSTGRES_USER: sonar
      POSTGRES_PASSWORD: sonar
      POSTGRES_DB: sonar
    volumes:
      - sonarqube_db_data:/var/lib/postgresql/data

volumes:
  sonarqube_data:
  sonarqube_extensions:
  sonarqube_logs:
  sonarqube_db_data:
COMPOSE_EOF

cd /opt/sonarqube
docker compose up -d

echo "=== [5/7] Wait for SonarQube to report healthy (can take 2-4 min on first boot) ==="
for i in $(seq 1 60); do
  status="$(curl -s http://localhost:9000/api/system/health | jq -r '.health' 2>/dev/null || true)"
  if [ "$status" = "GREEN" ]; then
    echo "SonarQube is up."
    break
  fi
  echo "Waiting for SonarQube... ($i/60, last status: $status)"
  sleep 10
done

echo "=== [6/7] Reset default admin password, create project, generate CI token ==="
NEW_PASSWORD="$(openssl rand -base64 24)"

# Probe whether admin/admin still works. On a genuine first boot it will;
# on a re-run (e.g. instance rebooted, script re-triggered manually) it
# won't, and we bail out loudly instead of silently pushing a password
# that doesn't match what's actually set on the server.
probe_code="$(curl -s -o /dev/null -w '%%{http_code}' -u admin:admin \
  "http://localhost:9000/api/authentication/validate")"

if [ "$probe_code" = "200" ]; then
  change_code="$(curl -s -o /tmp/change_pw.out -w '%%{http_code}' \
    -u admin:admin -X POST "http://localhost:9000/api/users/change_password" \
    --data-urlencode "login=admin" \
    --data-urlencode "previousPassword=admin" \
    --data-urlencode "password=$NEW_PASSWORD")"

  if [ "$change_code" != "204" ]; then
    echo "ERROR: password change failed (HTTP $change_code): $(cat /tmp/change_pw.out)"
    exit 1
  fi
  echo "Admin password changed."
else
  echo "ERROR: admin/admin login did not succeed (HTTP $probe_code from validate endpoint)."
  echo "This means either SonarQube isn't actually healthy yet, or the password"
  echo "was already changed by a previous run - in which case this script cannot"
  echo "recover the current password and the SSM parameters below will be stale."
  exit 1
fi

create_code="$(curl -s -o /tmp/create_project.out -w '%%{http_code}' \
  -u "admin:$NEW_PASSWORD" -X POST "http://localhost:9000/api/projects/create" \
  --data-urlencode "project=${sonar_project_key}" \
  --data-urlencode "name=${sonar_project_key}")"
if [ "$create_code" != "200" ]; then
  echo "WARNING: project create returned HTTP $create_code: $(cat /tmp/create_project.out)"
fi

# Retry token generation a few times - SonarQube's internal auth store can
# take a couple seconds to settle right after a password change.
TOKEN=""
for i in 1 2 3 4 5; do
  TOKEN_JSON="$(curl -s -u "admin:$NEW_PASSWORD" -X POST \
    "http://localhost:9000/api/user_tokens/generate" \
    --data-urlencode "name=ci-cd-token-$(date +%s)")"
  TOKEN="$(echo "$TOKEN_JSON" | jq -r '.token // empty')"
  [ -n "$TOKEN" ] && break
  echo "Token generation attempt $i failed, response: $TOKEN_JSON"
  sleep 5
done

if [ -z "$TOKEN" ]; then
  echo "ERROR: token generation failed after 5 attempts - aborting before writing to SSM."
  exit 1
fi

echo "=== [7/7] Push admin password + CI token to SSM Parameter Store ==="
aws ssm put-parameter --region "${aws_region}" \
  --name "${ssm_path_prefix}/admin_password" \
  --value "$NEW_PASSWORD" --type SecureString --overwrite

aws ssm put-parameter --region "${aws_region}" \
  --name "${ssm_path_prefix}/token" \
  --value "$TOKEN" --type SecureString --overwrite

echo "Both parameters written successfully:"
echo "  ${ssm_path_prefix}/admin_password"
echo "  ${ssm_path_prefix}/token"

echo "SonarQube bootstrap complete."