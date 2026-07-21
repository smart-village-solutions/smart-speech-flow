#!/bin/bash
# Regenerate the hash-verified runtime locks used by the service Dockerfiles.

set -euo pipefail

EXPECTED_PIP_TOOLS_VERSION="7.5.2"
PIP_COMPILE="${PIP_COMPILE:-pip-compile}"

if ! "${PIP_COMPILE}" --version | grep -q "${EXPECTED_PIP_TOOLS_VERSION}"; then
    echo "pip-tools ${EXPECTED_PIP_TOOLS_VERSION} is required to regenerate container locks." >&2
    exit 1
fi

for service_name in api_gateway asr translation tts; do
    "${PIP_COMPILE}" \
        --allow-unsafe \
        --generate-hashes \
        --strip-extras \
        --resolver=backtracking \
        --output-file="services/${service_name}/requirements.txt" \
        "services/${service_name}/requirements.in"
done
