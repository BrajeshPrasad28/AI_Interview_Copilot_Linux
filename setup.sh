#!/usr/bin/env bash
# setup.sh — Automated setup for AI Interview Copilot on Linux
# Usage: bash setup.sh
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

echo "=================================================="
echo "  AI Interview Copilot — Linux Setup Wizard"
echo "=================================================="

# 1. Check Python
if ! command -v python3 &>/dev/null; then
    echo "❌ Python 3 not found. Install it with:"
    echo "   sudo apt install python3 python3-venv python3-pip   # Debian/Ubuntu"
    echo "   sudo dnf install python3                             # Fedora"
    exit 1
fi
echo "✅ Python $(python3 --version) found."

if ! python3 -c 'import sys; raise SystemExit(sys.version_info < (3, 10))'; then
    echo "❌ Python 3.10 or newer is required."
    exit 1
fi

# 2. Install system dependencies (audio + GTK/WebKit)
echo ""
echo "📋 Installing system dependencies (requires sudo)..."
if command -v apt-get &>/dev/null; then
    sudo apt-get update
    APT_PACKAGES=(
        python3-venv
        portaudio19-dev
        python3-gi python3-gi-cairo
        gir1.2-gtk-3.0
        build-essential
    )
    if ! sudo apt-get install -y "${APT_PACKAGES[@]}" gir1.2-webkit2-4.1; then
        sudo apt-get install -y "${APT_PACKAGES[@]}" gir1.2-webkit2-4.0
    fi
elif command -v dnf &>/dev/null; then
    sudo dnf install -y portaudio-devel gobject-introspection-devel webkit2gtk3-devel gcc 2>/dev/null || true
elif command -v pacman &>/dev/null; then
    sudo pacman -Sy --noconfirm portaudio python-gobject webkit2gtk 2>/dev/null || true
fi

# 3. Create virtual environment with access to Ubuntu's system GTK bindings
if [ ! -d ".venv" ]; then
    echo "📦 Creating virtual environment..."
    python3 -m venv --system-site-packages .venv
fi

PYTHON=".venv/bin/python"
PIP=".venv/bin/pip"

# 4. Install Python dependencies
echo ""
echo "📦 Installing Python dependencies..."
"$PIP" install --upgrade pip wheel
"$PIP" install -r requirements.txt

# 5. Create desktop shortcut
echo ""
echo "🖥️  Creating desktop shortcut..."
"$PYTHON" create_shortcut.py || true

# 6. Done
echo ""
echo "=================================================="
echo "  ✅ Setup complete!"
echo ""
echo "  To launch: bash run.sh"
echo "  Or:        .venv/bin/python run.py"
echo "  Browser:   .venv/bin/python run.py --browser"
echo "=================================================="
