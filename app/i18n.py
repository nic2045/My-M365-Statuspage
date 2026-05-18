"""Internationalisation: per-language label dictionaries plus a request-scoped
language resolver.

The current language is held in a ContextVar that is set once per HTTP request
by the language middleware (see ``app.main``). Templates access labels via the
``L`` proxy registered as a Jinja global; Python code can call
``get_label("key")`` directly or read ``LABELS["key"]`` from the same proxy.
"""
from __future__ import annotations

import contextvars
import logging
import os
from collections.abc import Iterator, Mapping

logger = logging.getLogger(__name__)

# ── Supported languages ─────────────────────────────────────────────────────
DEFAULT_LANGUAGE = "de"
SUPPORTED_LANGUAGES: tuple[str, ...] = ("de", "en")

# Human-readable native names used in the UI selector.
LANGUAGE_NAMES: dict[str, str] = {
    "de": "Deutsch",
    "en": "English",
}


LABELS_DE: dict[str, str] = {
    # Status
    "status.operational":         "In Betrieb",
    "status.degraded":            "Eingeschränkt",
    "status.interrupted":         "Unterbrochen",
    "status.unknown":             "Unbekannt",
    "status.no_data":             "Keine Daten",
    # Page
    "page.title":                 "M365 Dienststatus",
    "page.all_good":              "Alle Dienste in Betrieb",
    "page.some_degraded":         "Leistungseinschränkungen",
    "page.incidents_active":      "Aktive Störungen",
    "page.uptime_heading":        "Verfügbarkeit – letzte 90 Tage",
    "page.range.label":           "Zeitraum:",
    "page.range.24h":             "24h",
    "page.range.7d":              "7 Tage",
    "page.range.30d":             "30 Tage",
    "page.range.90d":             "90 Tage",
    "page.incidents_heading":     "Aktive Störungen & Hinweise",
    "page.incidents_heading_active": "Aktive Störungen",
    "page.advisories_heading":    "Aktuelle Hinweise",
    "page.advisories_none":       "keine",
    "page.last_updated":          "Zuletzt aktualisiert",
    "page.logout":                "Abmelden",
    "page.darkmode":              "Dunkel",
    "page.lightmode":             "Hell",
    "page.no_incidents":          "Keine aktiven Störungen gemeldet.",
    # Incidents
    "incident.type.incident":     "Störung",
    "incident.type.advisory":     "Hinweis",
    "incident.affects":           "Betrifft",
    "incident.since":             "Seit",
    "incident.until":             "bis",
    "incident.updates":           "Updates",
    "incident.older_updates":     "+ {n} ältere — Details öffnen",
    "incident.resolved":          "Behoben",
    # Embed
    "embed.active_incidents":     "Aktive Störungen vorhanden",
    "embed.details":              "Details anzeigen",
    "embed.updated":              "Aktualisiert",
    "embed.all_good":             "Alle Dienste in Betrieb",
    # Page – Maintenance
    "page.maintenance_heading":   "Geplante Wartungen",
    "page.no_maintenances":       "Keine geplanten Wartungen.",
    # Admin
    "admin.title":                "Admin",
    "admin.dashboard":            "Dashboard",
    "admin.incidents":            "Störungen & Hinweise",
    "admin.incidents_only":       "Aktive Störungen",
    "admin.show_all_incidents":   "Alle Störungen anzeigen",
    "admin.incidents_all_title":  "Alle Störungen",
    "admin.incidents_all_sub":    "Aktive, behobene und ignorierte Einträge",
    "admin.back_to_dashboard":    "Zum Dashboard",
    "admin.filter_state":         "Status:",
    "admin.filter_all":           "Alle",
    "admin.filter_active":        "Aktiv",
    "admin.filter_suppressed":    "Ignoriert",
    "admin.suppressed_heading":   "Ignoriert",
    "admin.filter_resolved":      "Behoben",
    "admin.filter_empty":         "Keine Einträge mit diesem Filter.",
    "admin.advisories":           "Hinweise",
    "admin.services_count_suffix": "Dienste",
    "empty.admin.advisories":     "Keine aktiven Hinweise.",
    # Admin – Sidebar navigation
    "admin.nav.dashboard":        "Dashboard",
    "admin.nav.incidents":        "Störungen",
    "admin.nav.maintenances":     "Wartungen",
    "admin.nav.settings":         "Einstellungen",
    "admin.nav.debug":            "Debug",
    "admin.nav.public_page":      "Zur Statusseite",
    "admin.nav.toggle":           "Navigation öffnen",
    "admin.nav.close":            "Navigation schließen",
    "admin.nav.own_incidents":    "Eigene Meldungen",
    "admin.nav.new_incident":     "Neue Meldung",
    "admin.nav.general_section":    "Allgemein",
    "admin.nav.services_mgmt":      "Dienstverwaltung",
    "admin.nav.meldungen_section":  "Meldungen",
    "admin.nav.system_section":     "System",
    "admin.new_incident":         "Neue Störung / Hinweis",
    "admin.new_maintenance":      "Neue Wartung",
    "admin.maintenances":         "Geplante Wartungen",
    "admin.create":               "Erstellen",
    "admin.save":                 "Speichern",
    "admin.resolve":              "Als behoben markieren",
    "admin.reopen":               "Erneut öffnen",
    "admin.add_update":           "Update hinzufügen",
    "admin.post_placeholder":     "Status-Update eingeben…",
    "admin.service_status":       "Dienststatus",
    "admin.set_status":           "Status setzen",
    "admin.title_label":          "Titel",
    "admin.description_label":    "Beschreibung",
    "admin.severity_label":       "Schweregrad",
    "admin.start_datetime":       "Beginn",
    "admin.now":                  "Jetzt",
    "admin.notify_subscribers":   "Subscriber benachrichtigen",
    "admin.delete":               "Löschen",
    "admin.delete_confirm":       "Diesen Eintrag wirklich löschen?",
    # Severity levels
    "severity.critical":          "Kritisch",
    "severity.high":              "Hoch",
    "severity.medium":            "Mittel",
    "severity.low":               "Niedrig",
    # Incident state phases
    "state.active":               "Untersuchung läuft",
    "state.acknowledged":         "Identifiziert",
    "state.monitoring":           "Überwachung",
    "state.resolved":             "Behoben",
    "state.scheduled":            "Geplant",
    "state.in_progress":          "In Durchführung",
    "state.completed":            "Abgeschlossen",
    "admin.service_label":        "Dienst",
    "admin.classification_label": "Typ",
    "admin.status_label":         "Status",
    "admin.end_datetime":         "Ende (tatsächlich)",
    "admin.scheduled_start":      "Beginn (geplant)",
    "admin.scheduled_end":        "Ende (geplant)",
    "admin.back":                 "Zurück",
    "admin.no_incidents":         "Keine aktiven Einträge.",
    "admin.suppress":             "Ignorieren",
    "admin.unsuppress":           "Wiederherstellen",
    "admin.acknowledge":          "Ich übernehme",
    "admin.release":              "Freigeben",
    "admin.owner":                "Bearbeiter",
    "admin.acknowledged_at":      "Übernommen am",
    "toast.acknowledged":         "Übernommen",
    "toast.released":             "Freigegeben",
    "admin.suppressed_heading":   "Ignorierte Meldungen",
    "admin.no_suppressed":        "Keine ignorierten Meldungen.",
    "admin.no_maintenances":      "Keine geplanten Wartungen.",
    # Maintenance status
    "maintenance.scheduled":      "Geplant",
    "maintenance.in_progress":    "In Durchführung",
    "maintenance.completed":      "Abgeschlossen",
    # Incident type
    "incident.type.maintenance":  "Wartung",
    # Incident history (public page)
    "page.history_heading":       "Kürzlich behoben",
    "page.history_subheading":    "Letzte 30 Tage",
    "page.history_empty":         "Keine behobenen Störungen in den letzten 30 Tagen.",
    "page.history_filter":        "Filter:",
    "page.history_filter_all":    "Alle",
    "page.history_filter_empty":  "Keine Einträge für diesen Dienst.",
    "page.history_show":          "Störungs-Verlauf anzeigen",
    "incident.resolved_at":       "Behoben am",
    # Incident detail metadata
    "details.heading":            "Eckdaten",
    "details.reference":          "Referenz",
    "details.start":              "Beginn",
    "details.end":                "Ende",
    "details.duration":           "Dauer",
    "details.last_update":        "Letztes Update",
    "details.acknowledged":       "Identifiziert",
    "details.owner":              "Verantwortlich",
    # Service management
    "admin.service_management":   "Dienstverwaltung",
    "admin.discover_services":    "Von Microsoft laden",
    "admin.service_enable":       "Aktivieren",
    "admin.service_disable":      "Deaktivieren",
    "admin.no_known_services":    "Noch keine Dienste bekannt.",
    "empty.admin.services":       "Noch keine Dienste bekannt. Klicke \"Von Microsoft laden\" um alle M365-Dienste zu importieren.",
    "empty.admin.services_cta":   "Von Microsoft laden",
    "empty.admin.incidents":      "Keine aktiven Störungen.",
    "empty.admin.incidents_sub":  "Das System läuft normal.",
    "empty.admin.suppressed":     "Keine ignorierten Meldungen.",
    "empty.admin.maintenances":   "Keine geplanten Wartungen.",
    "empty.admin.maintenances_sub": "Es stehen aktuell keine Arbeiten an.",
    "empty.public.all_good":      "Keine aktiven Störungen.",
    "empty.public.all_good_sub":  "Alle Dienste laufen normal.",
    "empty.public.history":       "Keine behobenen Störungen in den letzten 30 Tagen.",
    "toast.dismiss":              "Meldung schließen",
    "toast.group_saved":          "Gruppe gespeichert.",
    "admin.service_backfill_hint": "90-Tage-Verlauf wird im Hintergrund geladen…",
    "admin.uptime_shown":         "Verfügbarkeit sichtbar",
    "admin.uptime_hidden":        "Verfügbarkeit ausgeblendet",
    "admin.uptime_toggle_hint":   "Gesamtverfügbarkeit der letzten 90 Tage auf der Statusseite ein-/ausblenden",
    "page.uptime_90d":            "Gesamtverfügbarkeit (90 Tage)",
    "page.uptime_suffix":         "verfügbar",
    # Service groups
    "admin.service_group":            "Gruppe",
    "admin.service_group_placeholder": "z. B. Microsoft 365",
    "admin.service_group_save":       "Übernehmen",
    "admin.service_group_hint":       "Leer lassen = ohne Gruppe (erscheint unter „Sonstiges“)",
    "page.group_other":               "Sonstiges",
    "page.group_count":               "{count} Dienste",
    "page.group_count_one":           "1 Dienst",
    # Subscriber
    # Top tab nav
    "page.tab_overview":              "Übersicht",
    "page.tab_incidents":             "Störungen",
    "page.tab_advisories":            "Hinweise",
    "page.tab_maintenances":          "Wartungen",
    "page.tab_history":               "Verlauf",
    "subscribe.tab":                  "Anmelden",
    "subscribe.modal_title":          "Benachrichtigungen abonnieren",
    "subscribe.modal_sub":            "Werde per E-Mail informiert, sobald eine Störung auftritt oder ein Update gepostet wird.",
    "subscribe.cancel":               "Abbrechen",
    "subscribe.label":                "Benachrichtigungen",
    "subscribe.email_placeholder":    "E-Mail-Adresse eingeben",
    "subscribe.submit":               "Anmelden",
    "subscribe.hint":                 "Du erhältst eine Bestätigungs-E-Mail.",
    "subscribe.pending_title":        "Fast fertig!",
    "subscribe.pending_body":         "Bitte bestätige deine E-Mail-Adresse über den Link in der Bestätigungs-E-Mail.",
    "subscribe.confirmed_title":      "Anmeldung bestätigt",
    "subscribe.confirmed_body":       "Du erhältst ab jetzt Benachrichtigungen bei neuen Störungen.",
    "subscribe.unsubscribed_title":   "Abgemeldet",
    "subscribe.unsubscribed_body":    "Du erhältst keine weiteren Benachrichtigungen.",
    "subscribe.error_title":          "Fehler",
    "subscribe.error_body":           "Dein Link ist ungültig oder bereits abgelaufen.",
    "subscribe.back_to_status":       "Zur Statusseite",
    # Admin – subscriber management
    "admin.nav.subscribers":          "Abonnenten",
    "admin.subscribers_heading":      "E-Mail-Abonnenten",
    "admin.subscribers_hint":         "Bestätigte Abonnenten erhalten Benachrichtigungen wenn \"Subscriber benachrichtigen\" aktiv ist.",
    "admin.subscriber_email":         "E-Mail",
    "admin.subscriber_confirmed":     "Bestätigt am",
    "admin.subscriber_delete":        "Entfernen",
    "admin.subscriber_pending":       "Ausstehend",
    "admin.teams_heading":            "MS Teams Webhook",
    "admin.teams_hint":               "Incoming Webhook URLs (kommasepariert). Leer = deaktiviert.",
    "admin.teams_save":               "Speichern",
    "toast.subscriber_deleted":       "Abonnent entfernt.",
    "toast.service_moved":            "Reihenfolge angepasst.",
    "admin.move_up":                  "Nach oben",
    "admin.move_down":                "Nach unten",
    "toast.email_saved":              "E-Mail-Einstellungen gespeichert.",
    # Email settings
    "admin.email_heading":            "E-Mail-Versand",
    "admin.email_hint":               "Methode für den Versand von Bestätigungs- und Benachrichtigungs-E-Mails.",
    "admin.email_method":             "Versandmethode",
    "admin.email_method_none":        "Deaktiviert",
    "admin.email_method_password":    "SMTP (Benutzer/Passwort)",
    "admin.email_method_oauth2":      "Microsoft Graph (OAuth2)",
    "admin.email_smtp_host":          "SMTP-Host",
    "admin.email_smtp_port":          "Port",
    "admin.email_smtp_user":          "Benutzername",
    "admin.email_smtp_pass":          "Passwort",
    "admin.email_smtp_pass_hint":     "Leer lassen = bestehendes Passwort behalten",
    "admin.email_smtp_from":          "Absender-Adresse (From)",
    "admin.email_smtp_tls":           "STARTTLS verwenden",
    "admin.email_graph_from":         "Postfach (From-Adresse im Tenant)",
    "admin.email_graph_hint":         "Reuse der Azure-AD-App. Erfordert Mail.Send Application Permission + Admin Consent.",
    "admin.email_save":               "Speichern",
    "admin.email_test_heading":       "Test-Versand",
    "admin.email_test_to":            "Empfänger",
    "admin.email_test_send":          "Test-E-Mail senden",
    "admin.email_status_configured":  "Konfiguriert",
    "admin.email_status_pending":     "Unvollständig",
    "admin.email_status_disabled":    "Deaktiviert",
    # Notification send
    "notify.new_incident":            "Neue Störung",
    "notify.update":                  "Status-Update",
    # Source / reference on incidents
    "admin.source_label":            "Quelle",
    "admin.source_microsoft":        "Microsoft (Graph)",
    "admin.source_manual":           "Manuell",
    "admin.source_other":            "Sonstige",
    "admin.external_id_label":       "Referenz / ID",
    "admin.external_id_placeholder": "z. B. MO1310977",
    # Azure AD settings
    "admin.azure_heading":            "Azure AD App",
    "admin.azure_hint":               "Credentials der Azure-AD-App für Microsoft Graph API und E-Mail-Versand.",
    "admin.azure_tenant_label":       "Tenant-ID",
    "admin.azure_client_label":       "Client-ID (App-ID)",
    "admin.azure_secret_label":       "Client-Secret",
    "admin.azure_secret_hint":        "Leer lassen = bestehendes Secret behalten",
    "admin.azure_save":               "Speichern & Verbindung prüfen",
    "admin.azure_status_configured":  "Verbunden",
    "admin.azure_status_pending":     "Unvollständig",
    "toast.azure_saved":              "Azure AD App gespeichert.",
    # Admin – global search palette (Cmd+K / Ctrl+K)
    "admin.search.placeholder":        "Suchen…",
    "admin.search.group.incidents":    "Störungen",
    "admin.search.group.updates":      "Updates",
    "admin.search.group.services":     "Dienste",
    "admin.search.group.subscribers":  "Subscriber",
    "admin.search.no_results":         "Keine Treffer.",
    "admin.search.hint":               "Cmd+K oder Strg+K zum Öffnen",
    # Language selector
    "settings.title":                 "Einstellungen",
    "settings.language_heading":      "Sprache",
    "settings.language_hint":         "Standardsprache der Oberfläche für neue Besucher. Einzelne Besucher können die Sprache jederzeit per Umschalter ändern.",
    "settings.language_save":         "Speichern",
    "settings.language_label":        "Standardsprache",
    "toast.language_saved":           "Sprache gespeichert.",
    "ui.switch_language":             "Sprache wechseln",
    "ui.close":                       "Schließen",
    "ui.back_to_overview":            "Zurück zur Übersicht",
    "ui.app_install":                 "App installieren",
    "ui.app_install_short":           "Installieren",
    "ui.theme_toggle":                "Farbschema wechseln",
    "ui.no_title":                    "(ohne Titel)",
    "ui.related_entries":             "Zugehörige Einträge",
    "ui.no_details_available":        "Keine weiteren Details verfügbar.",
    "ui.history":                     "Verlauf",
    "ui.click_for_details":           "Klicken für Details",
    "ui.more_click_for_details":      "+{count} weitere – klicken für Details",
    "ui.day.operational_body":        "Keine Vorfälle an diesem Tag — Dienst lief normal.",
    "ui.day.degraded_body":           "Eingeschränkte Verfügbarkeit an diesem Tag.",
    "ui.day.interrupted_body":        "Dienstunterbrechung an diesem Tag.",
    "ui.day.no_data_body":            "Keine Datenpunkte für diesen Tag verfügbar.",
    "ui.day.unknown_body":            "Status unbekannt.",
    "ui.start":                       "Start",
    "ui.end":                         "Ende",
    "ui.build_info_tooltip":          "App-Version · Commit · Build-Zeit (UTC)",
    "ui.range.ago_24h":               "vor 24h",
    "ui.range.ago_days":              "vor {n} Tagen",
    "admin.incident_summary_placeholder":     "Kurze Beschreibung der Störung…",
    "admin.incident_description_placeholder": "Detailbeschreibung der Störung…",
    "admin.maintenance_summary_placeholder":  "Kurze Beschreibung der Wartung…",
    "admin.source_labels_hint":               "Bezeichnungen für Quell-Werte bei Meldungen. Systemeinträge sind schreibgeschützt.",
    "admin.service_filter_default":           "Dienst",
    # Duration suffixes (used by duration filter)
    "duration.sec":                   "Sek",
    "duration.min":                   "Min",
    "duration.hr":                    "Std",
    "duration.day_one":               "1 Tag",
    "duration.day_many":              "{n} Tage",
    "duration.week_one":              "1 Woche",
    "duration.week_many":             "{n} Wochen",
    "duration.month_one":             "1 Monat",
    "duration.month_many":            "{n} Monate",
    "datetime.today":                 "heute",
}


LABELS_EN: dict[str, str] = {
    # Status
    "status.operational":         "Operational",
    "status.degraded":            "Degraded",
    "status.interrupted":         "Outage",
    "status.unknown":             "Unknown",
    "status.no_data":             "No data",
    # Page
    "page.title":                 "M365 Service Status",
    "page.all_good":              "All services operational",
    "page.some_degraded":         "Performance issues",
    "page.incidents_active":      "Active incidents",
    "page.uptime_heading":        "Uptime – last 90 days",
    "page.range.label":           "Range:",
    "page.range.24h":             "24h",
    "page.range.7d":              "7 days",
    "page.range.30d":             "30 days",
    "page.range.90d":             "90 days",
    "page.incidents_heading":     "Active incidents & advisories",
    "page.incidents_heading_active": "Active incidents",
    "page.advisories_heading":    "Current advisories",
    "page.advisories_none":       "none",
    "page.last_updated":          "Last updated",
    "page.logout":                "Sign out",
    "page.darkmode":              "Dark",
    "page.lightmode":             "Light",
    "page.no_incidents":          "No active incidents reported.",
    # Incidents
    "incident.type.incident":     "Incident",
    "incident.type.advisory":     "Advisory",
    "incident.affects":           "Affects",
    "incident.since":             "Since",
    "incident.until":             "until",
    "incident.updates":           "Updates",
    "incident.older_updates":     "+ {n} older — open details",
    "incident.resolved":          "Resolved",
    # Embed
    "embed.active_incidents":     "Active incidents detected",
    "embed.details":              "Show details",
    "embed.updated":              "Updated",
    "embed.all_good":             "All services operational",
    # Page – Maintenance
    "page.maintenance_heading":   "Scheduled maintenance",
    "page.no_maintenances":       "No scheduled maintenance.",
    # Admin
    "admin.title":                "Admin",
    "admin.dashboard":            "Dashboard",
    "admin.incidents":            "Incidents & advisories",
    "admin.incidents_only":       "Active incidents",
    "admin.show_all_incidents":   "Show all incidents",
    "admin.incidents_all_title":  "All incidents",
    "admin.incidents_all_sub":    "Active, resolved and ignored entries",
    "admin.back_to_dashboard":    "Back to dashboard",
    "admin.filter_state":         "Status:",
    "admin.filter_all":           "All",
    "admin.filter_active":        "Active",
    "admin.filter_suppressed":    "Ignored",
    "admin.suppressed_heading":   "Ignored",
    "admin.filter_resolved":      "Resolved",
    "admin.filter_empty":         "No entries match this filter.",
    "admin.advisories":           "Advisories",
    "admin.services_count_suffix": "services",
    "empty.admin.advisories":     "No active advisories.",
    # Admin – Sidebar navigation
    "admin.nav.dashboard":        "Dashboard",
    "admin.nav.incidents":        "Incidents",
    "admin.nav.maintenances":     "Maintenance",
    "admin.nav.settings":         "Settings",
    "admin.nav.debug":            "Debug",
    "admin.nav.public_page":      "Public status page",
    "admin.nav.toggle":           "Open navigation",
    "admin.nav.close":            "Close navigation",
    "admin.nav.own_incidents":    "My incidents",
    "admin.nav.new_incident":     "New incident",
    "admin.nav.general_section":    "General",
    "admin.nav.services_mgmt":      "Service management",
    "admin.nav.meldungen_section":  "Incidents",
    "admin.nav.system_section":     "System",
    "admin.new_incident":         "New incident / advisory",
    "admin.new_maintenance":      "New maintenance",
    "admin.maintenances":         "Scheduled maintenance",
    "admin.create":               "Create",
    "admin.save":                 "Save",
    "admin.resolve":              "Mark as resolved",
    "admin.reopen":               "Reopen",
    "admin.add_update":           "Add update",
    "admin.post_placeholder":     "Enter status update…",
    "admin.service_status":       "Service status",
    "admin.set_status":           "Set status",
    "admin.title_label":          "Title",
    "admin.description_label":    "Description",
    "admin.severity_label":       "Severity",
    "admin.start_datetime":       "Start",
    "admin.now":                  "Now",
    "admin.notify_subscribers":   "Notify subscribers",
    "admin.delete":               "Delete",
    "admin.delete_confirm":       "Really delete this entry?",
    # Severity levels
    "severity.critical":          "Critical",
    "severity.high":              "High",
    "severity.medium":            "Medium",
    "severity.low":               "Low",
    # Incident state phases
    "state.active":               "Investigating",
    "state.acknowledged":         "Identified",
    "state.monitoring":           "Monitoring",
    "state.resolved":             "Resolved",
    "state.scheduled":            "Scheduled",
    "state.in_progress":          "In progress",
    "state.completed":            "Completed",
    "admin.service_label":        "Service",
    "admin.classification_label": "Type",
    "admin.status_label":         "Status",
    "admin.end_datetime":         "End (actual)",
    "admin.scheduled_start":      "Start (scheduled)",
    "admin.scheduled_end":        "End (scheduled)",
    "admin.back":                 "Back",
    "admin.no_incidents":         "No active entries.",
    "admin.suppress":             "Ignore",
    "admin.unsuppress":           "Restore",
    "admin.acknowledge":          "Take ownership",
    "admin.release":              "Release",
    "admin.owner":                "Owner",
    "admin.acknowledged_at":      "Acknowledged at",
    "toast.acknowledged":         "Taken over",
    "toast.released":             "Released",
    "admin.suppressed_heading":   "Ignored entries",
    "admin.no_suppressed":        "No ignored entries.",
    "admin.no_maintenances":      "No scheduled maintenance.",
    # Maintenance status
    "maintenance.scheduled":      "Scheduled",
    "maintenance.in_progress":    "In progress",
    "maintenance.completed":      "Completed",
    # Incident type
    "incident.type.maintenance":  "Maintenance",
    # Incident history (public page)
    "page.history_heading":       "Recently resolved",
    "page.history_subheading":    "Last 30 days",
    "page.history_empty":         "No incidents resolved in the last 30 days.",
    "page.history_filter":        "Filter:",
    "page.history_filter_all":    "All",
    "page.history_filter_empty":  "No entries for this service.",
    "page.history_show":          "Show incident history",
    "incident.resolved_at":       "Resolved at",
    # Incident detail metadata
    "details.heading":            "Key facts",
    "details.reference":          "Reference",
    "details.start":              "Started",
    "details.end":                "Ended",
    "details.duration":           "Duration",
    "details.last_update":        "Last update",
    "details.acknowledged":       "Identified",
    "details.owner":              "Owner",
    # Service management
    "admin.service_management":   "Service management",
    "admin.discover_services":    "Load from Microsoft",
    "admin.service_enable":       "Enable",
    "admin.service_disable":      "Disable",
    "admin.no_known_services":    "No services known yet.",
    "empty.admin.services":       "No services known yet. Click \"Load from Microsoft\" to import all M365 services.",
    "empty.admin.services_cta":   "Load from Microsoft",
    "empty.admin.incidents":      "No active incidents.",
    "empty.admin.incidents_sub":  "The system is running normally.",
    "empty.admin.suppressed":     "No ignored entries.",
    "empty.admin.maintenances":   "No scheduled maintenance.",
    "empty.admin.maintenances_sub": "Nothing scheduled at the moment.",
    "empty.public.all_good":      "No active incidents.",
    "empty.public.all_good_sub":  "All services running normally.",
    "empty.public.history":       "No incidents resolved in the last 30 days.",
    "toast.dismiss":              "Dismiss notification",
    "toast.group_saved":          "Group saved.",
    "admin.service_backfill_hint": "Loading 90-day history in the background…",
    "admin.uptime_shown":         "Uptime visible",
    "admin.uptime_hidden":        "Uptime hidden",
    "admin.uptime_toggle_hint":   "Show/hide total 90-day uptime on the status page",
    "page.uptime_90d":            "Overall uptime (90 days)",
    "page.uptime_suffix":         "available",
    # Service groups
    "admin.service_group":            "Group",
    "admin.service_group_placeholder": "e.g. Microsoft 365",
    "admin.service_group_save":       "Apply",
    "admin.service_group_hint":       "Empty = no group (shown under \"Other\")",
    "page.group_other":               "Other",
    "page.group_count":               "{count} services",
    "page.group_count_one":           "1 service",
    # Subscriber
    # Top tab nav
    "page.tab_overview":              "Overview",
    "page.tab_incidents":             "Incidents",
    "page.tab_advisories":            "Advisories",
    "page.tab_maintenances":          "Maintenance",
    "page.tab_history":               "History",
    "subscribe.tab":                  "Subscribe",
    "subscribe.modal_title":          "Subscribe to notifications",
    "subscribe.modal_sub":            "Get notified by email when an incident occurs or an update is posted.",
    "subscribe.cancel":               "Cancel",
    "subscribe.label":                "Notifications",
    "subscribe.email_placeholder":    "Enter email address",
    "subscribe.submit":               "Subscribe",
    "subscribe.hint":                 "You will receive a confirmation email.",
    "subscribe.pending_title":        "Almost done!",
    "subscribe.pending_body":         "Please confirm your email address via the link in the confirmation email.",
    "subscribe.confirmed_title":      "Subscription confirmed",
    "subscribe.confirmed_body":       "You will now receive notifications about new incidents.",
    "subscribe.unsubscribed_title":   "Unsubscribed",
    "subscribe.unsubscribed_body":    "You will not receive any further notifications.",
    "subscribe.error_title":          "Error",
    "subscribe.error_body":           "Your link is invalid or has already expired.",
    "subscribe.back_to_status":       "Back to status page",
    # Admin – subscriber management
    "admin.nav.subscribers":          "Subscribers",
    "admin.subscribers_heading":      "Email subscribers",
    "admin.subscribers_hint":         "Confirmed subscribers receive notifications when \"Notify subscribers\" is active.",
    "admin.subscriber_email":         "Email",
    "admin.subscriber_confirmed":     "Confirmed at",
    "admin.subscriber_delete":        "Remove",
    "admin.subscriber_pending":       "Pending",
    "admin.teams_heading":            "MS Teams webhook",
    "admin.teams_hint":               "Incoming webhook URLs (comma-separated). Empty = disabled.",
    "admin.teams_save":               "Save",
    "toast.subscriber_deleted":       "Subscriber removed.",
    "toast.service_moved":            "Order updated.",
    "admin.move_up":                  "Move up",
    "admin.move_down":                "Move down",
    "toast.email_saved":              "Email settings saved.",
    # Email settings
    "admin.email_heading":            "Email delivery",
    "admin.email_hint":               "Method used to send confirmation and notification emails.",
    "admin.email_method":             "Delivery method",
    "admin.email_method_none":        "Disabled",
    "admin.email_method_password":    "SMTP (user/password)",
    "admin.email_method_oauth2":      "Microsoft Graph (OAuth2)",
    "admin.email_smtp_host":          "SMTP host",
    "admin.email_smtp_port":          "Port",
    "admin.email_smtp_user":          "Username",
    "admin.email_smtp_pass":          "Password",
    "admin.email_smtp_pass_hint":     "Empty = keep existing password",
    "admin.email_smtp_from":          "Sender address (From)",
    "admin.email_smtp_tls":           "Use STARTTLS",
    "admin.email_graph_from":         "Mailbox (From address in tenant)",
    "admin.email_graph_hint":         "Reuses the Azure AD app. Requires Mail.Send application permission + admin consent.",
    "admin.email_save":               "Save",
    "admin.email_test_heading":       "Test delivery",
    "admin.email_test_to":            "Recipient",
    "admin.email_test_send":          "Send test email",
    "admin.email_status_configured":  "Configured",
    "admin.email_status_pending":     "Incomplete",
    "admin.email_status_disabled":    "Disabled",
    # Notification send
    "notify.new_incident":            "New incident",
    "notify.update":                  "Status update",
    # Source / reference on incidents
    "admin.source_label":            "Source",
    "admin.source_microsoft":        "Microsoft (Graph)",
    "admin.source_manual":           "Manual",
    "admin.source_other":            "Other",
    "admin.external_id_label":       "Reference / ID",
    "admin.external_id_placeholder": "e.g. MO1310977",
    # Azure AD settings
    "admin.azure_heading":            "Azure AD app",
    "admin.azure_hint":               "Credentials of the Azure AD app for Microsoft Graph API and email delivery.",
    "admin.azure_tenant_label":       "Tenant ID",
    "admin.azure_client_label":       "Client ID (app ID)",
    "admin.azure_secret_label":       "Client secret",
    "admin.azure_secret_hint":        "Empty = keep existing secret",
    "admin.azure_save":               "Save & test connection",
    "admin.azure_status_configured":  "Connected",
    "admin.azure_status_pending":     "Incomplete",
    "toast.azure_saved":              "Azure AD app saved.",
    # Admin – global search palette (Cmd+K / Ctrl+K)
    "admin.search.placeholder":        "Search…",
    "admin.search.group.incidents":    "Incidents",
    "admin.search.group.updates":      "Updates",
    "admin.search.group.services":     "Services",
    "admin.search.group.subscribers":  "Subscribers",
    "admin.search.no_results":         "No matches.",
    "admin.search.hint":               "Cmd+K or Ctrl+K to open",
    # Language selector
    "settings.title":                 "Settings",
    "settings.language_heading":      "Language",
    "settings.language_hint":         "Default UI language for new visitors. Individual visitors can switch languages at any time via the toggle.",
    "settings.language_save":         "Save",
    "settings.language_label":        "Default language",
    "toast.language_saved":           "Language saved.",
    "ui.switch_language":             "Switch language",
    "ui.close":                       "Close",
    "ui.back_to_overview":            "Back to overview",
    "ui.app_install":                 "Install app",
    "ui.app_install_short":           "Install",
    "ui.theme_toggle":                "Toggle colour scheme",
    "ui.no_title":                    "(untitled)",
    "ui.related_entries":             "Related entries",
    "ui.no_details_available":        "No further details available.",
    "ui.history":                     "History",
    "ui.click_for_details":           "Click for details",
    "ui.more_click_for_details":      "+{count} more – click for details",
    "ui.day.operational_body":        "No incidents on this day — service ran normally.",
    "ui.day.degraded_body":           "Reduced availability on this day.",
    "ui.day.interrupted_body":        "Service outage on this day.",
    "ui.day.no_data_body":            "No data points available for this day.",
    "ui.day.unknown_body":            "Status unknown.",
    "ui.start":                       "Start",
    "ui.end":                         "End",
    "ui.build_info_tooltip":          "App version · commit · build time (UTC)",
    "ui.range.ago_24h":               "24h ago",
    "ui.range.ago_days":              "{n} days ago",
    "admin.incident_summary_placeholder":     "Short incident summary…",
    "admin.incident_description_placeholder": "Detailed incident description…",
    "admin.maintenance_summary_placeholder":  "Short maintenance summary…",
    "admin.source_labels_hint":               "Display labels for source values on incidents. System entries are read-only.",
    "admin.service_filter_default":           "Service",
    # Duration suffixes (used by duration filter)
    "duration.sec":                   "sec",
    "duration.min":                   "min",
    "duration.hr":                    "h",
    "duration.day_one":               "1 day",
    "duration.day_many":              "{n} days",
    "duration.week_one":              "1 week",
    "duration.week_many":             "{n} weeks",
    "duration.month_one":             "1 month",
    "duration.month_many":            "{n} months",
    "datetime.today":                 "today",
}


LABELS_BY_LANG: dict[str, dict[str, str]] = {
    "de": LABELS_DE,
    "en": LABELS_EN,
}


# ── Per-request current language ────────────────────────────────────────────
_current_lang: contextvars.ContextVar[str] = contextvars.ContextVar(
    "current_lang", default=DEFAULT_LANGUAGE
)


def set_current_language(lang: str) -> contextvars.Token:
    """Set the language for the current request/context. Returns a token usable
    with ``reset_current_language()``."""
    if lang not in LABELS_BY_LANG:
        lang = DEFAULT_LANGUAGE
    return _current_lang.set(lang)


def reset_current_language(token: contextvars.Token) -> None:
    try:
        _current_lang.reset(token)
    except (ValueError, LookupError):
        pass


def get_current_language() -> str:
    return _current_lang.get()


def get_label(key: str) -> str:
    lang = _current_lang.get()
    return (
        LABELS_BY_LANG.get(lang, {}).get(key)
        or LABELS_DE.get(key)
        or key
    )


class _LabelProxy(Mapping[str, str]):
    """Dict-like view that resolves keys against the language active for the
    current request (set by the language middleware)."""

    def __getitem__(self, key: str) -> str:
        return get_label(key)

    def __iter__(self) -> Iterator[str]:
        return iter(LABELS_DE)

    def __len__(self) -> int:
        return len(LABELS_DE)

    def __contains__(self, key: object) -> bool:
        return key in LABELS_DE

    def get(self, key: str, default: str | None = None) -> str | None:
        if key in LABELS_DE or key in LABELS_EN:
            return get_label(key)
        return default


LABELS: _LabelProxy = _LabelProxy()


# ── Language negotiation ────────────────────────────────────────────────────
def parse_accept_language(header: str | None) -> list[str]:
    """Return supported language codes parsed from an Accept-Language header,
    ordered by descending q-value. Unsupported languages are dropped."""
    if not header:
        return []
    candidates: list[tuple[float, str]] = []
    for chunk in header.split(","):
        parts = chunk.strip().split(";")
        lang = parts[0].strip().lower()
        if not lang:
            continue
        q = 1.0
        for p in parts[1:]:
            p = p.strip()
            if p.startswith("q="):
                try:
                    q = float(p[2:])
                except ValueError:
                    q = 0.0
        primary = lang.split("-")[0]
        if primary in LABELS_BY_LANG:
            candidates.append((q, primary))
    candidates.sort(key=lambda x: -x[0])
    seen: set[str] = set()
    out: list[str] = []
    for _, lang in candidates:
        if lang not in seen:
            seen.add(lang)
            out.append(lang)
    return out


def language_from_os_locale() -> str | None:
    """Best-effort: derive a supported language from the server's LANG/LC_* env."""
    for var in ("LC_ALL", "LC_MESSAGES", "LANG", "LANGUAGE"):
        raw = os.environ.get(var, "").strip()
        if not raw:
            continue
        primary = raw.split(".")[0].split("_")[0].lower()
        if primary in LABELS_BY_LANG:
            return primary
    return None


def resolve_language(
    *,
    cookie: str | None = None,
    accept_language: str | None = None,
    app_default: str | None = None,
) -> str:
    """Pick the best language for the current visitor.

    Precedence: explicit cookie → Accept-Language header → app-wide default
    (admin setting) → server OS locale → ``DEFAULT_LANGUAGE``.
    """
    if cookie and cookie in LABELS_BY_LANG:
        return cookie

    for candidate in parse_accept_language(accept_language):
        return candidate

    if app_default and app_default in LABELS_BY_LANG:
        return app_default

    from_os = language_from_os_locale()
    if from_os:
        return from_os

    return DEFAULT_LANGUAGE
