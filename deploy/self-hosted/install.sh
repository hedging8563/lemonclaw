#!/bin/bash
# ============================================================
# LemonClaw Self-Hosted Installer
# ============================================================
# Installs LemonClaw for a dedicated self-hosted machine.
#
# Defaults:
#   - Reuses Python >= 3.11 if available, otherwise installs it
#   - Uses `uv tool install` when uv is available
#   - Falls back to an isolated venv at ~/.local/share/lemonclaw/venv
#   - Runs `lemonclaw init` at the end unless disabled
#
# Common usage:
#   curl -fsSL https://raw.githubusercontent.com/hedging8563/lemonclaw/main/deploy/self-hosted/install.sh | bash
#
# Optional environment variables:
#   LEMONCLAW_INSTALL_TARGET   Package or URL to install (default: lemonclaw)
#   LEMONCLAW_SKIP_INIT=1      Skip the interactive init wizard
#   LEMONCLAW_NO_UV=1          Force the venv-based installer path
#   LEMONCLAW_BIN_DIR=...      Override binary dir (default: ~/.local/bin)
#   LEMONCLAW_VENV_DIR=...     Override isolated venv dir
# ============================================================

set -euo pipefail

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[0;33m'
CYAN='\033[0;36m'
NC='\033[0m'

info()  { echo -e "${CYAN}[INFO]${NC}  $*"; }
ok()    { echo -e "${GREEN}[OK]${NC}    $*"; }
warn()  { echo -e "${YELLOW}[WARN]${NC}  $*"; }
fail()  { echo -e "${RED}[FAIL]${NC}  $*"; exit 1; }

INSTALL_TARGET="${LEMONCLAW_INSTALL_TARGET:-lemonclaw}"
SKIP_INIT="${LEMONCLAW_SKIP_INIT:-0}"
NO_UV="${LEMONCLAW_NO_UV:-0}"
DEFAULT_BIN_DIR="$HOME/.local/bin"
BIN_DIR="${LEMONCLAW_BIN_DIR:-$DEFAULT_BIN_DIR}"
VENV_DIR="${LEMONCLAW_VENV_DIR:-$HOME/.local/share/lemonclaw/venv}"

OS="$(uname -s)"
ARCH="$(uname -m)"

case "$OS" in
    Darwin) OS_TYPE="macos" ;;
    Linux)  OS_TYPE="linux" ;;
    *)      fail "Unsupported OS: $OS. LemonClaw requires macOS or Linux." ;;
esac

info "Detected: $OS $ARCH ($OS_TYPE)"

find_python() {
    for cmd in python3.12 python3.11 python3 python; do
        if command -v "$cmd" >/dev/null 2>&1; then
            ver=$("$cmd" -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')" 2>/dev/null || echo "0.0")
            major="${ver%%.*}"
            minor="${ver#*.}"
            if [ "$major" -ge 3 ] && [ "$minor" -ge 11 ]; then
                echo "$cmd"
                return 0
            fi
        fi
    done
    return 1
}

install_python() {
    warn "Python >= 3.11 not found. Attempting to install..."

    case "$OS_TYPE" in
        macos)
            if command -v brew >/dev/null 2>&1; then
                info "Installing Python 3.12 via Homebrew..."
                brew install python@3.12
            else
                fail "Homebrew not found. Install it first: https://brew.sh"
            fi
            ;;
        linux)
            if command -v apt-get >/dev/null 2>&1; then
                info "Installing Python 3.12 via apt..."
                sudo apt-get update -qq
                sudo apt-get install -y -qq python3.12 python3.12-venv python3-pip
            elif command -v dnf >/dev/null 2>&1; then
                info "Installing Python 3.12 via dnf..."
                sudo dnf install -y python3.12 python3.12-pip
            elif command -v pacman >/dev/null 2>&1; then
                info "Installing Python via pacman..."
                sudo pacman -Sy --noconfirm python python-pip
            else
                fail "No supported package manager found (apt/dnf/pacman). Install Python >= 3.11 manually."
            fi
            ;;
    esac
}

ensure_pip() {
    if ! "$PYTHON" -m pip --version >/dev/null 2>&1; then
        warn "pip not found, attempting to install..."
        "$PYTHON" -m ensurepip --default-pip 2>/dev/null || true
        if ! "$PYTHON" -m pip --version >/dev/null 2>&1; then
            fail "pip not available. Install it manually for $PYTHON."
        fi
    fi
}

path_has_bin_dir() {
    case ":$PATH:" in
        *":$BIN_DIR:"*) return 0 ;;
        *) return 1 ;;
    esac
}

print_path_hint() {
    if path_has_bin_dir; then
        return 0
    fi

    warn "${BIN_DIR} is not on your PATH. Add it before using lemonclaw in new shells."
    case "${SHELL:-}" in
        */zsh)
            echo "  echo 'export PATH=\"$BIN_DIR:\$PATH\"' >> ~/.zshrc"
            ;;
        */bash)
            echo "  echo 'export PATH=\"$BIN_DIR:\$PATH\"' >> ~/.bashrc"
            ;;
        *)
            echo "  export PATH=\"$BIN_DIR:\$PATH\""
            ;;
    esac
}

resolve_lemonclaw_cmd() {
    if command -v lemonclaw >/dev/null 2>&1; then
        command -v lemonclaw
        return 0
    fi
    if [ -x "$BIN_DIR/lemonclaw" ]; then
        echo "$BIN_DIR/lemonclaw"
        return 0
    fi
    if [ -x "$DEFAULT_BIN_DIR/lemonclaw" ]; then
        echo "$DEFAULT_BIN_DIR/lemonclaw"
        return 0
    fi
    if [ -x "$VENV_DIR/bin/lemonclaw" ]; then
        echo "$VENV_DIR/bin/lemonclaw"
        return 0
    fi
    return 1
}

install_with_uv() {
    info "Installing ${INSTALL_TARGET} with uv tool..."
    mkdir -p "$BIN_DIR"
    uv tool install --upgrade --force --python "$PYTHON" "$INSTALL_TARGET"
    if [ "$BIN_DIR" != "$DEFAULT_BIN_DIR" ] && [ -x "$DEFAULT_BIN_DIR/lemonclaw" ]; then
        ln -sf "$DEFAULT_BIN_DIR/lemonclaw" "$BIN_DIR/lemonclaw"
    fi
}

install_with_venv() {
    info "Installing ${INSTALL_TARGET} into isolated venv: $VENV_DIR"
    mkdir -p "$BIN_DIR"
    mkdir -p "$(dirname "$VENV_DIR")"
    "$PYTHON" -m venv "$VENV_DIR"
    "$VENV_DIR/bin/python" -m pip install --upgrade pip setuptools wheel
    "$VENV_DIR/bin/python" -m pip install --upgrade "$INSTALL_TARGET"
    ln -sf "$VENV_DIR/bin/lemonclaw" "$BIN_DIR/lemonclaw"
}

PYTHON=""
if PYTHON=$(find_python); then
    ok "Found Python: $PYTHON ($($PYTHON --version 2>&1))"
else
    install_python
    if PYTHON=$(find_python); then
        ok "Python installed: $PYTHON ($($PYTHON --version 2>&1))"
    else
        fail "Python installation failed. Please install Python >= 3.11 manually."
    fi
fi

ensure_pip

USE_UV=false
if [ "$NO_UV" != "1" ] && command -v uv >/dev/null 2>&1; then
    ok "Found uv package manager"
    USE_UV=true
fi

if [ "$USE_UV" = true ]; then
    install_with_uv
else
    install_with_venv
fi

LEMONCLAW_CMD="$(resolve_lemonclaw_cmd || true)"
if [ -z "$LEMONCLAW_CMD" ]; then
    fail "lemonclaw installation failed."
fi

ok "Installed LemonClaw: $($LEMONCLAW_CMD --version 2>&1)"
print_path_hint

if [ "$SKIP_INIT" = "1" ]; then
    info "Skipping init wizard because LEMONCLAW_SKIP_INIT=1"
    echo ""
    info "Next steps:"
    echo "  $LEMONCLAW_CMD init"
    echo "  $LEMONCLAW_CMD gateway"
    exit 0
fi

echo ""
info "Starting LemonClaw setup wizard..."
echo ""
"$LEMONCLAW_CMD" init
