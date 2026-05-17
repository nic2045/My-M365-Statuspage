import uuid
from datetime import date, datetime, timedelta
from typing import Any

import bleach
from sqlalchemy import desc, select
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models import Incident, IncidentUpdate, MonitoredService, ServiceStatus, Subscriber
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


CRITICAL_SEVERITIES = {"critical"}


def _incident_bar_status(severity: str | None) -> str:
    """Map an incident's severity to the bar color it imposes.

    Incidents with severity 'critical' make the day red (interrupted);
    all other severities (including high/medium/low/empty) make it yellow
    (degraded). Real ServiceStatus DB rows always override this.
    """
    sev = (severity or "").lower()
    return "interrupted" if sev in CRITICAL_SEVERITIES else "degraded"


def _incident_date_range(incident: Incident, today: date) -> tuple[date, date] | None:
    """Return (start, end) date range an incident covers, or None to skip.

    - Skips incidents without a start_datetime.
    - End preference: end_datetime → last_modified (if resolved) → today.
    """
    if incident.start_datetime is None:
        return None
    start = incident.start_datetime.date()
    if incident.end_datetime is not None:
        end = incident.end_datetime.date()
    elif incident.is_resolved and incident.last_modified is not None:
        end = incident.last_modified.date()
    else:
        end = today
    if end < start:
        end = start
    return start, end


async def get_uptime_bars(
    db: AsyncSession,
    service_name: str,
    days: int = 90,
) -> list[DayStatusSchema]:
    """Build 90 day-bars for a service.

    Logic:
      1. Default every day to 'operational' (green) – missing data means
         the service was healthy.
      2. Overlay each non-maintenance, non-suppressed Incident across its
         [start, end] date range:
           - severity 'critical' → 'interrupted' (red)
           - any other severity → 'degraded' (yellow)
         Higher severity wins when ranges overlap.
      3. Real entries from the service_status table (excluding synthetic
         'backfill' rows) override everything – they're authoritative.
    """
    today = date.today()
    start_date = today - timedelta(days=days - 1)

    real_result = await db.execute(
        select(ServiceStatus.date, ServiceStatus.status, ServiceStatus.raw_graph_status)
        .where(
            ServiceStatus.service_name == service_name,
            ServiceStatus.date >= start_date,
            ServiceStatus.date <= today,
        )
    )
    real_entries: dict[date, str] = {
        row.date: row.status
        for row in real_result.fetchall()
        if row.raw_graph_status != "backfill"
    }

    # Only true incidents paint the uptime bars; advisories are
    # informational ("Updates" category) and maintenance is scheduled,
    # so neither should ding availability.
    incidents_result = await db.execute(
        select(Incident).where(
            Incident.service_name == service_name,
            Incident.classification == "incident",
            Incident.is_suppressed.is_(False),
            Incident.start_datetime.is_not(None),
        )
    )
    incidents = list(incidents_result.scalars().all())

    computed: dict[date, str] = {}
    for inc in incidents:
        date_range = _incident_date_range(inc, today)
        if date_range is None:
            continue
        inc_start, inc_end = date_range
        if inc_end < start_date or inc_start > today:
            continue
        inc_status = _incident_bar_status(inc.severity)
        cursor = max(inc_start, start_date)
        end_clamped = min(inc_end, today)
        while cursor <= end_clamped:
            current = computed.get(cursor, "operational")
            if _STATUS_SEVERITY.get(inc_status, 0) > _STATUS_SEVERITY.get(current, 0):
                computed[cursor] = inc_status
            cursor += timedelta(days=1)

    bars: list[DayStatusSchema] = []
    for i in range(days):
        d = start_date + timedelta(days=i)
        if d in real_entries:
            status = real_entries[d]
        else:
            status = computed.get(d, "operational")
        bars.append(DayStatusSchema(date=d, status=status))
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
    classification: str | None = None,
) -> list[Incident]:
    """Return non-maintenance incidents. Pass classification='incident' for
    real disruptions only, 'advisory' for informational items."""
    stmt = (
        select(Incident)
        .options(selectinload(Incident.updates))
        .where(Incident.classification != "maintenance")
        .order_by(desc(Incident.last_modified))
    )
    if not include_resolved:
        stmt = stmt.where(Incident.is_resolved.is_(False))
    if classification is not None:
        stmt = stmt.where(Incident.classification == classification)
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
    start_datetime: datetime | None = None,
    scheduled_start: datetime | None = None,
    scheduled_end: datetime | None = None,
    source: str = "manual",
    external_id: str | None = None,
) -> Incident:
    now = datetime.utcnow()
    start = start_datetime or now
    incident = Incident(
        graph_issue_id=f"manual-{uuid.uuid4().hex[:12]}",
        title=title,
        service_name=service_name,
        classification=classification,
        status=status,
        severity=severity,
        description=description or None,
        start_datetime=start,
        last_modified=now,
        is_resolved=False,
        source=source or "manual",
        external_id=external_id or None,
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


async def delete_incident(db: AsyncSession, incident_id: int) -> bool:
    incident = await get_incident_by_id(db, incident_id)
    if incident is None:
        return False
    await db.delete(incident)
    await db.flush()
    return True


async def add_incident_post(
    db: AsyncSession,
    incident_id: int,
    content: str,
    notify_subscribers: bool = True,
) -> IncidentUpdate:
    update = IncidentUpdate(
        incident_id=incident_id,
        content=_sanitize_html(content),
        update_type="note",
        post_created_at=datetime.utcnow(),
        notify_subscribers=notify_subscribers,
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


def _service_sort_clause():
    """Sort: group (NULL last) → admin-set sort_order → service_name."""
    from sqlalchemy import case
    group_sort = case(
        (MonitoredService.group_name.is_(None), "￿"),
        else_=MonitoredService.group_name,
    )
    return [group_sort, MonitoredService.sort_order, MonitoredService.service_name]


async def get_enabled_services(db: AsyncSession) -> list[str]:
    result = await db.execute(
        select(MonitoredService.service_name)
        .where(MonitoredService.is_enabled.is_(True))
        .order_by(*_service_sort_clause())
    )
    return [row[0] for row in result.fetchall()]


async def get_enabled_services_with_status(db: AsyncSession) -> list[dict]:
    """Same order as get_enabled_services, enriched with current status + group."""
    result = await db.execute(
        select(
            MonitoredService.service_name,
            MonitoredService.group_name,
        )
        .where(MonitoredService.is_enabled.is_(True))
        .order_by(*_service_sort_clause())
    )
    rows = result.fetchall()
    enriched: list[dict] = []
    for name, group in rows:
        status = await get_service_current_status(db, name)
        enriched.append({
            "service_name": name,
            "group_name": group,
            "current_status": status,
        })
    return enriched


async def get_all_monitored_services(db: AsyncSession) -> list[MonitoredService]:
    result = await db.execute(
        select(MonitoredService).order_by(*_service_sort_clause())
    )
    return list(result.scalars().all())


async def move_service(db: AsyncSession, service_name: str, direction: str) -> bool:
    """Swap sort_order with the adjacent service in the same group.

    direction: 'up' or 'down'. Returns True if swap happened.
    Falls back to setting an explicit sort_order based on neighbor positions
    if multiple services share the same sort_order (legacy default 0).
    """
    if direction not in {"up", "down"}:
        return False
    result = await db.execute(
        select(MonitoredService).order_by(*_service_sort_clause())
    )
    all_svcs = list(result.scalars().all())

    idx = next((i for i, s in enumerate(all_svcs) if s.service_name == service_name), None)
    if idx is None:
        return False
    cur = all_svcs[idx]
    # Find adjacent in same group
    if direction == "up":
        prev_idx = idx - 1
        while prev_idx >= 0 and all_svcs[prev_idx].group_name != cur.group_name:
            prev_idx -= 1
        if prev_idx < 0:
            return False
        neighbor = all_svcs[prev_idx]
    else:
        next_idx = idx + 1
        while next_idx < len(all_svcs) and all_svcs[next_idx].group_name != cur.group_name:
            next_idx += 1
        if next_idx >= len(all_svcs):
            return False
        neighbor = all_svcs[next_idx]

    # If both have the same sort_order, assign a stable spread first
    if cur.sort_order == neighbor.sort_order:
        group_members = [s for s in all_svcs if s.group_name == cur.group_name]
        for i, s in enumerate(group_members):
            s.sort_order = i * 10
        await db.flush()

    cur.sort_order, neighbor.sort_order = neighbor.sort_order, cur.sort_order
    await db.flush()
    return True


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


async def set_service_group(
    db: AsyncSession, service_name: str, group_name: str | None
) -> MonitoredService:
    svc = await ensure_service_known(db, service_name)
    cleaned = (group_name or "").strip() or None
    svc.group_name = cleaned
    await db.flush()
    return svc


async def get_known_groups(db: AsyncSession) -> list[str]:
    """Distinct, non-empty group names for the datalist autocomplete."""
    result = await db.execute(
        select(MonitoredService.group_name)
        .where(MonitoredService.group_name.is_not(None))
        .distinct()
        .order_by(MonitoredService.group_name)
    )
    return [row[0] for row in result.fetchall() if row[0]]


async def get_uptime_percentage(
    db: AsyncSession,
    service_name: str,
    days: int = 90,
) -> float | None:
    """Return uptime % over the window. operational=1.0, degraded=0.5, interrupted=0.

    Derived from the same bar logic as get_uptime_bars so values stay
    consistent with what's rendered. Returns None when no bar in the
    window has a weighted status.
    """
    bars = await get_uptime_bars(db, service_name, days)
    weights = {"operational": 1.0, "degraded": 0.5, "interrupted": 0.0}
    total = 0
    score = 0.0
    for bar in bars:
        if bar.status not in weights:
            continue
        total += 1
        score += weights[bar.status]
    if total == 0:
        return None
    return round(score / total * 100, 2)


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

    svc_meta_result = await db.execute(
        select(
            MonitoredService.service_name,
            MonitoredService.show_uptime_percentage,
            MonitoredService.group_name,
        )
        .where(MonitoredService.service_name.in_(service_names))
    )
    svc_meta = {row[0]: {"show_uptime": row[1], "group": row[2]} for row in svc_meta_result.fetchall()}

    for name in service_names:
        current_status = await get_service_current_status(db, name)
        uptime_days = await get_uptime_bars(db, name)
        raw_incidents = await get_active_incidents(db, service_name=name)
        meta = svc_meta.get(name, {})
        uptime_pct = (
            await get_uptime_percentage(db, name) if meta.get("show_uptime", True) else None
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
                group_name=meta.get("group"),
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


# ── Subscriber CRUD ───────────────────────────────────────────────────────────

async def create_subscriber(db: AsyncSession, email: str) -> Subscriber | None:
    """Create a pending (unconfirmed) subscriber. Returns None if email already exists."""
    existing = await db.execute(select(Subscriber).where(Subscriber.email == email))
    if existing.scalar_one_or_none():
        return None
    sub = Subscriber(
        email=email,
        confirm_token=uuid.uuid4().hex,
        unsubscribe_token=uuid.uuid4().hex,
    )
    db.add(sub)
    await db.flush()
    return sub


async def confirm_subscriber(db: AsyncSession, token: str) -> Subscriber | None:
    result = await db.execute(select(Subscriber).where(Subscriber.confirm_token == token))
    sub = result.scalar_one_or_none()
    if sub and sub.confirmed_at is None:
        sub.confirmed_at = datetime.utcnow()
        await db.flush()
    return sub


async def get_subscriber_by_unsub_token(db: AsyncSession, token: str) -> Subscriber | None:
    result = await db.execute(
        select(Subscriber).where(Subscriber.unsubscribe_token == token)
    )
    return result.scalar_one_or_none()


async def delete_subscriber(db: AsyncSession, subscriber_id: int) -> bool:
    result = await db.execute(select(Subscriber).where(Subscriber.id == subscriber_id))
    sub = result.scalar_one_or_none()
    if not sub:
        return False
    await db.delete(sub)
    await db.flush()
    return True


async def get_all_subscribers(db: AsyncSession) -> list[Subscriber]:
    result = await db.execute(select(Subscriber).order_by(Subscriber.created_at.desc()))
    return list(result.scalars().all())


async def get_confirmed_subscribers(db: AsyncSession) -> list[Subscriber]:
    result = await db.execute(
        select(Subscriber)
        .where(Subscriber.confirmed_at.is_not(None))
        .order_by(Subscriber.email)
    )
    return list(result.scalars().all())
