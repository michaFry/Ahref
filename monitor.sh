#!/usr/bin/env bash
# Hourly Reddit monitor for an immobilier / gestion-locative SaaS.
# Fetches /r/<sub>/new.json for each sub in subreddits.txt, filters posts
# whose title or body matches any keyword in keywords.txt, dedupes by post
# id, appends matches to data/alerts.json, and regenerates index.html.
#
# Auth modes (auto-detected):
#   - If REDDIT_CLIENT_ID and REDDIT_CLIENT_SECRET are set:
#       OAuth "client_credentials" flow against oauth.reddit.com.
#       Strongly recommended on shared infra (GitHub Actions, cloud VMs) —
#       Reddit's anti-bot routinely returns 403 to unauthenticated traffic
#       from those IP ranges.
#   - Otherwise: anonymous GET to www.reddit.com. Usually fine from a home IP.
#
# Designed for cron — silent on success, errors go to data/monitor.log.

set -euo pipefail
cd "$(dirname "$(readlink -f "$0")")"

UA="immobilier-saas-monitor/1.0 (gestion locative lead watcher)"
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

# --- Auth ---------------------------------------------------------------
API_HOST="https://www.reddit.com"
AUTH_HEADER=()
if [ -n "${REDDIT_CLIENT_ID:-}" ] && [ -n "${REDDIT_CLIENT_SECRET:-}" ]; then
  token_resp=$(curl -fsSL --max-time 15 \
    -u "${REDDIT_CLIENT_ID}:${REDDIT_CLIENT_SECRET}" \
    -A "$UA" \
    -d "grant_type=client_credentials" \
    "https://www.reddit.com/api/v1/access_token" 2>>"$LOG" || true)
  token=$(echo "$token_resp" | jq -r '.access_token // empty')
  if [ -n "$token" ]; then
    API_HOST="https://oauth.reddit.com"
    AUTH_HEADER=(-H "Authorization: bearer $token")
    log "OAuth token acquired"
  else
    log "WARN: OAuth token request failed, falling back to anonymous"
  fi
fi

# Build a single case-insensitive regex from keywords.txt.
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
  sub="${sub%%#*}"
  sub="$(echo "$sub" | xargs)"
  [ -z "$sub" ] && continue
  sub="${sub#r/}"

  # OAuth endpoint uses /r/<sub>/new (no .json); www endpoint uses .json.
  if [[ "$API_HOST" == *"oauth.reddit.com"* ]]; then
    url="${API_HOST}/r/${sub}/new?limit=50&raw_json=1"
  else
    url="${API_HOST}/r/${sub}/new.json?limit=50&raw_json=1"
  fi

  if ! resp=$(curl -fsSL --max-time 20 -A "$UA" "${AUTH_HEADER[@]}" "$url" 2>>"$LOG"); then
    log "WARN: fetch failed for r/$sub"
    continue
  fi
  fetched=$((fetched + 1))

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
    # `command grep` bypasses any shell wrapper that rewrites
    # `grep <pattern> <file>` into a recursive search.
    if command grep -qxF -- "$id" "$SEEN"; then
      continue
    fi
    echo "$id" >> "$SEEN"
    haystack=$(jq -r '.title + " \n " + .selftext' <<<"$post")
    if echo "$haystack" | command grep -qiE -- "$KEYWORDS_REGEX"; then
      echo "$post" >> "$NEW_MATCHES_FILE"
    fi
  done

  sleep 1
done < "$SUBS_FILE"

if [ -s "$NEW_MATCHES_FILE" ]; then
  matched=$(wc -l < "$NEW_MATCHES_FILE")
  jq -s 'add | unique_by(.id) | sort_by(-.created_utc)' \
    <(jq -s '.' "$NEW_MATCHES_FILE") "$ALERTS" \
    > "$ALERTS.tmp"
  mv "$ALERTS.tmp" "$ALERTS"
fi

python3 render.py

log "fetched=$fetched matched=$matched total=$(jq length "$ALERTS")"
