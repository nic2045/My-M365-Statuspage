#!/usr/bin/env python3
"""Synthetic Prometheus exporter for the Customer-Care demo.

Not a real integration - there is no actual Avaya/Citrix/Cognigy/LLM
behind this. Models a distributed Customer-Care service: on-prem
telephony (Avaya ACD, SIP), Citrix-hosted agent desktops, a customer
support app, a billing app, and the internal LLM (llm.pyur.com) feeding
Cognigy (the one cloud/SaaS component - everything else is on-prem) -
plus 6 Customer-Care sites across Germany, each connected back to the
Leipzig datacenter via site-to-site VPN, with VoIP quality (MOS/jitter)
and bandwidth utilization per link.

Baseline: busy-but-healthy (roughly 45-75% utilization, VPN links up,
good MOS scores), with visible movement so a live dashboard doesn't look
frozen. STATE_FILE (default /tmp/customer-care-state) toggles a real
incident when set to "unhealthy": the Chemnitz VPN link degrades hard
(packet loss, bad MOS, bandwidth collapse) and the Avaya queue backs up -
so break-customer-care.sh / fix-customer-care.sh can demo a live
disruption without restarting this process.
"""
import http.server
import math
import os
import random
import time

PORT = int(os.environ.get("METRICS_PORT", "9300"))
STATE_FILE = os.environ.get("STATE_FILE", "/tmp/customer-care-state")

START = time.time()
_calls_offered_total = 0.0
_calls_abandoned_total = 0.0
_cognigy_requests_total = 0.0
_llm_requests_total = 0.0

# site -> (lat, lon, base_bandwidth_capacity_mbps)
SITES = {
    "Berlin":         (52.5200, 13.4050, 100),
    "Dresden":        (51.0504, 13.7373, 50),
    "Chemnitz":       (50.8278, 12.9214, 50),
    "Halle (Saale)":  (51.4964, 11.9683, 50),
    "Rostock":        (54.0887, 12.1404, 30),
    "Erfurt":         (50.9848, 11.0299, 30),
}
LEIPZIG_HUB = ("Leipzig (RZ)", 51.3397, 12.3731)
DEGRADED_SITE = "Chemnitz"  # the one break-customer-care.sh degrades

# Fictional call-center operators per site (no real companies) - used only
# as a human-readable label on the Germany map, each name spells out its
# city so a single text label is enough orientation on its own.
SITE_COMPANIES = {
    "Berlin":         "NordCom Kundenkontakt Berlin",
    "Dresden":        "Elbtal Servicecenter Dresden",
    "Chemnitz":       "Sachsenring Contact Chemnitz",
    "Halle (Saale)":  "Saalekontakt Halle",
    "Rostock":        "Ostseecontact Rostock",
    "Erfurt":         "Thüringen Direkt Erfurt",
}
HUB_COMPANY = "PYUR Rechenzentrum Leipzig"

# Small badge icons for the Geomap "Photos" layer (source SVGs under
# assets/icons/, inlined here as data URIs since only this one script file
# is bind-mounted into the exporter container - see docker-compose.yml).
# Colour encodes the site's current health tier directly in the icon,
# since the Photos layer's own style has no per-value colour binding
# (only a fixed border colour) - unlike the markers/route layers.
ICON_CALLCENTER_GREEN = "data:image/svg+xml;base64,PHN2ZyB4bWxucz0iaHR0cDovL3d3dy53My5vcmcvMjAwMC9zdmciIHdpZHRoPSI2NCIgaGVpZ2h0PSI2NCIgdmlld0JveD0iMCAwIDY0IDY0Ij4KICA8Y2lyY2xlIGN4PSIzMiIgY3k9IjMyIiByPSIzMCIgZmlsbD0iIzJlN2QzMiIvPgogIDxyZWN0IHg9IjIwIiB5PSIyMiIgd2lkdGg9IjI0IiBoZWlnaHQ9IjE4IiByeD0iMyIgZmlsbD0iI2ZmZmZmZiIvPgogIDxyZWN0IHg9IjI0IiB5PSIyNiIgd2lkdGg9IjYiIGhlaWdodD0iNiIgZmlsbD0iIzJlN2QzMiIvPgogIDxyZWN0IHg9IjM0IiB5PSIyNiIgd2lkdGg9IjYiIGhlaWdodD0iNiIgZmlsbD0iIzJlN2QzMiIvPgogIDxyZWN0IHg9IjI0IiB5PSIzNCIgd2lkdGg9IjYiIGhlaWdodD0iNCIgZmlsbD0iIzJlN2QzMiIvPgogIDxyZWN0IHg9IjM0IiB5PSIzNCIgd2lkdGg9IjYiIGhlaWdodD0iNCIgZmlsbD0iIzJlN2QzMiIvPgogIDxyZWN0IHg9IjI2IiB5PSIxNiIgd2lkdGg9IjEyIiBoZWlnaHQ9IjYiIHJ4PSIyIiBmaWxsPSIjZmZmZmZmIi8+Cjwvc3ZnPgo="
ICON_CALLCENTER_YELLOW = "data:image/svg+xml;base64,PHN2ZyB4bWxucz0iaHR0cDovL3d3dy53My5vcmcvMjAwMC9zdmciIHdpZHRoPSI2NCIgaGVpZ2h0PSI2NCIgdmlld0JveD0iMCAwIDY0IDY0Ij4KICA8Y2lyY2xlIGN4PSIzMiIgY3k9IjMyIiByPSIzMCIgZmlsbD0iI2Y5YTgyNSIvPgogIDxyZWN0IHg9IjIwIiB5PSIyMiIgd2lkdGg9IjI0IiBoZWlnaHQ9IjE4IiByeD0iMyIgZmlsbD0iI2ZmZmZmZiIvPgogIDxyZWN0IHg9IjI0IiB5PSIyNiIgd2lkdGg9IjYiIGhlaWdodD0iNiIgZmlsbD0iI2Y5YTgyNSIvPgogIDxyZWN0IHg9IjM0IiB5PSIyNiIgd2lkdGg9IjYiIGhlaWdodD0iNiIgZmlsbD0iI2Y5YTgyNSIvPgogIDxyZWN0IHg9IjI0IiB5PSIzNCIgd2lkdGg9IjYiIGhlaWdodD0iNCIgZmlsbD0iI2Y5YTgyNSIvPgogIDxyZWN0IHg9IjM0IiB5PSIzNCIgd2lkdGg9IjYiIGhlaWdodD0iNCIgZmlsbD0iI2Y5YTgyNSIvPgogIDxyZWN0IHg9IjI2IiB5PSIxNiIgd2lkdGg9IjEyIiBoZWlnaHQ9IjYiIHJ4PSIyIiBmaWxsPSIjZmZmZmZmIi8+Cjwvc3ZnPgo="
ICON_CALLCENTER_RED = "data:image/svg+xml;base64,PHN2ZyB4bWxucz0iaHR0cDovL3d3dy53My5vcmcvMjAwMC9zdmciIHdpZHRoPSI2NCIgaGVpZ2h0PSI2NCIgdmlld0JveD0iMCAwIDY0IDY0Ij4KICA8Y2lyY2xlIGN4PSIzMiIgY3k9IjMyIiByPSIzMCIgZmlsbD0iI2M2MjgyOCIvPgogIDxyZWN0IHg9IjIwIiB5PSIyMiIgd2lkdGg9IjI0IiBoZWlnaHQ9IjE4IiByeD0iMyIgZmlsbD0iI2ZmZmZmZiIvPgogIDxyZWN0IHg9IjI0IiB5PSIyNiIgd2lkdGg9IjYiIGhlaWdodD0iNiIgZmlsbD0iI2M2MjgyOCIvPgogIDxyZWN0IHg9IjM0IiB5PSIyNiIgd2lkdGg9IjYiIGhlaWdodD0iNiIgZmlsbD0iI2M2MjgyOCIvPgogIDxyZWN0IHg9IjI0IiB5PSIzNCIgd2lkdGg9IjYiIGhlaWdodD0iNCIgZmlsbD0iI2M2MjgyOCIvPgogIDxyZWN0IHg9IjM0IiB5PSIzNCIgd2lkdGg9IjYiIGhlaWdodD0iNCIgZmlsbD0iI2M2MjgyOCIvPgogIDxyZWN0IHg9IjI2IiB5PSIxNiIgd2lkdGg9IjEyIiBoZWlnaHQ9IjYiIHJ4PSIyIiBmaWxsPSIjZmZmZmZmIi8+Cjwvc3ZnPgo="
ICON_HUB = "data:image/svg+xml;base64,PHN2ZyB4bWxucz0iaHR0cDovL3d3dy53My5vcmcvMjAwMC9zdmciIHdpZHRoPSI2NCIgaGVpZ2h0PSI2NCIgdmlld0JveD0iMCAwIDY0IDY0Ij4KICA8Y2lyY2xlIGN4PSIzMiIgY3k9IjMyIiByPSIzMCIgZmlsbD0iIzBmNmNiZCIvPgogIDxyZWN0IHg9IjE5IiB5PSIxNiIgd2lkdGg9IjI2IiBoZWlnaHQ9IjMyIiByeD0iMyIgZmlsbD0iI2ZmZmZmZiIvPgogIDxyZWN0IHg9IjIzIiB5PSIyMSIgd2lkdGg9IjE4IiBoZWlnaHQ9IjUiIGZpbGw9IiMwZjZjYmQiLz4KICA8cmVjdCB4PSIyMyIgeT0iMjkiIHdpZHRoPSIxOCIgaGVpZ2h0PSI1IiBmaWxsPSIjMGY2Y2JkIi8+CiAgPHJlY3QgeD0iMjMiIHk9IjM3IiB3aWR0aD0iMTgiIGhlaWdodD0iNSIgZmlsbD0iIzBmNmNiZCIvPgogIDxjaXJjbGUgY3g9IjM5IiBjeT0iMjMuNSIgcj0iMS40IiBmaWxsPSIjZmZmZmZmIi8+CiAgPGNpcmNsZSBjeD0iMzkiIGN5PSIzMS41IiByPSIxLjQiIGZpbGw9IiNmZmZmZmYiLz4KICA8Y2lyY2xlIGN4PSIzOSIgY3k9IjM5LjUiIHI9IjEuNCIgZmlsbD0iI2ZmZmZmZiIvPgo8L3N2Zz4K"


def is_unhealthy():
    try:
        with open(STATE_FILE) as fh:
            return fh.read().strip() == "unhealthy"
    except FileNotFoundError:
        return False


def wave(period_s, low, high, phase=0.0):
    t = time.time() - START
    frac = (math.sin(2 * math.pi * (t / period_s) + phase) + 1) / 2
    jitter = random.uniform(-0.03, 0.03) * (high - low)
    return max(low, min(high, low + frac * (high - low) + jitter))


def render_metrics():
    global _calls_offered_total, _calls_abandoned_total
    global _cognigy_requests_total, _llm_requests_total
    unhealthy = is_unhealthy()

    lines = []

    # ── Leipzig hub marker (always healthy - it's the source, not a link) ──
    name, lat, lon = LEIPZIG_HUB
    lines += [
        "# HELP cc_site_info Static info row per Customer-Care site (value always 1) - used for the Germany map.",
        "# TYPE cc_site_info gauge",
        f'cc_site_info{{site="{name}",lat="{lat}",lon="{lon}",role="hub",'
        f'company="{HUB_COMPANY}",photo="{ICON_HUB}"}} 1',
    ]

    # ── Telefonie: Avaya ACD / SIP ────────────────────────────────────────
    queue_len = wave(50, 3, 14, phase=0.2) if not unhealthy else wave(20, 20, 45)
    avg_wait = wave(55, 15, 60, phase=0.5) if not unhealthy else wave(20, 90, 240)
    offered_rate = random.uniform(2.0, 5.0)
    abandoned_rate = offered_rate * (random.uniform(0.02, 0.06) if not unhealthy else random.uniform(0.15, 0.30))
    _calls_offered_total += offered_rate
    _calls_abandoned_total += abandoned_rate
    trunk_util = wave(65, 45, 75, phase=0.1) if not unhealthy else wave(20, 80, 98)

    lines += [
        "# HELP cc_avaya_calls_queued Calls currently waiting in the ACD queue.",
        "# TYPE cc_avaya_calls_queued gauge",
        f"cc_avaya_calls_queued {queue_len:.0f}",
        "# HELP cc_avaya_avg_wait_seconds Average caller wait time.",
        "# TYPE cc_avaya_avg_wait_seconds gauge",
        f"cc_avaya_avg_wait_seconds {avg_wait:.0f}",
        "# HELP cc_avaya_calls_offered_total Calls offered to the ACD.",
        "# TYPE cc_avaya_calls_offered_total counter",
        f"cc_avaya_calls_offered_total {_calls_offered_total:.0f}",
        "# HELP cc_avaya_calls_abandoned_total Calls abandoned while queued.",
        "# TYPE cc_avaya_calls_abandoned_total counter",
        f"cc_avaya_calls_abandoned_total {_calls_abandoned_total:.0f}",
        "# HELP cc_avaya_sip_trunk_utilization_percent SIP trunk utilization to the carrier.",
        "# TYPE cc_avaya_sip_trunk_utilization_percent gauge",
        f"cc_avaya_sip_trunk_utilization_percent {trunk_util:.1f}",
        "# HELP cc_avaya_sip_registration_status SIP registration with the carrier (1=registered).",
        "# TYPE cc_avaya_sip_registration_status gauge",
        "cc_avaya_sip_registration_status 1",
    ]

    total_agents = 0
    agents_available_lines = []
    agents_busy_lines = []
    for site, (lat, lon, _cap) in SITES.items():
        agent_base = {"Berlin": 40, "Dresden": 22, "Chemnitz": 18, "Halle (Saale)": 20, "Rostock": 12, "Erfurt": 14}[site]
        degraded_here = unhealthy and site == DEGRADED_SITE
        available = 0 if degraded_here else round(wave(45, agent_base * 0.5, agent_base * 0.85, phase=hash(site) % 10))
        busy = 0 if degraded_here else round(wave(45, agent_base * 0.15, agent_base * 0.4, phase=hash(site) % 7))
        total_agents += available + busy
        agents_available_lines.append(f'cc_avaya_agents_available{{site="{site}"}} {available}')
        agents_busy_lines.append(f'cc_avaya_agents_busy{{site="{site}"}} {busy}')
    agent_lines = (
        ["# HELP cc_avaya_agents_available Agents logged in and available, per site.",
         "# TYPE cc_avaya_agents_available gauge"] + agents_available_lines
        + ["# HELP cc_avaya_agents_busy Agents logged in and on a call, per site.",
           "# TYPE cc_avaya_agents_busy gauge"] + agents_busy_lines
    )

    # ── Citrix (agent desktops) ──────────────────────────────────────────
    citrix_lines = [
        "# HELP cc_citrix_active_sessions Active Citrix sessions, per site.",
        "# TYPE cc_citrix_active_sessions gauge",
    ]
    for site, (lat, lon, _cap) in SITES.items():
        base = {"Berlin": 38, "Dresden": 20, "Chemnitz": 16, "Halle (Saale)": 18, "Rostock": 11, "Erfurt": 13}[site]
        degraded_here = unhealthy and site == DEGRADED_SITE
        sessions = 0 if degraded_here else round(wave(50, base * 0.6, base * 0.9, phase=hash(site + "c") % 10))
        citrix_lines.append(f'cc_citrix_active_sessions{{site="{site}"}} {sessions}')
    citrix_lines += [
        "# HELP cc_citrix_ica_latency_ms ICA protocol round-trip latency, per site.",
        "# TYPE cc_citrix_ica_latency_ms gauge",
    ]
    for site, (lat, lon, _cap) in SITES.items():
        degraded_here = unhealthy and site == DEGRADED_SITE
        latency = wave(40, 180, 420, phase=hash(site + "l") % 10) if degraded_here else wave(40, 18, 55, phase=hash(site + "l") % 10)
        citrix_lines.append(f'cc_citrix_ica_latency_ms{{site="{site}"}} {latency:.0f}')
    citrix_lines += [
        "# HELP cc_citrix_server_cpu_percent CPU utilization of a Citrix farm server.",
        "# TYPE cc_citrix_server_cpu_percent gauge",
        f'cc_citrix_server_cpu_percent{{server="citrix1"}} {wave(70, 45, 75, phase=0.4):.1f}',
        f'cc_citrix_server_cpu_percent{{server="citrix2"}} {wave(70, 45, 75, phase=1.8):.1f}',
        "# HELP cc_citrix_server_memory_percent Memory utilization of a Citrix farm server.",
        "# TYPE cc_citrix_server_memory_percent gauge",
        f'cc_citrix_server_memory_percent{{server="citrix1"}} {wave(85, 45, 75, phase=0.9):.1f}',
        f'cc_citrix_server_memory_percent{{server="citrix2"}} {wave(85, 45, 75, phase=2.3):.1f}',
    ]

    # ── Kundensupport-App / Rechnungswesen-App ───────────────────────────
    app_lines = [
        "# HELP cc_support_app_response_time_ms Response time of the customer support app.",
        "# TYPE cc_support_app_response_time_ms gauge",
        f"cc_support_app_response_time_ms {wave(55, 80, 220, phase=0.7):.0f}",
        "# HELP cc_support_app_error_rate_percent Error rate of the customer support app.",
        "# TYPE cc_support_app_error_rate_percent gauge",
        f"cc_support_app_error_rate_percent {wave(60, 0.0, 0.8, phase=1.1):.2f}",
        "# HELP cc_support_app_active_users Users currently active in the customer support app.",
        "# TYPE cc_support_app_active_users gauge",
        f"cc_support_app_active_users {wave(50, total_agents * 0.7, total_agents * 0.95, phase=0.3):.0f}",

        "# HELP cc_billing_app_response_time_ms Response time of the billing (Rechnungswesen) app.",
        "# TYPE cc_billing_app_response_time_ms gauge",
        f"cc_billing_app_response_time_ms {wave(65, 100, 260, phase=1.5):.0f}",
        "# HELP cc_billing_app_batch_job_status Nightly billing batch job status (1=ok, 0=failed).",
        "# TYPE cc_billing_app_batch_job_status gauge",
        "cc_billing_app_batch_job_status 1",
    ]

    # ── Cognigy (cloud/SaaS - the one non-on-prem component) + LLM usage ──
    _cognigy_requests_total += random.uniform(3, 9)
    _llm_requests_total += random.uniform(2, 7)
    cognigy_lines = [
        "# HELP cc_cognigy_api_latency_ms Latency of the Cognigy.AI cloud API (the one SaaS component - everything else on-prem).",
        "# TYPE cc_cognigy_api_latency_ms gauge",
        f"cc_cognigy_api_latency_ms {wave(45, 60, 180, phase=0.6):.0f}",
        "# HELP cc_cognigy_bot_sessions_active Active voice-/chatbot sessions in Cognigy.",
        "# TYPE cc_cognigy_bot_sessions_active gauge",
        f"cc_cognigy_bot_sessions_active {wave(40, 8, 35, phase=0.9):.0f}",
        "# HELP cc_cognigy_intent_success_rate_percent Share of bot turns where intent recognition succeeded.",
        "# TYPE cc_cognigy_intent_success_rate_percent gauge",
        f"cc_cognigy_intent_success_rate_percent {wave(55, 91, 98, phase=1.2):.1f}",
        "# HELP cc_cognigy_requests_total Requests handled by the Cognigy bot.",
        "# TYPE cc_cognigy_requests_total counter",
        f"cc_cognigy_requests_total {_cognigy_requests_total:.0f}",
        "# HELP cc_llm_requests_from_bot_total Requests the Cognigy bot forwarded to the internal LLM (llm.pyur.com).",
        "# TYPE cc_llm_requests_from_bot_total counter",
        f"cc_llm_requests_from_bot_total {_llm_requests_total:.0f}",
    ]

    # ── Infrastruktur (on-prem servers hosting the above) ─────────────────
    infra_lines = [
        "# HELP cc_infra_server_cpu_percent CPU utilization of an on-prem Customer-Care infrastructure server.",
        "# TYPE cc_infra_server_cpu_percent gauge",
        f'cc_infra_server_cpu_percent{{server="support-app-1",role="Kundensupport-App"}} {wave(60, 45, 75, phase=0.2):.1f}',
        f'cc_infra_server_cpu_percent{{server="billing-app-1",role="Rechnungswesen-App"}} {wave(60, 45, 75, phase=1.4):.1f}',
        f'cc_infra_server_cpu_percent{{server="avaya-acd-1",role="Avaya ACD"}} {wave(60, 45, 75, phase=2.6):.1f}',
        "# HELP cc_infra_server_memory_percent Memory utilization of an on-prem Customer-Care infrastructure server.",
        "# TYPE cc_infra_server_memory_percent gauge",
        f'cc_infra_server_memory_percent{{server="support-app-1",role="Kundensupport-App"}} {wave(80, 45, 75, phase=0.5):.1f}',
        f'cc_infra_server_memory_percent{{server="billing-app-1",role="Rechnungswesen-App"}} {wave(80, 45, 75, phase=1.7):.1f}',
        f'cc_infra_server_memory_percent{{server="avaya-acd-1",role="Avaya ACD"}} {wave(80, 45, 75, phase=2.9):.1f}',
    ]

    # ── 6 Standorte: S2S-VPN zum Leipziger RZ, Bandbreite & VoIP-Qualität ──
    site_lines = [
        "# HELP cc_site_vpn_up Site-to-site VPN tunnel status to the Leipzig datacenter (1=up).",
        "# TYPE cc_site_vpn_up gauge",
        "# HELP cc_site_vpn_bandwidth_used_mbps Current bandwidth used on the site's VPN link.",
        "# TYPE cc_site_vpn_bandwidth_used_mbps gauge",
        "# HELP cc_site_vpn_bandwidth_capacity_mbps Provisioned capacity of the site's VPN link.",
        "# TYPE cc_site_vpn_bandwidth_capacity_mbps gauge",
        "# HELP cc_site_vpn_latency_ms Round-trip latency to the Leipzig datacenter.",
        "# TYPE cc_site_vpn_latency_ms gauge",
        "# HELP cc_site_voip_mos_score VoIP call quality (Mean Opinion Score, 1.0-5.0, 5=best).",
        "# TYPE cc_site_voip_mos_score gauge",
        "# HELP cc_site_voip_jitter_ms VoIP jitter on the site's link.",
        "# TYPE cc_site_voip_jitter_ms gauge",
        "# HELP cc_site_voip_concurrent_calls Concurrent VoIP calls currently on this site's link.",
        "# TYPE cc_site_voip_concurrent_calls gauge",
    ]
    for site, (lat, lon, capacity) in SITES.items():
        degraded_here = unhealthy and site == DEGRADED_SITE
        if degraded_here:
            vpn_up = 0
            used = capacity * random.uniform(0.05, 0.15)
            latency = wave(20, 180, 340, phase=hash(site) % 10)
            mos = wave(20, 1.2, 2.1, phase=hash(site) % 10)
            jitter = wave(20, 60, 140, phase=hash(site) % 10)
            calls = round(wave(20, 0, 2, phase=hash(site) % 10))
        else:
            vpn_up = 1
            used = wave(60, capacity * 0.35, capacity * 0.7, phase=hash(site) % 10)
            latency = wave(50, 8, 28, phase=hash(site) % 10)
            mos = wave(60, 4.1, 4.7, phase=hash(site) % 10)
            jitter = wave(50, 2, 12, phase=hash(site) % 10)
            calls = round(wave(50, 2, 9, phase=hash(site) % 10))

        if not vpn_up:
            icon = ICON_CALLCENTER_RED
        elif used / capacity >= 0.85:
            icon = ICON_CALLCENTER_YELLOW
        else:
            icon = ICON_CALLCENTER_GREEN
        labels = (f'site="{site}",lat="{lat}",lon="{lon}",'
                  f'company="{SITE_COMPANIES[site]}",photo="{icon}"')

        site_lines.append(f'cc_site_vpn_up{{{labels}}} {vpn_up}')
        site_lines.append(f'cc_site_vpn_bandwidth_used_mbps{{{labels}}} {used:.1f}')
        site_lines.append(f'cc_site_vpn_bandwidth_capacity_mbps{{{labels}}} {capacity}')
        site_lines.append(f'cc_site_vpn_latency_ms{{{labels}}} {latency:.0f}')
        site_lines.append(f'cc_site_voip_mos_score{{{labels}}} {mos:.2f}')
        site_lines.append(f'cc_site_voip_jitter_ms{{{labels}}} {jitter:.0f}')
        site_lines.append(f'cc_site_voip_concurrent_calls{{{labels}}} {calls}')

    all_lines = (
        lines
        + agent_lines
        + citrix_lines
        + app_lines
        + cognigy_lines
        + infra_lines
        + site_lines
    )
    return "\n".join(all_lines) + "\n"


class Handler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path != "/metrics":
            self.send_response(404)
            self.end_headers()
            return
        body = render_metrics().encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/plain; version=0.0.4")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt, *args):
        pass


if __name__ == "__main__":
    http.server.HTTPServer(("0.0.0.0", PORT), Handler).serve_forever()
