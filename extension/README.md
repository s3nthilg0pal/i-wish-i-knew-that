# Chrome Extension

This extension saves the current Chrome tab to the I Wish I Knew That link API.

## Load locally

1. Open `chrome://extensions`.
2. Enable **Developer mode**.
3. Click **Load unpacked**.
4. Select this `extension/` folder.

## Configure

The popup posts to `https://api.senthil.nz/links` by default. Open **Options** in the popup to change:

- API URL
- API token
- whether the tab title is sent with the URL

Settings are stored with `chrome.storage.sync`.

If the API URL does not end in `/links`, the popup appends `/links` before saving.

## Request format

The extension sends:

```http
POST /links
content-type: application/json
x-api-key: <token>
```

The API token header is omitted when no token is configured.

Default payload:

```json
{
  "url": "https://example.com"
}
```

When **Send tab title** is enabled:

```json
{
  "url": "https://example.com",
  "title": "Example"
}
```

Only `http` and `https` tabs can be saved.
