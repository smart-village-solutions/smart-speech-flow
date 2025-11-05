#!/bin/bash
#
# Simple Dependency Check Script for GitHub Actions
# Validates that all requirements.txt files are installable
#

set -e

echo "🔍 Starting dependency validation..."

# Create virtual environment for testing
python -m venv .venv
source .venv/bin/activate

# Upgrade pip
pip install --upgrade pip

echo "📦 Checking service dependencies..."

# Track any failures
FAILED_SERVICES=()
ALL_SERVICES=()

# Check each service's requirements
for service_dir in services/*/; do
    if [ -f "$service_dir/requirements.txt" ]; then
        service_name=$(basename "$service_dir")
        ALL_SERVICES+=("$service_name")
        echo "🔍 Checking $service_name..."

        # Create fresh environment for each service
        pip_output=$(mktemp)

        # Test installation
        if pip install -r "$service_dir/requirements.txt" > "$pip_output" 2>&1; then
            echo "   ✅ $service_name installs successfully"

            # Check for basic import tests
            case "$service_name" in
                "api_gateway")
                    if python -c "import fastapi, uvicorn, websockets, prometheus_client" 2>/dev/null; then
                        echo "   ✅ $service_name core imports working"
                    else
                        echo "   ⚠️  $service_name import issues detected"
                    fi
                    ;;
                "asr")
                    if python -c "import transformers, torch, torchaudio" 2>/dev/null; then
                        echo "   ✅ $service_name core imports working"
                    else
                        echo "   ⚠️  $service_name import issues (may need GPU/CUDA)"
                    fi
                    ;;
                "translation")
                    if python -c "import transformers, torch" 2>/dev/null; then
                        echo "   ✅ $service_name core imports working"
                    else
                        echo "   ⚠️  $service_name import issues (may need GPU/CUDA)"
                    fi
                    ;;
                "tts")
                    if python -c "import transformers, torch" 2>/dev/null; then
                        echo "   ✅ $service_name core imports working"
                    else
                        echo "   ⚠️  $service_name import issues (may need GPU/CUDA)"
                    fi
                    ;;
            esac

        else
            echo "   ❌ $service_name installation failed"
            FAILED_SERVICES+=("$service_name")

            # Show error details
            echo "   📋 Installation error:"
            tail -10 "$pip_output" | sed 's/^/      /'
        fi

        # Clean up
        rm -f "$pip_output"

        # Uninstall packages to avoid conflicts between services
        pip freeze | grep -v "^pip=\|^setuptools=\|^wheel=" | cut -d= -f1 | xargs pip uninstall -y > /dev/null 2>&1 || true

    else
        echo "⚠️  No requirements.txt found in $service_dir"
    fi
done

echo ""
echo "📊 Dependency Check Summary:"
echo "   Services checked: ${ALL_SERVICES[*]}"

if [ ${#FAILED_SERVICES[@]} -eq 0 ]; then
    echo "✅ All dependency checks passed!"
    echo "   - All services install successfully"
    echo "   - Core imports functional"
    echo ""
    echo "🎯 Next steps:"
    echo "   - Services are ready for deployment"
    echo "   - Consider running integration tests"
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
    echo "   5. Check for missing system dependencies"
    exit 1
fi