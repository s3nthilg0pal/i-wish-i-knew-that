#!/usr/bin/env python3
import argparse
import hmac
import json
import os
import re
import sqlite3
import subprocess
import sys
import tomllib
import urllib.request
from datetime import date, datetime, timezone
from html import unescape
from html.parser import HTMLParser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Literal
from urllib.parse import quote, unquote, urlparse

ROOT = Path(__file__).resolve().parents[1]
DB_PATH = ROOT / "var" / "links.db"
DATA_PATH = ROOT / "data" / "links.json"
CONTENT_DIR = ROOT / "content"
ALLOWED_TYPES = {"video", "blog", "product", "repo", "docs", "link"}
VIDEO_HOSTS = {
    "youtu.be",
    "youtube.com",
    "www.youtube.com",
    "vimeo.com",
    "www.vimeo.com",
}
YOUTUBE_HOSTS = {
    "youtu.be",
    "youtube.com",
    "www.youtube.com",
}
PRODUCT_HOSTS = {
    "linear.app",
    "vercel.com",
    "zed.dev",
    "www.producthunt.com",
    "producthunt.com",
}
DOC_HOST_HINTS = {
    "developer.mozilla.org",
    "doc.rust-lang.org",
    "docs.github.com",
    "www.sqlite.org",
}
OLLAMA_DEFAULT_MODEL = "qwen3.5:2b"
CLASSIFIER_PROMPT = """Classify this URL for a personal link archive.

Categories:
video, blog, product, repo, docs, link

Definitions:
video = watchable video or video platform page
blog = article, essay, tutorial, news, blog post
product = tool, app, SaaS, service, company product page
repo = source code repository
docs = official docs, API reference, manual, guide
link = fallback when unclear

Choose the best category. If uncertain, choose link.

Input:
title={title}
url={url}
excerpt={excerpt}
"""


class MetadataParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.og_title = ""
        self.description = ""
        self.title = ""
        self._in_title = False
        self._skip_tag = ""
        self._title_parts = []
        self._text_parts = []

    def handle_starttag(self, tag, attrs):
        tag = tag.lower()
        attrs = {key.lower(): value for key, value in attrs if key and value}
        if tag in {"script", "style", "noscript"}:
            self._skip_tag = tag
        if tag == "meta":
            property_name = attrs.get("property", "").lower()
            name = attrs.get("name", "").lower()
            if property_name == "og:title":
                self.og_title = attrs.get("content", "").strip()
            elif property_name == "og:description" or name == "description":
                self.description = attrs.get("content", "").strip()
        elif tag == "title":
            self._in_title = True

    def handle_endtag(self, tag):
        tag = tag.lower()
        if tag == self._skip_tag:
            self._skip_tag = ""
        if tag == "title":
            self._in_title = False
            self.title = "".join(self._title_parts).strip()

    def handle_data(self, data):
        if self._in_title:
            self._title_parts.append(data)
        elif not self._skip_tag and len(" ".join(self._text_parts)) < 1200:
            text = data.strip()
            if text:
                self._text_parts.append(text)

    @property
    def excerpt(self):
        return clean_page_title(self.description or " ".join(self._text_parts))[:1000]


def connect():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute(
        """
        create table if not exists links (
          id integer primary key autoincrement,
          title text not null,
          url text not null unique,
          content_type text not null default 'link',
          date text not null,
          created_at text not null
        )
        """
    )
    return conn


def title_from_url(url):
    parsed = urlparse(url)
    slug = unquote(parsed.path.strip("/").split("/")[-1])
    if not slug:
        slug = parsed.netloc
    title = re.sub(r"[-_]+", " ", slug)
    title = re.sub(r"\s+", " ", title).strip()
    return title.capitalize() if title else url


def clean_page_title(title):
    title = unescape(title or "")
    title = re.sub(r"\s+", " ", title).strip()
    return title


def is_youtube_url(url):
    host = urlparse(url).netloc.lower()
    return host in YOUTUBE_HOSTS or host.removeprefix("www.") in YOUTUBE_HOSTS


def fetch_youtube_title(url):
    oembed_url = f"https://www.youtube.com/oembed?url={quote(url, safe='')}&format=json"
    request = urllib.request.Request(
        oembed_url,
        headers={
            "accept": "application/json",
            "user-agent": "iwishiknewthat-api",
        },
    )
    with urllib.request.urlopen(request, timeout=5) as response:
        payload = json.loads(response.read(64 * 1024).decode("utf-8"))
    return clean_page_title(payload.get("title", ""))


def fetch_page_metadata(url):
    request = urllib.request.Request(
        url,
        headers={
            "accept": "text/html,application/xhtml+xml",
            "user-agent": "iwishiknewthat-api",
        },
    )
    with urllib.request.urlopen(request, timeout=5) as response:
        content_type = response.headers.get("content-type", "")
        if "html" not in content_type.lower():
            return ""
        html = response.read(128 * 1024).decode("utf-8", errors="replace")

    parser = MetadataParser()
    parser.feed(html)
    return {
        "title": clean_page_title(parser.og_title or parser.title),
        "excerpt": parser.excerpt,
    }


def fetch_page_title(url):
    return fetch_page_metadata(url)["title"]


def infer_title(url):
    try:
        if is_youtube_url(url):
            return fetch_youtube_title(url) or title_from_url(url)
        return fetch_page_title(url) or title_from_url(url)
    except (json.JSONDecodeError, OSError, TimeoutError, ValueError):
        return title_from_url(url)


def validate_link(payload):
    title = str(payload.get("title") or "").strip()
    url = str(payload.get("url") or "").strip()
    link_date = str(payload.get("date") or date.today().isoformat()).strip()

    if not url:
        raise ValueError("url is required")
    if urlparse(url).scheme not in {"http", "https"}:
        raise ValueError("url must start with http:// or https://")
    if not title:
        title = infer_title(url)
    provided_type = payload.get("content_type")
    content_type = str(provided_type or infer_content_type(url, title)).strip().lower()
    if content_type == "auto":
        content_type = infer_content_type(url, title)
    if content_type not in ALLOWED_TYPES:
        raise ValueError(f"content_type must be one of: {', '.join(sorted(ALLOWED_TYPES))}")
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", link_date):
        raise ValueError("date must use YYYY-MM-DD")

    return {
        "title": title,
        "url": url,
        "content_type": content_type,
        "date": link_date,
    }


def infer_content_type(url, title=""):
    heuristic_type = infer_content_type_from_url(url)
    if heuristic_type != "link":
        return heuristic_type
    return infer_content_type_with_llm(url, title) or "link"


def infer_content_type_from_url(url):
    parsed = urlparse(url)
    host = parsed.netloc.lower().removeprefix("www.")
    path = parsed.path.lower()
    full_host = parsed.netloc.lower()

    if full_host in VIDEO_HOSTS or host in VIDEO_HOSTS:
        return "video"
    if host == "github.com":
        return "repo"
    if full_host in DOC_HOST_HINTS or host in DOC_HOST_HINTS:
        return "docs"
    if any(part in path for part in ("/docs", "/documentation", "/guide", "/manual", "/reference")):
        return "docs"
    if any(part in path for part in ("/blog", "/news", "/articles", "/posts")):
        return "blog"
    if host in PRODUCT_HOSTS or full_host in PRODUCT_HOSTS:
        return "product"
    return "link"


def env_flag_enabled(name):
    return os.environ.get(name, "").strip().lower() in {"1", "true", "yes", "on"}


def build_category_response_model():
    from pydantic import BaseModel

    class LinkCategory(BaseModel):
        content_type: Literal["video", "blog", "product", "repo", "docs", "link"]

    return LinkCategory


class OllamaCategoryAgent:
    def __init__(self, client, model, response_model):
        self.client = client
        self.model = model
        self.response_model = response_model

    def classify(self, url, title="", excerpt=""):
        prompt = CLASSIFIER_PROMPT.format(title=title or title_from_url(url), url=url, excerpt=excerpt)
        response = self.client.chat(
            model=self.model,
            messages=[
                {
                    "role": "system",
                    "content": "You classify saved links. Return a JSON object with a content_type field. Use the requested response format.",
                },
                {"role": "user", "content": prompt},
            ],
            format=self.response_model.model_json_schema(),
            think=False,
            options={"temperature": 0, "num_predict": 32},
        )
        result = self.response_model.model_validate_json(response["message"]["content"])
        content_type = str(result.content_type).strip().lower()
        if content_type in ALLOWED_TYPES:
            return content_type
        return ""


def infer_content_type_with_llm(url, title=""):
    if not env_flag_enabled("OLLAMA_CLASSIFIER_ENABLED"):
        return ""

    try:
        import ollama
    except ImportError:
        print("OLLAMA_CLASSIFIER_ENABLED is set, but the ollama package is not installed", file=sys.stderr)
        return ""
    try:
        response_model = build_category_response_model()
    except ImportError:
        print("OLLAMA_CLASSIFIER_ENABLED is set, but the pydantic package is not installed", file=sys.stderr)
        return ""

    excerpt = ""
    try:
        if not is_youtube_url(url):
            metadata = fetch_page_metadata(url)
            title = title or metadata["title"]
            excerpt = metadata["excerpt"]
    except (OSError, TimeoutError, ValueError):
        pass

    model = os.environ.get("OLLAMA_CLASSIFIER_MODEL", OLLAMA_DEFAULT_MODEL)
    agent = OllamaCategoryAgent(ollama, model, response_model)

    try:
        return agent.classify(url, title, excerpt)
    except Exception as error:
        print(f"ollama classification failed for {url}: {error}", file=sys.stderr)
        return ""


def add_link(payload):
    link = validate_link(payload)
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    with connect() as conn:
        conn.execute(
            """
            insert into links (title, url, content_type, date, created_at)
            values (?, ?, ?, ?, ?)
            on conflict(url) do update set
              title = excluded.title,
              content_type = excluded.content_type,
              date = excluded.date
            """,
            (link["title"], link["url"], link["content_type"], link["date"], now),
        )
    return link


def list_links():
    with connect() as conn:
        rows = conn.execute(
            """
            select title, url, content_type, date
            from links
            order by date desc, id desc
            """
        ).fetchall()
    return [dict(row) for row in rows]


def sync_links():
    DATA_PATH.parent.mkdir(parents=True, exist_ok=True)
    DATA_PATH.write_text(json.dumps({"links": list_links()}, indent=2) + "\n", encoding="utf-8")


def build_site():
    subprocess.run(["zola", "build"], cwd=ROOT, check=True)


def deploy_site():
    command = os.environ.get("DEPLOY_COMMAND")
    if command:
        subprocess.run(command, cwd=ROOT, shell=True, check=True)


def trigger_deploy_webhook(link):
    webhook_url = os.environ.get("DEPLOY_WEBHOOK_URL")
    if not webhook_url:
        return False

    payload = json.dumps({"event_type": "link-added", "client_payload": {"link": link}}).encode("utf-8")
    request = urllib.request.Request(
        webhook_url,
        data=payload,
        headers={
            "accept": "application/vnd.github+json",
            "content-type": "application/json",
            "user-agent": "iwishiknewthat-api",
        },
        method="POST",
    )

    token = os.environ.get("DEPLOY_WEBHOOK_TOKEN")
    if token:
        request.add_header("authorization", f"Bearer {token}")

    with urllib.request.urlopen(request, timeout=10) as response:
        if response.status >= 400:
            raise RuntimeError(f"deploy webhook failed with status {response.status}")
    return True


def parse_frontmatter(path):
    text = path.read_text(encoding="utf-8")
    if not text.startswith("+++\n"):
        return None
    end = text.find("\n+++", 4)
    if end == -1:
        return None
    return tomllib.loads(text[4:end])


def import_existing_content():
    imported = 0
    for path in CONTENT_DIR.glob("*.md"):
        if path.name == "_index.md":
            continue
        metadata = parse_frontmatter(path)
        if not metadata:
            continue
        extra = metadata.get("extra", {})
        url = extra.get("external_url")
        if not url:
            continue
        link_date = metadata.get("date")
        if hasattr(link_date, "isoformat"):
            link_date = link_date.isoformat()
        add_link(
            {
                "title": metadata.get("title", path.stem),
                "url": url,
                "content_type": extra.get("content_type", "link"),
                "date": link_date or date.today().isoformat(),
            }
        )
        imported += 1
    sync_links()
    return imported


class LinkHandler(BaseHTTPRequestHandler):
    def send_json(self, status, payload):
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def authenticated(self):
        expected_token = os.environ.get("LINK_API_TOKEN", "").strip()
        if not expected_token:
            self.send_json(503, {"error": "LINK_API_TOKEN is not configured"})
            return False

        authorization = self.headers.get("authorization", "").strip()
        supplied_token = self.headers.get("x-api-token", "").strip()
        if authorization.lower().startswith("bearer "):
            supplied_token = authorization[7:].strip()

        if not supplied_token or not hmac.compare_digest(supplied_token, expected_token):
            self.send_json(401, {"error": "unauthorized"})
            return False

        return True

    def do_GET(self):
        if self.path == "/health":
            self.send_json(200, {"ok": True})
            return
        if self.path == "/links":
            self.send_json(200, {"links": list_links()})
            return
        self.send_json(404, {"error": "not found"})

    def do_POST(self):
        if self.path != "/links":
            self.send_json(404, {"error": "not found"})
            return
        if not self.authenticated():
            return

        length = int(self.headers.get("content-length", "0"))
        try:
            payload = json.loads(self.rfile.read(length))
            link = add_link(payload)
            sync_links()
            deploy_triggered = trigger_deploy_webhook(link)
        except (json.JSONDecodeError, ValueError) as error:
            self.send_json(400, {"error": str(error)})
            return
        except subprocess.CalledProcessError as error:
            self.send_json(500, {"error": f"command failed: {error.cmd}"})
            return
        except (RuntimeError, TimeoutError, OSError) as error:
            self.send_json(502, {"error": str(error)})
            return

        self.send_json(201, {"link": link, "deploy_triggered": deploy_triggered})


def serve(host, port):
    server = ThreadingHTTPServer((host, port), LinkHandler)
    print(f"Link API listening on http://{host}:{port}", flush=True)
    server.serve_forever()


def main():
    parser = argparse.ArgumentParser(description="Manage links for the Zola site.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("init")
    subparsers.add_parser("import")
    subparsers.add_parser("sync")
    subparsers.add_parser("build")

    add_parser = subparsers.add_parser("add")
    add_parser.add_argument("--title")
    add_parser.add_argument("--url", required=True)
    add_parser.add_argument("--type", dest="content_type")
    add_parser.add_argument("--date", default=date.today().isoformat())

    serve_parser = subparsers.add_parser("serve")
    serve_parser.add_argument("--host", default="127.0.0.1")
    serve_parser.add_argument("--port", default=8787, type=int)

    args = parser.parse_args()

    if args.command == "init":
        connect().close()
    elif args.command == "import":
        print(f"imported {import_existing_content()} links")
    elif args.command == "sync":
        sync_links()
    elif args.command == "build":
        sync_links()
        build_site()
        deploy_site()
    elif args.command == "add":
        add_link(vars(args))
        sync_links()
        build_site()
        deploy_site()
    elif args.command == "serve":
        connect().close()
        sync_links()
        serve(args.host, args.port)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(0)
