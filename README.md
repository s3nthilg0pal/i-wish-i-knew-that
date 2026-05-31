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

Omit `--type` to infer the category automatically.

## Add a link from Chrome

Load the unpacked extension from `extension/` in `chrome://extensions`. It saves the current tab to `https://api.senthil.nz/links` by default.

`content_type` is optional for the API and CLI. When omitted, the service first infers a type from the URL:

- YouTube/Vimeo -> `video`
- GitHub repository URLs -> `repo`
- documentation-looking URLs -> `docs`
- blog/news/article URLs -> `blog`
- known product domains -> `product`
- everything else -> `link`

For ambiguous links, you can enable an Ollama-backed classifier:

```sh
export OLLAMA_CLASSIFIER_ENABLED=1
export OLLAMA_HOST=https://ollama.home.arpa
export OLLAMA_CLASSIFIER_MODEL=qwen3.5:2b
```

The model must return one of the same categories. If Ollama is unavailable or returns an invalid response, the service falls back to `link`.
The classifier uses Ollama's structured output support with a Pydantic response model, so the JSON schema is passed through the SDK instead of being written into the prompt.

## Run the API

```sh
export LINK_API_TOKEN='replace-me-with-a-long-random-token'
/usr/bin/python3 scripts/link_service.py serve --port 8787
```

Add a link:

```sh
curl -X POST http://127.0.0.1:8787/links \
  -H "authorization: Bearer $LINK_API_TOKEN" \
  -H 'content-type: application/json' \
  -d '{"title":"Example","url":"https://example.com","content_type":"blog"}'
```

`POST /links` requires `LINK_API_TOKEN`. Send it as `Authorization: Bearer <token>` or `X-API-Token: <token>`. If the token is not configured, writes fail closed.

Every successful API insert regenerates the local `data/links.json` export and, when configured, triggers a deployment webhook. The API does not run Zola in Kubernetes.

## Redeploy Azure Static Web Apps

Set these environment variables on the API deployment:

```sh
DEPLOY_WEBHOOK_URL=https://api.github.com/repos/OWNER/REPO/dispatches
DEPLOY_WEBHOOK_TOKEN=github_pat_or_fine_grained_token
LINK_API_TOKEN=long_random_token_for_post_links
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

## Build and publish the API image

The workflow at `.github/workflows/api-build-deploy.yml` validates the Python API, builds `Dockerfile.api`, and pushes the image to GitHub Container Registry:

```text
ghcr.io/s3nthilg0pal/iwishiknewthat-api:latest
ghcr.io/s3nthilg0pal/iwishiknewthat-api:<commit-sha>
```

Argo CD can then deploy the API from the manifests in `k8s/base`.
