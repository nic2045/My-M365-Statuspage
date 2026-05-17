import logging
from datetime import date, datetime

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger

from app.config import settings
from app.crud import (
    backfill_service_status_from_issues,
    count_status_days_in_window,
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
    fetch_issues_since,
    fetch_recently_resolved_issues,
)
from app.models import GRAPH_STATUS_MAP

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


def _classify_issue(issue: dict) -> str | None:
    """Return internal classification string, or None if the issue should be skipped."""
    if issue.get("status") == "falsePositive":
        return None
    return _GRAPH_CLASSIFICATION_MAP.get(issue.get("classification", ""))


def _issue_status(issue: dict, classification: str) -> str:
    """Map Graph API issue to our internal status string."""
    if issue.get("isResolved"):
        return "completed" if classification == "maintenance" else "resolved"
    return "scheduled" if classification == "maintenance" else "active"


def _parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return dt.replace(tzinfo=None)
    except (ValueError, AttributeError):
        return None


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
                classification = _classify_issue(issue)
                if classification is None:
                    continue  # advisory, falsePositive, or unknown – skip
                severity = _GRAPH_SEVERITY_MAP.get(issue.get("severity", ""), "")
                fields: dict = {
                    "title": issue.get("title", ""),
                    "service_name": issue.get("service", ""),
                    "classification": classification,
                    "status": _issue_status(issue, classification),
                    "start_datetime": _parse_dt(issue.get("startDateTime")),
                    "last_modified": _parse_dt(issue.get("lastModifiedDateTime")),
                    "is_resolved": issue.get("isResolved", False),
                    "severity": severity,
                }
                if classification == "maintenance":
                    fields["scheduled_start"] = _parse_dt(issue.get("startDateTime"))
                    fields["scheduled_end"] = _parse_dt(issue.get("endDateTime"))
                incident = await upsert_incident(db, graph_issue_id=issue["id"], **fields)
                posts = issue.get("posts") or []
                await upsert_incident_updates(db, incident.id, posts)
                synced += 1
            await db.commit()
            logger.info("Active issues committed: %d synced (of %d fetched).", synced, len(active_issues))
        except Exception:
            await db.rollback()
            logger.exception("Active issues poll failed")

    # ── Phase 3: Recently resolved (30 days) – independent, safe to fail ────────
    async with AsyncSessionLocal() as db:
        try:
            resolved_issues = await fetch_recently_resolved_issues(days=30)
            synced = 0
            for issue in resolved_issues:
                if issue.get("service") not in monitored:
                    continue
                classification = _classify_issue(issue)
                if classification is None:
                    continue  # advisory, falsePositive, or unknown – skip
                severity = _GRAPH_SEVERITY_MAP.get(issue.get("severity", ""), "")
                fields = {
                    "title": issue.get("title", ""),
                    "service_name": issue.get("service", ""),
                    "classification": classification,
                    "status": _issue_status(issue, classification),
                    "start_datetime": _parse_dt(issue.get("startDateTime")),
                    "last_modified": _parse_dt(issue.get("lastModifiedDateTime")),
                    "is_resolved": issue.get("isResolved", False),
                    "severity": severity,
                }
                if classification == "maintenance":
                    fields["scheduled_start"] = _parse_dt(issue.get("startDateTime"))
                    fields["scheduled_end"] = _parse_dt(issue.get("endDateTime"))
                incident = await upsert_incident(db, graph_issue_id=issue["id"], **fields)
                posts = issue.get("posts") or []
                await upsert_incident_updates(db, incident.id, posts)
                synced += 1
            await db.commit()
            logger.info("Recently resolved committed: %d synced (of %d fetched).", synced, len(resolved_issues))
        except Exception:
            await db.rollback()
            logger.exception("Recently resolved issues poll failed – active issues unaffected")

    # ── Phase 4: 90-day history backfill (only if gaps exist) ───────────────────
    # After a container restart with a fresh volume, service_status is empty and
    # the 90-day uptime bars show "no_data". Reconstruct missing days from the
    # Graph API issue history: days with no incident → operational; days covered
    # by an incident → degraded/interrupted.
    for name in monitored:
        async with AsyncSessionLocal() as db:
            try:
                existing = await count_status_days_in_window(db, name, days=90)
                if existing >= 90:
                    continue
                issues = await fetch_issues_since(name, days=90)
                await backfill_service_status_from_issues(db, name, issues, days=90)
                await db.commit()
                logger.info(
                    "Backfill committed for %s: %d issues, filled %d missing days.",
                    name, len(issues), 90 - existing,
                )
            except Exception:
                await db.rollback()
                logger.exception("Backfill failed for %s", name)


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
