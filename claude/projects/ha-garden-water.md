# ha-garden-water — Claude Instructions

@../CLAUDE.md
Home Assistant blueprint for garden irrigation.

## Blueprint Schema
Only use validated HA blueprint fields. Confirmed top-level keys inside `blueprint:`:
- `name`, `description`, `domain`, `author`, `source_url`, `input`
- `homeassistant` → nested: `min_version: "YYYY.M.0"` (NOT `min_ha_version`)

Input sections with `name`, `icon`, `collapsed`, nested `input` require `min_version: "2024.6.0"`.

Reference: https://github.com/home-assistant/core/blob/dev/homeassistant/components/blueprint/schemas.py

## HA Version Support
Minimum supported HA version is always **today minus 2 years**.

When setting `homeassistant.min_version`, calculate 2 years back from today. Never set a lower minimum just because a feature is technically older.

## Versioning
Version string embedded in the blueprint description field:
```
**Version: vX.Y.Z (build YYMMDD.HHMM)**
```
