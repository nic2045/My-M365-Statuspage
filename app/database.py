import os

from sqlalchemy import event, func, select, text
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.config import settings
from app.models import (
    Base,
    IncidentState,
    MonitoredService,
    SeverityLevel,
    SourceLabel,
    UpdateTemplate,
)

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
            "ALTER TABLE monitored_services ADD COLUMN group_name VARCHAR(64)",
            "ALTER TABLE incident_updates ADD COLUMN notify_subscribers BOOLEAN NOT NULL DEFAULT 0",
            "ALTER TABLE monitored_services ADD COLUMN sort_order INTEGER NOT NULL DEFAULT 0",
            "ALTER TABLE incidents ADD COLUMN external_id VARCHAR(128)",
            "ALTER TABLE incidents ADD COLUMN owner_email VARCHAR(256)",
            "ALTER TABLE incidents ADD COLUMN acknowledged_at DATETIME",
            "ALTER TABLE incidents ADD COLUMN acknowledged_by_email VARCHAR(256)",
            "ALTER TABLE incident_updates ADD COLUMN author VARCHAR(256)",
            "ALTER TABLE incidents ADD COLUMN translated_lang VARCHAR(8)",
            "ALTER TABLE incident_updates ADD COLUMN is_published BOOLEAN NOT NULL DEFAULT 1",
            "ALTER TABLE subscribers ADD COLUMN channel VARCHAR(16) NOT NULL DEFAULT 'email'",
            "ALTER TABLE subscribers ADD COLUMN teams_webhook_url VARCHAR(512)",
            "ALTER TABLE subscribers ADD COLUMN services TEXT",
            "ALTER TABLE incidents ADD COLUMN postmortem_impact TEXT",
            "ALTER TABLE incidents ADD COLUMN postmortem_root_cause TEXT",
            "ALTER TABLE incidents ADD COLUMN postmortem_action_items TEXT",
            "ALTER TABLE incidents ADD COLUMN postmortem_timeline TEXT",
            "ALTER TABLE incidents ADD COLUMN postmortem_published_at DATETIME",
            # subscribers table is created by metadata.create_all above;
            # these stmts only fire if it already existed without the column
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

    # Seed system source labels (idempotent upsert)
    _system_labels = [
        ("manual", "Manuell"),
        ("graph", "Microsoft (Graph)"),
    ]
    async with AsyncSessionLocal() as db:
        for src, lbl in _system_labels:
            existing = await db.get(SourceLabel, src)
            if existing is None:
                db.add(SourceLabel(source=src, label=lbl, is_system=True))
        await db.commit()

    # Seed default update templates
    _default_templates = [
        (
            "Untersuchung gestartet",
            "Untersuchung gestartet — wir analysieren das Problem und werden Sie bald aktualisieren.",
            "active,acknowledged",
        ),
        (
            "Ursache identifiziert",
            "Wir haben die Ursache identifiziert und arbeiten an der Behebung.",
            "acknowledged,monitoring",
        ),
        (
            "Workaround verfügbar",
            "Ein Workaround ist verfügbar. Siehe die Details oben.",
            "monitoring",
        ),
        (
            "Fix eingespielt",
            "Der Fix wurde eingespielt. Wir überwachen die Situation genau.",
            "monitoring",
        ),
        (
            "Behoben",
            "Das Problem wurde behoben. Der Service ist wieder voll verfügbar.",
            "resolved",
        ),
    ]
    async with AsyncSessionLocal() as db:
        result = await db.execute(select(func.count()).select_from(UpdateTemplate))
        if result.scalar_one() == 0:
            for name, content, phases in _default_templates:
                db.add(UpdateTemplate(name=name, content=content, applicable_phases=phases))
            await db.commit()

    # Seed default severity levels (idempotent)
    _default_severities = [
        ("critical", "Kritisch", "#dc3545", 4),
        ("high", "Hoch", "#fd7e14", 3),
        ("medium", "Mittel", "#ffc107", 2),
        ("low", "Niedrig", "#0dcaf0", 1),
    ]
    async with AsyncSessionLocal() as db:
        for name, label, color, weight in _default_severities:
            existing = await db.get(SeverityLevel, name)
            if existing is None:
                db.add(
                    SeverityLevel(
                        name=name,
                        label=label,
                        color=color,
                        weight=weight,
                        display_order=weight,
                        is_system=True,
                    )
                )
        await db.commit()

    # Seed default incident states (idempotent)
    _default_states = [
        ("active", "Untersuchung läuft", "#fbbf24", False, 1),
        ("acknowledged", "Identifiziert", "#fb923c", False, 2),
        ("monitoring", "Überwachung", "#60a5fa", False, 3),
        ("resolved", "Behoben", "#10b981", True, 4),
    ]
    async with AsyncSessionLocal() as db:
        for name, label, color, is_terminal, order in _default_states:
            existing = await db.get(IncidentState, name)
            if existing is None:
                db.add(
                    IncidentState(
                        name=name,
                        label=label,
                        color=color,
                        is_terminal=is_terminal,
                        display_order=order,
                        is_system=True,
                    )
                )
        await db.commit()
