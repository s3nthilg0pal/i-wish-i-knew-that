# I Wish I Knew That

A Zola-powered personal index of useful software engineering links, tools, docs, videos, products, and repositories.

The site renders links from `data/links.json`, exposes them through homepage filters, and can be updated by the Chrome extension in `extension/`.

## Project Structure

```text
config.toml                  Zola site configuration
content/                     Zola content pages
data/links.json              Link archive consumed by the homepage
static/                      Static assets copied into the build
templates/                   Zola templates
extension/                   Chrome extension for saving the current tab
.github/workflows/           Azure Static Web Apps deployment workflow
```

Generated or local-only paths such as `public/` and `var/` are ignored.

## Link Data

The homepage reads `data/links.json` with this shape:

```json
{
  "links": [
    {
      "title": "Example",
      "url": "https://example.com",
      "date": "2026-06-07",
      "content_type": "blog"
    }
  ]
}
```

Supported `content_type` values are:

- `video`
- `blog`
- `product`
- `repo`
- `docs`
- `link`

Unknown or missing content types render as `link`.

## Run Locally

Install Zola, then serve the site from the repository root:

```sh
zola serve
```

Build the static site:

```sh
zola build
```

The generated site is written to `public/`.

## Chrome Extension

The extension in `extension/` saves the active browser tab to the link API.

1. Open `chrome://extensions`.
2. Enable Developer mode.
3. Click Load unpacked.
4. Select the `extension/` directory.

The popup posts to `https://api.senthil.nz/links` by default. Use the popup options to change the API URL, set an API token, and choose whether to include the page title.

When a token is configured, the extension sends it as:

```text
x-api-key: <token>
```

## API

The link API lives in a separate repository:

https://github.com/s3nthilg0pal/senthil-api

This site expects the API to expose:

- `GET /links`, returning the same JSON shape as `data/links.json`
- `POST /links`, accepting a link payload from the Chrome extension

## Deployment

`.github/workflows/azure-static-web-app.yml` deploys the Zola site to Azure Static Web Apps on pushes to `main`, manual dispatches, and `repository_dispatch` events with type `link-added`.

Before building, the workflow fetches the current archive from:

```text
${LINK_API_URL}/links
```

Required GitHub repository secrets:

```text
LINK_API_URL=https://your-api.example.com
AZURE_STATIC_WEB_APPS_API_TOKEN=...
```

The fetched response must match the `data/links.json` format shown above.
