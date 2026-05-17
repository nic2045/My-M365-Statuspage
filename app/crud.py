import uuid
from datetime import date, datetime, timedelta
from typing import Any

import bleach
from sqlalchemy import desc, select
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models import Incident, IncidentUpdate, MonitoredService, ServiceStatus
from app.schemas import (
    DayStatusSchema,
    IncidentSchema,
    IncidentUpdateSchema,
    ServiceStatusSchema,
    StatusPageSchema,
)

ALLOWED_HTML_TAGS = ["p", "b", "i", "strong", "em", "a", "ul", "ol", "li", "br", "span"]
ALLOWED_HTML_ATTRS = {"a": ["href", "title"]}

_STATUS_SEVERITY = {"operational": 0, "unknown": 1, "degraded": 2, "interrupted": 3}


def _sanitize_html(raw: str) -> str:
    return bleach.clean(raw, tags=ALLOWED_HTML_TAGS, attributes=ALLOWED_HTML_ATTRS, strip=True)


def _parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return dt.replace(tzinfo=None) if dt.tzinfo else dt
    except (ValueError, AttributeError):
        return None


async def upsert_service_status(
    db: AsyncSession,
    service_name: str,
    record_date: date,
    status: str,
    raw_graph_status: str,
) -> None:
    stmt = (
        sqlite_insert(ServiceStatus)
        .values(
            service_name=service_name,
            date=record_date,
            status=status,
            raw_graph_status=raw_graph_status,
        )
        .on_conflict_do_update(
            index_elements=["service_name", "date"],
            set_={"status": status, "raw_graph_status": raw_graph_status},
        )
    )
    await db.execute(stmt)


async def upsert_incident(
    db: AsyncSession,
    graph_issue_id: str,
    **fields: Any,
) -> Incident:
    result = await db.execute(
        select(Incident).where(Incident.graph_issue_id == graph_issue_id)
    )
    incident = result.scalar_one_or_none()
    if incident is None:
        incident = Incident(graph_issue_id=graph_issue_id, **fields)
        db.add(incident)
        await db.flush()
    else:
        for k, v in fields.items():
            # Don't overwrite severity if admin has set it manually
            if k == "severity" and incident.source == "manual":
                continue
            setattr(incident, k, v)
        await db.flush()
    return incident


async def upsert_incident_updates(
    db: AsyncSession,
    incident_id: int,
    posts: list[dict],
) -> None:
    result = await db.execute(
        select(IncidentUpdate.post_created_at).where(
            IncidentUpdate.incident_id == incident_id
        )
    )
    existing_times = {row[0] for row in result.fetchall()}

    for post in posts:
        body = post.get("description", {})
        raw_content = body.get("content", "") if isinstance(body, dict) else str(body)
        content = _sanitize_html(raw_content)
        post_created_at = _parse_dt(post.get("createdDateTime"))

        if post_created_at in existing_times:
            continue

        db.add(
            IncidentUpdate(
                incident_id=incident_id,
                content=content,
                post_created_at=post_created_at,
            )
        )


async def count_status_days_in_window(
    db: AsyncSession,
    service_name: str,
    days: int = 90,
) -> int:
    from sqlalchemy import func
    today = date.today()
    start_date = today - timedelta(days=days - 1)
    result = await db.execute(
        select(func.count(ServiceStatus.id)).where(
            ServiceStatus.service_name == service_name,
            ServiceStatus.date >= start_date,
            ServiceStatus.date <= today,
        )
    )
    return int(result.scalar_one() or 0)


async def get_uptime_bars(
    db: AsyncSession,
    service_name: str,
    days: int = 90,
) -> list[DayStatusSchema]:
    today = date.today()
    start_date = today - timedelta(days=days - 1)

    result = await db.execute(
        select(ServiceStatus.date, ServiceStatus.status)
        .where(
            ServiceStatus.service_name == service_name,
            ServiceStatus.date >= start_date,
            ServiceStatus.date <= today,
        )
        .order_by(ServiceStatus.date)
    )
    rows = {r.date: r.status for r in result.fetchall()}

    bars: list[DayStatusSchema] = []
    for i in range(days):
        d = start_date + timedelta(days=i)
        bars.append(DayStatusSchema(date=d, status=rows.get(d, "no_data")))
    return bars


async def get_active_incidents(
    db: AsyncSession,
    service_name: str | None = None,
) -> list[Incident]:
    stmt = (
        select(Incident)
        .options(selectinload(Incident.updates))
        .where(
            Incident.is_resolved.is_(False),
            Incident.classification != "maintenance",
            Incident.is_suppressed.is_(False),
        )
        .order_by(desc(Incident.last_modified))
    )
    if service_name:
        stmt = stmt.where(Incident.service_name == service_name)
    result = await db.execute(stmt)
    return list(result.scalars().all())


async def get_service_current_status(
    db: AsyncSession,
    service_name: str,
) -> str:
    result = await db.execute(
        select(ServiceStatus.status)
        .where(ServiceStatus.service_name == service_name)
        .order_by(desc(ServiceStatus.date))
        .limit(1)
    )
    row = result.scalar_one_or_none()
    return row or "unknown"


async def get_last_poll_time(db: AsyncSession) -> datetime | None:
    from sqlalchemy import func
    result = await db.execute(select(func.max(ServiceStatus.created_at)))
    return result.scalar_one_or_none()


async def get_scheduled_maintenances(db: AsyncSession) -> list[Incident]:
    result = await db.execute(
        select(Incident)
        .options(selectinload(Incident.updates))
        .where(Incident.classification == "maintenance", Incident.is_resolved.is_(False))
        .order_by(Incident.scheduled_start)
    )
    return list(result.scalars().all())


async def get_all_incidents(
    db: AsyncSession,
    include_resolved: bool = False,
) -> list[Incident]:
    stmt = (
        select(Incident)
        .options(selectinload(Incident.updates))
        .where(Incident.classification != "maintenance")
        .order_by(desc(Incident.last_modified))
    )
    if not include_resolved:
        stmt = stmt.where(Incident.is_resolved.is_(False))
    result = await db.execute(stmt)
    return list(result.scalars().all())


async def get_incident_by_id(db: AsyncSession, incident_id: int) -> Incident | None:
    result = await db.execute(
        select(Incident)
        .options(selectinload(Incident.updates))
        .where(Incident.id == incident_id)
    )
    return result.scalar_one_or_none()


async def create_manual_incident(
    db: AsyncSession,
    title: str,
    service_name: str,
    classification: str = "incident",
    status: str = "active",
    severity: str = "",
    description: str | None = None,
    scheduled_start: datetime | None = None,
    scheduled_end: datetime | None = None,
) -> Incident:
    incident = Incident(
        graph_issue_id=f"manual-{uuid.uuid4().hex[:12]}",
        title=title,
        service_name=service_name,
        classification=classification,
        status=status,
        severity=severity,
        description=description or None,
        start_datetime=datetime.utcnow(),
        last_modified=datetime.utcnow(),
        is_resolved=False,
        source="manual",
        scheduled_start=scheduled_start,
        scheduled_end=scheduled_end,
    )
    db.add(incident)
    await db.flush()
    return incident


async def admin_update_incident(
    db: AsyncSession,
    incident_id: int,
    **fields: Any,
) -> Incident | None:
    incident = await get_incident_by_id(db, incident_id)
    if incident is None:
        return None
    for k, v in fields.items():
        setattr(incident, k, v)
    incident.last_modified = datetime.utcnow()
    await db.flush()
    return incident


async def add_incident_post(
    db: AsyncSession,
    incident_id: int,
    content: str,
) -> IncidentUpdate:
    update = IncidentUpdate(
        incident_id=incident_id,
        content=_sanitize_html(content),
        update_type="note",
        post_created_at=datetime.utcnow(),
    )
    db.add(update)
    await db.flush()
    return update


async def add_state_change_entry(
    db: AsyncSession,
    incident_id: int,
    new_status: str,
) -> IncidentUpdate:
    update = IncidentUpdate(
        incident_id=incident_id,
        content=new_status,
        update_type="state_change",
        post_created_at=datetime.utcnow(),
    )
    db.add(update)
    await db.flush()
    return update


async def get_resolved_incidents(
    db: AsyncSession,
    limit: int = 20,
    days: int | None = None,
) -> list[Incident]:
    stmt = (
        select(Incident)
        .options(selectinload(Incident.updates))
        .where(Incident.is_resolved.is_(True), Incident.classification != "maintenance")
        .order_by(desc(Incident.last_modified))
        .limit(limit)
    )
    if days is not None:
        cutoff = datetime.utcnow() - timedelta(days=days)
        stmt = stmt.where(Incident.last_modified >= cutoff)
    result = await db.execute(stmt)
    return list(result.scalars().all())


async def toggle_suppress_incident(
    db: AsyncSession,
    incident_id: int,
    suppress: bool,
) -> None:
    incident = await get_incident_by_id(db, incident_id)
    if incident:
        incident.is_suppressed = suppress
        await db.flush()


async def get_suppressed_incidents(db: AsyncSession) -> list[Incident]:
    result = await db.execute(
        select(Incident)
        .where(Incident.is_suppressed.is_(True), Incident.is_resolved.is_(False))
        .order_by(desc(Incident.last_modified))
    )
    return list(result.scalars().all())


async def get_enabled_services(db: AsyncSession) -> list[str]:
    result = await db.execute(
        select(MonitoredService.service_name)
        .where(MonitoredService.is_enabled.is_(True))
        .order_by(MonitoredService.service_name)
    )
    return [row[0] for row in result.fetchall()]


async def get_all_monitored_services(db: AsyncSession) -> list[MonitoredService]:
    result = await db.execute(
        select(MonitoredService).order_by(MonitoredService.service_name)
    )
    return list(result.scalars().all())


async def ensure_service_known(db: AsyncSession, service_name: str) -> MonitoredService:
    result = await db.execute(
        select(MonitoredService).where(MonitoredService.service_name == service_name)
    )
    svc = result.scalar_one_or_none()
    if svc is None:
        svc = MonitoredService(service_name=service_name, is_enabled=False)
        db.add(svc)
        await db.flush()
    return svc


async def set_service_enabled(
    db: AsyncSession, service_name: str, is_enabled: bool
) -> MonitoredService:
    svc = await ensure_service_known(db, service_name)
    svc.is_enabled = is_enabled
    await db.flush()
    return svc


async def set_show_uptime_percentage(
    db: AsyncSession, service_name: str, show: bool
) -> MonitoredService:
    svc = await ensure_service_known(db, service_name)
    svc.show_uptime_percentage = show
    await db.flush()
    return svc


async def get_uptime_percentage(
    db: AsyncSession,
    service_name: str,
    days: int = 90,
) -> float | None:
    """Return uptime % over the window. operational=1.0, degraded=0.5, interrupted=0.

    no_data/unknown days are excluded from the denominator. Returns None when
    no day in the window has data.
    """
    today = date.today()
    start_date = today - timedelta(days=days - 1)
    result = await db.execute(
        select(ServiceStatus.status).where(
            ServiceStatus.service_name == service_name,
            ServiceStatus.date >= start_date,
            ServiceStatus.date <= today,
        )
    )
    weights = {"operational": 1.0, "degraded": 0.5, "interrupted": 0.0}
    total = 0
    score = 0.0
    for row in result.fetchall():
        status = row[0]
        if status not in weights:
            continue
        total += 1
        score += weights[status]
    if total == 0:
        return None
    return round(score / total * 100, 2)


async def backfill_service_status_from_issues(
    db: AsyncSession,
    service_name: str,
    issues: list[dict],
    days: int = 90,
) -> None:
    today = date.today()
    start_date = today - timedelta(days=days - 1)

    _severity = {"operational": 0, "unknown": 1, "degraded": 2, "interrupted": 3}

    def _parse_issue_date(val: str | None) -> date | None:
        if not val:
            return None
        try:
            dt = datetime.fromisoformat(val.replace("Z", "+00:00"))
            return dt.date()
        except (ValueError, AttributeError):
            return None

    day_status: dict[date, str] = {}
    for issue in issues:
        issue_start = _parse_issue_date(issue.get("startDateTime"))
        issue_end = _parse_issue_date(issue.get("endDateTime") or issue.get("lastModifiedDateTime"))
        if not issue_start:
            continue
        if issue_end is None or issue_end < issue_start:
            issue_end = today
        classification = issue.get("classification", "incident")
        status = "interrupted" if classification == "incident" else "degraded"

        cursor = max(issue_start, start_date)
        end_clamped = min(issue_end, today)
        while cursor <= end_clamped:
            if _severity.get(status, 0) > _severity.get(day_status.get(cursor, "operational"), 0):
                day_status[cursor] = status
            cursor += timedelta(days=1)

    result = await db.execute(
        select(ServiceStatus.date).where(
            ServiceStatus.service_name == service_name,
            ServiceStatus.date >= start_date,
        )
    )
    existing_dates = {row[0] for row in result.fetchall()}

    for i in range(days):
        d = start_date + timedelta(days=i)
        if d not in existing_dates:
            status = day_status.get(d, "operational")
            await upsert_service_status(db, service_name, d, status, "backfill")


async def set_service_status_manual(
    db: AsyncSession,
    service_name: str,
    status: str,
) -> None:
    await upsert_service_status(db, service_name, date.today(), status, "manual")


async def build_status_page_data(
    db: AsyncSession,
    service_names: list[str],
) -> StatusPageSchema:
    services: list[ServiceStatusSchema] = []
    overall_severity = 0

    show_flags_result = await db.execute(
        select(MonitoredService.service_name, MonitoredService.show_uptime_percentage)
        .where(MonitoredService.service_name.in_(service_names))
    )
    show_flags = {row[0]: row[1] for row in show_flags_result.fetchall()}

    for name in service_names:
        current_status = await get_service_current_status(db, name)
        uptime_days = await get_uptime_bars(db, name)
        raw_incidents = await get_active_incidents(db, service_name=name)
        uptime_pct = (
            await get_uptime_percentage(db, name) if show_flags.get(name, True) else None
        )

        incident_schemas = [
            IncidentSchema(
                graph_issue_id=inc.graph_issue_id,
                title=inc.title,
                service_name=inc.service_name,
                classification=inc.classification,
                status=inc.status,
                severity=inc.severity,
                description=inc.description,
                start_datetime=inc.start_datetime,
                last_modified=inc.last_modified,
                is_resolved=inc.is_resolved,
                updates=[
                    IncidentUpdateSchema(
                        content=u.content,
                        update_type=u.update_type,
                        post_created_at=u.post_created_at,
                    )
                    for u in sorted(inc.updates, key=lambda x: x.post_created_at or datetime.min)
                ],
            )
            for inc in raw_incidents
        ]

        overall_severity = max(
            overall_severity, _STATUS_SEVERITY.get(current_status, 0)
        )

        services.append(
            ServiceStatusSchema(
                service_name=name,
                current_status=current_status,
                uptime_days=uptime_days,
                active_incidents=incident_schemas,
                uptime_percentage=uptime_pct,
            )
        )

    severity_to_status = {0: "operational", 1: "unknown", 2: "degraded", 3: "interrupted"}
    overall_status = severity_to_status.get(overall_severity, "unknown")

    last_updated = await get_last_poll_time(db)

    return StatusPageSchema(
        services=services,
        last_updated=last_updated,
        overall_status=overall_status,
    )
