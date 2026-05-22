# Template Apps

Each app lives in its own folder under `templates/apps/`.

## Folder structure

```text
templates/apps/
└── <app-name>/
    ├── app.json
    └── docker-compose.yaml
```

## Manifest files

- `app.json` — app metadata shown in the dashboard.
- `docker-compose.yaml` — the deployable service definition used by the app installer.

### `app.json` structure

Each app manifest should include:

- `name` — display name for the app.
- `description` — short summary shown in the dashboard.
- `icon` — Font Awesome icon class used for the app card.
- `port` — the primary exposed port for the app.

Example:

```json
{
  "name": "FileBrowser",
  "description": "A web-based file manager for your server",
  "icon": "fas fa-folder-open",
  "port": 8080
}
```

## Example

```text
templates/apps/filebrowser/
├── app.json
└── docker-compose.yaml
```
