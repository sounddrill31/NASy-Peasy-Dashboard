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

- `app.json` — app metadata shown in the dashboard, such as name, description, icon, and port.
- `docker-compose.yaml` — the deployable service definition used by the app installer.

## Example

```text
templates/apps/filebrowser/
├── app.json
└── docker-compose.yaml
```
