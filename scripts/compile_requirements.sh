#!/bin/bash
#
# Regenerate pinned Python requirements from *.in sources.
#

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENV_DIR="${ROOT_DIR}/.venv-requirements"

python3 -m venv "${VENV_DIR}"
source "${VENV_DIR}/bin/activate"

pip install --upgrade pip pip-tools

cd "${ROOT_DIR}"

pip-compile --resolver=backtracking --output-file requirements-dev.txt requirements-dev.in

for service_dir in services/*; do
    if [ -f "${service_dir}/requirements.in" ]; then
        pip-compile \
            --resolver=backtracking \
            --output-file "${service_dir}/requirements.txt" \
            "${service_dir}/requirements.in"
    fi
done

echo "Pinned requirements regenerated."
