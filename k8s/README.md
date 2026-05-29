# Kubernetes

This directory contains Kustomize manifests for the link API only.

The Zola site is deployed separately to Azure Static Web Apps by GitHub Actions. Kubernetes does not serve the static dashboard/site.

## Shape

- `iwishiknewthat-api`: one replica, owns SQLite writes, exposes `GET /links` and `POST /links`.
- `iwishiknewthat-db`: persistent SQLite storage mounted at `/app/var`.
- `iwishiknewthat-deploy-webhook`: secret containing the GitHub `repository_dispatch` endpoint and token.

SQLite should stay single-writer, so the API deployment intentionally uses:

```yaml
replicas: 1
strategy:
  type: Recreate
```

## Build requirements

The API image must include:

- this repository at `/app`
- `/usr/bin/python3`

The API image does not need Zola for Kubernetes runtime.

## Deploy trigger

After a successful `POST /links`, the API sends a GitHub `repository_dispatch` event to trigger the Azure Static Web Apps workflow.

Set these secret values in an overlay or replace the generated secret values before applying:

```text
DEPLOY_WEBHOOK_URL=https://api.github.com/repos/OWNER/REPO/dispatches
DEPLOY_WEBHOOK_TOKEN=github_pat_or_fine_grained_token
```

## Render manifests

```sh
kubectl kustomize k8s/base
```

Local overlay:

```sh
kubectl kustomize k8s/overlays/local
```

## Apply

```sh
kubectl apply -k k8s/base
```

## Ingress

Expose only the API from Kubernetes:

- API: `Service/iwishiknewthat-api`, port `8787`

The public website should point to Azure Static Web Apps, not Kubernetes.
