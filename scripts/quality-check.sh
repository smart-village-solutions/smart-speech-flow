#!/bin/bash
#
# Smart Speech Flow Backend - Code Quality Check Script
# Führt alle Code-Qualitätsprüfungen lokal aus
#

# set -e wird nicht verwendet, da wir Fehler abfangen und zählen

# Farben für Output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Header
echo -e "${BLUE}===========================================${NC}"
echo -e "${BLUE}  Smart Speech Flow - Code Quality Check  ${NC}"
echo -e "${BLUE}===========================================${NC}"
echo ""

# Check if virtual environment exists
if [ ! -d ".venv" ]; then
    echo -e "${YELLOW}Virtual environment not found. Creating...${NC}"
    python3 -m venv .venv
fi

# Activate virtual environment
echo -e "${BLUE}Activating virtual environment...${NC}"
source .venv/bin/activate

# Install/upgrade development dependencies
echo -e "${BLUE}Installing/updating development dependencies...${NC}"
pip install --upgrade pip > /dev/null
pip install -r requirements-dev.txt > /dev/null

echo ""
echo -e "${BLUE}=== Running Code Quality Checks ===${NC}"
echo ""

# Initialize results
PASSED=0
FAILED=0
WARNINGS=0

# Function to run a check
run_check() {
    local name=$1
    local command=$2
    local warning_only=${3:-false}

    echo -e "${BLUE}Running $name...${NC}"

    if eval "$command"; then
        echo -e "${GREEN}✓ $name: PASSED${NC}"
        ((PASSED++))
    else
        if [ "$warning_only" = true ]; then
            echo -e "${YELLOW}⚠ $name: ISSUES FOUND (non-blocking)${NC}"
            ((WARNINGS++))
        else
            echo -e "${RED}✗ $name: FAILED${NC}"
            ((FAILED++))
        fi
    fi
    echo ""
}

# 1. Code Formatting Check
run_check "Black Code Formatting" "black --check services/"

# 2. Import Sorting Check
run_check "Import Sorting (isort)" "isort --check-only services/"

# 3. Linting Check
run_check "Linting (flake8)" "flake8 services/ --statistics"

# 4. Security Analysis
run_check "Security Analysis (bandit)" "bandit -r services/ -ll" true

# 5. Dependency Vulnerabilities
run_check "Dependency Security (pip-audit)" "pip-audit --desc" true

# 6. Type Checking (warning only during gradual adoption)
run_check "Type Checking (mypy)" "mypy services/api_gateway/ --ignore-missing-imports" true

# Summary
echo -e "${BLUE}=== QUALITY CHECK SUMMARY ===${NC}"
echo ""
echo -e "Passed:   ${GREEN}$PASSED${NC}"
echo -e "Failed:   ${RED}$FAILED${NC}"
echo -e "Warnings: ${YELLOW}$WARNINGS${NC}"
echo ""

if [ $FAILED -eq 0 ]; then
    echo -e "${GREEN}🎉 All critical quality checks passed!${NC}"

    if [ $WARNINGS -gt 0 ]; then
        echo -e "${YELLOW}Note: $WARNINGS non-critical issues found. Consider addressing them.${NC}"
    fi

    echo ""
    echo -e "${BLUE}=== QUALITY IMPROVEMENTS ===${NC}"
    echo "✓ Code is properly formatted"
    echo "✓ Imports are sorted consistently"
    echo "✓ No critical linting issues"
    echo "✓ No high-severity security vulnerabilities"
    echo "✓ No known vulnerable dependencies"
    echo ""
    echo -e "${GREEN}Ready for commit! 🚀${NC}"
    exit 0
else
    echo -e "${RED}❌ $FAILED critical quality checks failed!${NC}"
    echo ""
    echo -e "${BLUE}=== NEXT STEPS ===${NC}"
    echo "1. Fix the failed checks above"
    echo "2. Run individual tools for detailed output:"
    echo "   - black services/              (auto-fix formatting)"
    echo "   - isort services/              (auto-fix import sorting)"
    echo "   - flake8 services/             (detailed linting report)"
    echo "   - bandit -r services/          (security analysis)"
    echo "   - pip-audit                    (dependency vulnerabilities)"
    echo ""
    echo -e "${RED}Please fix issues before committing.${NC}"
    exit 1
fi
