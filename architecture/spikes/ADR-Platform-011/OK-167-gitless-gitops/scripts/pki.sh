#!/usr/bin/env bash
#
# OK-167 — local PKI for the zot registry.
#
# Creates a throwaway CA and a server certificate for zot, both valid 30 days.
# Everything lands in .local/pki/ at mode 600 and is gitignored: this CA exists
# only for this spike on this machine.
#
# The CA is never added to the macOS keychain (BRIEF B4 rule 7). Every client
# is pointed at it explicitly instead — curl with --cacert, oras with
# --ca-file, cosign with --registry-cacert, Argo CD through
# argocd-tls-certs-cm. Go tools ignore SSL_CERT_FILE on macOS and read the
# system store, so an implicit path would silently not work.
#
# Idempotent: existing files are kept. Delete .local/pki/ to start over.
#
# Exit codes
#   0  ok
#   2  prerequisite missing

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SPIKE_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

# shellcheck source=./lib.sh
# shellcheck disable=SC1091
. "$SCRIPT_DIR/lib.sh"

PKI_DIR="$SPIKE_ROOT/.local/pki"

# System openssl on macOS is LibreSSL, which differs from OpenSSL in extension
# handling. openssl@3 is required (see evidence/00-preflight.md).
OPENSSL="${OPENSSL:-openssl}"
ok167::require_tool "$OPENSSL"
if ! "$OPENSSL" version | grep -q '^OpenSSL'; then
  ok167::die "$OPENSSL is not OpenSSL ($("$OPENSSL" version)); use openssl@3" 2
fi

mkdir -p "$PKI_DIR"
chmod 700 "$PKI_DIR"

CA_KEY="$PKI_DIR/ca.key"
CA_CRT="$PKI_DIR/ca.crt"
SRV_KEY="$PKI_DIR/tls.key"
SRV_CSR="$PKI_DIR/tls.csr"
SRV_CRT="$PKI_DIR/tls.crt"
SRV_EXT="$PKI_DIR/server-ext.cnf"

DAYS=30

# ---------------------------------------------------------------------------
# CA
# ---------------------------------------------------------------------------
if [ -f "$CA_KEY" ] && [ -f "$CA_CRT" ]; then
  ok167::info "CA already present, keeping it ($CA_CRT)"
else
  ok167::info "creating CA (valid ${DAYS} days)"
  ok167::touch_private "$CA_KEY"
  "$OPENSSL" genrsa -out "$CA_KEY" 4096 2>/dev/null
  chmod 600 "$CA_KEY"

  "$OPENSSL" req -x509 -new -nodes \
    -key "$CA_KEY" \
    -sha256 \
    -days "$DAYS" \
    -subj "/CN=OK-167 local spike CA/O=OpenKubes/OU=OK-167" \
    -addext "basicConstraints=critical,CA:TRUE,pathlen:0" \
    -addext "keyUsage=critical,keyCertSign,cRLSign" \
    -out "$CA_CRT"
  chmod 644 "$CA_CRT"   # the CA certificate is public material
fi

# ---------------------------------------------------------------------------
# Server certificate
# ---------------------------------------------------------------------------
# SANs cover every name zot is reached by:
#   zot.zot.svc.cluster.local  Argo CD's repo-server (in-cluster, the real path)
#   zot, zot.zot, zot.zot.svc  shorter in-cluster forms
#   localhost / 127.0.0.1      the host, through NodePort 30500
if [ -f "$SRV_KEY" ] && [ -f "$SRV_CRT" ]; then
  ok167::info "server certificate already present, keeping it ($SRV_CRT)"
else
  ok167::info "creating server certificate (valid ${DAYS} days)"

  cat > "$SRV_EXT" <<'EOF'
basicConstraints = CA:FALSE
keyUsage = critical,digitalSignature,keyEncipherment
extendedKeyUsage = serverAuth
subjectAltName = @alt_names

[alt_names]
DNS.1 = zot
DNS.2 = zot.zot
DNS.3 = zot.zot.svc
DNS.4 = zot.zot.svc.cluster.local
DNS.5 = localhost
IP.1  = 127.0.0.1
EOF

  ok167::touch_private "$SRV_KEY"
  "$OPENSSL" genrsa -out "$SRV_KEY" 2048 2>/dev/null
  chmod 600 "$SRV_KEY"

  "$OPENSSL" req -new \
    -key "$SRV_KEY" \
    -subj "/CN=zot.zot.svc.cluster.local/O=OpenKubes/OU=OK-167" \
    -out "$SRV_CSR"

  "$OPENSSL" x509 -req \
    -in "$SRV_CSR" \
    -CA "$CA_CRT" -CAkey "$CA_KEY" -CAcreateserial \
    -days "$DAYS" -sha256 \
    -extfile "$SRV_EXT" \
    -out "$SRV_CRT" 2>/dev/null
  chmod 644 "$SRV_CRT"
  rm -f "$SRV_CSR"
fi

# ---------------------------------------------------------------------------
# Verify what was produced, rather than trusting that openssl did as asked
# ---------------------------------------------------------------------------
ok167::info "verifying the certificate chain"

"$OPENSSL" verify -CAfile "$CA_CRT" "$SRV_CRT" >/dev/null \
  || ok167::die "server certificate does not verify against the CA" 1

for name in zot zot.zot zot.zot.svc zot.zot.svc.cluster.local localhost; do
  "$OPENSSL" x509 -in "$SRV_CRT" -noout -ext subjectAltName \
    | grep -q "DNS:$name" \
    || ok167::die "SAN missing from server certificate: DNS:$name" 1
done
"$OPENSSL" x509 -in "$SRV_CRT" -noout -ext subjectAltName \
  | grep -q 'IP Address:127.0.0.1' \
  || ok167::die "SAN missing from server certificate: IP:127.0.0.1" 1

"$OPENSSL" x509 -in "$SRV_CRT" -noout -ext extendedKeyUsage \
  | grep -q 'TLS Web Server Authentication' \
  || ok167::die "server certificate lacks extendedKeyUsage=serverAuth" 1

"$OPENSSL" x509 -in "$CA_CRT" -noout -ext basicConstraints \
  | grep -q 'CA:TRUE' \
  || ok167::die "CA certificate is not marked CA:TRUE" 1

ok167::assert_private "$CA_KEY"
ok167::assert_private "$SRV_KEY"

ok167::ok "PKI ready in .local/pki/ (CA + server cert, $(
  "$OPENSSL" x509 -in "$SRV_CRT" -noout -enddate | cut -d= -f2
))"
