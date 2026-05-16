from datetime import date as date_type
from datetime import datetime

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


# Maps Graph API status strings to internal status values
GRAPH_STATUS_MAP: dict[str, str] = {
    "serviceOperational":        "operational",
    "serviceRestored":           "operational",
    "serviceInformation":        "operational",
    "degradedPerformance":       "degraded",
    "serviceDegradation":        "degraded",
    "extendedRecovery":          "degraded",
    "investigationSuspended":    "degraded",
    "serviceInterruption":       "interrupted",
    "restoringService":          "interrupted",
    "falsePositive":             "operational",
}

STATUS_TAILWIND_BAR: dict[str, str] = {
    "operational": "bg-emerald-500",
    "degraded":    "bg-amber-400",
    "interrupted": "bg-red-500",
    "no_data":     "bg-gray-200 dark:bg-gray-700",
    "unknown":     "bg-gray-300 dark:bg-gray-600",
}

STATUS_BADGE_CLASSES: dict[str, str] = {
    "operational": "bg-emerald-100 text-emerald-800 dark:bg-emerald-900/40 dark:text-emerald-400",
    "degraded":    "bg-amber-100 text-amber-800 dark:bg-amber-900/40 dark:text-amber-400",
    "interrupted": "bg-red-100 text-red-800 dark:bg-red-900/40 dark:text-red-400",
    "unknown":     "bg-gray-100 text-gray-600 dark:bg-gray-800 dark:text-gray-400",
}

INCIDENT_BORDER: dict[str, str] = {
    "incident":    "border-red-500",
    "advisory":    "border-amber-400",
    "maintenance": "border-blue-400",
}


class ServiceStatus(Base):
    __tablename__ = "service_status"
    __table_args__ = (UniqueConstraint("service_name", "date", name="uq_service_date"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    service_name: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    date: Mapped[date_type] = mapped_column(Date, nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="unknown")
    raw_graph_status: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class Incident(Base):
    __tablename__ = "incidents"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    graph_issue_id: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(512), nullable=False)
    service_name: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    classification: Mapped[str] = mapped_column(String(32), nullable=False, default="incident")
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="active")
    start_datetime: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_modified: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    is_resolved: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    source: Mapped[str] = mapped_column(String(32), nullable=False, server_default="graph")
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    scheduled_start: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    scheduled_end: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )

    updates: Mapped[list["IncidentUpdate"]] = relationship(
        "IncidentUpdate",
        back_populates="incident",
        cascade="all, delete-orphan",
        order_by="IncidentUpdate.post_created_at",
    )


class IncidentUpdate(Base):
    __tablename__ = "incident_updates"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    incident_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("incidents.id", ondelete="CASCADE"), nullable=False, index=True
    )
    content: Mapped[str] = mapped_column(Text, nullable=False, default="")
    post_created_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    incident: Mapped["Incident"] = relationship("Incident", back_populates="updates")
