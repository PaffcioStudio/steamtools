#!/usr/bin/env bash
# Uruchamia testy jednostkowe (pytest). Wymaga .venv - jeśli go nie ma,
# odsyła do venv.sh. Brakujący pytest doinstaluje z requirements-dev.txt.
# Dodatkowe argumenty trafiają do pytesta, np. ./tests.sh -v
# albo ./tests.sh tests/test_owned.py
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_PYTHON="${ROOT_DIR}/.venv/bin/python"

if [[ ! -x "${VENV_PYTHON}" ]]; then
    echo "Środowisko .venv nie istnieje lub jest niekompletne."
    echo "Utwórz je poleceniem: ./venv.sh"
    exit 1
fi

cd "${ROOT_DIR}"

if ! "${VENV_PYTHON}" -c "import pytest" 2>/dev/null; then
    echo "Brak pytesta w .venv - instaluję z requirements-dev.txt..."
    "${VENV_PYTHON}" -m pip install -q -r requirements-dev.txt
fi

exec "${VENV_PYTHON}" -m pytest "$@"
