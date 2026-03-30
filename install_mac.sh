#!/usr/bin/env bash
# RC Car Track Timer – macOS installer
set -e

echo "=== RC Car Track Timer – macOS Setup ==="

# 1. Check for Python 3
if ! command -v python3 &>/dev/null; then
  echo "Python 3 not found. Please install it from https://python.org and re-run."
  exit 1
fi

echo "Python 3 found: $(python3 --version)"

# 2. Create / activate a virtual environment
if [ ! -d ".venv" ]; then
  echo "Creating virtual environment..."
  python3 -m venv .venv
fi

source .venv/bin/activate

# 3. Upgrade pip silently
pip install --upgrade pip -q

# 4. Install dependencies
echo "Installing dependencies (this may take a minute)..."
pip install -r requirements.txt -q

echo ""
echo "=== Setup complete! ==="
echo ""
echo "To launch the timer, run:"
echo "  source .venv/bin/activate && python3 rc_timer.py"
echo ""
echo "Or just double-click run_timer.command (created below)."

# 5. Create a double-clickable launcher
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cat > "$SCRIPT_DIR/run_timer.command" <<EOF
#!/usr/bin/env bash
cd "$(dirname "$0")"
source .venv/bin/activate
python3 rc_timer.py
EOF
chmod +x "$SCRIPT_DIR/run_timer.command"
echo "Launcher created: run_timer.command"
