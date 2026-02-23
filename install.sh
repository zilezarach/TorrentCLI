#!/usr/bin/env bash
# =============================================================================
# Yarr CLI – Installer
# Installs the `yarr` command so it is available system-wide without having
# to activate a virtual-environment manually.
#
# Usage:
#   chmod +x install.sh
#   ./install.sh
# =============================================================================
set -euo pipefail

# ── Colours ──────────────────────────────────────────────────────────────────
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
BOLD='\033[1m'
NC='\033[0m'

info()    { echo -e "${CYAN}[INFO]${NC}  $*"; }
success() { echo -e "${GREEN}[OK]${NC}    $*"; }
warn()    { echo -e "${YELLOW}[WARN]${NC}  $*"; }
error()   { echo -e "${RED}[ERROR]${NC} $*" >&2; exit 1; }

# ── Banner ───────────────────────────────────────────────────────────────────
echo -e "${BOLD}"
cat <<'EOF'
  ██╗   ██╗ █████╗ ██████╗ ██████╗
  ╚██╗ ██╔╝██╔══██╗██╔══██╗██╔══██╗
   ╚████╔╝ ███████║██████╔╝██████╔╝
    ╚██╔╝  ██╔══██║██╔══██╗██╔══██╗
     ██║   ██║  ██║██║  ██║██║  ██║
     ╚═╝   ╚═╝  ╚═╝╚═╝  ╚═╝╚═╝  ╚═╝

  🏴‍☠️  The Pirate's Terminal – Installer  🏴‍☠️
EOF
echo -e "${NC}"

# ── Prerequisites ─────────────────────────────────────────────────────────────
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

info "Checking prerequisites …"

# Python 3.9+
if ! command -v python3 &>/dev/null; then
    error "python3 not found. Install Python 3.9+ and re-run."
fi
PY_VER=$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
PY_MAJOR=$(echo "$PY_VER" | cut -d. -f1)
PY_MINOR=$(echo "$PY_VER" | cut -d. -f2)
if [[ "$PY_MAJOR" -lt 3 || ( "$PY_MAJOR" -eq 3 && "$PY_MINOR" -lt 10 ) ]]; then
    error "Python 3.10+ required (found $PY_VER)."
fi
success "Python $PY_VER found"

# pip
if ! python3 -m pip --version &>/dev/null; then
    error "pip not found. Install pip and re-run (e.g. python3 -m ensurepip --upgrade)."
fi

# qBittorrent (optional – warn only)
if ! command -v qbittorrent &>/dev/null && ! command -v qbittorrent-nox &>/dev/null; then
    warn "qBittorrent not found. Torrent downloads require qBittorrent with Web UI enabled."
    warn "Install via your package manager, e.g.: sudo apt install qbittorrent-nox"
fi

# ── zil_tor (backbone API server) ─────────────────────────────────────────────
echo ""
echo -e "${BOLD}Step 1 – zil_tor API backend${NC}"
echo "────────────────────────────────────────────────────────"
info "The TUI relies on the zil_tor Go API server (https://github.com/zilezarach/zil_tor)."
info "It must be running before you use 'yarr'."

ZIL_TOR_INSTALLED=false
if command -v docker &>/dev/null; then
    success "Docker found – you can run zil_tor with Docker (recommended)."
    ZIL_TOR_INSTALLED=true
    cat <<'DOCKER_TIP'

  Quickstart with Docker:
    docker pull ghcr.io/zilezarach/zil_tor:latest
    docker run -d --name zil_tor -p 9117:9117 ghcr.io/zilezarach/zil_tor:latest

  Or use the docker-compose file from the zil_tor repo:
    git clone https://github.com/zilezarach/zil_tor.git
    cd zil_tor && docker-compose up -d

DOCKER_TIP
elif command -v go &>/dev/null; then
    success "Go toolchain found – you can build zil_tor from source."
    ZIL_TOR_INSTALLED=true
    cat <<'GO_TIP'

  Build from source:
    git clone https://github.com/zilezarach/zil_tor.git
    cd zil_tor && go build -o zil_tor ./cmd/server
    ./zil_tor  # listens on :9117

GO_TIP
else
    warn "Neither Docker nor Go found. Install one to run the zil_tor backend."
    warn "See: https://github.com/zilezarach/zil_tor#installation"
fi

# ── Choose installation method ────────────────────────────────────────────────
echo ""
echo -e "${BOLD}Step 2 – Install yarr${NC}"
echo "────────────────────────────────────────────────────────"

USE_PIPX=false
if command -v pipx &>/dev/null; then
    info "pipx detected – using pipx for isolated installation (recommended)."
    USE_PIPX=true
elif python3 -m pipx --version &>/dev/null 2>&1; then
    info "pipx (via python3 -m pipx) detected – using pipx."
    USE_PIPX=true
fi

if $USE_PIPX; then
    # ── pipx installation ─────────────────────────────────────────────────────
    info "Installing yarr with pipx …"
    if command -v pipx &>/dev/null; then
        pipx install --force "$SCRIPT_DIR"
    else
        python3 -m pipx install --force "$SCRIPT_DIR"
    fi
    success "yarr installed via pipx."
    echo ""
    info "Ensure pipx's bin directory is on your PATH:"
    echo "  $(python3 -m pipx environment --value PIPX_BIN_DIR 2>/dev/null || echo '~/.local/bin')"
    echo "  Add to ~/.bashrc or ~/.zshrc: export PATH=\"\$HOME/.local/bin:\$PATH\""
else
    # ── venv + wrapper-script installation ────────────────────────────────────
    VENV_DIR="$SCRIPT_DIR/.venv"
    info "Creating virtual environment at $VENV_DIR …"
    python3 -m venv "$VENV_DIR"
    success "Virtual environment created."

    info "Installing Python dependencies …"
    "$VENV_DIR/bin/pip" install --quiet --upgrade pip
    "$VENV_DIR/bin/pip" install --quiet "$SCRIPT_DIR"
    success "Dependencies installed."

    # Create a thin wrapper script so the user never needs to activate the venv
    WRAPPER="$SCRIPT_DIR/yarr-run"
    cat > "$WRAPPER" <<WRAPPER_SCRIPT
#!/usr/bin/env bash
exec "$VENV_DIR/bin/yarr" "\$@"
WRAPPER_SCRIPT
    chmod +x "$WRAPPER"

    # Try to install the wrapper to a directory on PATH
    INSTALL_DIR=""
    for candidate in "$HOME/.local/bin" /usr/local/bin; do
        if [[ -d "$candidate" && -w "$candidate" ]]; then
            INSTALL_DIR="$candidate"
            break
        fi
    done

    if [[ -n "$INSTALL_DIR" ]]; then
        cp "$WRAPPER" "$INSTALL_DIR/yarr"
        success "Installed yarr to $INSTALL_DIR/yarr"
    else
        warn "Could not find a writable directory on PATH."
        warn "Run the following to install manually (may need sudo):"
        echo "  sudo cp \"$WRAPPER\" /usr/local/bin/yarr"
        warn "Or add $SCRIPT_DIR to your PATH:"
        echo "  export PATH=\"$SCRIPT_DIR:\$PATH\""
    fi
fi

# ── Post-install instructions ─────────────────────────────────────────────────
echo ""
echo -e "${BOLD}${GREEN}✓ Installation complete!${NC}"
echo "════════════════════════════════════════════════════════"
echo ""
echo -e "${BOLD}Getting started:${NC}"
echo ""
echo "  1. Start the zil_tor API backend (see Step 1 above)."
echo ""
echo "  2. Start qBittorrent with Web UI enabled on http://127.0.0.1:8080"
echo "     (Preferences → Web UI → Enable the Web User Interface)."
echo ""
echo "  3. Run yarr:"
echo "     yarr             # interactive menu"
echo "     yarr browse      # interactive search & download"
echo "     yarr search <q>  # quick search"
echo "     yarr --help      # all commands"
echo ""
echo "  4. (Optional) edit ~/.yarr/config.json to customise paths and credentials."
echo ""
echo -e "${CYAN}Documentation:${NC} https://github.com/zilezarach/TorrentCLI"
echo -e "${CYAN}API backend:${NC}   https://github.com/zilezarach/zil_tor"
echo ""
