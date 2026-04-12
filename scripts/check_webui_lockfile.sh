#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
repo_root="$(cd "$script_dir/.." && pwd)"
source_dir="${LEMONCLAW_SOURCE_DIR:-$repo_root/lemonclaw}"
if [[ -d "$source_dir/gateway/webui/webui-v2" ]]; then
  webui_dir="$source_dir/gateway/webui/webui-v2"
elif [[ -d "$source_dir/lemonclaw/gateway/webui/webui-v2" ]]; then
  webui_dir="$source_dir/lemonclaw/gateway/webui/webui-v2"
else
  webui_dir="$source_dir/gateway/webui/webui-v2"
fi

if [[ ! -d "$webui_dir" ]]; then
  echo "WebUI directory not found: $webui_dir" >&2
  exit 1
fi

cd "$webui_dir"

echo "Checking webui-v2 package.json/package-lock.json consistency..."
npm ci --dry-run --ignore-scripts --no-audit --no-fund
