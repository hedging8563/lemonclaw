#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
repo_root="$(cd "$script_dir/.." && pwd)"
webui_dir="$repo_root/lemonclaw/gateway/webui/webui-v2"
static_dir="$repo_root/lemonclaw/gateway/webui/static"

cd "$webui_dir"

echo "Installing webui-v2 dependencies..."
npm ci --ignore-scripts --no-audit --no-fund

echo "Building webui-v2..."
npm run build

cd "$repo_root"
status="$(git status --porcelain -- "$static_dir")"
if [[ -n "$status" ]]; then
  echo "WebUI static assets are out of sync with source."
  echo "Run: cd lemonclaw/gateway/webui/webui-v2 && npm run build"
  echo
  echo "$status"
  exit 1
fi

echo "WebUI static assets are in sync."
