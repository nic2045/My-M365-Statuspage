#!/usr/bin/env python3
"""Import SQLite database from JSON export file.

Usage:
    python scripts/db_import.py [input_file.json]

Imports all tables from JSON export (created by db_export.py).
Merges with existing data (doesn't delete).
"""

import asyncio
import json
import sys
from datetime import datetime
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

# Add parent directory to path so we can import app modules
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.config import settings
from app.database import Base
from app.models import (
    AppSetting,
    Incident,
    IncidentUpdate,
    MonitoredService,
    ServiceStatus,
    SourceLabel,
    Subscriber,
)


async def import_table(session: AsyncSession, model_class, records: list[dict]):
    """Import records into a single table.

    Skips records that would violate unique constraints (e.g., existing IDs).
    """
    imported = 0
    skipped = 0

    for record in records:
        try:
            # For incident_updates, ensure incident_id points to existing incident
            if model_class == IncidentUpdate:
                incident_id = record.get("incident_id")
                if incident_id:
                    result = await session.execute(
                        select(Incident).where(Incident.id == incident_id)
                    )
                    if not result.scalar_one_or_none():
                        skipped += 1
                        continue

            # Create instance and add to session
            obj = model_class(**record)
            session.add(obj)
            imported += 1
        except Exception as e:
            print(f"    ⚠ Skipping record (constraint/error): {e}")
            skipped += 1

    if imported > 0:
        await session.flush()

    return imported, skipped


async def main():
    input_file = sys.argv[1] if len(sys.argv) > 1 else "db_export.json"

    if not Path(input_file).exists():
        print(f"❌ Export file not found: {input_file}")
        return 1

    print(f"Importing database from {input_file}...")

    with open(input_file) as f:
        export_data = json.load(f)

    print(f"  Export timestamp: {export_data['export_info']['timestamp']}")
    print(f"  Original database: {export_data['export_info']['database']}")

    engine = create_async_engine(settings.DATABASE_URL, echo=False)

    # Create tables if they don't exist
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    # Import each table
    async with AsyncSession(engine) as session:
        print("\nImporting tables:")
        totals_imported = 0
        totals_skipped = 0

        # Import in dependency order (services before incidents, etc.)
        import_order = [
            ("monitored_services", MonitoredService),
            ("service_status", ServiceStatus),
            ("source_labels", SourceLabel),
            ("incidents", Incident),
            ("incident_updates", IncidentUpdate),
            ("subscribers", Subscriber),
            ("app_settings", AppSetting),
        ]

        for table_name, model_class in import_order:
            records = export_data["tables"].get(table_name, [])
            if not records:
                continue

            imported, skipped = await import_table(session, model_class, records)
            totals_imported += imported
            totals_skipped += skipped

            status = "✓" if skipped == 0 else "⚠"
            print(f"  {status} {table_name}: {imported} imported, {skipped} skipped")

        await session.commit()

    print(f"\n✓ Import complete!")
    print(f"  Total imported: {totals_imported}")
    print(f"  Total skipped: {totals_skipped} (duplicates/constraints)")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
