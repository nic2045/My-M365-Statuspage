#!/bin/sh
# Generates a Prometheus file_sd target list from the DEMO_TARGET_URLS
# env var (comma-separated). Runs once at stack startup as an init
# container; Prometheus picks up the resulting file via file_sd_configs.
set -eu

OUT_DIR=/etc/prometheus/targets
OUT_FILE="$OUT_DIR/http_targets.json"
mkdir -p "$OUT_DIR"

urls="${DEMO_TARGET_URLS:-}"
if [ -z "$urls" ]; then
  echo "ERROR: DEMO_TARGET_URLS is empty. Set 2-3 URLs in .env, e.g.:" >&2
  echo '  DEMO_TARGET_URLS=https://a.example.com,https://b.example.com' >&2
  exit 1
fi

json_targets=""
old_ifs="$IFS"
IFS=','
for u in $urls; do
  IFS="$old_ifs"
  u=$(echo "$u" | sed 's/^[[:space:]]*//;s/[[:space:]]*$//')
  [ -z "$u" ] && continue
  if [ -z "$json_targets" ]; then
    json_targets="\"$u\""
  else
    json_targets="$json_targets, \"$u\""
  fi
  IFS=','
done
IFS="$old_ifs"

cat > "$OUT_FILE" <<EOF
[
  {
    "targets": [$json_targets]
  }
]
EOF

echo "Generated $OUT_FILE:"
cat "$OUT_FILE"
