"""Server-Sent Events router for live status updates."""
import asyncio

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse

from app.event_bus import StatusEvent, get_event_bus

router = APIRouter(tags=["sse"])


async def event_stream(request: Request) -> None:
    """SSE generator that streams status events."""
    event_bus = get_event_bus()
    queue = await event_bus.subscribe()

    try:
        while True:
            try:
                event = await asyncio.wait_for(queue.get(), timeout=30.0)
                yield f"data: {event.to_sse_data()}\n\n"
            except asyncio.TimeoutError:
                yield ": heartbeat\n\n"

            if await request.is_disconnected():
                break
    finally:
        await event_bus.unsubscribe(queue)


@router.get("/sse/status")
async def sse_status(request: Request):
    """Endpoint for client EventSource connection."""
    return StreamingResponse(
        event_stream(request),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )
