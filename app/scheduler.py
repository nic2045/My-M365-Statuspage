import logging
from datetime import date, datetime

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger

from app.config import settings
from app.crud import upsert_incident, upsert_incident_updates, upsert_service_status
from app.database import AsyncSessionLocal
from app.graph_client import fetch_active_issues, fetch_health_overviews
from app.models import GRAPH_STATUS_MAP

logger = logging.getLogger(__name__)

scheduler = AsyncIOScheduler()

_GRAPH_SEVERITY_MAP: dict[str, str] = {
    "minor":    "low",
    "moderate": "medium",
    "major":    "high",
}


def _parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return dt.replace(tzinfo=None)
    except (ValueError, AttributeError):
        return None


async def poll_graph_api() -> None:
    monitored = settings.monitored_services_list
    today = date.today()
    logger.info("Graph API poll started for services: %s", monitored)

    # ── Phase 1: Health overviews (committed independently) ──────────────────
    async with AsyncSessionLocal() as db:
        try:
            overviews = await fetch_health_overviews()
            seen_services: set[str] = set()

            for svc in overviews:
                name = svc.get("service", "")
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

    # ── Phase 2: Active incidents (separate session – failure won't roll back phase 1) ──
    async with AsyncSessionLocal() as db:
        try:
            issues = await fetch_active_issues()
            for issue in issues:
                if issue.get("service") not in monitored:
                    continue
                severity = _GRAPH_SEVERITY_MAP.get(issue.get("severity", ""), "")
                incident = await upsert_incident(
                    db,
                    graph_issue_id=issue["id"],
                    title=issue.get("title", ""),
                    service_name=issue.get("service", ""),
                    classification=issue.get("classification", "incident"),
                    status="resolved" if issue.get("isResolved") else "active",
                    start_datetime=_parse_dt(issue.get("startDateTime")),
                    last_modified=_parse_dt(issue.get("lastModifiedDateTime")),
                    is_resolved=issue.get("isResolved", False),
                    severity=severity,
                )
                posts = issue.get("posts", [])
                await upsert_incident_updates(db, incident.id, posts)

            await db.commit()
            logger.info("Graph API poll completed successfully.")

        except Exception:
            await db.rollback()
            logger.exception("Active issues poll failed")


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
