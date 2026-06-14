#!/usr/bin/env bash
# Generate a self-signed TLS certificate for the orchestrator.
#
# Usage:
#   ./gen_selfsigned_cert.sh 1.2.3.4            # for an IP
#   ./gen_selfsigned_cert.sh cpr.example.com    # for a hostname
#
# Produces cert.pem + key.pem in the current directory. Copy cert.pem to each
# client and set "ca_cert" in its config.json (and "verify_tls": true) so the
# client trusts this exact certificate.
set -euo pipefail

HOST="${1:-}"
if [[ -z "$HOST" ]]; then
  echo "Usage: $0 <public-ip-or-hostname> [days]" >&2
  exit 1
fi
DAYS="${2:-3650}"

# Decide whether HOST is an IP or a DNS name for the SAN.
if [[ "$HOST" =~ ^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
  SAN="IP:${HOST}"
else
  SAN="DNS:${HOST}"
fi

openssl req -x509 -newkey rsa:2048 -nodes \
  -keyout key.pem -out cert.pem -days "$DAYS" \
  -subj "/CN=${HOST}" \
  -addext "subjectAltName=${SAN}"

chmod 600 key.pem
echo "Wrote cert.pem and key.pem for ${HOST} (valid ${DAYS} days, SAN=${SAN})."
echo "Server: set tls_certfile=cert.pem, tls_keyfile=key.pem."
echo "Clients: copy cert.pem and set ca_cert to its path."
