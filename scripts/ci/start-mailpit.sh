#!/bin/sh
# Starts two Mailpit servers for the re-enrolment mail tests (spec §9.9), with a
# self-signed certificate no client trusts: one offers STARTTLS, one speaks TLS
# from the first byte. Writes the ports and the certificate path to $GITHUB_ENV.
#
#   GITHUB_ENV=<file> scripts/ci/start-mailpit.sh <directory for the certificate>
#
# SSF_CI_MAILPIT_NAME and SSF_CI_MAILPIT_PORT (default ssf-mailpit-ci, 1025) let it
# run beside another one locally; it uses that port and the next three.
set -eu

: "${GITHUB_ENV:?GITHUB_ENV names the file the ports are written to}"
dir="${1:?the directory for the certificate}"
name="${SSF_CI_MAILPIT_NAME:-ssf-mailpit-ci}"
port="${SSF_CI_MAILPIT_PORT:-1025}"
image="axllent/mailpit@sha256:23fe39e81bde596a918000b3135c0f85dc8bb4c9ea6be274b051143f3e300387" # v1.31.6

mkdir -p "$dir"
openssl req -x509 -newkey rsa:2048 -nodes -days 2 -subj "/CN=localhost" \
  -addext "subjectAltName=DNS:localhost,IP:127.0.0.1" \
  -keyout "$dir/mailpit.key" -out "$dir/mailpit.crt" 2>/dev/null
chmod 644 "$dir/mailpit.key"

docker run -d --name "$name" -v "$dir:/certs:ro" \
  -p "127.0.0.1:$port:1025" -p "127.0.0.1:$((port + 1)):8025" \
  "$image" --smtp-tls-cert /certs/mailpit.crt --smtp-tls-key /certs/mailpit.key >/dev/null
docker run -d --name "$name-tls" -v "$dir:/certs:ro" \
  -p "127.0.0.1:$((port + 2)):1025" -p "127.0.0.1:$((port + 3)):8025" \
  "$image" --smtp-tls-cert /certs/mailpit.crt --smtp-tls-key /certs/mailpit.key \
  --smtp-require-tls >/dev/null

for api in $((port + 1)) $((port + 3)); do
  ready=no
  for _ in $(seq 1 30); do
    if curl -fs "http://127.0.0.1:$api/api/v1/info" >/dev/null 2>&1; then
      ready=yes
      break
    fi
    sleep 1
  done
  if [ "$ready" != yes ]; then
    echo "start-mailpit.sh: Mailpit on $api never answered" >&2
    docker logs "$name" >&2
    docker logs "$name-tls" >&2
    exit 1
  fi
done

{
  echo "SSF_MAILPIT_SMTP_PORT=$port"
  echo "SSF_MAILPIT_API_PORT=$((port + 1))"
  echo "SSF_MAILPIT_TLS_PORT=$((port + 2))"
  echo "SSF_MAILPIT_TLS_API_PORT=$((port + 3))"
  echo "SSF_MAILPIT_CERTIFICATE=$dir/mailpit.crt"
} >> "$GITHUB_ENV"
echo "start-mailpit.sh: $name ready on 127.0.0.1:$port"
