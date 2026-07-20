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

pip-compile --resolver=backtracking --output-file "${ROOT_DIR}/requirements-dev.txt" "${ROOT_DIR}/requirements-dev.in"

for service_dir in "${ROOT_DIR}"/services/*; do
    if [ -f "${service_dir}/requirements.in" ]; then
        pip-compile \
            --resolver=backtracking \
            --output-file "${service_dir}/requirements.txt" \
            "${service_dir}/requirements.in"
    fi
done

echo "Pinned requirements regenerated."
