#!/usr/bin/env python3
"""Export SQLite database to JSON file for backup/migration.

Usage:
    python scripts/db_export.py [output_file.json]

Exports all tables (incidents, updates, services, subscribers, etc.) to JSON.
Output can be imported with db_import.py on another system.
"""

import json
import sys
from datetime import date, datetime
from pathlib import Path

from sqlalchemy import create_engine, select, text

# Add parent directory to path so we can import app modules
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.config import settings
from app.models import (
    AppSetting,
    Incident,
    IncidentUpdate,
    MonitoredService,
    ServiceStatus,
    SourceLabel,
    Subscriber,
)

DATABASE_URL = settings.DATABASE_URL.replace("aiosqlite", "sqlite")


def serialize_value(value):
    """Serialize values that aren't JSON-serializable."""
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if value is None:
        return None
    return str(value)


def export_table(engine, model_class):
    """Export a single table to a list of dicts."""
    with engine.connect() as conn:
        result = conn.execute(select(model_class))
        rows = result.fetchall()

    data = []
    for row in rows:
        row_dict = {}
        for col in model_class.__table__.columns:
            val = getattr(row, col.name)
            row_dict[col.name] = serialize_value(val)
        data.append(row_dict)

    return data


def main():
    output_file = sys.argv[1] if len(sys.argv) > 1 else "db_export.json"

    engine = create_engine(DATABASE_URL, echo=False)

    print(f"Exporting database to {output_file}...")

    export_data = {
        "export_info": {
            "timestamp": datetime.now().isoformat(),
            "database": DATABASE_URL,
        },
        "tables": {
            "monitored_services": export_table(engine, MonitoredService),
            "service_status": export_table(engine, ServiceStatus),
            "incidents": export_table(engine, Incident),
            "incident_updates": export_table(engine, IncidentUpdate),
            "subscribers": export_table(engine, Subscriber),
            "source_labels": export_table(engine, SourceLabel),
            "app_settings": export_table(engine, AppSetting),
        },
    }

    # Count totals
    totals = {k: len(v) for k, v in export_data["tables"].items()}
    print("\nExported records:")
    for table, count in totals.items():
        print(f"  {table}: {count}")

    with open(output_file, "w") as f:
        json.dump(export_data, f, indent=2, default=str)

    print(f"\n✓ Export complete: {output_file}")
    print(f"  File size: {Path(output_file).stat().st_size / 1024:.1f} KB")
    return 0


if __name__ == "__main__":
    sys.exit(main())
