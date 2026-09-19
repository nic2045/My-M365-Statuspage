from datetime import date as date_type
from datetime import datetime

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    Float,
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
    "operational": "bg-[#28a745]",
    "degraded":    "bg-[#ffc107]",
    "interrupted": "bg-[#dc3545]",
    "no_data":     "bg-gray-200 dark:bg-gray-700",
    "unknown":     "bg-gray-300 dark:bg-gray-600",
}

STATUS_BADGE_CLASSES: dict[str, str] = {
    "operational": "bg-green-100 text-green-800 dark:bg-green-900/40 dark:text-green-400",
    "degraded":    "bg-amber-100 text-amber-800 dark:bg-amber-900/40 dark:text-amber-400",
    "interrupted": "bg-red-100 text-red-800 dark:bg-red-900/40 dark:text-red-400",
    "unknown":     "bg-gray-100 text-gray-600 dark:bg-gray-800 dark:text-gray-400",
}

STATUS_RING_CLASSES: dict[str, str] = {
    "operational": "bg-emerald-100 dark:bg-emerald-900/40",
    "degraded":    "bg-amber-100 dark:bg-amber-900/40",
    "interrupted": "bg-red-100 dark:bg-red-900/40",
    "unknown":     "bg-gray-100 dark:bg-gray-800",
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
    is_suppressed: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="0")
    source: Mapped[str] = mapped_column(String(100), nullable=False, server_default="graph")
    external_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    severity: Mapped[str] = mapped_column(String(32), nullable=False, server_default="")
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    end_datetime: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    scheduled_start: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    scheduled_end: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    owner_email: Mapped[str | None] = mapped_column(String(256), nullable=True)
    acknowledged_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    acknowledged_by_email: Mapped[str | None] = mapped_column(String(256), nullable=True)
    # Set once an admin manually translates this incident (see routers/admin.py
    # translate_incident). While set, the scheduler stops overwriting `title`
    # from Graph's English text on every poll - title becomes a one-time
    # manual action instead of a continuously-synced field.
    translated_lang: Mapped[str | None] = mapped_column(String(8), nullable=True)
    postmortem_impact: Mapped[str | None] = mapped_column(Text, nullable=True)
    postmortem_root_cause: Mapped[str | None] = mapped_column(Text, nullable=True)
    postmortem_action_items: Mapped[str | None] = mapped_column(Text, nullable=True)
    postmortem_timeline: Mapped[str | None] = mapped_column(Text, nullable=True)
    postmortem_published_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
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
    update_type: Mapped[str] = mapped_column(String(32), nullable=False, server_default="note")
    post_created_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    notify_subscribers: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="0", default=False
    )
    author: Mapped[str | None] = mapped_column(String(256), nullable=True)
    # False for message-center posts synced straight from Graph - an operator
    # must review and publish them explicitly (see routers/admin.py
    # publish_incident_update) before they appear on the public status page.
    # True by default for admin-authored updates/state-changes, which are
    # already public the moment an operator creates them.
    is_published: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="1", default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    incident: Mapped["Incident"] = relationship("Incident", back_populates="updates")


class MonitoredService(Base):
    __tablename__ = "monitored_services"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    service_name: Mapped[str] = mapped_column(String(128), unique=True, nullable=False, index=True)
    service_type: Mapped[str] = mapped_column(String(32), nullable=False, server_default="m365", default="m365")
    is_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    show_uptime_percentage: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="1", default=True
    )
    group_name: Mapped[str | None] = mapped_column(String(64), nullable=True)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0", default=0)
    sla_target_percentage: Mapped[float] = mapped_column(Float, nullable=False, default=99.9)
    sla_exclude_maintenance: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    sla_exclude_advisory: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    cert_hostname: Mapped[str | None] = mapped_column(String(256), nullable=True)
    check_interval_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)
    http_url: Mapped[str | None] = mapped_column(String(512), nullable=True)
    http_expected_status: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class HttpCheckResult(Base):
    """History of HTTP uptime-check results, used for the monitoring dashboard's
    uptime percentage and latency display."""
    __tablename__ = "http_check_results"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    service_name: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    checked_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), index=True)
    is_up: Mapped[bool] = mapped_column(Boolean, nullable=False)
    status_code: Mapped[int | None] = mapped_column(Integer, nullable=True)
    response_time_ms: Mapped[float | None] = mapped_column(Float, nullable=True)
    error_message: Mapped[str | None] = mapped_column(String(512), nullable=True)


class Subscriber(Base):
    __tablename__ = "subscribers"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    email: Mapped[str] = mapped_column(String(256), unique=True, nullable=False, index=True)
    confirm_token: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    unsubscribe_token: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    # Notification channel: "email" (default, uses `email` above as the send
    # target) or "teams" (posts to teams_webhook_url instead - `email` is
    # still required as a contact/identifier, but isn't sent to).
    channel: Mapped[str] = mapped_column(String(16), nullable=False, server_default="email")
    teams_webhook_url: Mapped[str | None] = mapped_column(String(512), nullable=True)
    # Comma-separated service_names this subscriber wants notifications for.
    # NULL/empty = all services (also the meaning for every pre-existing row,
    # which predates this per-service selection feature).
    services: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class AppSetting(Base):
    """Key-value store for runtime-editable settings. Use for configuration
    that must be changeable without redeploying (SMTP host/port/auth, etc.)."""
    __tablename__ = "app_settings"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[str] = mapped_column(Text, nullable=False, default="")
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )


class SourceLabel(Base):
    """Human-readable labels for source/origin values on incidents.
    System entries (manual, graph) are seeded and marked read-only via is_system."""
    __tablename__ = "source_labels"

    source: Mapped[str] = mapped_column(String(100), primary_key=True)
    label: Mapped[str] = mapped_column(String(200), nullable=False)
    is_system: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="0")


class UpdateTemplate(Base):
    """Pre-written templates for incident updates to speed up admin postings."""
    __tablename__ = "update_templates"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False, index=True)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    applicable_phases: Mapped[str | None] = mapped_column(Text, nullable=True, default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class SeverityLevel(Base):
    """Configurable severity levels for incidents (critical, high, medium, low, etc.)."""
    __tablename__ = "severity_levels"
    __table_args__ = (UniqueConstraint("name", name="uq_severity_name"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    label: Mapped[str] = mapped_column(String(64), nullable=False)
    color: Mapped[str] = mapped_column(String(7), nullable=False)
    weight: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    display_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    is_system: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="0")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class IncidentState(Base):
    """Configurable incident states/phases (active, acknowledged, monitoring, resolved, etc.)."""
    __tablename__ = "incident_states"
    __table_args__ = (UniqueConstraint("name", name="uq_state_name"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    label: Mapped[str] = mapped_column(String(64), nullable=False)
    color: Mapped[str] = mapped_column(String(7), nullable=False)
    is_terminal: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    display_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    is_system: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="0")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
