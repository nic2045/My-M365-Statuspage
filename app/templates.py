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
from app.config import settings as _settings

templates.env.globals["L"] = LABELS
templates.env.globals["APP_VERSION"] = __version__
templates.env.globals["APP_TITLE"] = _settings.APP_TITLE
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


# ── Severity & status colour system ───────────────────────────────────────────
#
# Single source of truth for every coloured chip, dot, border, badge and bar
# rendered anywhere in the app. Whenever a template needs a colour for one of
# these dimensions, it should go through a helper here — not hardcode a
# Tailwind class — so a future palette tweak only happens in one place.
#
# Dimensions and their colour families:
#
#   service status        operational   degraded   interrupted   unknown
#                         green         amber      red           gray
#
#   incident severity     critical      high       medium        low
#                         red           orange     amber         blue
#
#   incident phase        active        acknowledged   monitoring   resolved
#                         yellow        orange         blue         emerald
#
#   incident type         incident      advisory   maintenance
#                         red           amber      blue
#
# Pulse animation: an active phase (active / acknowledged / monitoring) and a
# non-operational service status both pulse — see PULSE_PHASES below and
# `status_dot_pulse()`. Tailwind's animate-pulse is suppressed automatically
# under `prefers-reduced-motion: reduce` (base.html).

SEVERITY_BADGE: dict[str, str] = {
    "critical": "bg-red-100 text-red-800 dark:bg-red-900/40 dark:text-red-400",
    "high":     "bg-orange-100 text-orange-800 dark:bg-orange-900/40 dark:text-orange-400",
    "medium":   "bg-amber-100 text-amber-800 dark:bg-amber-900/40 dark:text-amber-400",
    "low":      "bg-blue-100 text-blue-800 dark:bg-blue-900/40 dark:text-blue-400",
}

# Incident-response phases:
# active        → Investigating  (yellow)
# acknowledged  → Identified     (orange)
# monitoring    → Monitoring     (blue)
# resolved/completed → Resolved  (green)
# scheduled/in_progress (maintenance) → blue / amber
PHASE_DOT: dict[str, str] = {
    "active":       "bg-yellow-400",
    "acknowledged": "bg-orange-400",
    "monitoring":   "bg-blue-400",
    "resolved":     "bg-emerald-500",
    "completed":    "bg-emerald-500",
    "scheduled":    "bg-blue-400",
    "in_progress":  "bg-amber-400",
}

# Phases / statuses that should *visually pulse* to signal "something is
# happening right now". Resolved/completed/scheduled stay static.
PULSE_PHASES: set[str] = {"active", "acknowledged", "monitoring", "in_progress"}
PULSE_STATUSES: set[str] = {"degraded", "interrupted"}

templates.env.globals["severity_badge_class"] = (
    lambda s: SEVERITY_BADGE.get(s, "")
)
templates.env.globals["severity_label"] = (
    lambda s: LABELS.get(f"severity.{s}", s)
)
templates.env.globals["state_label"] = (
    lambda s: LABELS.get(f"state.{s}", s)
)
templates.env.globals["phase_dot_class"] = (
    lambda s: PHASE_DOT.get(s, "bg-gray-300 dark:bg-gray-600")
)
templates.env.globals["phase_pulse_class"] = (
    lambda s: "animate-pulse" if s in PULSE_PHASES else ""
)
templates.env.globals["status_pulse_class"] = (
    lambda s: "animate-pulse" if s in PULSE_STATUSES else ""
)


def _group_services(services, fallback_label: str):
    """Bucket services by group_name (None → fallback_label), preserving the
    incoming order. Used by status.html instead of Jinja's groupby, which
    cannot sort mixed None/str keys. Accepts both ORM objects and dicts."""
    buckets: dict[str, list] = {}
    for s in services:
        group = s.get("group_name") if isinstance(s, dict) else getattr(s, "group_name", None)
        key = group or fallback_label
        buckets.setdefault(key, []).append(s)
    return list(buckets.items())


templates.env.globals["group_services"] = _group_services


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
