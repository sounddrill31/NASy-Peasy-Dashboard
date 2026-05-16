#!/usr/bin/env bash
set -euo pipefail

echo "=== NASy-Peasy Setup ==="

# 1. Generate random secret key
SECRET_KEY=$(python3 -c "import secrets; print(secrets.token_hex(32))")
cat > .env <<EOF
FLASK_SECRET_KEY=$SECRET_KEY
EOF
echo "[1/5] Secret key generated"

if ! command -v podman-compose &>/dev/null; then
    echo "WARNING: podman-compose not found. Install it: sudo zypper install podman podman-compose"
fi

# 2. Install pixi dependencies
echo "[2/5] Installing dependencies..."
pixi install

# 3. Shared directory for app data
echo "[3/5] Configuring shared directory..."
read -r -p "Enter a shared directory path for app data (press enter to skip): " SHARED_DIR
if [ -n "$SHARED_DIR" ]; then
    mkdir -p "$SHARED_DIR"
    pixi run add-shared-dir "$SHARED_DIR"
    echo "  Shared directory set to $SHARED_DIR"
fi

# 4. Create a user
echo "[4/5] Creating admin user..."
echo ""
read -r -p "Enter username [admin]: " USERNAME
USERNAME="${USERNAME:-admin}"
read -r -s -p "Enter password: " PASSWORD
echo ""
read -r -s -p "Confirm password: " PASSWORD2
echo ""
if [ "$PASSWORD" != "$PASSWORD2" ]; then
    echo "ERROR: Passwords do not match"
    exit 1
fi
pixi run create-user "$USERNAME" "$PASSWORD"

# 5. Tailscale API key (optional)
echo ""
echo "[5/5] Optional: Tailscale API key for remote access"
read -r -p "Tailscale API key (press enter to skip): " TS_KEY
if [ -n "$TS_KEY" ]; then
    read -r -p "Tailscale tailnet name: " TS_TAILNET
    cat >> .env <<EOF
TAILSCALE_API_KEY=$TS_KEY
TAILSCALE_TAILNET=$TS_TAILNET
EOF
    echo "  Tailscale vars appended to .env"
fi

echo ""
echo "=== Setup complete! ==="
echo ""
echo "Start the host agent (collects podman/tailscale data):"
echo "  pixi run host-agent"
echo ""
echo "Then start the dashboard:"
echo "  pixi run server    # containerized"
echo "  pixi run start     # directly on host"
echo ""
echo "Access the dashboard at http://localhost:5000"
