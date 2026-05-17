import os

from sqlalchemy import event, func, select, text
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.config import settings
from app.models import Base, MonitoredService

os.makedirs("data", exist_ok=True)

engine = create_async_engine(
    settings.DATABASE_URL,
    connect_args={"check_same_thread": False},
    echo=settings.DEBUG,
)


@event.listens_for(engine.sync_engine, "connect")
def _set_sqlite_pragmas(conn, _record):
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA foreign_keys=ON")


AsyncSessionLocal = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


async def init_db() -> None:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        # Additive migrations for columns added after initial deployment
        for stmt in [
            "ALTER TABLE incidents ADD COLUMN source VARCHAR NOT NULL DEFAULT 'graph'",
            "ALTER TABLE incidents ADD COLUMN severity VARCHAR NOT NULL DEFAULT ''",
            "ALTER TABLE incidents ADD COLUMN description TEXT",
            "ALTER TABLE incidents ADD COLUMN scheduled_start DATETIME",
            "ALTER TABLE incidents ADD COLUMN scheduled_end DATETIME",
            "ALTER TABLE incident_updates ADD COLUMN update_type VARCHAR NOT NULL DEFAULT 'note'",
            "ALTER TABLE incidents ADD COLUMN is_suppressed BOOLEAN NOT NULL DEFAULT 0",
            "ALTER TABLE incidents ADD COLUMN end_datetime DATETIME",
            "ALTER TABLE monitored_services ADD COLUMN show_uptime_percentage BOOLEAN NOT NULL DEFAULT 1",
            "ALTER TABLE incident_updates ADD COLUMN notify_subscribers BOOLEAN NOT NULL DEFAULT 0",
        ]:
            try:
                await conn.execute(text(stmt))
            except Exception:  # noqa: S110
                pass  # column already exists

    # Seed monitored_services from env var if the table is empty
    async with AsyncSessionLocal() as db:
        result = await db.execute(select(func.count()).select_from(MonitoredService))
        if result.scalar_one() == 0:
            for name in settings.monitored_services_list:
                db.add(MonitoredService(service_name=name, is_enabled=True))
            await db.commit()
