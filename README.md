# Link API

This Zola site reads archive links from `data/links.json`.

The source of truth is SQLite at `var/links.db`. The helper script can update the database, regenerate `data/links.json`, and rebuild the site for local use. In Kubernetes, the API only stores links and triggers the external deploy workflow.

## Seed the database

```sh
/usr/bin/python3 scripts/link_service.py import
```

## Add a link from the CLI

```sh
/usr/bin/python3 scripts/link_service.py add \
  --title "Example" \
  --url "https://example.com" \
  --type blog
```

Types: `video`, `blog`, `product`, `repo`, `docs`, `link`.

`content_type` is optional for the API and CLI. When omitted, the service infers a type from the URL:

- YouTube/Vimeo -> `video`
- GitHub repository URLs -> `repo`
- documentation-looking URLs -> `docs`
- blog/news/article URLs -> `blog`
- known product domains -> `product`
- everything else -> `link`

## Run the API

```sh
/usr/bin/python3 scripts/link_service.py serve --port 8787
```

Add a link:

```sh
curl -X POST http://127.0.0.1:8787/links \
  -H 'content-type: application/json' \
  -d '{"title":"Example","url":"https://example.com","content_type":"blog"}'
```

Every successful API insert regenerates the local `data/links.json` export and, when configured, triggers a deployment webhook. The API does not run Zola in Kubernetes.

## Redeploy Azure Static Web Apps

Set these environment variables on the API deployment:

```sh
DEPLOY_WEBHOOK_URL=https://api.github.com/repos/OWNER/REPO/dispatches
DEPLOY_WEBHOOK_TOKEN=github_pat_or_fine_grained_token
```

The token needs permission to create `repository_dispatch` events. After `POST /links`, the API sends:

```json
{
  "event_type": "link-added",
  "client_payload": {"link": {}}
}
```

The workflow at `.github/workflows/azure-static-web-app.yml` then:

1. fetches `GET /links` from the API,
2. writes `data/links.json`,
3. runs `zola build`,
4. deploys `public/` to Azure Static Web Apps.

Required GitHub repository secrets:

```text
LINK_API_URL=https://your-api.example.com
AZURE_STATIC_WEB_APPS_API_TOKEN=...
```
