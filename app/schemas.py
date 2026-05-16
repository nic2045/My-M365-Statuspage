from datetime import datetime, date
from pydantic import BaseModel, ConfigDict


class IncidentUpdateSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    content: str
    post_created_at: datetime | None


class IncidentSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    graph_issue_id: str
    title: str
    service_name: str
    classification: str
    status: str
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


class StatusPageSchema(BaseModel):
    services: list[ServiceStatusSchema]
    last_updated: datetime | None
    overall_status: str  # operational | degraded | interrupted
