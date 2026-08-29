#!/usr/bin/env bash
# Downloads the community Grafana dashboards referenced in README.md into
# dashboards/, where provisioning/dashboards/dashboards.yml auto-loads any
# *.json placed there.
#
# Needs real internet access to grafana.com - run this from your own machine,
# not from a network-restricted sandbox/CI runner. Re-run any time to refresh
# to the latest revision of each dashboard.
set -euo pipefail

cd "$(dirname "$0")/dashboards"

# id -> output filename. IDs for Apache/MSSQL are a starting point from
# training data, NOT guaranteed current - verify on grafana.com before
# relying on them (search there by name + "Prometheus" data source if in
# doubt). Node Exporter Full (1860) is long-stable and safe to trust as-is.
declare -A DASHBOARDS=(
  [1860]="node-exporter-full.json"          # Systemadmins - Server/VM host metrics
  [3894]="apache2-webserver.json"           # Webserver-Admins - Apache2 (apache_exporter)
  [9159]="mssql-server-performance.json"    # DB-Admins - MS SQL Server (sql_exporter)
)

for id in "${!DASHBOARDS[@]}"; do
  file="${DASHBOARDS[$id]}"
  echo "Fetching dashboard ${id} -> ${file} ..."
  curl -fsSL "https://grafana.com/api/dashboards/${id}/revisions/latest/download" -o "${file}"
done

echo
echo "Done. VMware host dashboard has no ID hardcoded here (see README.md) -"
echo "download it manually from grafana.com and save it into this same directory."
echo "Commit the resulting *.json files so they ship with the repo."
