#!/bin/sh
# Flips the Webshop metrics exporter into "ddos": a DDoS flood against
# shop.pyur.com, live in the webshop dashboards.
#
# Deliberately a different-shaped incident than break-customer-care.sh's
# "unhealthy" (database root cause): here the tell is the split between
# real-user metrics and raw traffic - visitors/sessions stay on their
# normal healthy wave (real people aren't flooding the site) while
# request rate explodes ~100-200x, status codes swing into 4xx/5xx, page
# load/LCP/INP degrade across EVERY page (not just Checkout), and the
# frontend/catalog services plus the CDN edge saturate on CPU/network/
# bandwidth while cache hit rate collapses. Database, payment gateway,
# inventory and other integrations stay untouched - this is an edge/
# network problem, not a backend one, and the dashboards should make
# that legible at a glance, not just say so.
#
# Run this from demo-cert-monitoring/ while the stack is up. Use
# fix-ddos-shop.sh to reverse it.
set -eu

cd "$(dirname "$0")"

echo "==> Flipping the Webshop metrics exporter to 'ddos' ..."
docker compose exec -T webshop-metrics-exporter sh -c 'echo ddos > /tmp/webshop-state'

echo ""
echo "==> Done. Within ~15-30s the webshop dashboards show:"
echo "      - Web-Traffic & Fehlercodes: Request-Rate springt auf das ~100-200-fache,"
echo "        Status-Codes kippen Richtung 4xx/5xx, Fehlerrate steigt auf allen Pfaden"
echo "      - Frontend Observability: LCP/INP/Ladezeit brechen auf JEDER Seite ein"
echo "        (nicht nur Checkout), Absprungrate springt hoch"
echo "      - Health & Business: Conversion bricht ein, Warenkorbabbruch steigt"
echo "      - Infrastruktur: Frontend + Catalog CPU/Netzwerk gesättigt, CDN-Trefferquote"
echo "        fällt, CDN-Bandbreite steigt stark"
echo "      - Datenbank-Performance: bleibt unauffällig - bewusst kein Backend-Problem"
echo "    Grafana: http://localhost:\${GRAFANA_PORT:-3000} (Dashboard-Gruppe 'shop.pyur.com')"
