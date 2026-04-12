#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
repo_root="$(cd "$script_dir/.." && pwd)"
source_dir="${LEMONCLAW_SOURCE_DIR:-$repo_root/lemonclaw}"
if [[ -d "$source_dir/gateway/webui/webui-v2" ]]; then
  webui_dir="$source_dir/gateway/webui/webui-v2"
  static_dir="$source_dir/gateway/webui/static"
elif [[ -d "$source_dir/lemonclaw/gateway/webui/webui-v2" ]]; then
  webui_dir="$source_dir/lemonclaw/gateway/webui/webui-v2"
  static_dir="$source_dir/lemonclaw/gateway/webui/static"
else
  webui_dir="$source_dir/gateway/webui/webui-v2"
  static_dir="$source_dir/gateway/webui/static"
fi

if [[ ! -d "$webui_dir" ]]; then
  echo "WebUI directory not found: $webui_dir" >&2
  exit 1
fi

cd "$webui_dir"

echo "Installing webui-v2 dependencies..."
npm ci --ignore-scripts --no-audit --no-fund

echo "Building webui-v2..."
npm run build

cd "$source_dir"
status="$(git status --porcelain -- "$static_dir")"
if [[ -n "$status" ]]; then
  echo "WebUI static assets are out of sync with source."
  echo "Run: cd $webui_dir && npm run build"
  echo
  echo "$status"
  exit 1
fi

echo "WebUI static assets are in sync."
