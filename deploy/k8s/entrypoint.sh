#!/bin/bash
# LemonClaw K8s Entrypoint
#
# Simplified vs OpenClaw (395 lines → ~80 lines):
#   - No crash-guard.cjs (Python has no undici TLS bug)
#   - No config-sync.cjs (Python loader handles env overrides)
#   - No token-inject.cjs (no WebUI to inject into)
#   - No install-plugins.sh (all channels built into Python package)
#   - No auto-pairing.cjs (will be built-in Python, P1)
#   - No skill removal hacks (we control the codebase)
#
# Required env vars:
#   GATEWAY_TOKEN  - Auth token for /api/status endpoint
#   API_BASE_URL   - LemonData API (e.g. https://api.lemondata.cc/v1)
#   API_KEY        - LemonData API key (sk-xxx)
# Optional:
#   DEFAULT_MODEL  - Default model ID (default: claude-sonnet-4-6)
#   INSTANCE_ID    - Instance identifier
#   LOG_TARGET     - stdout (default) or file
set -euo pipefail

# --- Persistent overlay filesystem ---
# PVC at /mnt/persist: durable storage backend.
# overlayfs merges image (read-only) with PVC (read-write).
PERSIST_DIR="/mnt/persist"
OVERLAY_UPPER="$PERSIST_DIR/.overlay/upper"
OVERLAY_WORK="$PERSIST_DIR/.overlay/work"

if [ -d "$PERSIST_DIR" ]; then
    overlay_ok=0
    overlay_fail=0
    for dir in /home/lemonclaw /tmp /var; do
        safe_name=$(echo "$dir" | tr '/' '_')
        mkdir -p "$OVERLAY_UPPER$dir" "$OVERLAY_WORK/$safe_name"
        chmod --reference="$dir" "$OVERLAY_UPPER$dir" 2>/dev/null || true
        if mount -t overlay overlay \
            -o "lowerdir=$dir,upperdir=$OVERLAY_UPPER$dir,workdir=$OVERLAY_WORK/$safe_name" \
            "$dir"; then
            overlay_ok=$((overlay_ok + 1))
        else
            echo "WARNING: overlay mount failed for $dir" >&2
            overlay_fail=$((overlay_fail + 1))
        fi
    done
    echo "Overlay: $overlay_ok mounted, $overlay_fail failed"
else
    echo "No PVC at $PERSIST_DIR, running without persistence"
fi

# --- Validate required env vars ---
for var in GATEWAY_TOKEN API_BASE_URL API_KEY; do
    if [ -z "${!var:-}" ]; then
        echo "ERROR: Required env var $var is not set" >&2
        exit 1
    fi
done

# --- Generate minimal config if missing ---
# Python's config/loader.py _apply_env_overrides() handles the rest:
#   API_KEY → all 3 LemonData providers
#   API_BASE_URL → correct /v1 vs no-/v1 per provider
#   GATEWAY_TOKEN → gateway.auth_token
#   DEFAULT_MODEL → agents.defaults.model
#   INSTANCE_ID → lemondata.instance_id
CONFIG_DIR="/home/lemonclaw/.lemonclaw"
CONFIG_FILE="$CONFIG_DIR/config.json"

if [ ! -f "$CONFIG_FILE" ]; then
    mkdir -p "$CONFIG_DIR"
    echo '{}' > "$CONFIG_FILE"
    echo "Generated empty config at $CONFIG_FILE (env overrides handle the rest)"
else
    echo "Config exists at $CONFIG_FILE, preserving"
fi

# --- Ensure workspace has latest SOUL.md ---
WORKSPACE_DIR="$CONFIG_DIR/workspace"
SOUL_FILE="$WORKSPACE_DIR/SOUL.md"
TEMPLATE_SOUL="/app/lemonclaw/templates/SOUL.md"
mkdir -p "$WORKSPACE_DIR/sessions" "$WORKSPACE_DIR/memory" "$WORKSPACE_DIR/skills"

if [ ! -f "$SOUL_FILE" ]; then
    cp "$TEMPLATE_SOUL" "$SOUL_FILE"
    echo "Initialized SOUL.md from template"
elif grep -q "nanobot" "$SOUL_FILE" 2>/dev/null; then
    cp "$TEMPLATE_SOUL" "$SOUL_FILE"
    echo "Upgraded SOUL.md (replaced nanobot version)"
fi

# --- Run user startup script if present ---
USER_STARTUP="$CONFIG_DIR/startup.sh"
if [ -f "$USER_STARTUP" ]; then
    echo "Running user startup: $USER_STARTUP"
    bash "$USER_STARTUP" || echo "Warning: startup.sh exited $?"
fi

# --- Export for Python config loader ---
export HOME="/home/lemonclaw"
export LOG_TARGET="${LOG_TARGET:-stdout}"

# --- Browser tool env (agent-browser) ---
export AGENT_BROWSER_CONTENT_BOUNDARIES="${AGENT_BROWSER_CONTENT_BOUNDARIES:-1}"
export PLAYWRIGHT_BROWSERS_PATH="/ms-playwright"

echo "Starting LemonClaw gateway (instance: ${INSTANCE_ID:-unknown})"
exec /usr/local/bin/lemonclaw gateway --bind lan --port 18789