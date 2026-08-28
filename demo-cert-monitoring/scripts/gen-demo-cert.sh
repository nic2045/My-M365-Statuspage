#!/bin/sh
# Generates a self-signed TLS cert+key for the demo-broken-site fixture,
# with an explicit, deliberately-chosen expiry date - so the demo can
# show a real (not simulated) certificate expiry flowing through
# blackbox_exporter -> Prometheus -> Grafana -> oneuptime-sync -> OneUptime.
#
# DEMO_CERT_DAYS_REMAINING controls how far the cert's notAfter is from
# "now": positive = healthy (default 90), small positive = expiring soon,
# negative = already expired. The site starts healthy by default -
# use ../break-demo.sh / ../fix-demo.sh to flip it live during a demo
# instead of starting broken.
#
# Runs as an init container (on `docker compose up` and whenever
# break-demo.sh/fix-demo.sh re-run it via `docker compose run`); nginx
# (demo-broken-site) picks up the generated files on its next (re)start.
set -eu

OUT_DIR=/certs
DAYS_REMAINING="${DEMO_CERT_DAYS_REMAINING:-90}"
CN="${DEMO_CERT_CN:-demo-broken-site.local}"

mkdir -p "$OUT_DIR"
cd "$OUT_DIR"

# GNU coreutils' `date -d "-2 days"` is needed for reliable relative-date
# math - BusyBox's built-in `date` (Alpine's default) doesn't parse that
# the same way.
apk add --no-cache openssl coreutils >/dev/null

rm -rf demoCA cert.pem key.pem csr.pem demo-openssl.cnf
mkdir -p demoCA/newcerts
: > demoCA/index.txt
echo 1000 > demoCA/serial

cat > demo-openssl.cnf <<EOF
[ ca ]
default_ca = CA_default

[ CA_default ]
dir             = $OUT_DIR/demoCA
database        = \$dir/index.txt
serial          = \$dir/serial
new_certs_dir   = \$dir/newcerts
default_md      = sha256
policy          = policy_anything
email_in_dn     = no
copy_extensions = none
unique_subject  = no

[ policy_anything ]
commonName = supplied

[ req ]
distinguished_name = req_distinguished_name
prompt = no

[ req_distinguished_name ]
CN = $CN
EOF

openssl req -new -newkey rsa:2048 -nodes \
  -keyout key.pem -out csr.pem \
  -subj "/CN=$CN" -config demo-openssl.cnf

# notBefore is always 30 days before "now" so the window is valid even
# when DAYS_REMAINING is negative (an already-expired cert still needs
# notBefore < notAfter).
NOT_BEFORE=$(date -u -d "-30 days" +%y%m%d%H%M%SZ 2>/dev/null || date -u -v-30d +%y%m%d%H%M%SZ)
NOT_AFTER=$(date -u -d "${DAYS_REMAINING} days" +%y%m%d%H%M%SZ 2>/dev/null || date -u -v${DAYS_REMAINING}d +%y%m%d%H%M%SZ)

openssl ca -config demo-openssl.cnf -selfsign \
  -keyfile key.pem -in csr.pem -out cert.pem \
  -startdate "$NOT_BEFORE" -enddate "$NOT_AFTER" -batch -notext

rm -f csr.pem
chmod 644 cert.pem
chmod 644 key.pem

echo "==> Generated $OUT_DIR/cert.pem (CN=$CN, DEMO_CERT_DAYS_REMAINING=$DAYS_REMAINING):"
openssl x509 -in cert.pem -noout -dates -subject
