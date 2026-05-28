#!/usr/bin/env bash
set -euo pipefail

echo "=== NASy-Peasy Teardown ==="

echo "[1/5] Stopping dashboard container..."
podman-compose -f docker-compose.yml down 2>/dev/null || true
podman rm -f nasypeasy-dashboard 2>/dev/null || true

echo "[2/5] Stopping Caddy..."
pixi run caddy-stop 2>/dev/null || true

echo "[3/5] Stopping nginx..."
pixi run nginx-stop 2>/dev/null || true

echo "[4/5] Stopping host-agent..."
pkill -f 'host_agent.py' 2>/dev/null || true

echo "[5/5] Removing database, deployments, and generated configs..."
rm -f nasypeasy.db nasypeasy.db.wal
rm -rf deployments
rm -f Caddyfile nginx.conf nginx.pid
rm -rf logs/*
rm -f .env

echo ""
echo "=== Teardown complete! ==="
echo "Run 'pixi run setup' to start fresh."
