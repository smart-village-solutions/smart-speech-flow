#!/bin/bash
#
# Dependency Check Script for Smart Speech Flow Backend
# Validates Python dependencies across all services.
#

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TOOLS_VENV="${ROOT_DIR}/.venv-dependency-tools"
TEMP_VENVS=()
AUDIT_WARNINGS=()

cleanup() {
    for temp_venv in "${TEMP_VENVS[@]:-}"; do
        [ -n "${temp_venv}" ] && [ -d "${temp_venv}" ] && rm -rf "${temp_venv}"
    done
}

trap cleanup EXIT

echo "🔍 Starting dependency validation..."

python3 -m venv "${TOOLS_VENV}"
source "${TOOLS_VENV}/bin/activate"

pip install --upgrade pip
pip install pip-tools==7.5.3 pip-audit==2.7.3

echo "📦 Checking service dependencies..."

FAILED_SERVICES=()

for service_dir in "${ROOT_DIR}"/services/*; do
    [ -d "${service_dir}" ] || continue
    [ -f "${service_dir}/requirements.txt" ] || continue

    service_name="$(basename "${service_dir}")"
    source_requirements="${service_dir}/requirements.in"
    if [ ! -f "${source_requirements}" ]; then
        source_requirements="${service_dir}/requirements.txt"
    fi

    echo "🔍 Checking ${service_name}..."

    if pip-compile --dry-run --quiet "${source_requirements}" > /dev/null 2>&1; then
        echo "   ✅ ${service_name} dependencies OK"
    else
        echo "   ❌ ${service_name} has dependency conflicts"
        FAILED_SERVICES+=("${service_name}")
        echo "   📋 Detailed error for ${service_name}:"
        pip-compile --dry-run "${source_requirements}" || true
    fi

    install_venv="$(mktemp -d -t "ssf-${service_name}-venv-XXXXXX")"
    TEMP_VENVS+=("${install_venv}")
    python3 -m venv "${install_venv}"
    source "${install_venv}/bin/activate"
    pip install --upgrade pip > /dev/null

    if pip install -r "${service_dir}/requirements.txt" > /dev/null 2>&1; then
        echo "   ✅ ${service_name} installs successfully"
    else
        echo "   ❌ ${service_name} installation failed"
        FAILED_SERVICES+=("${service_name}")
    fi

    deactivate

    source "${TOOLS_VENV}/bin/activate"

    if pip-audit -r "${service_dir}/requirements.txt" > /dev/null 2>&1; then
        echo "   ✅ ${service_name} security check passed"
    else
        echo "   ⚠️  ${service_name} has security vulnerabilities"
        AUDIT_WARNINGS+=("${service_name}")
    fi
done

echo
echo "📊 Dependency Check Summary:"
if [ ${#FAILED_SERVICES[@]} -eq 0 ]; then
    echo "✅ All dependency checks passed!"
    echo "   - All services have resolvable dependencies"
    echo "   - All packages install successfully"
    if [ ${#AUDIT_WARNINGS[@]} -eq 0 ]; then
        echo "   - No security vulnerabilities reported by pip-audit"
    else
        echo "   - pip-audit reported vulnerabilities for:"
        printf '     - %s\n' "${AUDIT_WARNINGS[@]}" | sort -u
    fi
    exit 0
fi

echo "❌ Dependency issues found in:"
printf '   - %s\n' "${FAILED_SERVICES[@]}" | sort -u
echo
echo "💡 Possible solutions:"
echo "   1. Check for conflicting package versions"
echo "   2. Pin specific package versions in requirements.txt"
echo "   3. Remove duplicate or conflicting dependencies"
echo "   4. Update packages to compatible versions"
exit 1
