from typing import Literal
from starlette.requests import Request

Level = Literal["success", "error", "info", "warning"]
_KEY = "_flashes"


def flash(request: Request, message: str, level: Level = "success") -> None:
    queue = request.session.setdefault(_KEY, [])
    queue.append({"message": message, "level": level})


def consume_flashes(request: Request) -> list[dict]:
    return request.session.pop(_KEY, [])
