#!/usr/bin/env python3
"""
Migration: Add enterprise_app_id column to monitored_services table.
Run this once after pulling the Enterprise Apps feature.
"""
import sqlite3
from pathlib import Path


def migrate():
    db_path = Path(__file__).parent.parent / "statuspage.db"

    if not db_path.exists():
        print("Database not found at", db_path)
        print("Tip: Start the app with 'make dev' first to create the database")
        return

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    try:
        # Check if monitored_services table exists
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='monitored_services'")
        if not cursor.fetchone():
            print("monitored_services table does not exist yet")
            print("Tip: Start the app with 'make dev' first to create all tables")
            print("Then run this migration script again")
            return

        # Check if column already exists
        cursor.execute("PRAGMA table_info(monitored_services)")
        columns = {row[1] for row in cursor.fetchall()}

        if "enterprise_app_id" in columns:
            print("enterprise_app_id column already exists")
            return

        # Add the column
        print("Adding enterprise_app_id column to monitored_services...")
        cursor.execute("""
            ALTER TABLE monitored_services
            ADD COLUMN enterprise_app_id VARCHAR NULL
        """)
        conn.commit()
        print("Migration complete: enterprise_app_id column added")

    except Exception as e:
        print("Migration failed:", str(e))
        conn.rollback()
        raise
    finally:
        conn.close()


if __name__ == "__main__":
    migrate()
