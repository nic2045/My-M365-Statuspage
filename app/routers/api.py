import logging
from datetime import datetime

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import require_auth
from app.config import settings
from app.crud import build_status_page_data
from app.dependencies import get_db
from app.graph_client import fetch_health_overviews
from app.schemas import StatusPageSchema

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1", tags=["api"])


@router.get("/health")
async def health_check():
    """Docker healthcheck endpoint – no authentication required.

    Response shape is a fixed {"status": "ok"} contract (see
    tests/test_docker_integration.py::test_health_200) - add new fields to
    /health/full instead of changing this one.
    """
    return {"status": "ok"}


@router.get("/health/ready")
async def readiness_check(db: AsyncSession = Depends(get_db)):
    """Readiness check — verifies app is ready to serve requests (DB connectivity).
    Returns 200 if all dependencies are healthy, 503 otherwise.
    No authentication required."""
    checks = {
        "database": False,
        "timestamp": datetime.utcnow().isoformat(),
    }

    try:
        await db.execute(text("SELECT 1"))
        checks["database"] = True
    except Exception as e:
        logger.error(f"Database health check failed: {e}")
        return JSONResponse(
            status_code=503,
            content={"status": "unavailable", "database": False, "timestamp": datetime.utcnow().isoformat()},
        )

    return {"status": "ready", **checks}


@router.get("/health/full")
async def detailed_health_check(db: AsyncSession = Depends(get_db)):
    """Full health check with all dependency details (no auth required).
    Returns 200 if critical checks pass, 503 if any critical check fails."""
    checks = {
        "app": {"status": "up"},
        "database": {"status": "unknown"},
        "graph_api": {"status": "unknown"},
        "timestamp": datetime.utcnow().isoformat(),
    }

    # Check database
    try:
        result = await db.execute(text("SELECT COUNT(*) FROM incidents"))
        count = result.scalar()
        checks["database"] = {
            "status": "up",
            "incident_count": count,
        }
    except Exception as e:
        logger.error(f"Database health check failed: {e}")
        checks["database"] = {"status": "down"}

    # Check Graph API (non-critical for readiness, but useful for monitoring)
    try:
        if settings.DISABLE_AUTH or settings.AZURE_CLIENT_ID:
            overviews = await fetch_health_overviews()
            checks["graph_api"] = {
                "status": "up",
                "services_checked": len(overviews) if overviews else 0,
            }
        else:
            checks["graph_api"] = {
                "status": "skipped",
                "reason": "Auth disabled or not configured",
            }
    except Exception as e:
        logger.warning(f"Graph API health check failed: {e}")
        checks["graph_api"] = {"status": "down"}

    # Overall status: critical if database is down, otherwise healthy
    overall_status = (
        "healthy"
        if checks["database"]["status"] == "up"
        else "unhealthy"
    )
    status_code = 200 if overall_status == "healthy" else 503

    return JSONResponse(
        status_code=status_code,
        content={
            "status": overall_status,
            "checks": checks,
        },
    )


@router.get("/status", response_model=StatusPageSchema)
async def api_status(
    _user: dict = Depends(require_auth),
    db: AsyncSession = Depends(get_db),
):
    return await build_status_page_data(db, settings.monitored_services_list)
