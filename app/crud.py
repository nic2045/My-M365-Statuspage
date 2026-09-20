import uuid
from calendar import monthrange
from datetime import date, datetime, timedelta
from typing import Any

import nh3
from sqlalchemy import Integer, and_, delete, desc, func, or_, select
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models import (
    CertificateCheckResult,
    HttpCheckResult,
    Incident,
    IncidentUpdate,
    MonitoredService,
    ServiceStatus,
    SourceLabel,
    Subscriber,
)
from app.schemas import (
    DayStatusSchema,
    IncidentSchema,
    IncidentUpdateSchema,
    ServiceStatusSchema,
    StatusPageSchema,
)

ALLOWED_HTML_TAGS = {"p", "b", "i", "strong", "em", "a", "ul", "ol", "li", "br", "span",
                     "h1", "h2", "h3", "h4", "div", "table", "thead", "tbody", "tr", "td", "th"}
ALLOWED_HTML_ATTRS = {"a": {"href", "title"}}

_STATUS_SEVERITY = {"operational": 0, "unknown": 1, "degraded": 2, "interrupted": 3}


def _sanitize_html(raw: str) -> str:
    return nh3.clean(raw, tags=ALLOWED_HTML_TAGS, attributes=ALLOWED_HTML_ATTRS)


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
            # Preserve admin-set end_datetime if Graph API has no value yet
            if k == "end_datetime" and v is None and incident.end_datetime is not None:
                continue
            setattr(incident, k, v)
        await db.flush()
    return incident


async def upsert_incident_updates(
    db: AsyncSession,
    incident_id: int,
    posts: list[dict],
    auto_publish: bool = False,
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
                # Microsoft's own text, not an operator's - stays a draft
                # until someone reviews and publishes it (see
                # routers/admin.py publish_incident_update) - except the
                # closing post written when Microsoft resolves the issue,
                # which goes public immediately since it's the reason the
                # incident is over (auto_publish, set by the caller).
                is_published=auto_publish,
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
        real = real_entries.get(d)
        inc = computed.get(d, "operational")
        if real is not None:
            # Use whichever is worse: a manual critical incident should turn the
            # bar red even when Graph reports the service as operational that day.
            status = real if _STATUS_SEVERITY.get(real, 0) >= _STATUS_SEVERITY.get(inc, 0) else inc
        else:
            status = inc
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
    status = row or "unknown"
    # Microsoft's own healthOverview status is a coarse aggregate that often
    # reads "degraded" for a service with nothing worse than an active
    # advisory attached. Advisories are informational (see get_uptime_bars'
    # same reasoning) and shouldn't turn the badge amber - only demote when
    # there's no genuine active incident backing it.
    if status == "degraded" and not await _has_active_incident(db, service_name):
        return "operational"
    return status


async def _has_active_incident(db: AsyncSession, service_name: str) -> bool:
    result = await db.execute(
        select(Incident.id)
        .where(
            Incident.service_name == service_name,
            Incident.classification == "incident",
            Incident.is_resolved.is_(False),
            Incident.is_suppressed.is_(False),
        )
        .limit(1)
    )
    return result.scalar_one_or_none() is not None


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


async def get_all_maintenances(db: AsyncSession) -> list[Incident]:
    result = await db.execute(
        select(Incident)
        .options(selectinload(Incident.updates))
        .where(Incident.classification == "maintenance")
        .order_by(desc(Incident.last_modified))
    )
    return list(result.scalars().all())


async def get_all_incidents(
    db: AsyncSession,
    include_resolved: bool = False,
    classification: str | None = None,
    source: str | None = None,
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
    if source is not None:
        stmt = stmt.where(Incident.source == source)
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
    end_datetime: datetime | None = None,
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
        end_datetime=end_datetime,
        last_modified=now,
        is_resolved=end_datetime is not None,
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
    author: str | None = None,
) -> IncidentUpdate:
    update = IncidentUpdate(
        incident_id=incident_id,
        content=_sanitize_html(content),
        update_type="note",
        post_created_at=datetime.utcnow(),
        notify_subscribers=notify_subscribers,
        author=author,
    )
    db.add(update)
    await db.flush()
    return update


async def add_state_change_entry(
    db: AsyncSession,
    incident_id: int,
    new_status: str,
    author: str | None = None,
) -> IncidentUpdate:
    update = IncidentUpdate(
        incident_id=incident_id,
        content=new_status,
        update_type="state_change",
        post_created_at=datetime.utcnow(),
        author=author,
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


async def publish_incident_update(
    db: AsyncSession,
    incident_id: int,
    update_id: int,
) -> bool:
    """Operator approval step for a Graph-synced message-center post (see
    upsert_incident_updates) - makes it visible on the public status page."""
    update = await db.get(IncidentUpdate, update_id)
    if update is None or update.incident_id != incident_id:
        return False
    update.is_published = True
    await db.flush()
    return True


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


async def get_distinct_sources(db: AsyncSession) -> list[str]:
    result = await db.execute(
        select(Incident.source)
        .where(Incident.source.is_not(None), Incident.source != "")
        .distinct()
        .order_by(Incident.source)
    )
    return [row[0] for row in result.fetchall()]


async def get_all_source_labels(db: AsyncSession) -> list[SourceLabel]:
    result = await db.execute(
        select(SourceLabel).order_by(SourceLabel.is_system.desc(), SourceLabel.source)
    )
    return list(result.scalars().all())


async def upsert_source_label(db: AsyncSession, source: str, label: str) -> None:
    existing = await db.get(SourceLabel, source)
    if existing:
        existing.label = label
    else:
        db.add(SourceLabel(source=source, label=label, is_system=False))
    await db.commit()


async def delete_source_label(db: AsyncSession, source: str) -> bool:
    existing = await db.get(SourceLabel, source)
    if existing and not existing.is_system:
        await db.delete(existing)
        await db.flush()
        return True
    return False


async def get_all_severity_levels(db: AsyncSession) -> list:
    from app.models import SeverityLevel

    result = await db.execute(
        select(SeverityLevel).order_by(SeverityLevel.display_order, SeverityLevel.name)
    )
    return result.scalars().all()


async def get_all_incident_states(db: AsyncSession) -> list:
    from app.models import IncidentState

    result = await db.execute(
        select(IncidentState).order_by(IncidentState.display_order, IncidentState.name)
    )
    return result.scalars().all()


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
    """Same order as get_enabled_services, enriched with current status + group.

    Optimized to avoid N+1 queries by joining with latest ServiceStatus in single query.
    """
    # Subquery: latest status per service
    latest_status_sq = (
        select(
            ServiceStatus.service_name,
            ServiceStatus.status,
            func.row_number()
            .over(
                partition_by=ServiceStatus.service_name,
                order_by=desc(ServiceStatus.date),
            )
            .label("rn"),
        )
        .subquery()
    )

    result = await db.execute(
        select(
            MonitoredService.service_name,
            MonitoredService.group_name,
            func.coalesce(latest_status_sq.c.status, "unknown").label("status"),
        )
        .where(MonitoredService.is_enabled.is_(True))
        .outerjoin(
            latest_status_sq,
            and_(
                latest_status_sq.c.service_name == MonitoredService.service_name,
                latest_status_sq.c.rn == 1,
            ),
        )
        .order_by(*_service_sort_clause())
    )
    rows = result.fetchall()
    enriched: list[dict] = []
    for name, group, status in rows:
        # Apply advisory-downgrade logic: if status is degraded but no active
        # incident, show operational (advisories are informational only)
        if status == "degraded":
            has_incident = await _has_active_incident(db, name)
            if not has_incident:
                status = "operational"
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
    days: int = 90,
) -> StatusPageSchema:
    services: list[ServiceStatusSchema] = []
    overall_severity = 0

    svc_meta_result = await db.execute(
        select(
            MonitoredService.service_name,
            MonitoredService.show_uptime_percentage,
            MonitoredService.group_name,
            MonitoredService.show_sla_on_status_page,
        )
        .where(MonitoredService.service_name.in_(service_names))
    )
    svc_meta = {
        row[0]: {"show_uptime": row[1], "group": row[2], "show_sla": row[3]}
        for row in svc_meta_result.fetchall()
    }

    for name in service_names:
        current_status = await get_service_current_status(db, name)
        uptime_days = await get_uptime_bars(db, name, days=days)
        raw_incidents = await get_active_incidents(db, service_name=name)
        meta = svc_meta.get(name, {})
        uptime_pct = (
            await get_uptime_percentage(db, name, days=days) if meta.get("show_uptime", True) else None
        )

        sla_data = None
        if meta.get("show_sla"):
            today = date.today()
            sla_data = await get_sla_for_month(db, name, today.year, today.month)

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
                        is_published=u.is_published,
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
                sla_current_month=sla_data,
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

async def create_subscriber(
    db: AsyncSession,
    email: str,
    channel: str = "email",
    teams_webhook_url: str | None = None,
    services: list[str] | None = None,
) -> Subscriber | None:
    """Create a pending (unconfirmed) subscriber. Returns None if email already exists.

    `services` is the list of service_names to notify for; None/empty means
    "all services" (stored as NULL, same as every pre-existing subscriber).
    """
    existing = await db.execute(select(Subscriber).where(Subscriber.email == email))
    if existing.scalar_one_or_none():
        return None
    sub = Subscriber(
        email=email,
        confirm_token=uuid.uuid4().hex,
        unsubscribe_token=uuid.uuid4().hex,
        channel=channel,
        teams_webhook_url=teams_webhook_url,
        services=",".join(services) if services else None,
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


def subscriber_services(sub: Subscriber) -> list[str] | None:
    """Parsed service_name list from Subscriber.services, or None for "all"."""
    if not sub.services:
        return None
    return [s.strip() for s in sub.services.split(",") if s.strip()]


async def get_confirmed_subscribers_for_service(db: AsyncSession, service_name: str) -> list[Subscriber]:
    """Confirmed subscribers who opted into `service_name` (or into "all")."""
    all_confirmed = await get_confirmed_subscribers(db)
    return [
        s for s in all_confirmed
        if (wanted := subscriber_services(s)) is None or service_name in wanted
    ]


async def search_global(db: AsyncSession, q: str) -> dict:
    """Run a multi-table LIKE search and group hits for the admin Cmd+K palette.

    Returns a dict shaped for direct JSON serialisation:
    ``{"groups": [{"label": str, "items": [{"label", "href", "sub"}, ...]}, ...]}``.
    Empty / very short queries return an empty result set so we don't flood
    the palette while the user is still typing the first character.
    """
    query = (q or "").strip()
    if len(query) < 2:
        return {"groups": []}

    pattern = f"%{query}%"
    per_group = 5
    total_cap = 20

    incidents_res = await db.execute(
        select(Incident)
        .where(
            Incident.classification != "maintenance",
            or_(
                Incident.title.like(pattern),
                Incident.description.like(pattern),
                Incident.service_name.like(pattern),
            ),
        )
        .order_by(desc(Incident.last_modified))
        .limit(per_group)
    )
    incidents = list(incidents_res.scalars().all())

    updates_res = await db.execute(
        select(IncidentUpdate)
        .where(IncidentUpdate.content.like(pattern))
        .order_by(desc(IncidentUpdate.post_created_at))
        .limit(per_group)
    )
    updates = list(updates_res.scalars().all())

    services_res = await db.execute(
        select(MonitoredService)
        .where(MonitoredService.service_name.like(pattern))
        .order_by(MonitoredService.service_name)
        .limit(per_group)
    )
    services = list(services_res.scalars().all())

    subscribers_res = await db.execute(
        select(Subscriber)
        .where(Subscriber.email.like(pattern))
        .order_by(Subscriber.email)
        .limit(per_group)
    )
    subscribers = list(subscribers_res.scalars().all())

    groups: list[dict] = []
    if incidents:
        groups.append({
            "label": "admin.search.group.incidents",
            "items": [
                {
                    "label": inc.title,
                    "href": f"/admin/incidents/{inc.id}",
                    "sub": inc.service_name or "",
                }
                for inc in incidents
            ],
        })
    if updates:
        # Need parent incidents to build hrefs; fetch in one go to avoid N+1
        parent_ids = sorted({u.incident_id for u in updates})
        parents_res = await db.execute(
            select(Incident).where(Incident.id.in_(parent_ids))
        )
        parents = {i.id: i for i in parents_res.scalars().all()}
        items: list[dict] = []
        for upd in updates:
            parent = parents.get(upd.incident_id)
            snippet = upd.content[:120] + ("…" if len(upd.content) > 120 else "")
            items.append({
                "label": snippet,
                "href": f"/admin/incidents/{upd.incident_id}",
                "sub": parent.title if parent else "",
            })
        groups.append({"label": "admin.search.group.updates", "items": items})
    if services:
        groups.append({
            "label": "admin.search.group.services",
            "items": [
                {
                    "label": svc.service_name,
                    "href": "/admin/settings#services",
                    "sub": svc.group_name or "",
                }
                for svc in services
            ],
        })
    if subscribers:
        groups.append({
            "label": "admin.search.group.subscribers",
            "items": [
                {
                    "label": sub.email,
                    "href": "/admin/settings#subscribers",
                    "sub": "" if sub.confirmed_at else "admin.subscriber_pending",
                }
                for sub in subscribers
            ],
        })

    # Enforce global cap by trimming groups in order
    remaining = total_cap
    capped: list[dict] = []
    for g in groups:
        if remaining <= 0:
            break
        items = g["items"][:remaining]
        if items:
            capped.append({"label": g["label"], "items": items})
            remaining -= len(items)

    return {"groups": capped}


async def get_sla_breach_reasons(
    db: AsyncSession,
    service_name: str,
    year: int,
    month: int,
) -> list[dict[str, Any]]:
    """Get incidents that caused SLA breach for a service in a given month.

    Returns list of incidents with downtime contribution details.
    """
    svc_result = await db.execute(
        select(MonitoredService).where(MonitoredService.service_name == service_name)
    )
    service = svc_result.scalar_one_or_none()
    if not service:
        return []

    days_in_month = monthrange(year, month)[1]
    start_date = date(year, month, 1)
    end_date = date(year, month, days_in_month)

    incidents_result = await db.execute(
        select(Incident).where(
            Incident.service_name == service_name,
            Incident.is_suppressed.is_(False),
            Incident.start_datetime.is_not(None),
        )
    )
    incidents = list(incidents_result.scalars().all())

    breach_reasons = []

    for inc in incidents:
        if inc.end_datetime and inc.end_datetime.date() < start_date:
            continue
        if inc.start_datetime.date() > end_date:
            continue

        exclude = False
        if service.sla_exclude_maintenance and inc.classification == "maintenance":
            exclude = True
        if service.sla_exclude_advisory and inc.classification == "advisory":
            exclude = True
        # Only count high/critical severity incidents for SLA breach (exclude low/medium/none)
        if not inc.severity or inc.severity not in ("high", "critical"):
            exclude = True

        if exclude:
            continue

        inc_start = max(inc.start_datetime.date(), start_date)
        inc_end_date = inc.end_datetime.date() if inc.end_datetime else end_date
        inc_end = min(inc_end_date, end_date)

        days = (inc_end - inc_start).days + 1
        minutes = days * 24 * 60

        if inc.severity in ("critical",) or inc.status == "interrupted":
            weighted_minutes = minutes
        elif inc.status == "degraded":
            weighted_minutes = minutes * 0.5
        else:
            weighted_minutes = minutes

        breach_reasons.append({
            "id": inc.id,
            "title": inc.title,
            "status": inc.status,
            "classification": inc.classification,
            "severity": inc.severity,
            "start_datetime": inc.start_datetime.isoformat() if inc.start_datetime else None,
            "end_datetime": inc.end_datetime.isoformat() if inc.end_datetime else None,
            "duration_minutes": round(minutes, 1),
            "weighted_minutes": round(weighted_minutes, 1),
            "description": inc.description,
        })

    return sorted(breach_reasons, key=lambda x: x["weighted_minutes"], reverse=True)


async def get_sla_for_month(
    db: AsyncSession,
    service_name: str,
    year: int,
    month: int,
) -> dict[str, Any]:
    """Calculate SLA availability for a service in a given month.

    Severity weighting:
      - interrupted/critical: 100% downtime contribution
      - degraded: 50% downtime contribution

    Returns:
        {
            "actual_percent": 99.95,
            "target_percent": 99.9,
            "is_breach": False,
            "downtime_minutes": 21.6,
            "excluded_minutes": 0.0,
        }
    """
    svc_result = await db.execute(
        select(MonitoredService).where(MonitoredService.service_name == service_name)
    )
    service = svc_result.scalar_one_or_none()
    if not service:
        return {
            "actual_percent": 0.0,
            "target_percent": 99.9,
            "is_breach": True,
            "downtime_minutes": 0.0,
            "excluded_minutes": 0.0,
        }

    # Month boundaries
    days_in_month = monthrange(year, month)[1]
    start_date = date(year, month, 1)
    end_date = date(year, month, days_in_month)

    # Total minutes in month
    total_minutes = days_in_month * 24 * 60

    # Get all incidents
    incidents_result = await db.execute(
        select(Incident).where(
            Incident.service_name == service_name,
            Incident.is_suppressed.is_(False),
            Incident.start_datetime.is_not(None),
        )
    )
    incidents = list(incidents_result.scalars().all())

    downtime_minutes = 0.0
    excluded_minutes = 0.0

    for inc in incidents:
        # Skip if entirely outside month
        if inc.end_datetime and inc.end_datetime.date() < start_date:
            continue
        if inc.start_datetime.date() > end_date:
            continue

        # Check if should be excluded
        exclude = False
        if service.sla_exclude_maintenance and inc.classification == "maintenance":
            exclude = True
        if service.sla_exclude_advisory and inc.classification == "advisory":
            exclude = True

        # Clamp incident dates to month
        inc_start = max(inc.start_datetime.date(), start_date)
        inc_end_date = inc.end_datetime.date() if inc.end_datetime else end_date
        inc_end = min(inc_end_date, end_date)

        # Calculate minutes for this incident
        days = (inc_end - inc_start).days + 1
        minutes = days * 24 * 60

        if exclude:
            excluded_minutes += minutes
        else:
            # Apply severity weighting
            if inc.severity in ("critical",) or inc.status == "interrupted":
                weighted_minutes = minutes
            elif inc.status == "degraded":
                weighted_minutes = minutes * 0.5
            else:
                weighted_minutes = minutes

            downtime_minutes += weighted_minutes

    # Calculate actual percentage
    actual_minutes = max(0, total_minutes - downtime_minutes)
    actual_percent = (actual_minutes / total_minutes * 100) if total_minutes > 0 else 100
    is_breach = actual_percent < service.sla_target_percentage

    return {
        "actual_percent": round(actual_percent, 2),
        "target_percent": service.sla_target_percentage,
        "is_breach": is_breach,
        "downtime_minutes": round(downtime_minutes, 1),
        "excluded_minutes": round(excluded_minutes, 1),
    }


async def record_http_check_result(
    db: AsyncSession,
    service_name: str,
    result: dict[str, Any],
) -> HttpCheckResult:
    row = HttpCheckResult(
        service_name=service_name,
        is_up=result["is_up"],
        status_code=result.get("status_code"),
        response_time_ms=result.get("response_time_ms"),
        error_message=result.get("error_message"),
    )
    db.add(row)
    await db.flush()
    return row


async def prune_old_http_check_results(db: AsyncSession, retention_days: int) -> None:
    cutoff = datetime.utcnow() - timedelta(days=retention_days)
    await db.execute(delete(HttpCheckResult).where(HttpCheckResult.checked_at < cutoff))


async def get_http_dashboard_data(db: AsyncSession, uptime_days: int = 30) -> list[dict]:
    """HTTP-check services enriched with their latest result and uptime % over
    the window. Uses a window function to avoid an N+1 query per service."""
    latest_sq = (
        select(
            HttpCheckResult.service_name,
            HttpCheckResult.is_up,
            HttpCheckResult.status_code,
            HttpCheckResult.response_time_ms,
            HttpCheckResult.error_message,
            HttpCheckResult.checked_at,
            func.row_number()
            .over(
                partition_by=HttpCheckResult.service_name,
                order_by=desc(HttpCheckResult.checked_at),
            )
            .label("rn"),
        ).subquery()
    )

    cutoff = datetime.utcnow() - timedelta(days=uptime_days)
    uptime_sq = (
        select(
            HttpCheckResult.service_name,
            func.avg(func.cast(HttpCheckResult.is_up, Integer)).label("uptime_ratio"),
            func.count().label("sample_count"),
        )
        .where(HttpCheckResult.checked_at >= cutoff)
        .group_by(HttpCheckResult.service_name)
        .subquery()
    )

    result = await db.execute(
        select(
            MonitoredService,
            latest_sq.c.is_up,
            latest_sq.c.status_code,
            latest_sq.c.response_time_ms,
            latest_sq.c.error_message,
            latest_sq.c.checked_at,
            uptime_sq.c.uptime_ratio,
            uptime_sq.c.sample_count,
        )
        .where(MonitoredService.http_url.is_not(None))
        .outerjoin(
            latest_sq,
            and_(latest_sq.c.service_name == MonitoredService.service_name, latest_sq.c.rn == 1),
        )
        .outerjoin(uptime_sq, uptime_sq.c.service_name == MonitoredService.service_name)
        .order_by(*_service_sort_clause())
    )

    dashboard: list[dict] = []
    for service, is_up, status_code, response_time_ms, error_message, checked_at, uptime_ratio, sample_count in result.all():
        dashboard.append({
            "service": service,
            "is_up": is_up,
            "status_code": status_code,
            "response_time_ms": response_time_ms,
            "error_message": error_message,
            "checked_at": checked_at,
            "uptime_percent": round(uptime_ratio * 100, 2) if uptime_ratio is not None else None,
            "sample_count": sample_count or 0,
        })
    return dashboard


async def get_certificate_dashboard_data(db: AsyncSession) -> list[dict]:
    """Certificate services enriched with their current status, derived from
    the still-open incident poll_certificates creates for warning/expired certs."""
    services_result = await db.execute(
        select(MonitoredService)
        .where(MonitoredService.cert_hostname.is_not(None))
        .order_by(*_service_sort_clause())
    )
    services = list(services_result.scalars().all())

    incidents_result = await db.execute(
        select(Incident).where(
            Incident.source == "certificate",
            Incident.is_resolved.is_(False),
        )
    )
    open_by_service = {inc.service_name: inc for inc in incidents_result.scalars().all()}

    dashboard: list[dict] = []
    for service in services:
        incident = open_by_service.get(service.service_name)

        # Get latest certificate check result for this service
        cert_result = await db.execute(
            select(CertificateCheckResult)
            .where(CertificateCheckResult.service_name == service.service_name)
            .order_by(CertificateCheckResult.checked_at.desc())
            .limit(1)
        )
        latest_check = cert_result.scalars().first()

        dashboard.append({
            "service": service,
            "status": "ok" if incident is None else ("expired" if incident.status == "active" else "warning"),
            "incident": incident,
            "expires_at": latest_check.expires_at if latest_check else None,
            "days_remaining": latest_check.days_remaining if latest_check else None,
            "issuer": latest_check.issuer if latest_check else None,
            "checked_at": latest_check.checked_at if latest_check else None,
        })
    return dashboard
