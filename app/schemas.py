from datetime import date, datetime

from pydantic import BaseModel, ConfigDict


class IncidentUpdateSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    content: str
    update_type: str = "note"
    post_created_at: datetime | None


class IncidentSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    graph_issue_id: str
    title: str
    service_name: str
    classification: str
    status: str
    severity: str = ""
    description: str | None = None
    start_datetime: datetime | None
    last_modified: datetime | None
    is_resolved: bool
    updates: list[IncidentUpdateSchema] = []


class DayStatusSchema(BaseModel):
    date: date
    status: str  # operational | degraded | interrupted | unknown | no_data


class ServiceStatusSchema(BaseModel):
    service_name: str
    current_status: str
    uptime_days: list[DayStatusSchema]
    active_incidents: list[IncidentSchema] = []
    uptime_percentage: float | None = None


class StatusPageSchema(BaseModel):
    services: list[ServiceStatusSchema]
    last_updated: datetime | None
    overall_status: str  # operational | degraded | interrupted
