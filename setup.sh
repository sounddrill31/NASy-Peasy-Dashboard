#!/usr/bin/env bash
set -euo pipefail

echo "=== NASy-Peasy Setup ==="

# 1. Generate random secret key
SECRET_KEY=$(python3 -c "import secrets; print(secrets.token_hex(32))")
cat > .env <<EOF
FLASK_SECRET_KEY=$SECRET_KEY
EOF
echo "[1/6] Secret key generated"

if ! command -v podman-compose &>/dev/null; then
    echo "WARNING: podman-compose not found. Install it: pip3 install podman-compose"
fi

# 2. Install pixi dependencies
echo "[2/6] Installing dependencies..."
pixi install

# 3. Shared directory for app data
echo "[3/6] Configuring shared directory..."
read -r -p "Enter a shared directory path for app data (press enter to skip): " SHARED_DIR
if [ -n "$SHARED_DIR" ]; then
    mkdir -p "$SHARED_DIR"
    pixi run add-shared-dir "$SHARED_DIR"
    echo "  Shared directory set to $SHARED_DIR"
fi

# 4. Domain + SSL (Caddy)
echo ""
echo "[4/6] Optional: Domain for reverse proxy with auto SSL (Caddy)"
read -r -p "Enter your domain (e.g., nasypeasy.example.com) or press enter to skip: " DOMAIN
if [ -n "$DOMAIN" ]; then
    cat >> .env <<EOF
CADDY_DOMAIN=$DOMAIN
EOF
    cat > Caddyfile <<CADDYEOF
$DOMAIN {
    tls internal
    reverse_proxy localhost:5000
}

:80 {
    reverse_proxy localhost:5000
}
CADDYEOF
    echo "  Caddy configured for https://$DOMAIN"
else
    cp Caddyfile.redirect Caddyfile
    echo "  Caddy configured for HTTP (no domain)"
fi

PROJECT_DIR="$(pwd)"
CADDY_BIN="$PROJECT_DIR/.pixi/envs/default/bin/caddy"
mkdir -p ~/.config/systemd/user
cat > ~/.config/systemd/user/nasypeasy-caddy.service <<UNIT
[Unit]
Description=NASy-Peasy Caddy reverse proxy
After=network-online.target
Wants=network-online.target

[Service]
Type=notify
ExecStart=$CADDY_BIN run --config $PROJECT_DIR/Caddyfile
ExecReload=$CADDY_BIN reload --config $PROJECT_DIR/Caddyfile
Restart=on-failure
RestartSec=5
WorkingDirectory=$PROJECT_DIR

[Install]
WantedBy=default.target
UNIT
systemctl --user daemon-reload
if systemctl --user is-enabled nasypeasy-caddy &>/dev/null; then
    systemctl --user restart nasypeasy-caddy
else
    systemctl --user enable --now nasypeasy-caddy
fi
echo "  Caddy systemd service started"

# 5. Create a user
echo "[5/6] Creating admin user..."
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

# 6. Tailscale API key (optional)
echo ""
echo "[6/6] Optional: Tailscale API key for remote access"
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
echo "Start all services:"
echo "  pixi run host-agent  # collects podman/tailscale data"
echo "  pixi run server      # containerized dashboard"
echo "  pixi run caddy       # reverse proxy (already started as systemd service)"
echo ""
echo "Or run directly on host:"
echo "  pixi run start       # dashboard on port 5000"
echo ""
echo "Access the dashboard at:"
if [ -n "$DOMAIN" ]; then
    echo "  https://$DOMAIN"
fi
echo "  http://localhost:5000"
