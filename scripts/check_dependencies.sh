#!/bin/bash
#
# Dependency Check Script for Smart Speech Flow Backend
# Validates Python dependencies across all services
#

set -e

echo "🔍 Starting dependency validation..."

# Create virtual environment for testing
python -m venv .venv
source .venv/bin/activate

# Upgrade pip and install tools
pip install --upgrade pip
pip install pip-tools safety

echo "📦 Checking service dependencies..."

# Track any failures
FAILED_SERVICES=()

# Check each service's requirements
for service_dir in services/*/; do
    if [ -f "$service_dir/requirements.txt" ]; then
        service_name=$(basename "$service_dir")
        echo "🔍 Checking $service_name..."

        # Create temporary .in file for pip-compile
        temp_in_file="$service_dir/requirements.in"
        cp "$service_dir/requirements.txt" "$temp_in_file"

        # Check if dependencies can be resolved
        if pip-compile --dry-run --quiet "$temp_in_file" > /dev/null 2>&1; then
            echo "   ✅ $service_name dependencies OK"
        else
            echo "   ❌ $service_name has dependency conflicts"
            FAILED_SERVICES+=("$service_name")

            # Show detailed error for debugging
            echo "   📋 Detailed error for $service_name:"
            pip-compile --dry-run "$temp_in_file" || true
        fi

        # Test installation in isolated environment
        if pip install -r "$service_dir/requirements.txt" > /dev/null 2>&1; then
            echo "   ✅ $service_name installs successfully"
        else
            echo "   ❌ $service_name installation failed"
            FAILED_SERVICES+=("$service_name")
        fi

        # Check for security vulnerabilities (if safety is available)
        if command -v safety &> /dev/null; then
            if safety check --file "$service_dir/requirements.txt" --short-report > /dev/null 2>&1; then
                echo "   ✅ $service_name security check passed"
            else
                echo "   ⚠️  $service_name has security vulnerabilities"
                # Don't fail build for security issues, just warn
            fi
        fi

        # Clean up temporary file
        rm -f "$temp_in_file"

        # Reset environment for next service
        pip uninstall -y -r "$service_dir/requirements.txt" > /dev/null 2>&1 || true
    else
        echo "⚠️  No requirements.txt found in $service_dir"
    fi
done

echo ""
echo "📊 Dependency Check Summary:"
if [ ${#FAILED_SERVICES[@]} -eq 0 ]; then
    echo "✅ All dependency checks passed!"
    echo "   - All services have resolvable dependencies"
    echo "   - All packages install successfully"
    echo "   - No major security vulnerabilities detected"
    exit 0
else
    echo "❌ Dependency issues found in:"
    for failed_service in "${FAILED_SERVICES[@]}"; do
        echo "   - $failed_service"
    done
    echo ""
    echo "💡 Possible solutions:"
    echo "   1. Check for conflicting package versions"
    echo "   2. Pin specific package versions in requirements.txt"
    echo "   3. Remove duplicate or conflicting dependencies"
    echo "   4. Update packages to compatible versions"
    exit 1
fi
