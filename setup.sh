#!/usr/bin/env bash
set -euo pipefail

echo "=== NASy-Peasy Setup ==="

# Load existing .env if present
if [ -f .env ]; then
    set -a; source .env; set +a
fi

# 1. Generate random secret key (or keep existing)
if ! grep -q '^FLASK_SECRET_KEY=' .env 2>/dev/null; then
    SECRET_KEY=$(python3 -c "import secrets; print(secrets.token_hex(32))")
    cat > .env <<EOF
FLASK_SECRET_KEY=$SECRET_KEY
EOF
fi
echo "[1/6] Secret key OK"

if ! command -v podman-compose &>/dev/null; then
    echo "WARNING: podman-compose not found. Install it: pip3 install podman-compose"
fi

# 2. Install pixi dependencies
echo "[2/6] Installing dependencies..."
pixi install

# 3. Shared directory for app data
echo "[3/6] Configuring shared directory..."
SHARED_DIR="${SHARED_DIR:-}"
if [ -z "$SHARED_DIR" ]; then
    read -r -p "Enter a shared directory path for app data (press enter to skip): " SHARED_DIR
fi
if [ -n "$SHARED_DIR" ]; then
    mkdir -p "$SHARED_DIR"
    pixi run add-shared-dir "$SHARED_DIR"
    echo "  Shared directory set to $SHARED_DIR"
fi

# 4. Domain + SSL (Caddy → nginx)
echo ""
echo "[4/6] Domain for secure reverse proxy (Caddy SSL + nginx routing)"
DOMAIN="${DOMAIN:-}"
if [ -z "$DOMAIN" ]; then
    read -r -p "Enter your domain (e.g., nasypeasy.example.com) or press enter to skip: " DOMAIN
fi
mkdir -p logs apps.d/nginx

if [ -n "$DOMAIN" ]; then
    # Update or append DOMAIN in .env
    if grep -q '^DOMAIN=' .env 2>/dev/null; then
        sed -i "s/^DOMAIN=.*/DOMAIN=$DOMAIN/" .env
    else
        echo "DOMAIN=$DOMAIN" >> .env
    fi
    sed "s/__DOMAIN__/$DOMAIN/g" Caddyfile.template > Caddyfile
    echo "  Caddy will terminate SSL and proxy to nginx (internal) for $DOMAIN"
else
    rm -f Caddyfile
    echo "  No domain — nginx on port 8080, no SSL."
fi

# Generate nginx.conf (always simple HTTP on port 8069)
python3 << 'PYEOF'
import os
root = os.getcwd()
with open('nginx.conf.template') as f:
    content = f.read()
content = content.replace('__ROOT__', root)
with open('nginx.conf', 'w') as f:
    f.write(content)
print('  nginx.conf generated')
PYEOF

pixi run nginx-start || echo "  WARNING: nginx failed to start. Check logs/nginx-error.log"
echo "  nginx started (background)"

if [ -n "$DOMAIN" ]; then
    pixi run caddy-start || echo "  WARNING: Caddy failed to start. Check logs/caddy.log"
    echo "  Caddy started (background, ports 80/443)"
fi

# 5. Create a user (skip if already exists)
echo "[5/6] Creating admin user..."
USERNAME="${USERNAME:-}"
PASSWORD="${PASSWORD:-}"
if [ -z "$USERNAME" ]; then
    read -r -p "Enter username [admin]: " USERNAME
    USERNAME="${USERNAME:-admin}"
fi
if [ -z "$PASSWORD" ]; then
    read -r -s -p "Enter password: " PASSWORD
    echo ""
    read -r -s -p "Confirm password: " PASSWORD2
    echo ""
    if [ "$PASSWORD" != "$PASSWORD2" ]; then
        echo "ERROR: Passwords do not match"
        exit 1
    fi
fi
pixi run create-user "$USERNAME" "$PASSWORD"

# 6. Tailscale API key (optional)
echo ""
echo "[6/6] Optional: Tailscale API key for remote access"
TS_KEY="${TAILSCALE_API_KEY:-}"
TS_TAILNET="${TAILSCALE_TAILNET:-}"
if [ -z "$TS_KEY" ]; then
    read -r -p "Tailscale API key (press enter to skip): " TS_KEY
fi
if [ -n "$TS_KEY" ] && [ -z "$TS_TAILNET" ]; then
    read -r -p "Tailscale tailnet name: " TS_TAILNET
fi
if [ -n "$TS_KEY" ]; then
    # Remove old tailscale lines and append fresh ones
    sed -i '/^TAILSCALE_/d' .env 2>/dev/null || true
    cat >> .env <<EOF
TAILSCALE_API_KEY=$TS_KEY
TAILSCALE_TAILNET=$TS_TAILNET
EOF
    echo "  Tailscale vars appended to .env"
fi

echo ""
echo "=== Setup complete! ==="
echo ""
echo "Start the dashboard:"
echo "  pixi run up      # containerized dashboard (fresh build)"
echo "  pixi run fresh   # containerized dashboard (rebuild)"
echo ""
echo "Other services:"
echo "  pixi run host-agent  # collects podman/tailscale data"
echo "  pixi run caddy-logs  # tail Caddy log"
echo "  pixi run nginx-logs  # tail nginx log"
echo ""
echo "Access the dashboard at:"
if [ -n "$DOMAIN" ]; then
    echo "  https://$DOMAIN"
fi
echo "  http://localhost:5000"
