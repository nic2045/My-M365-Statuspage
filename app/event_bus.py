"""In-memory event bus for SSE pub/sub."""
import asyncio
from dataclasses import dataclass
from datetime import datetime


@dataclass
class StatusEvent:
    """Event emitted when service/incident status changes."""

    event_type: str  # "incident.created" | "incident.updated" | "incident.resolved" | "service.status_changed"
    service_name: str | None
    incident_id: int | None
    title: str | None
    status: str | None
    timestamp: datetime

    def to_sse_data(self) -> str:
        """Format as Server-Sent Event payload."""
        import json

        data = {
            "type": self.event_type,
            "service": self.service_name,
            "incident_id": self.incident_id,
            "title": self.title,
            "status": self.status,
            "timestamp": self.timestamp.isoformat(),
        }
        return json.dumps(data)


class EventBus:
    """Minimal pub/sub for SSE subscribers."""

    def __init__(self) -> None:
        self.subscribers: list[asyncio.Queue] = []
        self._lock = asyncio.Lock()

    async def subscribe(self) -> asyncio.Queue:
        """Return a queue that receives published events."""
        queue: asyncio.Queue = asyncio.Queue()
        async with self._lock:
            self.subscribers.append(queue)
        return queue

    async def unsubscribe(self, queue: asyncio.Queue) -> None:
        """Remove a subscriber."""
        async with self._lock:
            if queue in self.subscribers:
                self.subscribers.remove(queue)

    async def publish(self, event: StatusEvent) -> None:
        """Send event to all subscribers."""
        async with self._lock:
            for queue in self.subscribers:
                try:
                    queue.put_nowait(event)
                except asyncio.QueueFull:
                    pass  # Drop event if subscriber queue is full


# Global singleton
_event_bus = EventBus()


def get_event_bus() -> EventBus:
    return _event_bus
