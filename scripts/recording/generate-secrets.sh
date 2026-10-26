#!/bin/sh
# Writes the gateway's recording secrets into DIRECTORY (spec §12.5):
#   signing-key.pem  P-256 private key, PKCS#8 PEM, signs wraps and chain entries
#   blob-key         32 random bytes, base64, the server layer of private-key blobs
#
# Refuses to overwrite either file: a new blob key makes every stored
# private-key blob unreadable, and a new signing key orphans nothing but must
# be a decision, not an accident. Back the directory up offline; it is
# deliberately outside .env and outside every backup-production.sh path.
set -eu

directory="${1:?usage: generate-secrets.sh DIRECTORY}"
umask 077
mkdir -p "$directory"

for name in signing-key.pem blob-key; do
    if [ -e "$directory/$name" ]; then
        echo "generate-secrets.sh: refusing to overwrite $directory/$name" >&2
        exit 1
    fi
done

openssl genpkey -algorithm EC -pkeyopt ec_paramgen_curve:P-256 -out "$directory/signing-key.pem"
openssl rand -base64 32 > "$directory/blob-key"
echo "generate-secrets.sh: wrote $directory/signing-key.pem and $directory/blob-key"
