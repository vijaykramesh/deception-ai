#!/usr/bin/env bash
set -euo pipefail

# Run unit tests with coverage and emit Cobertura XML.
# Output files:
#   - coverage.xml (Cobertura)
#   - htmlcov/ (HTML report)

pytest --cov=app --cov-report=term-missing --cov-report=xml --cov-report=html

