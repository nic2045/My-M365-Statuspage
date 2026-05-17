import logging
from datetime import date, datetime

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger
from sqlalchemy import select as sa_select

from app.config import settings
from app.crud import (
    add_state_change_entry,
    ensure_service_known,
    get_enabled_services,
    upsert_incident,
    upsert_incident_updates,
    upsert_service_status,
)
from app.database import AsyncSessionLocal
from app.graph_client import (
    fetch_active_issues,
    fetch_health_overviews,
    fetch_recently_resolved_issues,
)
from app.models import GRAPH_STATUS_MAP, Incident

logger = logging.getLogger(__name__)

scheduler = AsyncIOScheduler()

_GRAPH_SEVERITY_MAP: dict[str, str] = {
    "minor":    "low",
    "moderate": "medium",
    "major":    "high",
}

# Maps Graph API classification to our internal classification.
# advisory and unknown classifications are excluded (return None → skip).
_GRAPH_CLASSIFICATION_MAP: dict[str, str] = {
    "incident":           "incident",
    "plannedMaintenance": "maintenance",
}

# Maps the Microsoft Graph issue `status` field to one of our incident phases:
#   active        – Investigating  (Untersuchung läuft)
#   acknowledged  – Identified     (Ursache bekannt, Behebung startet)
#   monitoring    – Monitoring     (Fix eingespielt, System wird beobachtet)
#   resolved      – Resolved       (Behoben)
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


def _issue_status(issue: dict, classification: str) -> str:
    """Map a Graph API issue to one of our internal phase/status strings.

    Maintenance items use their own lifecycle (scheduled / completed).
    Incidents are mapped via _GRAPH_INCIDENT_PHASE_MAP from the Graph
    `status` field – which Microsoft updates as the incident progresses
    from Investigating → ServiceDegradation/Interruption → RestoringService
    → ServiceRestored. We fall back to active / resolved if Graph hasn't
    set a recognized status.
    """
    if classification == "maintenance":
        return "completed" if issue.get("isResolved") else "scheduled"
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


async def sync_issue_as_incident(db, issue: dict) -> None:
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
        return
    severity = _GRAPH_SEVERITY_MAP.get(issue.get("severity", ""), "")
    new_status = _issue_status(issue, classification)

    existing = await db.execute(
        sa_select(Incident).where(Incident.graph_issue_id == issue["id"])
    )
    existing_incident = existing.scalar_one_or_none()
    old_status = existing_incident.status if existing_incident else None

    fields: dict = {
        "title": issue.get("title", ""),
        "service_name": issue.get("service", ""),
        "classification": classification,
        "status": new_status,
        "start_datetime": _parse_dt(issue.get("startDateTime")),
        "last_modified": _parse_dt(issue.get("lastModifiedDateTime")),
        "is_resolved": issue.get("isResolved", False),
        "severity": severity,
    }
    if classification == "maintenance":
        fields["scheduled_start"] = _parse_dt(issue.get("startDateTime"))
        fields["scheduled_end"] = _parse_dt(issue.get("endDateTime"))
    incident = await upsert_incident(db, graph_issue_id=issue["id"], **fields)

    if old_status is not None and old_status != new_status:
        await add_state_change_entry(db, incident.id, new_status)

    posts = issue.get("posts")
    if posts:
        await upsert_incident_updates(db, incident.id, posts)


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
    async with AsyncSessionLocal() as db:
        try:
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

            for name in monitored:
                if name not in seen_services:
                    await upsert_service_status(db, name, today, "operational", "serviceOperational")

            await db.commit()
            logger.info("Health overviews committed for %d services.", len(monitored))

        except Exception:
            await db.rollback()
            logger.exception("Health overview poll failed")

    # ── Phase 2: Active incidents (independent – failure here doesn't touch phase 3) ──
    async with AsyncSessionLocal() as db:
        try:
            active_issues = await fetch_active_issues()
            synced = 0
            for issue in active_issues:
                if issue.get("service") not in monitored:
                    continue
                if _classify_issue(issue) is None:
                    continue
                await sync_issue_as_incident(db, issue)
                synced += 1
            await db.commit()
            logger.info("Active issues committed: %d synced (of %d fetched).", synced, len(active_issues))
        except Exception:
            await db.rollback()
            logger.exception("Active issues poll failed")

    # ── Phase 3: Recently resolved (30 days) – independent, safe to fail ────────
    # The uptime bars compute live from Incidents in get_uptime_bars; keeping
    # the last 30 days of resolved issues here means the bars stay accurate
    # without a separate ServiceStatus backfill phase. For deeper history
    # (30–90 days) admins trigger a one-shot sync when enabling a service.
    async with AsyncSessionLocal() as db:
        try:
            resolved_issues = await fetch_recently_resolved_issues(days=30)
            synced = 0
            for issue in resolved_issues:
                if issue.get("service") not in monitored:
                    continue
                if _classify_issue(issue) is None:
                    continue
                await sync_issue_as_incident(db, issue)
                synced += 1
            await db.commit()
            logger.info("Recently resolved committed: %d synced (of %d fetched).", synced, len(resolved_issues))
        except Exception:
            await db.rollback()
            logger.exception("Recently resolved issues poll failed – active issues unaffected")


def start_scheduler() -> None:
    scheduler.add_job(
        poll_graph_api,
        trigger=IntervalTrigger(minutes=settings.POLL_INTERVAL_MINUTES),
        id="graph_poll",
        replace_existing=True,
        next_run_time=datetime.now(),  # run immediately on startup
    )
    scheduler.start()
    logger.info("Scheduler started (interval: %d min)", settings.POLL_INTERVAL_MINUTES)


def stop_scheduler() -> None:
    if scheduler.running:
        scheduler.shutdown(wait=False)
        logger.info("Scheduler stopped.")
