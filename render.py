#!/usr/bin/env python3
"""Render data/alerts.json -> index.html (single self-contained file)."""
from __future__ import annotations
import html
import json
import pathlib
from datetime import datetime, timezone

ROOT = pathlib.Path(__file__).resolve().parent
ALERTS = ROOT / "data" / "alerts.json"
OUT = ROOT / "index.html"

posts = json.loads(ALERTS.read_text()) if ALERTS.exists() else []

def fmt_ts(ts: float) -> str:
    return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

def excerpt(text: str, n: int = 500) -> str:
    text = text.strip()
    return text[:n] + ("…" if len(text) > n else "")

cards = []
for p in posts:
    cards.append(f"""
<article class="post">
  <div class="meta">
    <span class="sub">r/{html.escape(p["subreddit"])}</span>
    · u/{html.escape(p["author"])}
    · {fmt_ts(p["created_utc"])}
  </div>
  <h2 class="title">
    <a href="{html.escape(p["url"])}" target="_blank" rel="noopener noreferrer">{html.escape(p["title"])}</a>
  </h2>
  {f'<p class="body">{html.escape(excerpt(p["selftext"]))}</p>' if p["selftext"].strip() else ""}
</article>""")

now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
body = "\n".join(cards) if cards else '<p class="empty">No relevant posts yet. The cron job will populate this page.</p>'

OUT.write_text(f"""<!DOCTYPE html>
<html lang="fr">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Reddit alerts — gestion locative SaaS</title>
<style>
  :root {{ color-scheme: light dark; }}
  body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", system-ui, sans-serif;
         max-width: 820px; margin: 2em auto; padding: 0 1em; line-height: 1.5; }}
  header {{ border-bottom: 1px solid #ccc; padding-bottom: 0.5em; margin-bottom: 1.5em; }}
  h1 {{ color: #ff4500; margin: 0; font-size: 1.4em; }}
  .meta {{ color: #777; font-size: 0.82em; }}
  .post {{ border-left: 3px solid #ff4500; padding: 0.6em 1em; margin: 1.2em 0;
          background: rgba(127,127,127,0.06); border-radius: 0 4px 4px 0; }}
  .post .meta {{ margin-bottom: 0.3em; }}
  .sub {{ font-weight: 600; color: #ff4500; }}
  .title {{ margin: 0.2em 0; font-size: 1.05em; font-weight: 600; }}
  .title a {{ color: inherit; text-decoration: none; }}
  .title a:hover {{ text-decoration: underline; }}
  .body {{ font-size: 0.92em; color: #555; white-space: pre-wrap; margin: 0.4em 0 0; }}
  .empty {{ color: #888; font-style: italic; }}
</style>
</head>
<body>
<header>
  <h1>Reddit alerts — gestion locative SaaS</h1>
  <div class="meta">Last refresh: {now} · {len(posts)} post{"s" if len(posts) != 1 else ""}</div>
</header>
{body}
</body>
</html>
""")
print(f"rendered {len(posts)} posts -> {OUT}")
