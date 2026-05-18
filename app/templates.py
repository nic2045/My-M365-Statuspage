"""Shared Jinja2 templates instance with all globals and filters pre-registered."""
from datetime import datetime

import bleach
import mistune
from fastapi.templating import Jinja2Templates

from app import __version__
from app.config import settings as _settings
from app.i18n import (
    LABELS,
    LANGUAGE_NAMES,
    SUPPORTED_LANGUAGES,
    get_current_language,
    get_label,
)
from app.models import INCIDENT_BORDER, STATUS_BADGE_CLASSES, STATUS_TAILWIND_BAR

_ALLOWED_MD_TAGS = ["p", "b", "i", "strong", "em", "a", "ul", "ol", "li", "br", "code", "pre", "blockquote"]
_ALLOWED_MD_ATTRS = {"a": ["href", "title"]}
_md = mistune.create_markdown(escape=False)

templates = Jinja2Templates(directory="templates")

# ── Globals ───────────────────────────────────────────────────────────────────
templates.env.globals["L"] = LABELS
templates.env.globals["current_lang"] = get_current_language
templates.env.globals["LANGUAGE_NAMES"] = LANGUAGE_NAMES
templates.env.globals["SUPPORTED_LANGUAGES"] = SUPPORTED_LANGUAGES
templates.env.globals["APP_VERSION"] = __version__
templates.env.globals["APP_TITLE"] = _settings.APP_TITLE
templates.env.globals["BUILD_SHA"] = _settings.BUILD_SHA
templates.env.globals["BUILD_TIME"] = _settings.BUILD_TIME
templates.env.globals["DEBUG"] = _settings.DEBUG
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

# Incident-type badge — colour family mirrors INCIDENT_BORDER so the chip
# and the card's left border belong to the same hue.
INCIDENT_TYPE_BADGE: dict[str, str] = {
    "incident":    "bg-red-100 text-red-700 dark:bg-red-900/40 dark:text-red-400",
    "advisory":    "bg-amber-100 text-amber-700 dark:bg-amber-900/40 dark:text-amber-400",
    "maintenance": "bg-blue-100 text-blue-700 dark:bg-blue-900/40 dark:text-blue-400",
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
templates.env.globals["phase_dot_class"] = (
    lambda s: PHASE_DOT.get(s, "bg-gray-300 dark:bg-gray-600")
)
templates.env.globals["phase_pulse_class"] = (
    lambda s: "animate-pulse" if s in PULSE_PHASES else ""
)
templates.env.globals["status_pulse_class"] = (
    lambda s: "animate-pulse" if s in PULSE_STATUSES else ""
)
templates.env.globals["incident_type_badge_class"] = (
    lambda c: INCIDENT_TYPE_BADGE.get(c, INCIDENT_TYPE_BADGE["incident"])
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
_DATETIME_FORMATS = {
    "de": "%d.%m.%Y %H:%M Uhr",
    "en": "%Y-%m-%d %H:%M",
}
_DATE_FORMATS = {
    "de": "%d.%m.%Y",
    "en": "%Y-%m-%d",
}


def _strftime_localized(dt: datetime | None, fmt: str | None = None) -> str:
    if dt is None:
        return "—"
    if fmt is None:
        fmt = _DATETIME_FORMATS.get(get_current_language(), _DATETIME_FORMATS["de"])
    return dt.strftime(fmt)


def _date_localized(d, fmt: str | None = None) -> str:
    if d is None:
        return "—"
    if fmt is None:
        fmt = _DATE_FORMATS.get(get_current_language(), _DATE_FORMATS["de"])
    return d.strftime(fmt)


def _duration_localized(start: datetime | None, end: datetime | None) -> str:
    if start is None or end is None:
        return ""
    seconds = int((end - start).total_seconds())
    if seconds < 0:
        return ""
    if seconds < 60:
        return f"{seconds} {get_label('duration.sec')}"
    minutes = seconds // 60
    if minutes < 60:
        return f"{minutes} {get_label('duration.min')}"
    hours = minutes // 60
    if hours < 24:
        return f"{hours} {get_label('duration.hr')}"
    days = hours // 24
    if days < 7:
        return get_label("duration.day_one") if days == 1 else get_label("duration.day_many").format(n=days)
    weeks = days // 7
    if weeks < 5:
        return get_label("duration.week_one") if weeks == 1 else get_label("duration.week_many").format(n=weeks)
    months = days // 30
    return get_label("duration.month_one") if months == 1 else get_label("duration.month_many").format(n=months)


def _render_md(text: str | None) -> str:
    if not text:
        return ""
    raw_html = _md(text)
    return bleach.clean(raw_html, tags=_ALLOWED_MD_TAGS, attributes=_ALLOWED_MD_ATTRS, strip=True)


templates.env.filters["strftime_de"] = _strftime_localized
templates.env.filters["date_de"] = _date_localized
templates.env.filters["localized_datetime"] = _strftime_localized
templates.env.filters["localized_date"] = _date_localized
templates.env.filters["render_md"] = _render_md
templates.env.globals["duration_de"] = _duration_localized
templates.env.globals["localized_duration"] = _duration_localized
