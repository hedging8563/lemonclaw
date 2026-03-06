#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
repo_root="$(cd "$script_dir/.." && pwd)"
webui_dir="$repo_root/lemonclaw/gateway/webui/webui-v2"

cd "$webui_dir"

echo "Checking webui-v2 package.json/package-lock.json consistency..."
npm ci --dry-run --ignore-scripts --no-audit --no-fund
