import asyncio
import logging
from dataclasses import dataclass
from datetime import date, datetime

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger
from sqlalchemy import func
from sqlalchemy import select as sa_select

from app.certificate_client import (
    get_certificate_expiration,
    get_certificate_severity,
    get_certificate_status_display,
)
from app.config import settings
from app.crud import (
    add_state_change_entry,
    ensure_service_known,
    get_enabled_services,
    prune_old_http_check_results,
    record_http_check_result,
    upsert_incident,
    upsert_incident_updates,
    upsert_service_status,
)
from app.database import AsyncSessionLocal
from app.event_bus import StatusEvent, get_event_bus
from app.graph_client import (
    fetch_active_issues,
    fetch_health_overviews,
    fetch_recently_resolved_issues,
)
from app.http_check_client import check_http_endpoint, get_http_check_severity
from app.i18n import LABELS
from app.models import (
    GRAPH_STATUS_MAP,
    CertificateCheckResult,
    HttpCheckResult,
    Incident,
    MonitoredService,
    ServiceStatus,
)
from app.notifications import dispatch_incident_notifications

logger = logging.getLogger(__name__)

scheduler = AsyncIOScheduler()

_GRAPH_SEVERITY_MAP: dict[str, str] = {
    "minor":    "low",
    "moderate": "medium",
    "major":    "high",
}

# Maps Graph API classification to our internal classification.
# Unknown classifications are dropped (return None → skip).
# - "incident":            real outages
# - "advisory":            informational notices that don't impact uptime
# - "plannedMaintenance":  scheduled service maintenance
# - "planForChange":       upcoming feature/UI changes – treated as maintenance
_GRAPH_CLASSIFICATION_MAP: dict[str, str] = {
    "incident":           "incident",
    "advisory":           "advisory",
    "plannedMaintenance": "maintenance",
    "planForChange":      "maintenance",
}

# Maps the Microsoft Graph issue `status` field to one of our incident phases:
#   active        – Investigating  (problem known, root cause being searched)
#   acknowledged  – Identified     (root cause known, remediation starting)
#   monitoring    – Monitoring     (fix deployed, system being observed)
#   resolved      – Resolved       (incident closed)
# falsePositive is intentionally omitted; _classify_issue filters those out.
_GRAPH_INCIDENT_PHASE_MAP: dict[str, str] = {
    "investigating":               "active",
    "investigationSuspended":      "active",
    "serviceDegradation":          "acknowledged",
    "serviceInterruption":         "acknowledged",
    "restoringService":            "monitoring",
    "extendedRecovery":            "monitoring",
    "serviceRestored":             "resolved",
    "postIncidentReportPublished": "resolved",
    "resolved":                    "resolved",
}


def _classify_issue(issue: dict) -> str | None:
    """Return internal classification string, or None if the issue should be skipped."""
    if issue.get("status") == "falsePositive":
        return None
    return _GRAPH_CLASSIFICATION_MAP.get(issue.get("classification", ""))


def _maintenance_phase(issue: dict) -> str:
    """Compute the current phase for a maintenance/planForChange item.

    Three phases mirror the existing dropdown:
      scheduled    – future window
      in_progress  – we are inside [start, end] right now
      completed    – Graph marked it resolved
    """
    if issue.get("isResolved"):
        return "completed"
    start = _parse_dt(issue.get("startDateTime"))
    end = _parse_dt(issue.get("endDateTime"))
    now = datetime.utcnow()
    if start and end and start <= now < end:
        return "in_progress"
    return "scheduled"


def _issue_status(issue: dict, classification: str) -> str:
    """Map a Graph API issue to one of our internal phase/status strings.

    - Maintenance / planForChange items roll through scheduled →
      in_progress → completed based on their start/end window.
    - Incidents and advisories are mapped via _GRAPH_INCIDENT_PHASE_MAP
      from the Graph `status` field – which Microsoft updates as the
      incident progresses from Investigating →
      ServiceDegradation/Interruption → RestoringService → ServiceRestored.
      Fall back to active / resolved if Graph hasn't set a recognized
      status.
    """
    if classification == "maintenance":
        return _maintenance_phase(issue)
    raw_status = issue.get("status", "")
    mapped = _GRAPH_INCIDENT_PHASE_MAP.get(raw_status)
    if mapped:
        return mapped
    return "resolved" if issue.get("isResolved") else "active"


def _parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return dt.replace(tzinfo=None)
    except (ValueError, AttributeError):
        return None


@dataclass
class _NotifyEvent:
    """Notification trigger captured during sync — dispatched after DB commit."""
    incident_title: str
    service_name: str
    description: str
    status: str
    is_new: bool


async def sync_issue_as_incident(db, issue: dict) -> "_NotifyEvent | None":
    """Upsert a Graph API issue as an Incident (and its posts, if present).

    Returns silently if the issue should be skipped (advisory, falsePositive,
    or unknown classification). Posts are only synced when present on the
    issue dict – historical fetches may omit them for performance.

    When the mapped phase changes between two consecutive polls we record
    a state_change timeline entry so the incident detail phase-bar reflects
    Microsoft's progression (Investigating → Identified → Monitoring →
    Resolved) as proper segments.
    """
    classification = _classify_issue(issue)
    if classification is None:
        return None
    severity = _GRAPH_SEVERITY_MAP.get(issue.get("severity", ""), "")
    new_status = _issue_status(issue, classification)

    existing = await db.execute(
        sa_select(Incident).where(Incident.graph_issue_id == issue["id"])
    )
    existing_incident = existing.scalar_one_or_none()
    old_status = existing_incident.status if existing_incident else None

    impact_desc = issue.get("impactDescription") or None

    fields: dict = {
        "service_name": issue.get("service", ""),
        "classification": classification,
        "status": new_status,
        "start_datetime": _parse_dt(issue.get("startDateTime")),
        "end_datetime": _parse_dt(issue.get("endDateTime")),
        "last_modified": _parse_dt(issue.get("lastModifiedDateTime")),
        "is_resolved": issue.get("isResolved", False),
        "severity": severity,
    }
    # Microsoft's service-health text is English-only and DeepL translation
    # is an explicit, on-demand admin action (see routers/admin.py
    # translate_incident) - not run automatically here to avoid burning
    # through a free-tier DeepL quota on every poll. Once an admin has
    # translated an incident (translated_lang set), stop overwriting its
    # title from Graph so the translation sticks.
    if not (existing_incident and existing_incident.translated_lang):
        fields["title"] = issue.get("title", "")
    # Only set description from impactDescription when the incident has none yet,
    # preserving any description an admin has written manually (or translated).
    if impact_desc and not (existing_incident and existing_incident.description):
        fields["description"] = impact_desc
    if classification == "maintenance":
        fields["scheduled_start"] = _parse_dt(issue.get("startDateTime"))
        fields["scheduled_end"] = _parse_dt(issue.get("endDateTime"))
    incident = await upsert_incident(db, graph_issue_id=issue["id"], **fields)

    is_new = existing_incident is None
    status_changed = old_status is not None and old_status != new_status
    # Record state changes: for existing incidents when status changes,
    # for new incidents only if already resolved (historical incidents)
    should_record_state = status_changed or (is_new and new_status == "resolved")
    if should_record_state:
        await add_state_change_entry(db, incident.id, new_status)

    posts = issue.get("posts")
    if posts:
        # Once Microsoft has resolved the issue, its post(s) explain the
        # resolution itself - publish them immediately instead of waiting
        # on an operator, unlike posts written while the incident is still
        # open (see upsert_incident_updates).
        await upsert_incident_updates(db, incident.id, posts, auto_publish=(new_status == "resolved"))

    # Notify subscribers only for real incidents — advisories and maintenance
    # are intentionally excluded, matching the manual-create flow in
    # routers/admin.py. Fires on first detection and on every phase change
    # (Investigating → Identified → Monitoring → Resolved).
    if classification == "incident" and (is_new or status_changed):
        return _NotifyEvent(
            incident_title=incident.title,
            service_name=incident.service_name,
            description=(impact_desc or incident.description or ""),
            status=new_status,
            is_new=is_new,
        )
    return None


def _log_notification_error(task: asyncio.Task) -> None:
    """Log exceptions from fire-and-forget notification tasks."""
    try:
        task.result()
    except asyncio.CancelledError:
        pass
    except Exception as e:
        logger.exception("Notification dispatch failed: %s", e)


async def _dispatch_notifications(events: list[_NotifyEvent]) -> None:
    """Send email + Teams notifications for incidents detected during a poll."""
    for ev in events:
        subject_key = "notify.new_incident" if ev.is_new else "notify.update"
        task = asyncio.create_task(
            dispatch_incident_notifications(
                service_name=ev.service_name,
                incident_title=ev.incident_title,
                subject=LABELS[subject_key],
                description=ev.description,
                incident_status=ev.status,
            )
        )
        task.add_done_callback(_log_notification_error)


async def poll_graph_api() -> None:
    # Read enabled services from DB (not env var) so admin toggles take effect
    async with AsyncSessionLocal() as db:
        monitored = await get_enabled_services(db)

    if not monitored:
        logger.info("No enabled services configured. Skipping poll.")
        return

    today = date.today()
    logger.info("Graph API poll started for services: %s", monitored)

    # ── Phase 1: Health overviews (committed independently) ──────────────────
    service_status_changes: list[tuple[str, str]] = []  # (service_name, new_status)
    async with AsyncSessionLocal() as db:
        try:
            # Query existing service statuses for today before making changes
            existing_stmt = sa_select(ServiceStatus).where(ServiceStatus.date == today)
            existing_result = await db.execute(existing_stmt)
            existing_statuses: dict[str, str] = {
                row.service_name: row.status for row in existing_result.scalars()
            }

            overviews = await fetch_health_overviews()
            seen_services: set[str] = set()

            for svc in overviews:
                name = svc.get("service", "")
                if not name:
                    continue
                # Discover all services returned by Graph API (mark as known but not enabled)
                await ensure_service_known(db, name)
                if name not in monitored:
                    continue
                seen_services.add(name)
                raw_status = svc.get("status", "unknown")
                mapped = GRAPH_STATUS_MAP.get(raw_status, "unknown")
                await upsert_service_status(db, name, today, mapped, raw_status)
                # Track if status changed
                old_status = existing_statuses.get(name)
                if old_status is not None and old_status != mapped:
                    service_status_changes.append((name, mapped))

            for name in monitored:
                if name not in seen_services:
                    await upsert_service_status(db, name, today, "operational", "serviceOperational")
                    # Track if status changed
                    old_status = existing_statuses.get(name)
                    if old_status is not None and old_status != "operational":
                        service_status_changes.append((name, "operational"))

            await db.commit()
            logger.info("Health overviews committed for %d services.", len(monitored))

        except Exception:
            await db.rollback()
            logger.exception("Health overview poll failed")
            service_status_changes.clear()

    # Publish service status change events after Phase 1 commit
    event_bus = get_event_bus()
    for service_name, new_status in service_status_changes:
        await event_bus.publish(
            StatusEvent(
                event_type="service.status_changed",
                service_name=service_name,
                incident_id="",
                title="",
                status=new_status,
                timestamp=datetime.utcnow(),
            )
        )

    # ── Phase 2: Active incidents (independent – failure here doesn't touch phase 3) ──
    notify_events: list[_NotifyEvent] = []
    async with AsyncSessionLocal() as db:
        try:
            active_issues = await fetch_active_issues()
            synced = 0
            for issue in active_issues:
                if issue.get("service") not in monitored:
                    continue
                if _classify_issue(issue) is None:
                    continue
                ev = await sync_issue_as_incident(db, issue)
                if ev is not None:
                    notify_events.append(ev)
                synced += 1
            await db.commit()
            logger.info("Active issues committed: %d synced (of %d fetched).", synced, len(active_issues))
        except Exception:
            await db.rollback()
            notify_events.clear()
            logger.exception("Active issues poll failed")

    # Dispatch notifications only after the active-issues transaction has
    # been committed, so subscribers never see a notification for an
    # incident that was rolled back.
    await _dispatch_notifications(notify_events)

    # ── Phase 3: Recently resolved (30 days) – independent, safe to fail ────────
    # The uptime bars compute live from Incidents in get_uptime_bars; keeping
    # the last 30 days of resolved issues here means the bars stay accurate
    # without a separate ServiceStatus backfill phase. For deeper history
    # (30–90 days) admins trigger a one-shot sync when enabling a service.
    resolved_notify_events: list[_NotifyEvent] = []
    async with AsyncSessionLocal() as db:
        try:
            resolved_issues = await fetch_recently_resolved_issues(days=30)
            synced = 0
            for issue in resolved_issues:
                if issue.get("service") not in monitored:
                    continue
                if _classify_issue(issue) is None:
                    continue
                ev = await sync_issue_as_incident(db, issue)
                # Only forward transition events from phase 3 — suppress
                # "new" events so historical backfills of resolved incidents
                # don't trigger a flood of notifications on first run.
                if ev is not None and not ev.is_new:
                    resolved_notify_events.append(ev)
                synced += 1
            await db.commit()
            logger.info("Recently resolved committed: %d synced (of %d fetched).", synced, len(resolved_issues))
        except Exception:
            await db.rollback()
            resolved_notify_events.clear()
            logger.exception("Recently resolved issues poll failed – active issues unaffected")

    await _dispatch_notifications(resolved_notify_events)


async def poll_certificates() -> None:
    """Monitor TLS certificates and create/update incidents based on expiration status."""
    logger.info("Starting certificate poll...")
    async with AsyncSessionLocal() as db:
        try:
            result = await db.execute(
                sa_select(MonitoredService).where(
                    MonitoredService.cert_hostname.is_not(None)
                    & MonitoredService.is_enabled
                )
            )
            cert_services = result.scalars().all()

            for service in cert_services:
                service_name = service.service_name
                if not service.cert_hostname:
                    logger.warning(f"Certificate service {service_name} missing hostname")
                    continue

                try:
                    cert_info = await get_certificate_expiration(service.cert_hostname)
                    status = cert_info["status"]
                    severity = get_certificate_severity(status)
                    days_remaining = cert_info["days_remaining"]

                    # Record certificate check result for dashboard
                    check_result = CertificateCheckResult(
                        service_name=service_name,
                        status=status,
                        expires_at=cert_info["expires_at"],
                        valid_from=cert_info["valid_from"],
                        days_remaining=days_remaining,
                        common_name=cert_info["common_name"],
                        issuer=cert_info["issuer"],
                        serial_number=cert_info["serial_number"],
                    )
                    db.add(check_result)

                    # Determine incident status based on cert status
                    if status == "ok":
                        # If there was a previous incident, mark it resolved
                        result = await db.execute(
                            sa_select(Incident).where(
                                (Incident.service_name == service_name)
                                & (Incident.source == "certificate")
                                & ~Incident.is_resolved
                            )
                        )
                        existing = result.scalar_one_or_none()
                        if existing is not None:
                            existing.is_resolved = True
                            existing.status = "resolved"
                            existing.end_datetime = datetime.utcnow()
                            await db.flush()
                    else:
                        # Create or update incident for certificate warning/expiration
                        title = f"Certificate Expiration Warning: {cert_info['common_name']}"
                        if status == "expired":
                            title = f"Certificate Expired: {cert_info['common_name']}"

                        description = f"Certificate for {service.cert_hostname} expires in {days_remaining} days ({cert_info['expires_at'].isoformat()})"
                        incident_phase = "active" if status == "expired" else "monitoring"

                        incident = await upsert_incident(
                            db,
                            graph_issue_id=f"cert_{service_name}",
                            title=title,
                            service_name=service_name,
                            classification="incident",
                            status=incident_phase,
                            source="certificate",
                            severity=severity,
                            description=description,
                            start_datetime=datetime.utcnow(),
                            is_resolved=False,
                        )

                        # Add update with current status
                        await upsert_incident_updates(
                            db,
                            incident.id,
                            [
                                {
                                    "title": get_certificate_status_display(status),
                                    "body": description,
                                    "createdDateTime": datetime.utcnow().isoformat(),
                                    "postCreatedDateTime": datetime.utcnow().isoformat(),
                                }
                            ],
                            auto_publish=True,
                        )

                    await db.commit()
                except Exception:
                    await db.rollback()
                    logger.exception(f"Failed to poll certificate for {service_name}")

            logger.info(f"Certificate poll completed for {len(cert_services)} services")
        except Exception:
            logger.exception("Certificate poll failed")


async def poll_http_checks() -> None:
    """Check HTTP endpoints and create/update incidents based on reachability.

    Runs every minute but only actually checks a service once its own
    check_interval_seconds (or the HTTP_CHECK_DEFAULT_INTERVAL_SECONDS
    default) has elapsed since its last recorded result.
    """
    logger.info("Starting HTTP health check poll...")
    async with AsyncSessionLocal() as db:
        try:
            result = await db.execute(
                sa_select(MonitoredService).where(
                    MonitoredService.http_url.is_not(None) & MonitoredService.is_enabled
                )
            )
            http_services = result.scalars().all()

            checked = 0
            for service in http_services:
                service_name = service.service_name
                if not service.http_url:
                    logger.warning(f"HTTP check service {service_name} missing URL")
                    continue

                interval = service.check_interval_seconds or settings.HTTP_CHECK_DEFAULT_INTERVAL_SECONDS
                last_result = await db.execute(
                    sa_select(func.max(HttpCheckResult.checked_at)).where(
                        HttpCheckResult.service_name == service_name
                    )
                )
                last_checked_at = last_result.scalar_one_or_none()
                if last_checked_at and (datetime.utcnow() - last_checked_at).total_seconds() < interval:
                    continue

                try:
                    check_result = await check_http_endpoint(
                        service.http_url,
                        expected_status=service.http_expected_status or 200,
                        timeout_seconds=settings.HTTP_CHECK_TIMEOUT_SECONDS,
                    )
                    is_up = check_result["is_up"]
                    await record_http_check_result(db, service_name, check_result)
                    checked += 1

                    if is_up:
                        result = await db.execute(
                            sa_select(Incident).where(
                                (Incident.service_name == service_name)
                                & (Incident.source == "http_check")
                                & ~Incident.is_resolved
                            )
                        )
                        existing = result.scalar_one_or_none()
                        if existing is not None:
                            existing.is_resolved = True
                            existing.status = "resolved"
                            existing.end_datetime = datetime.utcnow()
                            await db.flush()
                    else:
                        severity = get_http_check_severity(is_up)
                        title = f"Endpoint Down: {service_name}"
                        description = check_result["error_message"] or "Endpoint unreachable"

                        incident = await upsert_incident(
                            db,
                            graph_issue_id=f"http_{service_name}",
                            title=title,
                            service_name=service_name,
                            classification="incident",
                            status="active",
                            source="http_check",
                            severity=severity,
                            description=description,
                            start_datetime=datetime.utcnow(),
                            is_resolved=False,
                        )
                        await upsert_incident_updates(
                            db,
                            incident.id,
                            [
                                {
                                    "title": "Endpoint Down",
                                    "body": description,
                                    "createdDateTime": datetime.utcnow().isoformat(),
                                    "postCreatedDateTime": datetime.utcnow().isoformat(),
                                }
                            ],
                            auto_publish=True,
                        )

                    await db.commit()
                except Exception:
                    await db.rollback()
                    logger.exception(f"Failed to poll HTTP check for {service_name}")

            await prune_old_http_check_results(db, settings.HTTP_CHECK_HISTORY_RETENTION_DAYS)
            await db.commit()
            logger.info(f"HTTP check poll completed for {checked} of {len(http_services)} services")
        except Exception:
            logger.exception("HTTP check poll failed")


def start_scheduler() -> None:
    scheduler.add_job(
        poll_graph_api,
        trigger=IntervalTrigger(minutes=settings.POLL_INTERVAL_MINUTES),
        id="graph_poll",
        replace_existing=True,
        next_run_time=datetime.now(),  # run immediately on startup
    )
    scheduler.add_job(
        poll_certificates,
        trigger=IntervalTrigger(hours=1),
        id="cert_poll",
        replace_existing=True,
        next_run_time=datetime.now(),
    )
    scheduler.add_job(
        poll_http_checks,
        trigger=IntervalTrigger(minutes=1),
        id="http_check_poll",
        replace_existing=True,
        next_run_time=datetime.now(),
    )
    scheduler.start()
    logger.info("Scheduler started (interval: %d min)", settings.POLL_INTERVAL_MINUTES)


def stop_scheduler() -> None:
    if scheduler.running:
        scheduler.shutdown(wait=False)
        logger.info("Scheduler stopped.")
