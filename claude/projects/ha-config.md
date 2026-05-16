# ha-config — Claude Instructions

@../CLAUDE.md
Home Assistant configuration for a local HA instance.

## Home Assistant Server
- URL: http://homeassistant.local/
- IP: 192.168.178.197
- SSH: `ssh root@192.168.178.197 -p 22222` (Terminal & SSH Add-on, port 22222)
- The repo at /Users/NicO/Coding/ha-config is a local copy — changes must be deployed to the server

## Deploy Workflow
`./deploy.sh` — pushes to GitHub, then on the server: git pull + `ha core restart`
- `ha core reload` does not exist — always use `ha core restart`
- `.vscode/settings.json` is gitignored (contains HA long-lived access token)

## HA Configuration
- `customize.yaml` is included via `!include` in `configuration.yaml` — use for device_class overrides that cannot be set on helpers directly
- Entity IDs are always ASCII — umlauts are transliterated (e.g. `ä` → `a`); verify exact IDs under Developer Tools → States

## Versioning
No version numbers in config files. Changelog tracks changes by date.
