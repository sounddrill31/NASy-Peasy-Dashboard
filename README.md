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
   pixi run server    # containerized
   # or
   pixi run start     # directly on host
   ```

Access the dashboard at `http://localhost:5000`.

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
