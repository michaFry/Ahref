#!/usr/bin/env bash
# Hourly Reddit monitor for an immobilier / gestion-locative SaaS.
# Fetches /r/<sub>/new.json for each sub in subreddits.txt, filters posts
# whose title or body matches any keyword in keywords.txt, dedupes by post
# id, appends matches to data/alerts.json, and regenerates index.html.
#
# Designed for cron — silent on success, errors go to data/monitor.log.

set -euo pipefail
cd "$(dirname "$(readlink -f "$0")")"

UA="immobilier-saas-monitor/1.0 (Reddit lead watcher)"
SUBS_FILE="subreddits.txt"
KW_FILE="keywords.txt"
DATA_DIR="data"
SEEN="$DATA_DIR/seen.txt"
ALERTS="$DATA_DIR/alerts.json"
LOG="$DATA_DIR/monitor.log"

mkdir -p "$DATA_DIR"
touch "$SEEN"
[ -s "$ALERTS" ] || echo "[]" > "$ALERTS"

log() { echo "[$(date -Iseconds)] $*" >> "$LOG"; }

# Build a single case-insensitive regex from keywords.txt.
# Special regex chars in keywords are escaped.
KEYWORDS_REGEX=$(
  awk 'NF && !/^[[:space:]]*#/' "$KW_FILE" \
    | sed -E 's/[][\\.^$|?*+(){}]/\\&/g' \
    | paste -sd'|' -
)
if [ -z "$KEYWORDS_REGEX" ]; then
  log "ERROR: no keywords configured"
  exit 1
fi

NEW_MATCHES_FILE=$(mktemp)
trap 'rm -f "$NEW_MATCHES_FILE"' EXIT

fetched=0
matched=0

while IFS= read -r sub; do
  # Skip blanks and comments
  sub="${sub%%#*}"
  sub="$(echo "$sub" | xargs)"
  [ -z "$sub" ] && continue
  sub="${sub#r/}"

  url="https://www.reddit.com/r/${sub}/new.json?limit=50"
  if ! resp=$(curl -fsSL --max-time 20 -A "$UA" "$url" 2>>"$LOG"); then
    log "WARN: fetch failed for r/$sub"
    continue
  fi
  fetched=$((fetched + 1))

  # Stream posts as JSON lines
  echo "$resp" | jq -c --arg sub "$sub" '
    .data.children[]?.data
    | select(.title != null)
    | {
        id,
        subreddit: $sub,
        title,
        selftext: (.selftext // ""),
        url: ("https://www.reddit.com" + .permalink),
        created_utc,
        author: (.author // "[deleted]")
      }
  ' | while IFS= read -r post; do
    id=$(jq -r '.id' <<<"$post")
    # Skip if already seen. `command grep` bypasses any shell wrapper that
    # might rewrite `grep <pattern> <file>` into a recursive search.
    if command grep -qxF -- "$id" "$SEEN"; then
      continue
    fi
    echo "$id" >> "$SEEN"
    haystack=$(jq -r '.title + " \n " + .selftext' <<<"$post")
    if echo "$haystack" | command grep -qiE -- "$KEYWORDS_REGEX"; then
      echo "$post" >> "$NEW_MATCHES_FILE"
    fi
  done

  # Be polite to Reddit (no auth, public JSON endpoint)
  sleep 1
done < "$SUBS_FILE"

if [ -s "$NEW_MATCHES_FILE" ]; then
  matched=$(wc -l < "$NEW_MATCHES_FILE")
  jq -s 'add | unique_by(.id) | sort_by(-.created_utc)' \
    <(jq -s '.' "$NEW_MATCHES_FILE") "$ALERTS" \
    > "$ALERTS.tmp"
  mv "$ALERTS.tmp" "$ALERTS"
fi

# Regenerate the static page
python3 render.py

log "fetched=$fetched matched=$matched total=$(jq length "$ALERTS")"
