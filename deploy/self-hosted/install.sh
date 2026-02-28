#!/bin/bash
# ============================================================
# LemonClaw Self-Hosted Installer
# ============================================================
# Bootstrap script for environments without Python.
# Downloads and installs Python 3.12+, then delegates to:
#   pip install lemonclaw && lemonclaw init
#
# Usage:
#   curl -O https://raw.githubusercontent.com/hedging8563/lemonclaw/main/deploy/self-hosted/install.sh
#   sha256sum install.sh   # verify against GitHub Release page
#   bash install.sh
# ============================================================

set -euo pipefail

# -- Colors --
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[0;33m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color

info()  { echo -e "${CYAN}[INFO]${NC}  $*"; }
ok()    { echo -e "${GREEN}[OK]${NC}    $*"; }
warn()  { echo -e "${YELLOW}[WARN]${NC}  $*"; }
fail()  { echo -e "${RED}[FAIL]${NC}  $*"; exit 1; }

# -- Detect OS --
OS="$(uname -s)"
ARCH="$(uname -m)"

case "$OS" in
    Darwin) OS_TYPE="macos" ;;
    Linux)  OS_TYPE="linux" ;;
    *)      fail "Unsupported OS: $OS. LemonClaw requires macOS or Linux." ;;
esac

info "Detected: $OS $ARCH ($OS_TYPE)"

# -- Find Python >= 3.11 --
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

PYTHON=""
if PYTHON=$(find_python); then
    ok "Found Python: $PYTHON ($($PYTHON --version 2>&1))"
else
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

    # Re-check
    if PYTHON=$(find_python); then
        ok "Python installed: $PYTHON ($($PYTHON --version 2>&1))"
    else
        fail "Python installation failed. Please install Python >= 3.11 manually."
    fi
fi

# -- Ensure pip is available --
if ! "$PYTHON" -m pip --version >/dev/null 2>&1; then
    warn "pip not found, attempting to install..."
    "$PYTHON" -m ensurepip --default-pip 2>/dev/null || true
    if ! "$PYTHON" -m pip --version >/dev/null 2>&1; then
        fail "pip not available. Install it: $PYTHON -m ensurepip"
    fi
fi

# -- Check for uv (faster installs) --
USE_UV=false
if command -v uv >/dev/null 2>&1; then
    ok "Found uv package manager (using for faster install)"
    USE_UV=true
fi

# -- Install lemonclaw --
info "Installing lemonclaw..."

if [ "$USE_UV" = true ]; then
    uv pip install lemonclaw
else
    "$PYTHON" -m pip install --user lemonclaw
fi

# Verify installation
if command -v lemonclaw >/dev/null 2>&1; then
    ok "lemonclaw installed: $(lemonclaw --version 2>&1)"
elif "$PYTHON" -m lemonclaw --version >/dev/null 2>&1; then
    ok "lemonclaw installed (via python -m)"
    # Create wrapper
    warn "lemonclaw not on PATH. You may need to add ~/.local/bin to PATH."
else
    fail "lemonclaw installation failed."
fi

# -- Verify checksum (optional, if EXPECTED_SHA256 is set) --
if [ -n "${EXPECTED_SHA256:-}" ]; then
    LC_BIN="$(command -v lemonclaw 2>/dev/null || echo "")"
    if [ -n "$LC_BIN" ]; then
        if command -v sha256sum >/dev/null 2>&1; then
            ACTUAL_SHA256="$(sha256sum "$LC_BIN" | awk '{print $1}')"
        elif command -v shasum >/dev/null 2>&1; then
            ACTUAL_SHA256="$(shasum -a 256 "$LC_BIN" | awk '{print $1}')"
        else
            warn "sha256sum/shasum not found, skipping checksum verification."
            ACTUAL_SHA256=""
        fi

        if [ -n "$ACTUAL_SHA256" ]; then
            if [ "$ACTUAL_SHA256" = "$EXPECTED_SHA256" ]; then
                ok "Checksum verified: $ACTUAL_SHA256"
            else
                fail "Checksum mismatch!\n  Expected: $EXPECTED_SHA256\n  Actual:   $ACTUAL_SHA256\n  This may indicate a tampered package. Aborting."
            fi
        fi
    else
        warn "Cannot locate lemonclaw binary for checksum verification."
    fi
else
    info "Tip: Set EXPECTED_SHA256=<hash> before running to verify package integrity."
fi

# -- Run init wizard --
echo ""
info "Starting LemonClaw setup wizard..."
echo ""

if command -v lemonclaw >/dev/null 2>&1; then
    lemonclaw init
else
    "$PYTHON" -m lemonclaw init
fi
