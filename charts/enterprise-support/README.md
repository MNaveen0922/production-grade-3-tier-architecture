# enterprise-support Helm chart

Templated replacement for the earlier `k8s/*.yaml` raw manifests — same
resources, now parameterized so environment-specific values (account ID,
image tags, replica counts) live in `values.yaml` instead of being
hand-edited into every manifest.

## Install manually (bootstrap / local testing)

```bash
helm upgrade --install enterprise-support ./charts/enterprise-support \
  --namespace enterprise-support --create-namespace \
  --set image.registry=<ACCOUNT_ID>.dkr.ecr.us-east-1.amazonaws.com \
  --set serviceAccount.roleArn=arn:aws:iam::<ACCOUNT_ID>:role/enterprise-support-prod-app-pod-role \
  --set ingress.albSecurityGroupId=<SG_ID> \
  --set cloudwatchAgent.roleArn=arn:aws:iam::<ACCOUNT_ID>:role/enterprise-support-prod-cloudwatch-agent-role
```

## Normal operation (GitOps via Argo CD)

In this project Helm is **not** invoked directly by CI/CD. Argo CD watches
this chart in the `main` branch and applies it automatically — see
`argocd/application.yaml`. CI/CD's only job after building an image is to
bump the matching `apiServices[].tag` / `frontend.tag` / `worker.tag` value
in `values.yaml` and commit it; Argo CD's auto-sync does the rest. See the
project root README for the full GitOps flow.

## Key values

| Value | Purpose |
|---|---|
| `image.registry` | ECR host — `terraform output ecr_repository_urls` |
| `serviceAccount.roleArn` | IRSA role for app pods — `terraform output app_pod_role_arn` |
| `ingress.albSecurityGroupId` | SG the ALB Controller attaches — `terraform output alb_security_group_id` |
| `cloudwatchAgent.roleArn` | IRSA role for the CloudWatch/Fluent Bit DaemonSet — `terraform output cloudwatch_agent_role_arn` |
| `apiServices[].tag`, `frontend.tag`, `worker.tag` | Image tags — bumped per-deploy by CI/CD |
| `metrics.serviceMonitor.enabled` | Set `false` if kube-prometheus-stack isn't installed in-cluster |
