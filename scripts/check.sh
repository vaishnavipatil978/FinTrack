#!/usr/bin/env bash
# Runs the same checks CI runs: lint, format check, type check, tests.
set -euo pipefail

echo "==> ruff"
ruff check .

echo "==> black --check"
black --check .

echo "==> mypy"
mypy app

echo "==> pytest"
pytest -q
