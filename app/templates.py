"""Shared Jinja2 templates instance with all globals and filters pre-registered."""
from datetime import datetime

from fastapi.templating import Jinja2Templates

from app.i18n import LABELS
from app.models import INCIDENT_BORDER, STATUS_BADGE_CLASSES, STATUS_TAILWIND_BAR

templates = Jinja2Templates(directory="templates")

# ── Globals ───────────────────────────────────────────────────────────────────
templates.env.globals["L"] = LABELS
templates.env.globals["status_bar_class"] = (
    lambda s: STATUS_TAILWIND_BAR.get(s, STATUS_TAILWIND_BAR["unknown"])
)
templates.env.globals["status_badge_class"] = (
    lambda s: STATUS_BADGE_CLASSES.get(s, STATUS_BADGE_CLASSES["unknown"])
)
templates.env.globals["incident_border_class"] = (
    lambda c: INCIDENT_BORDER.get(c, "border-gray-400")
)
templates.env.globals["status_label"] = (
    lambda s: LABELS.get(f"status.{s}", s)
)
templates.env.globals["incident_type_label"] = (
    lambda c: LABELS.get(f"incident.type.{c}", c)
)


# ── Filters ───────────────────────────────────────────────────────────────────
def _strftime_de(dt: datetime | None, fmt: str = "%d.%m.%Y %H:%M Uhr") -> str:
    if dt is None:
        return "—"
    return dt.strftime(fmt)


def _date_de(d, fmt: str = "%d.%m.%Y") -> str:
    if d is None:
        return "—"
    return d.strftime(fmt)


templates.env.filters["strftime_de"] = _strftime_de
templates.env.filters["date_de"] = _date_de
