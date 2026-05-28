# Nasypeasy

The selfhosting operating system dashboard for the rest of us.

Nasypeasy provides a simple, mono-styled dashboard to manage your Podman containers, check Tailscale status, and deploy apps from YAML specifications.

## Setup

### Prerequisites

- [Podman](https://podman.io/) and [podman-compose](https://github.com/containers/podman-compose) installed system-wide:
  Ubuntu/Debian/etc:  
   ```bash
   sudo apt install podman podman-compose
   ```
  OpenSUSE:  
   ```bash
   sudo zypper install podman podman-compose
   ```
1. Install [pixi](https://pixi.sh/install.sh).
2. Run the setup script:
   ```bash
   bash setup.sh
   ```
3. Start the host agent (collects podman/tailscale data from the host):
   ```bash
   pixi run host-agent
   ```
4. Start the dashboard:
   ```bash
   pixi run up       # containerized
   pixi run fresh    # containerized (rebuild)
   # or
   pixi run start    # directly on host (dev)
   ```

Access the dashboard at `http://localhost:5000`.

### Firewall Ports

Per-app services get SSL via Caddy on the **same port** the container uses (e.g. container port 3001 → `https://hole.undo.it:3001`). No special port range needed. Open only the container ports you need:

```bash
# OS firewall (firewalld) — example for port 3001
sudo firewall-cmd --add-port=3001/tcp --permanent && sudo firewall-cmd --reload
```

For cloud providers (Oracle Cloud, AWS, etc.), add the same ports to your instance's security list / security group.

## Creating a User

If you skipped user creation during setup, run:

```bash
pixi run create-user <username> <password>
```

Access the dashboard at `http://localhost:5000`.

## Features

- **Auth**: Secured by DuckDB.
- **Podman Integration**: View running containers and deploy new ones.
- **Tailscale Integration**: View your node's Tailscale status.
- **Cockpit Integration**: A link is automatically shown if Cockpit is detected on port 9090.
- **App Repository**: Deploy apps from `./templates/apps` or from a remote repo URL containing app YAML definitions.
