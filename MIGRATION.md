# Database Migration Guide

This guide explains how to export and import the M365 Statuspage database for cross-platform migrations (e.g., macOS → Windows) or backups.

## Quick Start

### Export from Source Environment (macOS)

```bash
make db-export
# Exports to: db_export.json
```

Or with a custom filename:

```bash
make db-export-file FILE=my-backup-2026-09-19.json
```

### Import to Target Environment (Windows)

```bash
make db-import FILE=db_export.json
```

Or with a custom file:

```bash
make db-import FILE=my-backup-2026-09-19.json
```

## What Gets Exported/Imported

The scripts handle all 7 database tables:

- **monitored_services**: Service toggle state
- **service_status**: Daily uptime snapshots (for 90-day bars)
- **incidents**: Synced incidents from Microsoft Graph + manual entries
- **incident_updates**: Posts and status changes (linked to incidents)
- **subscribers**: Email/Teams notification subscriptions
- **source_labels**: Custom labels for incident categorization
- **app_settings**: Runtime configuration (SMTP, DeepL token, etc.)

## How It Works

### Export (`scripts/db_export.py`)

- Connects to current database (SQLite)
- Queries all tables via SQLAlchemy ORM
- Serializes dates/datetimes to ISO 8601 format
- Writes JSON with metadata (timestamp, source database URL)
- Human-readable format; can be edited if needed

**Output example:**

```json
{
  "export_info": {
    "timestamp": "2026-09-19T13:34:00.123456",
    "database": "sqlite:///./data/statuspage.db"
  },
  "tables": {
    "monitored_services": [
      { "id": 1, "name": "Exchange Online", "is_enabled": true },
      { "id": 2, "name": "SharePoint Online", "is_enabled": true }
    ],
    "incidents": [...],
    ...
  }
}
```

### Import (`scripts/db_import.py`)

- Reads JSON export file
- Async connection to target database
- **Imports in dependency order** to respect foreign keys:
  1. monitored_services (no dependencies)
  2. service_status (depends on services)
  3. source_labels (no dependencies)
  4. incidents (depends on services)
  5. incident_updates (depends on incidents)
  6. subscribers (no dependencies)
  7. app_settings (no dependencies)
- **Skips duplicates** that violate unique constraints (e.g., existing incident IDs)
- **Validates references** (e.g., orphaned incident_updates are skipped)
- Reports import stats: count imported vs. skipped

## Use Cases

### 1. Macbook → Windows Migration

Export on macOS:

```bash
cd /path/to/My-M365-Statuspage
make db-export
# Creates: db_export.json
```

Transfer file to Windows machine, then import:

```bash
# Windows (WSL2 or native)
cd /path/to/My-M365-Statuspage
make db-import FILE=db_export.json
```

### 2. Backup for Safekeeping

Create timestamped backups:

```bash
make db-export-file FILE=backup-$(date +%Y-%m-%d-%H%M%S).json
```

### 3. Development/Testing

Export production data locally for testing:

```bash
# On production server (or via SSH)
./scripts/db_export.py prod-data.json

# Locally (after scp)
make db-import FILE=prod-data.json
```

### 4. Manual Editing

The JSON is human-readable. You can manually edit it (e.g., remove certain incidents) before importing:

```bash
# Edit db_export.json in your editor
# Remove specific incident records if needed

make db-import FILE=db_export.json
```

## Important Notes

### Merge Behavior (No Deletion)

The import script **merges** with existing data — it does **not** delete existing records first. This means:

- Records with duplicate IDs are skipped (preserved from target DB)
- New records are inserted
- Existing updates are not overwritten

**Example:** If you import twice with the same file, the second run skips all records (already exist).

To clear before importing, delete `data/statuspage.db` first:

```bash
rm data/statuspage.db
make db-import FILE=db_export.json  # Fresh import
```

### Foreign Key Validation

- `incident_updates` are validated against existing `incidents`
- Orphaned updates (no matching incident ID) are skipped with a warning
- This prevents referential integrity errors

### Serialization

- **Dates/datetimes**: Stored as ISO 8601 strings (e.g., `"2026-09-19T13:34:00"`)
- **None/null values**: Preserved
- **Other types**: Converted to strings (enums, IDs, etc.)

## Troubleshooting

### "Export file not found"

```bash
# Make sure file exists
ls -la db_export.json

# Run from the repo root
cd /path/to/My-M365-Statuspage
make db-import FILE=db_export.json
```

### "Skipping record: constraint/error"

One or more records violated unique constraints (likely duplicates). This is normal behavior — existing records are preserved.

### Database doesn't update

Check that:
1. `data/` directory exists (created automatically if missing)
2. No `.db` file permission issues
3. Database URL in `.env` matches (default: `sqlite+aiosqlite:///./data/statuspage.db`)

### Verify Import Success

After import, check the admin panel:

```bash
make dev  # Start dev server
# Visit http://localhost:8000/admin
# Check Incidents/Services tabs to confirm data arrived
```

## Raw Script Usage (Without Make)

If Make is unavailable:

```bash
# Export
uv run python scripts/db_export.py output.json

# Import
uv run python scripts/db_import.py input.json
```

## See Also

- `CLAUDE.md`: Architecture overview
- `scripts/db_export.py`: Export script source
- `scripts/db_import.py`: Import script source
