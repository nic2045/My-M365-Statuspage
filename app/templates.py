"""Shared Jinja2 templates instance with all globals and filters pre-registered."""
from datetime import datetime

import bleach
import mistune
from fastapi.templating import Jinja2Templates

from app import __version__
from app.i18n import LABELS
from app.models import INCIDENT_BORDER, STATUS_BADGE_CLASSES, STATUS_TAILWIND_BAR

_ALLOWED_MD_TAGS = ["p", "b", "i", "strong", "em", "a", "ul", "ol", "li", "br", "code", "pre", "blockquote"]
_ALLOWED_MD_ATTRS = {"a": ["href", "title"]}
_md = mistune.create_markdown(escape=False)

templates = Jinja2Templates(directory="templates")

# ── Globals ───────────────────────────────────────────────────────────────────
templates.env.globals["L"] = LABELS
templates.env.globals["APP_VERSION"] = __version__
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


SEVERITY_BADGE: dict[str, str] = {
    "critical": "bg-red-100 text-red-800 dark:bg-red-900/40 dark:text-red-400",
    "high":     "bg-orange-100 text-orange-800 dark:bg-orange-900/40 dark:text-orange-400",
    "medium":   "bg-amber-100 text-amber-800 dark:bg-amber-900/40 dark:text-amber-400",
    "low":      "bg-blue-100 text-blue-800 dark:bg-blue-900/40 dark:text-blue-400",
}

templates.env.globals["severity_badge_class"] = (
    lambda s: SEVERITY_BADGE.get(s, "")
)
templates.env.globals["severity_label"] = (
    lambda s: LABELS.get(f"severity.{s}", s)
)
templates.env.globals["state_label"] = (
    lambda s: LABELS.get(f"state.{s}", s)
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


def _render_md(text: str | None) -> str:
    if not text:
        return ""
    raw_html = _md(text)
    return bleach.clean(raw_html, tags=_ALLOWED_MD_TAGS, attributes=_ALLOWED_MD_ATTRS, strip=True)


templates.env.filters["strftime_de"] = _strftime_de
templates.env.filters["date_de"] = _date_de
templates.env.filters["render_md"] = _render_md
