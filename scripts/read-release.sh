#!/usr/bin/env bash
# Read one published stable GitHub release for the deploy lock.
# xtrace stays off so GH_TOKEN is never echoed.
set +x
set -euo pipefail

: "${GH_TOKEN:?}"
: "${GITHUB_REPOSITORY:?}"
: "${RELEASE_TAG:?}"

hdr=$(mktemp)
body=$(mktemp)
trap 'rm -f "$hdr" "$body"' EXIT

rate_remaining() {
  local value=""
  if [[ -f "$hdr" ]]; then
    value=$(
      grep -i '^x-ratelimit-remaining:' "$hdr" 2>/dev/null |
        tail -n 1 |
        cut -d: -f2- |
        tr -d '[:space:]' || true
    )
  fi
  if [[ -z "$value" ]]; then
    printf 'unknown'
  else
    printf '%s' "$value"
  fi
}

fail() {
  printf 'release read failed: HTTP %s, x-ratelimit-remaining=%s\n' "$1" "$(rate_remaining)"
  exit 1
}

attempt=1
while [[ "$attempt" -le 3 ]]; do
  curl_exit=0
  status=$(curl -sS --max-time 20 -D "$hdr" -o "$body" -w '%{http_code}' \
    -H 'Accept: application/vnd.github+json' \
    -H "Authorization: Bearer $GH_TOKEN" \
    -H 'X-GitHub-Api-Version: 2022-11-28' \
    "https://api.github.com/repos/$GITHUB_REPOSITORY/releases/tags/$RELEASE_TAG") || curl_exit=$?
  if [[ "$curl_exit" -ne 0 || -z "$status" || "$status" == "000" ]]; then
    status=000
    kind=000
  elif [[ "$status" =~ ^5[0-9][0-9]$ ]]; then
    kind=5xx
  else
    kind="$status"
  fi
  case "$kind" in
    200)
      if jq -e --arg tag "$RELEASE_TAG" '
        .tag_name == $tag and .draft == false and .prerelease == false and
        (.published_at | type == "string" and length > 0)
      ' "$body" >/dev/null; then
        exit 0
      fi
      fail "$status"
      ;;
    000|403|429|5xx)
      if [[ "$attempt" -lt 3 ]]; then
        sleep 5
        attempt=$((attempt + 1))
        continue
      fi
      fail "$status"
      ;;
    *)
      fail "$status"
      ;;
  esac
done
fail "${status:-000}"
