#!/usr/bin/env bash

set -euo pipefail

backup_dir="${1:-}"
if [[ $# -ne 1 || -z "$backup_dir" ]]; then
  printf 'Usage: %s <concrete-backup-directory>\n' "$0" >&2
  exit 2
fi
if [[ -L "$backup_dir" ]]; then
  printf 'A concrete backup directory is required; symlinks such as latest are not accepted.\n' >&2
  exit 2
fi
if [[ ! -d "$backup_dir" ]]; then
  printf 'Backup directory does not exist: %s\n' "$backup_dir" >&2
  exit 2
fi
if [[ ! -f "$backup_dir/manifest.json" ]]; then
  printf 'Missing manifest.json in %s\n' "$backup_dir" >&2
  exit 1
fi

mapfile -t required < <(python3 - "$backup_dir/manifest.json" <<'PY'
import json
import sys

try:
    manifest = json.load(open(sys.argv[1], encoding="utf-8"))
    required = manifest["required"]
    if not isinstance(required, list) or not all(isinstance(item, str) for item in required):
        raise ValueError("required must be a list of paths")
except (OSError, ValueError, KeyError, json.JSONDecodeError) as error:
    print(f"Invalid backup manifest: {error}", file=sys.stderr)
    sys.exit(1)

print(*required, sep="\n")
PY
) || exit 1

failed=0
for artifact in "${required[@]}"; do
  if [[ ! -f "$backup_dir/$artifact" ]]; then
    printf 'Missing required backup artifact: %s\n' "$artifact" >&2
    failed=1
  fi
done
(( failed == 0 )) || exit 1

for metadata in manifest.sha256 checksums.sha256; do
  if [[ ! -f "$backup_dir/$metadata" ]]; then
    printf 'Missing checksum metadata: %s\n' "$metadata" >&2
    exit 1
  fi
done

(cd "$backup_dir" && sha256sum --check manifest.sha256) || exit 1
(cd "$backup_dir" && sha256sum --check checksums.sha256) || exit 1

while IFS= read -r -d '' archive; do
  tar -tzf "$archive" >/dev/null || {
    printf 'Unreadable archive: %s\n' "$archive" >&2
    exit 1
  }
done < <(find "$backup_dir" -type f -name '*.tar.gz' -print0)

printf 'Backup verified: %s\n' "$backup_dir"
